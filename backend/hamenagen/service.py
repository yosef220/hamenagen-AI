"""Application service layer — orchestrates the core modules.

This is the single entry point the front-end (Electron via RPC) and the CLI
talk to. It owns the index, the classifier, the fetcher and the settings, and
turns a natural-language request into a concrete playlist by combining the
intent engine, the topic classifier and the fuzzy matcher.
"""

from __future__ import annotations

import json
import os
import platform
import random
import sys
import threading
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from . import __version__
from . import intent as intent_mod
from . import settings as settings_mod
from . import metadata as metadata_mod
from . import topics as topics_mod
from .classifier import EmbeddingBackend, HybridClassifier
from .fetcher import OnlineFetcher, ProgressHook, SearchResult, find_ffmpeg
from .fuzzy import MatchCandidate, near_matches, search as fuzzy_search
from .hebrew_calendar import VOCAL_TOPIC, detect_occasion, from_gregorian, today_info
from .index_db import AVERAGE_SONG_SECONDS, MusicIndex, encode_tags
from .intent import Action, Intent
from .models import Track
from .offline_pack import PackError, find_packs, install_pack
from .radio import RadioProvider
from .scanner import (
    SCAN_VERSION,
    default_roots,
    display_folder,
    is_placeholder_title,
    is_too_short,
    iter_media_files,
    read_sidecar_lyrics,
    scan_file,
    store_cover,
    track_id_for,
)
from .settings import (
    Settings,
    bundled_audio_models_dir,
    bundled_ffmpeg_dir,
    bundled_models_dir,
    default_data_dir,
    default_downloads_dir,
)
from .text_normalize import normalize
from .updater import Updater, current_ytdlp_version
from .vocal import MODEL_NAME as VOCAL_MODEL, VocalDetector
from .ytdlp_runner import YtDlpRunner

ScanProgress = Callable[[dict], None]

# A fuzzy title match at least this strong beats a topic reading of a request
# ("ירושלים של זהב" is a song, not "songs about Jerusalem").
_STRONG_TITLE_MATCH = 0.85


def _span_text(minutes: int) -> str:
    return {15: "רבע שעה", 30: "חצי שעה", 45: "שלושת רבעי שעה", 60: "שעה", 90: "שעה וחצי",
            120: "שעתיים", 150: "שעתיים וחצי", 180: "שלוש שעות"}.get(minutes, f"{minutes} דקות")


def _display_query(raw: str) -> str:
    """The user's own words minus the "play me" filler, for "חיפוש: …"."""
    words = [w for w in (raw or "").split() if normalize(w) not in intent_mod._PLAY_VERBS]
    return " ".join(words).strip() or (raw or "").strip()


class PlayerService:
    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.edition = settings_mod.edition()
        self.settings_path = self.data_dir / "settings.json"
        self.settings = Settings.load(self.settings_path)
        # A lexicon update downloaded earlier (spec §14) extends the tables.
        topics_mod.load_override(self.data_dir / "topics_override.json")
        self.db_path = self.data_dir / "library.db"
        self.index = MusicIndex(self.db_path)
        self.models_dir = self.data_dir / "models"
        self.bundled_models_dir = bundled_models_dir()
        self.classifier = HybridClassifier(self._build_backend())
        # Cover pictures, kept once each by content (scanner.store_cover).
        self.covers_dir = self.data_dir / "covers"
        # yt-dlp runs as its own process (ytdlp_runner); a newer copy can live
        # in data/engine; ffmpeg ships with the app for MP3 downloads.
        self.ffmpeg = find_ffmpeg(bundled_ffmpeg_dir())
        self.runner = YtDlpRunner(engine_dir=self.data_dir / "engine", ffmpeg=self.ffmpeg)
        self.fetcher = OnlineFetcher(runner=self.runner)
        if os.environ.get("HAMENAGEN_DEMO_ONLINE"):  # the UI harness: YouTube from memory
            from .demo_online import DemoSource

            self.fetcher = OnlineFetcher(DemoSource())
        self.download_stop = threading.Event()
        self.downloading = False
        self.radio = RadioProvider(
            self.settings.radio_list_url,
            cache_path=self.data_dir / "radio_cache.json",
        )
        self.updater = Updater(self.settings.update_manifest_url, self.data_dir, edition=self.edition)
        self.updater.engine_updater = self.runner.update_engine
        # Listening for a cappella songs: the model ships in every edition;
        # a dev run can put it in data/models (prepare_audio_model.py).
        self.vocal = VocalDetector([bundled_audio_models_dir() or "", self.models_dir])
        self.vocal_running = False
        self.vocal_stop = False
        self.scanning = False
        # First-run offline install: pick up any *.pack sitting next to the app.
        try:
            self._auto_install_packs()
        except Exception:
            pass

    # -- paths -------------------------------------------------------------
    @property
    def downloads_dir(self) -> Path:
        if self.settings.downloads_dir:
            return Path(self.settings.downloads_dir)
        return default_downloads_dir() if os.environ.get("HAMENAGEN_MUSIC_DIR") else self.data_dir / "downloads"

    def _model_cache_dir(self) -> Path:
        """The bundled model when the app ships one, else the data folder."""
        if self.bundled_models_dir is not None:
            probe = EmbeddingBackend(self.settings.embedding_model, cache_dir=str(self.bundled_models_dir))
            if probe._cache_has_model():
                return self.bundled_models_dir
        return self.models_dir

    def _build_backend(self) -> EmbeddingBackend | None:
        if not self.settings.use_embeddings:
            return None
        return EmbeddingBackend(
            self.settings.embedding_model,
            threshold=self.settings.embedding_threshold,
            cache_dir=str(self._model_cache_dir()),
        )

    # -- settings ------------------------------------------------------------
    def get_settings(self) -> dict:
        return self.settings.to_dict()

    def update_settings(self, values: dict) -> dict:
        changed = self.settings.update(values or {})
        self.settings.save(self.settings_path)
        if {"use_embeddings", "embedding_model", "embedding_threshold"} & set(changed):
            self.classifier.embedding = self._build_backend()
        if "vocal_detection" in changed and not self.settings.vocal_detection:
            self.vocal_stop = True
        if {"vocal_detection", "vocal_auto_include"} & set(changed):
            self._apply_vocal_verdicts()
        if "update_manifest_url" in changed:
            self.updater.manifest_url = self.settings.update_manifest_url
        if "radio_list_url" in changed:
            self.radio.source_url = self.settings.radio_list_url
        return {**self.settings.to_dict(), "_changed": changed}

    # -- library management ------------------------------------------------
    def _roots(self) -> list[str]:
        roots = list(self.settings.scan_roots) or default_roots()
        downloads = str(self.downloads_dir)
        if downloads not in roots and Path(downloads).exists():
            roots.append(downloads)
        return roots

    def rescan(
        self,
        roots: list[str] | None = None,
        index: MusicIndex | None = None,
        on_progress: ScanProgress | None = None,
    ) -> dict:
        """Scan the music folders, refresh the index and classify new songs.

        Incremental: a file whose size and modification time did not change
        since the last scan is not opened again, so the scan on every launch
        stays quick even for a large collection.

        Pass ``index`` to write through a caller-owned connection. When called
        from a background thread, leave it ``None`` — we open a fresh
        connection to the same DB file (WAL mode lets the UI keep reading).
        """
        partial = bool(roots)
        use_roots = roots or self._roots()
        own = index is None
        idx = index or MusicIndex(self.db_path)
        started = datetime.now()
        try:
            known = idx.file_state()
            overrides = idx.overrides()
            analyses = idx.analyses()
            details = idx.details()
            # A library scanned by an older version is read again once, so
            # what this version reads better (Hebrew in old encodings, WMA
            # tags, covers) reaches every song.
            force = not partial and bool(known) and idx.get_meta("scan_version") != SCAN_VERSION
            folder_cache: dict = {}
            seen: set[str] = set()
            added = updated = files = 0
            for path, st in iter_media_files(use_roots, include_video=self.settings.include_video):
                files += 1
                tid = track_id_for(path)
                previous = known.get(tid)
                if previous and previous == (st.st_mtime, st.st_size) and not force:
                    seen.add(tid)
                elif (track := scan_file(path, include_video=self.settings.include_video, stat=st,
                                         covers_dir=self.covers_dir, folder_cache=folder_cache)) is not None \
                        and not is_too_short(track):
                    seen.add(tid)
                    if previous:
                        old = idx.get(tid)
                        if old is not None and old.source != "local":
                            # Keep what we learned when it was downloaded.
                            track.title, track.artist = old.title or track.title, old.artist or track.artist
                            track.source, track.release_date = old.source, old.release_date
                            track.download_date = old.download_date or track.download_date
                        if old is not None:
                            track.cover = track.cover or old.cover
                            track.duration = track.duration or old.duration
                    self._apply_details(track, details.get(tid))
                    self._classify_track(track, override=overrides.get(tid), analysis=analyses.get(tid))
                    idx.upsert(track, commit=False)
                    if previous:
                        updated += 1
                    else:
                        added += 1
                    if (added + updated) % 200 == 0:
                        idx.commit()
                if on_progress and files % 250 == 0:
                    on_progress({"files": files, "added": added, "updated": updated})
            idx.commit()
            removed = self._remove_missing(idx, known, seen, use_roots if partial else None)
            propagated = self._propagate(idx)
            finished = datetime.now()
            idx.set_meta("last_scan_at", finished.isoformat(timespec="seconds"))
            if not partial:
                idx.set_meta("scan_version", SCAN_VERSION)
            return {
                "scanned_roots": use_roots,
                "files": files,
                "added": added,
                "updated": updated,
                "removed": removed,
                "propagated": propagated,
                "total": idx.count(),
                "seconds": round((finished - started).total_seconds(), 1),
            }
        finally:
            if own:
                idx.close()

    @staticmethod
    def _remove_missing(idx: MusicIndex, known: dict, seen: set[str], roots: list[str] | None) -> int:
        gone = set(known) - seen
        if roots is not None:  # a partial scan only answers for its own folders
            prefixes = [os.path.normcase(str(Path(r).resolve())) for r in roots]
            keep = set()
            for track in idx.get_many(sorted(gone)):
                where = os.path.normcase(track.path)
                if not any(where.startswith(p) for p in prefixes):
                    keep.add(track.id)
            gone -= keep
        return idx.delete_ids(gone) if gone else 0

    # Folder names that say nothing about a song's topic.
    _GENERIC_FOLDERS = {normalize(name) for name in (
        "music", "my music", "מוזיקה", "המוזיקה שלי", "שירים", "downloads", "הורדות", "desktop",
        "שולחן העבודה", "documents", "מסמכים", "users", "audio", "mp3", "new folder", "תיקייה חדשה",
        "hamenagen", "המנגן", "data", "media", "songs",
    )}

    def _folder_hint(self, path: str) -> str:
        """The names of the song's two nearest folders — people file music in
        folders such as "שבת" or "חתונות", which says a lot about a song."""
        names = []
        home = os.path.normcase(str(Path.home()))
        for parent in list(Path(path).parents)[:2]:
            here = os.path.normcase(str(parent))
            # Stop at the home folder (its name is the user's name) and above.
            if home.startswith(here) or parent.parent.name.lower() in ("users", "home"):
                break
            name = parent.name.strip()
            if name and normalize(name) not in self._GENERIC_FOLDERS and not name.endswith(":"):
                names.append(name)
        return " ".join(names)

    @staticmethod
    def _apply_details(track: Track, chosen: dict | None) -> Track:
        """Lay the details the listener chose from the web over the file's tags."""
        if chosen:
            for key in ("title", "artist", "album"):
                if chosen.get(key):
                    setattr(track, key, chosen[key])
            if chosen.get("year") and not track.release_date:
                track.release_date = chosen["year"]
            if chosen.get("cover"):
                track.cover = chosen["cover"]
        return track

    def _classify_track(self, track: Track, *, override: dict | None = None,
                        analysis: dict | None = None) -> Track:
        """Classify a song, then apply what the listener decided about it and
        (when allowed) what the vocal detector heard."""
        lyrics = ""
        if self.settings.classify_by_lyrics and track.path:
            lyrics = read_sidecar_lyrics(track.path)
        folder = self._folder_hint(track.path) if track.path else ""
        cls = self.classifier.classify(
            title=track.title,
            artist=track.artist,
            album=" ".join(p for p in (track.album, folder) if p),
            filename=track.filename,
            lyrics=lyrics,
            use_embeddings=self.settings.use_embeddings,
        )
        topic, source, note = cls.topic, cls.source, cls.note
        tags = list(cls.tags)
        if override and override.get("has_topic"):
            topic = override.get("topic") or None
            source, note = "user", "בחרת בנושא הזה"
        # Vocal: the listener's word first; otherwise what the detector heard,
        # if the listener let detected songs in without checking them.
        vocal = override.get("vocal") if override else None
        detected = (vocal is None and bool(analysis) and analysis.get("verdict") == "vocal"
                    and self.settings.vocal_detection and self.settings.vocal_auto_include)
        if vocal == 0:
            tags = [t for t in tags if t != VOCAL_TOPIC]
            if topic == VOCAL_TOPIC:
                topic, source, note = (tags.pop(0), source, note) if tags else (None, "none", "")
        elif vocal == 1 or detected:
            if topic is None:
                topic = VOCAL_TOPIC
                source = "user" if vocal == 1 else "audio"
                note = "סימנת שהשיר ווקאלי" if vocal == 1 else "זוהה מהשמע: שירה בלי כלי נגינה"
            elif topic != VOCAL_TOPIC and VOCAL_TOPIC not in tags:
                tags.append(VOCAL_TOPIC)
        track.topic = topic
        track.topic_source = source
        track.topic_note = note if topic else ""
        track.tags = encode_tags(t for t in tags if t != topic)
        return track

    # Album and folder propagation: a song nothing else could place takes the
    # topic most of its album (or folder) share, when at least this many
    # songs there are placed and this share of them agree.
    _PROPAGATE_MIN_SONGS = 3
    _PROPAGATE_SHARE = 0.6

    def _propagate(self, idx: MusicIndex) -> int:
        """Give unplaced songs the topic of their album or folder. Returns
        how many songs changed. Re-run after every scan and correction."""
        tracks = idx.all_tracks()
        inherited = {"album", "folder"}
        albums: dict[tuple[str, str], list[Track]] = {}
        folders: dict[str, list[Track]] = {}
        for t in tracks:
            if t.album and normalize(t.album):
                albums.setdefault((normalize(t.album), normalize(t.artist or "")), []).append(t)
            if t.path:
                folders.setdefault(os.path.normcase(str(Path(t.path).parent)), []).append(t)

        def majority(group: list[Track]) -> str | None:
            placed = [t.topic for t in group
                      if t.topic and t.topic_source not in inherited and t.topic != VOCAL_TOPIC]
            if len(placed) < self._PROPAGATE_MIN_SONGS:
                return None
            topic, n = Counter(placed).most_common(1)[0]
            return topic if n >= self._PROPAGATE_MIN_SONGS and n / len(placed) >= self._PROPAGATE_SHARE else None

        album_topic = {k: majority(v) for k, v in albums.items()}
        folder_topic = {k: majority(v) for k, v in folders.items()}
        changed = 0
        for t in tracks:
            if t.topic_source == "user" or (t.topic and t.topic_source not in inherited):
                continue  # placed by its own merits, or by the listener
            new, source, note = None, "none", ""
            key = (normalize(t.album), normalize(t.artist or "")) if t.album else None
            if key and album_topic.get(key):
                new, source = album_topic[key], "album"
                note = f"רוב השירים באלבום „{t.album}” הם {topics_mod.TOPIC_LABELS.get(new, new)}"
            elif t.path:
                folder = os.path.normcase(str(Path(t.path).parent))
                if folder_topic.get(folder):
                    new, source = folder_topic[folder], "folder"
                    note = (f"רוב השירים בתיקייה „{Path(t.path).parent.name}” הם "
                            f"{topics_mod.TOPIC_LABELS.get(new, new)}")
            if (new, source) != (t.topic, t.topic_source if t.topic else "none"):
                idx.set_topic(t.id, new, source, None, note, commit=False)
                changed += 1
        if changed:
            idx.commit()
        return changed

    # -- the listener's corrections ----------------------------------------------
    def set_track_topic(self, track_id: str, topic: str | None) -> dict:
        """``topic``: a topic key, "" for "no topic", or None to go back to the
        automatic topic."""
        if topic is None:
            self.index.set_override(track_id, has_topic=0, topic=None)
        else:
            self.index.set_override(track_id, has_topic=1, topic=topic or None)
        return self._reclassify_one(track_id)

    def set_track_vocal(self, track_id: str, value: bool | None) -> dict:
        """True: the song is vocal; False: it has instruments; None: decide automatically."""
        self.index.set_override(track_id, vocal=None if value is None else (1 if value else 0))
        return self._reclassify_one(track_id)

    def confirm_vocal(self, track_ids: list[str], value: bool) -> dict:
        for tid in track_ids:
            self.index.set_override(tid, vocal=1 if value else 0)
        tracks = self.index.get_many(list(track_ids))
        overrides = self.index.overrides_for([t.id for t in tracks])
        analyses = self.index.analyses_for([t.id for t in tracks])
        for t in tracks:
            self._classify_track(t, override=overrides.get(t.id), analysis=analyses.get(t.id))
            self.index.set_topic(t.id, t.topic, t.topic_source, t.tags, t.topic_note, commit=False)
        self.index.commit()
        return {"ok": True, "count": len(tracks), "propagated": self._propagate(self.index)}

    def _reclassify_one(self, track_id: str) -> dict:
        track = self.index.get(track_id)
        if track is None:
            return {"ok": False, "track": None}
        self._classify_track(track, override=self.index.get_override(track_id),
                             analysis=self.index.analyses_for([track_id]).get(track_id))
        self.index.set_topic(track.id, track.topic, track.topic_source, track.tags, track.topic_note)
        propagated = self._propagate(self.index)
        fresh = self.index.get(track_id) or track
        return {"ok": True, "track": self._tracks_payload([fresh])[0], "propagated": propagated}

    # -- AI classifier management (spec §8.2) -----------------------------
    def classifier_status(self) -> dict:
        """Report the state of the local embedding layer, for the UI/settings."""
        backend = self.classifier.embedding
        if backend is None:
            return {"enabled": False, "available": False, "model": None, "bundled": False}
        st = backend.status()
        st["enabled"] = True
        st["bundled"] = self.bundled_models_dir is not None and backend.cache_dir == str(self.bundled_models_dir)
        return st

    def install_model(self) -> dict:
        """Ensure the local AI model is ready (first-run install, spec §6.1).

        Loading the backend downloads the model once when online (or reads the
        copy bundled in the offline edition); afterwards it is used offline.
        Safe to call repeatedly — it no-ops once installed.
        """
        backend = self.classifier.embedding
        if backend is None:
            return {"ok": False, "reason": "embeddings disabled", **self.classifier_status()}
        ok = backend.load()
        return {"ok": ok, **self.classifier_status()}

    def reclassify_all(self, on_progress: ScanProgress | None = None) -> dict:
        """Re-run classification over every indexed track (e.g. after the model
        was installed or the lexicon updated). Returns how many changed."""
        self.classifier.refresh_lexicon()
        if self.classifier.embedding is None and self.settings.use_embeddings:
            self.classifier.embedding = self._build_backend()
        changed = 0
        tracks = self.index.all_tracks()
        overrides = self.index.overrides()
        analyses = self.index.analyses()
        for n, track in enumerate(tracks, 1):
            before = (track.topic, track.tags, track.topic_note)
            self._classify_track(track, override=overrides.get(track.id), analysis=analyses.get(track.id))
            if (track.topic, track.tags, track.topic_note) != before:
                self.index.set_topic(track.id, track.topic, track.topic_source, track.tags, track.topic_note,
                                     commit=False)
                changed += 1
            if on_progress and n % 100 == 0:
                self.index.commit()
                on_progress({"done": n, "total": len(tracks), "changed": changed})
        self.index.commit()
        changed += self._propagate(self.index)
        return {"total": len(tracks), "changed": changed, **self.classifier_status()}

    # -- listening for a cappella songs -------------------------------------
    def vocal_status(self) -> dict:
        counts = self.index.analysis_counts()
        total = sum(1 for t in self.index.all_tracks() if not t.is_video)
        analyzed = sum(counts.values())
        return {
            "enabled": self.settings.vocal_detection,
            "auto_include": self.settings.vocal_auto_include,
            **self.vocal.status(),
            "running": self.vocal_running,
            "total": total,
            "analyzed": min(analyzed, total),
            "vocal": counts.get("vocal", 0),
            "maybe": counts.get("maybe", 0),
            "instruments": counts.get("instruments", 0),
            "unreadable": counts.get("unreadable", 0),
            "to_review": len(self.vocal_review(limit=1000)["tracks"]),
        }

    def _needs_listening(self, idx: MusicIndex) -> list[Track]:
        done = idx.analyses()
        out = []
        for t in idx.all_tracks():
            if t.is_video or not t.path:
                continue
            a = done.get(t.id)
            if a is None or a.get("model") != VOCAL_MODEL or (a.get("mtime"), a.get("size")) != (t.mtime, t.size):
                out.append(t)
        return out

    def analyze_vocal(self, on_progress: ScanProgress | None = None) -> dict:
        """Listen to every song not yet heard (or changed since). Runs on its
        own connection, a song at a time, and stops when asked."""
        if not self.settings.vocal_detection:
            return {"ok": False, "reason": "disabled", **self.vocal.status()}
        if not self.vocal.available():
            return {"ok": False, "reason": "unavailable", **self.vocal.status()}
        self.vocal_running, self.vocal_stop = True, False
        idx = MusicIndex(self.db_path)
        found = done = 0
        try:
            todo = self._needs_listening(idx)
            overrides = idx.overrides()
            for n, track in enumerate(todo, 1):
                if self.vocal_stop:
                    break
                result = self.vocal.analyze(track.path)
                row = {
                    "model": VOCAL_MODEL, "verdict": result.verdict, "acapella": round(result.acapella, 4),
                    "instrument": round(result.instrument, 4),
                    "windows": json.dumps([w.as_list() for w in result.windows]),
                    "mtime": track.mtime, "size": track.size,
                    "analyzed_at": datetime.now().isoformat(timespec="seconds"),
                }
                idx.save_analysis(track.id, row, commit=False)
                done += 1
                if result.verdict == "vocal":
                    found += 1
                    self._classify_track(track, override=overrides.get(track.id), analysis=row)
                    idx.set_topic(track.id, track.topic, track.topic_source, track.tags, track.topic_note,
                                  commit=False)
                if n % 10 == 0 or n == len(todo):
                    idx.commit()
                    if on_progress:
                        on_progress({"done": n, "total": len(todo), "found": found})
            idx.commit()
            return {"ok": True, "analyzed": done, "found": found, "stopped": self.vocal_stop,
                    "left": len(todo) - done}
        finally:
            idx.close()
            self.vocal_running = False

    def _apply_vocal_verdicts(self) -> int:
        """Re-apply what was heard after the vocal settings changed."""
        analyses = self.index.analyses()
        if not analyses:
            return 0
        tracks = self.index.get_many([tid for tid, a in analyses.items() if a.get("verdict") == "vocal"])
        overrides = self.index.overrides_for([t.id for t in tracks])
        changed = 0
        for t in tracks:
            before = (t.topic, t.tags)
            self._classify_track(t, override=overrides.get(t.id), analysis=analyses.get(t.id))
            if (t.topic, t.tags) != before:
                self.index.set_topic(t.id, t.topic, t.topic_source, t.tags, t.topic_note, commit=False)
                changed += 1
        self.index.commit()
        return changed

    def vocal_review(self, limit: int = 300) -> dict:
        """Songs heard as vocal (or maybe) that the listener has not checked,
        leaving out songs whose names already say they are vocal."""
        out = []
        for t in self.index.vocal_candidates(limit * 2):
            text = " ".join(p for p in (t.title, t.album, t.filename) if p)
            if VOCAL_TOPIC in self.classifier.keyword_topics(text):
                continue
            out.append(t)
            if len(out) >= limit:
                break
        return {"tracks": self._tracks_payload(out), "count": len(out)}

    # -- online completion (spec §11) -------------------------------------
    def online_available(self) -> bool:
        return self.fetcher.available()

    def download_and_add(self, result: SearchResult, on_progress: ProgressHook | None = None,
                         cancel: threading.Event | None = None) -> dict:
        """Download a chosen result, add it to the library, and return its Track.

        Implements the tail of the spec §11 flow: the file lands in the local
        library, gets indexed + classified, and the caller (UI) auto-plays it
        unless the user opted out.
        """
        outcome = self.fetcher.download(result, self.downloads_dir, on_progress=on_progress, cancel=cancel)
        if not outcome.ok or not outcome.path:
            return {"ok": False, "message": outcome.message, "track": None,
                    "code": getattr(outcome, "code", ""), "blocked": bool(getattr(outcome, "blocked", False))}

        track = scan_file(outcome.path, include_video=self.settings.include_video, covers_dir=self.covers_dir)
        if track is None:
            return {"ok": True, "message": outcome.message, "track": None, "path": outcome.path}

        # Prefer metadata from the source over filename parsing (spec §10):
        # the clean song name and artist the fetcher took from the video.
        src = outcome.result or result
        title = getattr(outcome, "title", "") or src.title
        if title:
            track.title = title
        artist = getattr(outcome, "artist", "") or src.uploader
        if artist:
            track.artist = artist if not track.artist or track.artist == src.uploader else track.artist
        if not track.cover and getattr(outcome, "cover", None):
            track.cover = store_cover(outcome.cover, self.covers_dir)
        if src.duration and not track.duration:
            track.duration = float(src.duration)
        track.source = "youtube"
        # Use the source's upload date as the "release date" (spec §10 note).
        if src.upload_date and len(src.upload_date) == 8:
            track.release_date = (
                f"{src.upload_date[:4]}-{src.upload_date[4:6]}-{src.upload_date[6:]}"
            )
        track.download_date = datetime.now().isoformat()
        self._classify_track(track)
        self.index.upsert(track)
        return {"ok": True, "message": outcome.message, "track": self._tracks_payload([track])[0],
                "path": outcome.path, "code": "", "blocked": False}

    def download_many(self, items: list[SearchResult], on_event: Callable[[dict], None] | None = None) -> dict:
        """Download songs one after another (a channel, a playlist, a pick
        from the search). Songs already in the library are skipped; a song
        the network blocks is reported and the rest go on."""
        emit = on_event or (lambda e: None)
        self.download_stop.clear()
        self.downloading = True
        have = self.index.video_ids()
        done = skipped = failed = blocked = 0
        try:
            for i, item in enumerate(items):
                if self.download_stop.is_set():
                    break
                if item.id and item.id in have:
                    skipped += 1
                    emit({"type": "item", "index": i, "id": item.id, "status": "skipped"})
                    continue
                emit({"type": "item", "index": i, "id": item.id, "status": "started", "title": item.title})
                out = self.download_and_add(
                    item, cancel=self.download_stop,
                    on_progress=lambda p, i=i, vid=item.id: emit({"type": "progress", "index": i, "id": vid, **p}))
                if out["ok"]:
                    done += 1
                    have.add(item.id)
                    emit({"type": "item", "index": i, "id": item.id, "status": "done", "track": out.get("track")})
                else:
                    failed += 1
                    blocked += bool(out.get("blocked"))
                    emit({"type": "item", "index": i, "id": item.id, "status": "failed",
                          "message": out.get("message", ""), "blocked": bool(out.get("blocked"))})
        finally:
            self.downloading = False
        return {"total": len(items), "downloaded": done, "skipped": skipped, "failed": failed,
                "blocked": blocked, "stopped": self.download_stop.is_set()}

    def stop_downloads(self) -> dict:
        self.download_stop.set()
        self.runner.stop_all()
        return {"ok": True}

    # -- details and covers from the web (asked for, one song at a time) ---------
    def lookup_details(self, track_id: str) -> dict:
        track = self.index.get(track_id)
        if track is None:
            return {"ok": False, "message": "השיר לא נמצא", "candidates": []}
        title = track.title if not is_placeholder_title(track.title) else Path(track.filename).stem
        if os.environ.get("HAMENAGEN_DEMO_ONLINE"):
            from .demo_online import demo_details

            candidates, error = demo_details(title), ""
        else:
            candidates, error = metadata_mod.search(title, track.artist, track.duration)
        message = {"blocked": "החיפוש חסום ברשת הזו (נטפרי או סינון דומה).",
                   "network": "אין כרגע חיבור לרשת.", "bad_answer": "השירות לא ענה כמו שצריך."}.get(error, "")
        return {"ok": not error, "message": message, "error": error,
                "candidates": [c.to_dict() for c in candidates], "track": self._tracks_payload([track])[0]}

    def apply_details(self, track_id: str, chosen: dict, *, propagate: bool = True) -> dict:
        """Keep what the listener chose (never written to the file) and give
        the songs beside it that have no cover the same picture."""
        track = self.index.get(track_id)
        if track is None:
            return {"ok": False, "message": "השיר לא נמצא"}
        current = {"title": track.title, "artist": track.artist, "album": track.album,
                   "release_date": track.release_date}
        values = metadata_mod.merge(current, chosen or {})
        cover = ""
        data = metadata_mod.fetch_image((chosen or {}).get("cover_url", ""))
        if data:
            cover = store_cover(data, self.covers_dir)
        previous = self.index.details().get(track_id) or {}
        row = {**previous, **values, "source": (chosen or {}).get("source", "itunes"),
               "source_url": (chosen or {}).get("url", "")}
        if cover:
            row["cover"] = cover
        self.index.set_details(track_id, row)
        self._apply_details(track, row)
        self._classify_track(track, override=self.index.get_override(track_id),
                             analysis=self.index.analyses_for([track_id]).get(track_id))
        self.index.upsert(track)
        spread, covered = 0, []
        if cover and propagate and track.path:
            everything = self.index.details()
            for other in self.index.tracks_in_folder(str(Path(track.path).parent)):
                if other.id == track.id or other.cover:
                    continue
                self.index.set_details(other.id, {**everything.get(other.id, {}), "cover": cover,
                                                  "source": "folder"}, commit=False)
                self.index.set_cover(other.id, cover, commit=False)
                spread += 1
                covered.append(other.id)
            self.index.commit()
        return {"ok": True, "track": self._tracks_payload([track])[0], "applied": sorted(values),
                "cover": bool(cover), "propagated": spread, "covered_ids": covered, "cover_key": track.cover,
                "message": "" if values or cover else "לא היה מה להוסיף מהפרטים שנבחרו."}

    def _candidates(self) -> list[MatchCandidate]:
        return [
            MatchCandidate(
                id=t.id, title=t.title, artist=t.artist, album=t.album, filename=t.filename,
                folder=self._folder_hint(t.path) if t.path else "",
            )
            for t in self.index.iter_tracks()
        ]

    # -- shaping tracks for the UI -------------------------------------------
    def _track_dict(self, track: Track, favorites: set[str] | None = None,
                    override: dict | None = None, analysis: dict | None = None) -> dict:
        d = track.to_dict()
        d["tags"] = track.tag_list
        d["favorite"] = track.id in (favorites if favorites is not None else self.index.favorite_ids())
        d.pop("mtime", None)
        d.pop("size", None)
        d["folder"] = display_folder(track.path) if track.path else ""
        # What the listener decided and what the detector heard, for the menu
        # and the "found by listening" marks.
        vocal = override.get("vocal") if override else None
        d["vocal"] = ("yes" if vocal == 1 else "no" if vocal == 0
                      else (analysis or {}).get("verdict") if (analysis or {}).get("verdict") in ("vocal", "maybe")
                      else None)
        d["topic_chosen"] = bool(override and override.get("has_topic"))
        return d

    def _tracks_payload(self, tracks: list[Track]) -> list[dict]:
        favs = self.index.favorite_ids()
        ids = [t.id for t in tracks]
        overrides = self.index.overrides_for(ids)
        analyses = self.index.analyses_for(ids)
        return [self._track_dict(t, favs, overrides.get(t.id), analyses.get(t.id)) for t in tracks]

    # -- the main request path --------------------------------------------
    def handle_request(self, text: str) -> dict:
        """Turn a free Hebrew request into a playlist + explanation."""
        intent = intent_mod.parse(text)
        return self._respond(intent)

    def playlist(self, kind: str, *, topic: str | None = None, minutes: int | None = None,
                 limit: int | None = None) -> dict:
        """A ready-made list for a button (a topic tile, "favorites", …)."""
        try:
            action = Action(kind)
        except ValueError:
            action = Action.RANDOM
        params = {"minutes": minutes} if minutes else {}
        return self._respond(Intent(action, topic=topic, limit=limit, raw="", params=params))

    def _respond(self, intent: Intent) -> dict:
        tracks, understood, note = self._execute(intent)
        return {
            "intent": intent.to_dict(),
            "understood": understood,
            "tracks": self._tracks_payload(tracks),
            "count": len(tracks),
            "seconds": round(sum(t.duration or AVERAGE_SONG_SECONDS for t in tracks)),
            "note": note,
            "found_local": bool(tracks),
            "near": bool(intent.params.get("near")),
            "query": _display_query(intent.raw) if intent.action == Action.SEARCH_SONG else "",
        }

    @staticmethod
    def _fill_minutes(tracks: list[Track], minutes: int) -> list[Track]:
        """Take songs in order until the list lasts about ``minutes``."""
        target = minutes * 60
        out: list[Track] = []
        total = 0.0
        for t in tracks:
            if total >= target:
                break
            out.append(t)
            total += t.duration or AVERAGE_SONG_SECONDS
        return out

    def _execute(self, intent: Intent) -> tuple[list[Track], str, str]:
        """Return ``(tracks, what we understood, a note when empty)``."""
        minutes = intent.minutes
        limit = intent.limit or (1000 if minutes else 50)
        tracks: list[Track]

        if intent.action == Action.RECENT_DOWNLOADED:
            tracks, understood = self.index.recent_downloaded(limit), "השירים האחרונים שהורדת"
        elif intent.action == Action.RECENT_RELEASED:
            tracks, understood = self.index.recent_released(limit), "השירים האחרונים שיצאו"
        elif intent.action == Action.FAVORITES:
            tracks, understood = self.index.favorites(intent.limit or 500), "השירים שסימנת בלב"
        elif intent.action == Action.HISTORY:
            tracks, understood = self.index.history(limit), "מה ששמעת לאחרונה"
        elif intent.action == Action.MOST_PLAYED:
            tracks, understood = self.index.most_played(limit), "השירים הכי מושמעים"
        elif intent.action == Action.RANDOM:
            tracks, understood = self.index.random(limit), "מבחר אקראי מכל המאגר"
        elif intent.action == Action.PLAY_TOPIC and intent.topic:
            song_query = intent.params.get("song_query")
            if song_query:
                found = fuzzy_search(song_query, self._candidates(), limit=intent.limit or 25)
                if found and found[0].score >= _STRONG_TITLE_MATCH:
                    by_id = {t.id: t for t in self.index.get_many([r.candidate.id for r in found])}
                    hits = [by_id[r.candidate.id] for r in found if r.candidate.id in by_id]
                    return hits, f"חיפוש: {_display_query(intent.raw)}", ""
            tracks = self.index.by_topic(intent.topic, None if minutes else intent.limit, shuffle=bool(minutes))
            understood = topics_mod.topic_phrase(intent.topic)
        else:
            # SEARCH_SONG (or fallback): every word of the request must match.
            query = intent.query or intent.raw
            candidates = self._candidates()
            found = fuzzy_search(query, candidates, limit=limit)
            near = False
            if not found:
                found = near_matches(query, candidates, limit=limit)
                near = bool(found)
            by_id = {t.id: t for t in self.index.get_many([r.candidate.id for r in found])}
            tracks = [by_id[r.candidate.id] for r in found if r.candidate.id in by_id]
            shown = _display_query(intent.raw) or query
            understood = f"חיפוש: {shown}"
            artists = [t.artist for t, r in zip(tracks, found) if r.by_artist and t.artist]
            if tracks and not near and len(artists) >= max(1, 0.6 * len(tracks)):
                understood = f"השירים של {Counter(artists).most_common(1)[0][0]}"
            if not tracks:
                return [], understood, f"„{shown}” לא נמצא במחשב."
            if near:
                intent.params["near"] = True
                return tracks, understood, "אין במחשב שיר שמתאים לכל המילים. אלה הכי קרובים:"
            return tracks, understood, ""

        if minutes:
            if intent.action in (Action.RANDOM, Action.FAVORITES, Action.HISTORY, Action.MOST_PLAYED):
                random.shuffle(tracks)
            tracks = self._fill_minutes(tracks, minutes)
            understood = f"{_span_text(minutes)} של {understood}" if intent.action != Action.RANDOM \
                else f"{_span_text(minutes)} של מוזיקה מכל המאגר"
        note = "" if tracks else self._empty_note(intent)
        return tracks, understood, note

    def _empty_note(self, intent: Intent) -> str:
        if self.index.count() == 0:
            return "המאגר עדיין ריק — הסריקה מחפשת שירים במחשב."
        return {
            Action.FAVORITES: "עוד לא סימנת שירים בלב. לחיצה על הלב שליד שיר שומרת אותו כאן.",
            Action.HISTORY: "עוד לא הושמעו שירים.",
            Action.MOST_PLAYED: "עוד לא הושמעו שירים.",
            Action.RECENT_RELEASED: "לשירים במאגר אין תאריך יציאה.",
            Action.RECENT_DOWNLOADED: "לא נמצאו שירים שהורדו.",
        }.get(intent.action, f"לא מצאתי {topics_mod.topic_phrase(intent.topic)} במאגר." if intent.topic
              else "לא נמצאו שירים.")

    # -- listening habits ------------------------------------------------------
    def set_favorite(self, track_id: str, on: bool) -> dict:
        self.index.set_favorite(track_id, bool(on))
        return {"id": track_id, "favorite": bool(on)}

    def record_play(self, track_id: str) -> dict:
        if self.index.get(track_id) is None:
            return {"ok": False}
        self.index.record_play(track_id)
        return {"ok": True}

    def track_lyrics(self, track_id: str) -> dict:
        track = self.index.get(track_id)
        text = read_sidecar_lyrics(track.path, max_chars=20000) if track else ""
        return {"id": track_id, "lyrics": text}

    # -- browsing ------------------------------------------------------------
    def topics(self) -> list[dict]:
        counts = self.index.topic_counts()
        return [dict(t, count=counts.get(t["key"], 0)) for t in topics_mod.topic_list()]

    def list_tracks(self, **params) -> dict:
        allowed = {"sort", "descending", "topic", "text", "favorites_only", "source", "offset", "limit"}
        page = self.index.list_tracks(**{k: v for k, v in params.items() if k in allowed})
        return {**page, "tracks": self._tracks_payload(page["tracks"])}

    def library_overview(self) -> dict:
        stats = self.index.stats()
        return {
            "stats": stats,
            "topics": self.topics(),
            "recent": self._tracks_payload(self.index.recent_downloaded(12)),
            "history": self._tracks_payload(self.index.history(12)),
            "favorites": self._tracks_payload(self.index.favorites(12)),
            "last_scan_at": self.index.get_meta("last_scan_at"),
            "scanning": self.scanning,
            "roots": self._roots(),
        }

    # -- the calendar (spec §7) ------------------------------------------------
    def today(self, on: date | None = None) -> dict:
        # HAMENAGEN_TODAY=YYYY-MM-DD shows another day (screenshots, testing).
        if on is None and os.environ.get("HAMENAGEN_TODAY"):
            try:
                on = date.fromisoformat(os.environ["HAMENAGEN_TODAY"])
            except ValueError:
                on = None
        info = today_info(on, vocal_suggestions=self.settings.vocal_suggestions)
        counts = self.index.topic_counts()
        for occ in info["occasions"]:
            occ["count"] = counts.get(occ["topic"], 0) if occ["topic"] else 0
            occ["phrase"] = topics_mod.topic_phrase(occ["topic"]) if occ["topic"] else ""
        if info["primary"]:
            topic = info["primary"]["topic"]
            info["primary"]["count"] = counts.get(topic, 0)
            info["primary"]["phrase"] = topics_mod.topic_phrase(topic)
        if info["next"] and info["next"].get("topic"):
            topic = info["next"]["topic"]
            info["next"]["count"] = counts.get(topic, 0)
            info["next"]["phrase"] = topics_mod.topic_phrase(topic)
        return info

    def opening_suggestion(self, on: date | None = None) -> dict | None:
        """The single "play now" suggestion of the day (kept for 0.1 callers)."""
        occ = detect_occasion(on, vocal_suggestions=self.settings.vocal_suggestions)
        if occ is None or not occ.suggests:
            return None
        heb = from_gregorian(on or date.today())
        return {
            "occasion_key": occ.key,
            "label": occ.label,
            "topic": occ.topic,
            "detail": occ.detail,
            "hebrew_date": str(heb),
            "has_songs": bool(self.index.by_topic(occ.topic, limit=1)),
        }

    # -- radio (spec §13) --------------------------------------------------
    def radio_list(self, *, refresh: bool = True) -> dict:
        return self.radio.list(refresh=refresh)

    # -- updates (spec §14) ------------------------------------------------
    def check_updates(self, *, manual: bool = False) -> dict:
        if not manual and not self.settings.auto_update:
            return {"online": False, "reason": "auto-update disabled", "updates": [], "app": None}
        return self.updater.check()

    def apply_update(self, component: str, *, url: str | None = None, version: str = "") -> dict:
        result = self.updater.apply(component, url=url, version=version)
        if component == "lexicon" and result.get("ok"):
            topics_mod.load_override(self.data_dir / "topics_override.json")
            self.classifier.refresh_lexicon()
        return result

    # -- about ---------------------------------------------------------------
    def knowledge_status(self) -> dict:
        lexicon, index = self.classifier.topic_lexicon, self.classifier.song_index
        return {
            "songs": len(index) if index else 0,
            "topics": len(lexicon.topics) if lexicon else 0,
            "sources": getattr(lexicon, "sources", 0),
            "version": getattr(lexicon, "version", "") or getattr(index, "version", ""),
        }

    def app_info(self) -> dict:
        model = self.classifier_status()
        return {
            "knowledge": self.knowledge_status(),
            "version": __version__,
            "edition": self.edition,
            "data_dir": str(self.data_dir),
            "downloads_dir": str(self.downloads_dir),
            "models_dir": str(self._model_cache_dir()),
            "model_bundled": bool(model.get("bundled")),
            "python": platform.python_version(),
            "platform": f"{platform.system()} {platform.release()}",
            "ytdlp": self.runner.version() or current_ytdlp_version(),
            "ffmpeg": bool(self.ffmpeg),
            "online_source": self.fetcher.available(),
            "executable": sys.executable,
        }

    # -- offline pack (spec §6.2) -----------------------------------------
    def _app_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _installed_pack_names(self) -> set[str]:
        marker = self.data_dir / "installed_packs.json"
        if not marker.exists():
            return set()
        try:
            return {r.get("pack") for r in json.loads(marker.read_text(encoding="utf-8"))}
        except Exception:
            return set()

    def offline_pack_status(self) -> dict:
        # Look for packs next to the app and in the data dir.
        found = find_packs(self._app_root()) + find_packs(self.data_dir)
        names = sorted({p.name for p in found})
        installed = self._installed_pack_names()
        return {
            "available": names,
            "installed": sorted(n for n in installed if n),
            "pending": [n for n in names if n not in installed],
        }

    def _auto_install_packs(self) -> list[dict]:
        installed = self._installed_pack_names()
        results = []
        for pack in find_packs(self._app_root()) + find_packs(self.data_dir):
            if pack.name in installed:
                continue
            try:
                results.append(install_pack(pack, self.data_dir))
                installed.add(pack.name)
            except PackError:
                continue
        return results

    def install_offline_pack(self, path: str | None = None) -> dict:
        if path:
            try:
                return install_pack(path, self.data_dir)
            except PackError as exc:
                return {"ok": False, "message": str(exc)}
        results = self._auto_install_packs()
        return {"ok": True, "installed_packs": results, "count": len(results)}

    def close(self) -> None:
        self.index.close()
