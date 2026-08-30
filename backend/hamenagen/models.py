"""Shared data models for a song/track and its metadata (spec §10)."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus", ".wma"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}


@dataclass
class Track:
    """A single media file known to the library."""

    id: str                         # stable id (hash of absolute path)
    path: str                       # absolute file path (for playback)
    title: str = ""
    artist: str = ""
    album: str = ""
    filename: str = ""
    duration: float | None = None   # seconds, if known
    is_video: bool = False
    source: str = "local"           # "local" | "youtube"
    topic: str | None = None        # assigned by the classifier
    topic_source: str = "none"
    download_date: str | None = None  # ISO 8601 — when added to the library
    release_date: str | None = None   # ISO 8601 — original publication date
    added_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict) -> "Track":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in row.items() if k in known})
