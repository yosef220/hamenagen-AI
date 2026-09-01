"""Application service layer — orchestrates the core modules.

This is the single entry point the front-end (Electron via RPC) and the CLI
talk to. It owns the index, the classifier, the fetcher and the settings, and
turns a natural-language request into a concrete playlist by combining the
intent engine, the topic classifier and the fuzzy matcher.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from datetime import datetime

from . import intent as intent_mod
from .classifier import EmbeddingBackend, HybridClassifier
from .fetcher import OnlineFetcher, ProgressHook, SearchResult
from .fuzzy import MatchCandidate, search as fuzzy_search
from .hebrew_calendar import detect_occasion, from_gregorian
from .index_db import MusicIndex
from .intent import Action, Intent
from .models import Track
from .offline_pack import PackError, find_packs, install_pack
from .radio import RadioProvider
from .scanner import read_sidecar_lyrics, scan_file, scan_roots
from .settings import Settings, default_data_dir
from .updater import Updater


class PlayerService:
    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings = Settings.load(self.data_dir / "settings.json")
        self.index = MusicIndex(self.data_dir / "library.db")
        self.models_dir = self.data_dir / "models"
        backend = self._build_backend()
        self.classifier = HybridClassifier(backend)
        self.fetcher = OnlineFetcher()
        self.downloads_dir = self.data_dir / "downloads"
        self.radio = RadioProvider(
            self.settings.radio_list_url,
            cache_path=self.data_dir / "radio_cache.json",
        )
        self.updater = Updater(self.settings.update_manifest_url, self.data_dir)
        # First-run offline install: pick up any *.pack sitting next to the app.
        try:
            self._auto_install_packs()
        except Exception:
            pass

    def _build_backend(self) -> EmbeddingBackend | None:
        if not self.settings.use_embeddings:
            return None
        return EmbeddingBackend(
            self.settings.embedding_model,
            threshold=self.settings.embedding_threshold,
            cache_dir=str(self.models_dir),
        )

    # -- library management ------------------------------------------------
    def _roots(self) -> list[str]:
        if self.settings.scan_roots:
            return self.settings.scan_roots
        return [str(Path.home())]  # sensible default; the UI can widen this

    def rescan(self, roots: list[str] | None = None, index: MusicIndex | None = None) -> dict:
        """Scan the configured roots, refresh the index and classify songs.

        Pass ``index`` to write through a caller-owned connection. When called
        from a background thread, leave it ``None`` — SQLite connections are
        bound to one thread, so we open a fresh connection to the same DB file
        (WAL mode lets the UI keep reading meanwhile).
        """
        use_roots = roots or self._roots()
        own = index is None
        idx = index or MusicIndex(self.data_dir / "library.db")
        try:
            seen: set[str] = set()
            added = 0
            for track in scan_roots(use_roots, include_video=self.settings.include_video):
                seen.add(track.id)
                if idx.get(track.id) is None:
                    self._classify_track(track)
                    idx.upsert(track)
                    added += 1
            removed = idx.delete_missing(seen)
            return {"scanned_roots": use_roots, "added": added, "removed": removed, "total": idx.count()}
        finally:
            if own:
                idx.close()

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
        return track

    # -- AI classifier management (spec §8.2) -----------------------------
    def classifier_status(self) -> dict:
        """Report the state of the local embedding layer, for the UI/settings."""
        backend = self.classifier.embedding
        if backend is None:
            return {"enabled": False, "available": False, "model": None}
        st = backend.status()
        st["enabled"] = True
        return st

    def install_model(self) -> dict:
        """Ensure the local AI model is downloaded (first-run install, spec §6.1).

        Loading the backend downloads the model once when online; afterwards it
        is used offline. Safe to call repeatedly — it no-ops once installed.
        """
        backend = self.classifier.embedding
        if backend is None:
            return {"ok": False, "reason": "embeddings disabled", **self.classifier_status()}
        ok = backend.load()
        return {"ok": ok, **self.classifier_status()}

    def reclassify_all(self) -> dict:
        """Re-run classification over every indexed track (e.g. after enabling
        embeddings or updating the lexicon). Returns how many changed."""
        # Rebuild the backend in case settings changed since construction.
        self.classifier.embedding = self._build_backend()
        changed = 0
        for track in self.index.all_tracks():
            before = track.topic
            self._classify_track(track)
            if track.topic != before:
                self.index.set_topic(track.id, track.topic, track.topic_source)
                changed += 1
        return {"total": self.index.count(), "changed": changed, **self.classifier_status()}

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
        track.source = "youtube"
        # Use the source's upload date as the "release date" (spec §10 note).
        if src.upload_date and len(src.upload_date) == 8:
            track.release_date = (
                f"{src.upload_date[:4]}-{src.upload_date[4:6]}-{src.upload_date[6:]}"
            )
        track.download_date = datetime.now().isoformat()
        self._classify_track(track)
        self.index.upsert(track)
        return {"ok": True, "message": outcome.message, "track": track.to_dict(), "path": outcome.path}

    def _candidates(self) -> list[MatchCandidate]:
        return [
            MatchCandidate(
                id=t.id, title=t.title, artist=t.artist, album=t.album, filename=t.filename
            )
            for t in self.index.iter_tracks()
        ]

    # -- the main request path --------------------------------------------
    def handle_request(self, text: str) -> dict:
        """Turn a free Hebrew request into a playlist + explanation."""
        intent = intent_mod.parse(text)
        tracks, note = self._execute(intent)
        return {
            "intent": intent.to_dict(),
            "tracks": [t.to_dict() for t in tracks],
            "count": len(tracks),
            "note": note,
            "found_local": bool(tracks),
        }

    def _execute(self, intent: Intent) -> tuple[list[Track], str]:
        limit = intent.limit or 50

        if intent.action == Action.RECENT_DOWNLOADED:
            return self.index.recent_downloaded(limit), "השירים האחרונים שהורדת."
        if intent.action == Action.RECENT_RELEASED:
            return self.index.recent_released(limit), "השירים האחרונים שיצאו."
        if intent.action == Action.RANDOM:
            return self.index.random(limit), "מבחר אקראי."
        if intent.action == Action.PLAY_TOPIC and intent.topic:
            tracks = self.index.by_topic(intent.topic, limit)
            label = intent.topic
            if tracks:
                return tracks, f"שירים בנושא {label}."
            return [], f"לא נמצאו שירים בנושא {label} במאגר המקומי."

        # SEARCH_SONG (or fallback).
        query = intent.query or intent.raw
        results = fuzzy_search(query, self._candidates(), limit=limit)
        by_id = {t.id: t for t in self.index.iter_tracks()}
        tracks = [by_id[r.candidate.id] for r in results if r.candidate.id in by_id]
        if tracks:
            return tracks, f"תוצאות חיפוש עבור: {query}"
        return [], "לא נמצא שיר מתאים במאגר המקומי."

    # -- radio (spec §13) --------------------------------------------------
    def radio_list(self, *, refresh: bool = True) -> dict:
        return self.radio.list(refresh=refresh)

    # -- updates (spec §14) ------------------------------------------------
    def check_updates(self) -> dict:
        if not self.settings.auto_update and not self.settings.update_manifest_url:
            return {"online": False, "reason": "auto-update disabled", "updates": []}
        return self.updater.check()

    def apply_update(self, component: str, *, url: str | None = None, version: str = "") -> dict:
        return self.updater.apply(component, url=url, version=version)

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

    # -- time-based suggestion (spec §7) ----------------------------------
    def opening_suggestion(self, on: date | None = None) -> dict | None:
        occ = detect_occasion(on)
        if occ is None:
            return None
        heb = from_gregorian(on or date.today())
        available = self.index.by_topic(occ.topic, limit=1)
        return {
            "occasion_key": occ.key,
            "label": occ.label,
            "topic": occ.topic,
            "hebrew_date": str(heb),
            "has_songs": bool(available),
        }

    def close(self) -> None:
        self.index.close()
