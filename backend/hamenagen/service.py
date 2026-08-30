"""Application service layer — orchestrates the core modules.

This is the single entry point the front-end (Electron via RPC) and the CLI
talk to. It owns the index, the classifier, the fetcher and the settings, and
turns a natural-language request into a concrete playlist by combining the
intent engine, the topic classifier and the fuzzy matcher.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from . import intent as intent_mod
from .classifier import EmbeddingBackend, HybridClassifier
from .fuzzy import MatchCandidate, search as fuzzy_search
from .hebrew_calendar import detect_occasion, from_gregorian
from .index_db import MusicIndex
from .intent import Action, Intent
from .models import Track
from .scanner import scan_roots
from .settings import Settings, default_data_dir


class PlayerService:
    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings = Settings.load(self.data_dir / "settings.json")
        self.index = MusicIndex(self.data_dir / "library.db")
        backend = EmbeddingBackend() if self.settings.use_embeddings else None
        self.classifier = HybridClassifier(backend)

    # -- library management ------------------------------------------------
    def _roots(self) -> list[str]:
        if self.settings.scan_roots:
            return self.settings.scan_roots
        return [str(Path.home())]  # sensible default; the UI can widen this

    def rescan(self, roots: list[str] | None = None) -> dict:
        """Scan the configured roots, refresh the index and classify songs."""
        use_roots = roots or self._roots()
        seen: set[str] = set()
        added = 0
        for track in scan_roots(use_roots, include_video=self.settings.include_video):
            seen.add(track.id)
            existing = self.index.get(track.id)
            if existing is None:
                cls = self.classifier.classify(
                    title=track.title,
                    artist=track.artist,
                    album=track.album,
                    filename=track.filename,
                    use_embeddings=self.settings.use_embeddings,
                )
                track.topic = cls.topic
                track.topic_source = cls.source
                self.index.upsert(track)
                added += 1
        removed = self.index.delete_missing(seen)
        return {"scanned_roots": use_roots, "added": added, "removed": removed, "total": self.index.count()}

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
