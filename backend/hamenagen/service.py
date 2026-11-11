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
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from . import __version__
from . import intent as intent_mod
from . import settings as settings_mod
from . import topics as topics_mod
from .classifier import EmbeddingBackend, HybridClassifier
from .fetcher import OnlineFetcher, ProgressHook, SearchResult
from .fuzzy import MatchCandidate, search as fuzzy_search
from .hebrew_calendar import detect_occasion, from_gregorian, today_info
from .index_db import AVERAGE_SONG_SECONDS, MusicIndex, encode_tags
from .intent import Action, Intent
from .models import Track
from .offline_pack import PackError, find_packs, install_pack
from .radio import RadioProvider
from .scanner import (
    default_roots,
    is_too_short,
    iter_media_files,
    read_sidecar_lyrics,
    scan_file,
    track_id_for,
)
from .settings import Settings, bundled_models_dir, default_data_dir, default_downloads_dir
from .text_normalize import normalize
from .updater import Updater, current_ytdlp_version

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
        self.fetcher = OnlineFetcher()
        self.radio = RadioProvider(
            self.settings.radio_list_url,
            cache_path=self.data_dir / "radio_cache.json",
        )
        self.updater = Updater(self.settings.update_manifest_url, self.data_dir, edition=self.edition)
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
            seen: set[str] = set()
            added = updated = files = 0
            for path, st in iter_media_files(use_roots, include_video=self.settings.include_video):
                files += 1
                tid = track_id_for(path)
                previous = known.get(tid)
                if previous and previous == (st.st_mtime, st.st_size):
                    seen.add(tid)
                elif (track := scan_file(path, include_video=self.settings.include_video, stat=st)) is not None \
                        and not is_too_short(track):
                    seen.add(tid)
                    if previous:
                        old = idx.get(tid)
                        if old is not None and old.source != "local":
                            # Keep what we learned when it was downloaded.
                            track.title, track.artist = old.title or track.title, old.artist or track.artist
                            track.source, track.release_date = old.source, old.release_date
                            track.download_date = old.download_date or track.download_date
                    self._classify_track(track)
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
            finished = datetime.now()
            idx.set_meta("last_scan_at", finished.isoformat(timespec="seconds"))
            return {
                "scanned_roots": use_roots,
                "files": files,
                "added": added,
                "updated": updated,
                "removed": removed,
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

    def _classify_track(self, track: Track) -> Track:
        lyrics = ""
        if self.settings.classify_by_lyrics and track.path:
            lyrics = read_sidecar_lyrics(track.path)
        cls = self.classifier.classify(
            title=track.title,
            artist=track.artist,
            album=track.album,
            filename=track.filename,
            lyrics=lyrics,
            use_embeddings=self.settings.use_embeddings,
        )
        track.topic = cls.topic
        track.topic_source = cls.source
        track.tags = encode_tags(cls.tags)
        return track

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
        for n, track in enumerate(tracks, 1):
            before = (track.topic, track.tags)
            self._classify_track(track)
            if (track.topic, track.tags) != before:
                self.index.set_topic(track.id, track.topic, track.topic_source, track.tags)
                changed += 1
            if on_progress and n % 100 == 0:
                on_progress({"done": n, "total": len(tracks), "changed": changed})
        return {"total": len(tracks), "changed": changed, **self.classifier_status()}

    # -- online completion (spec §11) -------------------------------------
    def online_available(self) -> bool:
        return self.fetcher.available()

    def download_and_add(self, result: SearchResult, on_progress: ProgressHook | None = None) -> dict:
        """Download a chosen result, add it to the library, and return its Track.

        Implements the tail of the spec §11 flow: the file lands in the local
        library, gets indexed + classified, and the caller (UI) auto-plays it
        unless the user opted out.
        """
        outcome = self.fetcher.download(result, self.downloads_dir, on_progress=on_progress)
        if not outcome.ok or not outcome.path:
            return {"ok": False, "message": outcome.message, "track": None}

        track = scan_file(outcome.path, include_video=self.settings.include_video)
        if track is None:
            return {"ok": True, "message": outcome.message, "track": None, "path": outcome.path}

        # Prefer metadata from the source over filename parsing (spec §10).
        src = outcome.result or result
        if src.title:
            track.title = src.title
        if src.uploader:
            track.artist = track.artist or src.uploader
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
        return {"ok": True, "message": outcome.message, "track": self._track_dict(track), "path": outcome.path}

    def _candidates(self) -> list[MatchCandidate]:
        return [
            MatchCandidate(
                id=t.id, title=t.title, artist=t.artist, album=t.album, filename=t.filename
            )
            for t in self.index.iter_tracks()
        ]

    # -- shaping tracks for the UI -------------------------------------------
    def _track_dict(self, track: Track, favorites: set[str] | None = None) -> dict:
        d = track.to_dict()
        d["tags"] = track.tag_list
        d["favorite"] = track.id in (favorites if favorites is not None else self.index.favorite_ids())
        d.pop("mtime", None)
        d.pop("size", None)
        return d

    def _tracks_payload(self, tracks: list[Track]) -> list[dict]:
        favs = self.index.favorite_ids()
        return [self._track_dict(t, favs) for t in tracks]

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
            # SEARCH_SONG (or fallback).
            query = intent.query or intent.raw
            found = fuzzy_search(query, self._candidates(), limit=limit)
            by_id = {t.id: t for t in self.index.get_many([r.candidate.id for r in found])}
            tracks = [by_id[r.candidate.id] for r in found if r.candidate.id in by_id]
            understood = f"חיפוש: {_display_query(intent.raw) or query}"
            if not tracks:
                return [], understood, "השיר לא נמצא במחשב. אפשר לחפש אותו ברשת."
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
    def app_info(self) -> dict:
        model = self.classifier_status()
        return {
            "version": __version__,
            "edition": self.edition,
            "data_dir": str(self.data_dir),
            "downloads_dir": str(self.downloads_dir),
            "models_dir": str(self._model_cache_dir()),
            "model_bundled": bool(model.get("bundled")),
            "python": platform.python_version(),
            "platform": f"{platform.system()} {platform.release()}",
            "ytdlp": current_ytdlp_version(),
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
