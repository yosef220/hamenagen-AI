"""Local metadata index backed by SQLite (spec §9, §10).

The index is the single source of truth for "what songs exist on this
machine". It is built by the scanner and queried by the service layer. SQLite
is used because it is embedded, zero-config, fast for the catalogue sizes we
expect, and ships with Python — keeping the app portable and offline.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from pathlib import Path

from .models import Track

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id            TEXT PRIMARY KEY,
    path          TEXT UNIQUE NOT NULL,
    title         TEXT,
    artist        TEXT,
    album         TEXT,
    filename      TEXT,
    duration      REAL,
    is_video      INTEGER DEFAULT 0,
    source        TEXT DEFAULT 'local',
    topic         TEXT,
    topic_source  TEXT DEFAULT 'none',
    download_date TEXT,
    release_date  TEXT,
    added_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_tracks_topic         ON tracks(topic);
CREATE INDEX IF NOT EXISTS idx_tracks_download_date ON tracks(download_date);
CREATE INDEX IF NOT EXISTS idx_tracks_release_date  ON tracks(release_date);
"""

_COLUMNS = [
    "id", "path", "title", "artist", "album", "filename", "duration",
    "is_video", "source", "topic", "topic_source", "download_date",
    "release_date", "added_at",
]


class MusicIndex:
    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "MusicIndex":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- writes ------------------------------------------------------------
    def upsert(self, track: Track) -> None:
        row = track.to_dict()
        row["is_video"] = 1 if track.is_video else 0
        placeholders = ", ".join(f":{c}" for c in _COLUMNS)
        updates = ", ".join(f"{c}=excluded.{c}" for c in _COLUMNS if c not in ("id", "path"))
        self._conn.execute(
            f"INSERT INTO tracks ({', '.join(_COLUMNS)}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}",
            {c: row.get(c) for c in _COLUMNS},
        )
        self._conn.commit()

    def upsert_many(self, tracks: Iterable[Track]) -> int:
        count = 0
        for t in tracks:
            self.upsert(t)
            count += 1
        return count

    def delete_missing(self, existing_ids: set[str]) -> int:
        cur = self._conn.execute("SELECT id FROM tracks")
        to_delete = [r["id"] for r in cur.fetchall() if r["id"] not in existing_ids]
        for tid in to_delete:
            self._conn.execute("DELETE FROM tracks WHERE id=?", (tid,))
        self._conn.commit()
        return len(to_delete)

    def set_topic(self, track_id: str, topic: str | None, source: str) -> None:
        self._conn.execute(
            "UPDATE tracks SET topic=?, topic_source=? WHERE id=?",
            (topic, source, track_id),
        )
        self._conn.commit()

    # -- reads -------------------------------------------------------------
    def _rows_to_tracks(self, rows: Iterable[sqlite3.Row]) -> list[Track]:
        out = []
        for r in rows:
            d = dict(r)
            d["is_video"] = bool(d.get("is_video"))
            out.append(Track.from_row(d))
        return out

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM tracks").fetchone()["n"]

    def all_tracks(self) -> list[Track]:
        return self._rows_to_tracks(self._conn.execute("SELECT * FROM tracks"))

    def iter_tracks(self) -> Iterator[Track]:
        for r in self._conn.execute("SELECT * FROM tracks"):
            d = dict(r)
            d["is_video"] = bool(d.get("is_video"))
            yield Track.from_row(d)

    def get(self, track_id: str) -> Track | None:
        r = self._conn.execute("SELECT * FROM tracks WHERE id=?", (track_id,)).fetchone()
        return self._rows_to_tracks([r])[0] if r else None

    def by_topic(self, topic: str, limit: int | None = None) -> list[Track]:
        sql = "SELECT * FROM tracks WHERE topic=? ORDER BY title"
        params: list = [topic]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return self._rows_to_tracks(self._conn.execute(sql, params))

    def recent_downloaded(self, limit: int = 25) -> list[Track]:
        return self._rows_to_tracks(
            self._conn.execute(
                "SELECT * FROM tracks WHERE download_date IS NOT NULL "
                "ORDER BY download_date DESC LIMIT ?",
                (limit,),
            )
        )

    def recent_released(self, limit: int = 25) -> list[Track]:
        return self._rows_to_tracks(
            self._conn.execute(
                "SELECT * FROM tracks WHERE release_date IS NOT NULL "
                "ORDER BY release_date DESC LIMIT ?",
                (limit,),
            )
        )

    def random(self, limit: int = 25) -> list[Track]:
        return self._rows_to_tracks(
            self._conn.execute("SELECT * FROM tracks ORDER BY RANDOM() LIMIT ?", (limit,))
        )
