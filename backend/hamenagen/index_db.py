"""Local metadata index backed by SQLite (spec §9, §10).

The index is the single source of truth for "what songs exist on this
machine", plus what the listener did with them (favorites, play history).
It is built by the scanner and queried by the service layer. SQLite is used
because it is embedded, zero-config, fast for the catalogue sizes we expect,
and ships with Python — keeping the app portable and offline.

One :class:`MusicIndex` may be shared by several threads (the RPC server runs
slow requests in workers): every call holds an internal lock, and the
connection is opened with ``check_same_thread=False``. A background scan
opens its own connection to the same file; WAL mode lets it write while the
UI keeps reading.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Iterator
from datetime import datetime
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
CREATE TABLE IF NOT EXISTS favorites (
    track_id  TEXT PRIMARY KEY,
    added_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plays (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id   TEXT NOT NULL,
    played_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key    TEXT PRIMARY KEY,
    value  TEXT
);
CREATE INDEX IF NOT EXISTS idx_tracks_topic         ON tracks(topic);
CREATE INDEX IF NOT EXISTS idx_tracks_download_date ON tracks(download_date);
CREATE INDEX IF NOT EXISTS idx_tracks_release_date  ON tracks(release_date);
CREATE INDEX IF NOT EXISTS idx_plays_track          ON plays(track_id);
CREATE INDEX IF NOT EXISTS idx_plays_time           ON plays(played_at);
"""

# Columns added after 0.1 — created on open when an older library lacks them.
_MIGRATIONS = {
    "tags": "TEXT DEFAULT ''",
    "mtime": "REAL",
    "size": "INTEGER",
}

_COLUMNS = [
    "id", "path", "title", "artist", "album", "filename", "duration",
    "is_video", "source", "topic", "topic_source", "download_date",
    "release_date", "added_at", "tags", "mtime", "size",
]

# Sort keys the library table may ask for → SQL ORDER BY expressions. Empty
# values sort last ('תתת' collates after every Hebrew word).
_SORTS: dict[str, list[str]] = {
    "title": ["COALESCE(NULLIF(title, ''), filename) COLLATE NOCASE"],
    "artist": ["COALESCE(NULLIF(artist, ''), 'תתת') COLLATE NOCASE", "title COLLATE NOCASE"],
    "album": ["COALESCE(NULLIF(album, ''), 'תתת') COLLATE NOCASE", "title COLLATE NOCASE"],
    "topic": ["COALESCE(NULLIF(topic, ''), 'תתת')", "title COLLATE NOCASE"],
    "duration": ["COALESCE(duration, 0)"],
    "added": ["COALESCE(download_date, added_at)"],
    "released": ["COALESCE(release_date, '')"],
}

# The fallback length (seconds) for a song whose duration is unknown, when a
# playlist is built to fill a span of time.
AVERAGE_SONG_SECONDS = 240.0


def _tag_pattern(topic: str) -> str:
    return f"%|{topic}|%"


def encode_tags(tags: Iterable[str]) -> str:
    """Store tags as ``|a|b|`` so a topic is found with one LIKE."""
    clean = [t for t in tags if t]
    return f"|{'|'.join(clean)}|" if clean else ""


def decode_tags(raw: str | None) -> list[str]:
    return [t for t in (raw or "").split("|") if t]


class MusicIndex:
    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        # WAL lets a background scan (separate connection) write while the UI
        # reads, so scanning never freezes playback/search. A busy timeout
        # avoids "database is locked" under that concurrency.
        if self.db_path != ":memory:":
            try:
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA synchronous=NORMAL")
                self._conn.execute("PRAGMA busy_timeout=5000")
            except sqlite3.Error:
                pass
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        have = {r["name"] for r in self._conn.execute("PRAGMA table_info(tracks)")}
        for column, decl in _MIGRATIONS.items():
            if column not in have:
                self._conn.execute(f"ALTER TABLE tracks ADD COLUMN {column} {decl}")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_tags ON tracks(tags)")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "MusicIndex":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- writes ------------------------------------------------------------
    def upsert(self, track: Track, *, commit: bool = True) -> None:
        row = track.to_dict()
        row["is_video"] = 1 if track.is_video else 0
        placeholders = ", ".join(f":{c}" for c in _COLUMNS)
        updates = ", ".join(f"{c}=excluded.{c}" for c in _COLUMNS if c not in ("id", "path"))
        with self._lock:
            self._conn.execute(
                f"INSERT INTO tracks ({', '.join(_COLUMNS)}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}",
                {c: row.get(c) for c in _COLUMNS},
            )
            if commit:
                self._conn.commit()

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    def upsert_many(self, tracks: Iterable[Track]) -> int:
        count = 0
        with self._lock:
            for t in tracks:
                self.upsert(t, commit=False)
                count += 1
            self._conn.commit()
        return count

    def delete_missing(self, existing_ids: set[str]) -> int:
        with self._lock:
            cur = self._conn.execute("SELECT id FROM tracks")
            to_delete = [r["id"] for r in cur.fetchall() if r["id"] not in existing_ids]
            self._conn.executemany("DELETE FROM tracks WHERE id=?", [(t,) for t in to_delete])
            self._conn.commit()
        return len(to_delete)

    def delete_ids(self, track_ids: Iterable[str]) -> int:
        ids = [(t,) for t in track_ids]
        with self._lock:
            self._conn.executemany("DELETE FROM tracks WHERE id=?", ids)
            self._conn.commit()
        return len(ids)

    def set_topic(self, track_id: str, topic: str | None, source: str, tags: str | None = None) -> None:
        with self._lock:
            if tags is None:
                self._conn.execute(
                    "UPDATE tracks SET topic=?, topic_source=? WHERE id=?",
                    (topic, source, track_id),
                )
            else:
                self._conn.execute(
                    "UPDATE tracks SET topic=?, topic_source=?, tags=? WHERE id=?",
                    (topic, source, tags, track_id),
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

    def _query(self, sql: str, params: Iterable = ()) -> list[Track]:
        with self._lock:
            return self._rows_to_tracks(self._conn.execute(sql, tuple(params)).fetchall())

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) AS n FROM tracks").fetchone()["n"]

    def all_tracks(self) -> list[Track]:
        return self._query("SELECT * FROM tracks")

    def iter_tracks(self) -> Iterator[Track]:
        # Materialised under the lock so another thread cannot interleave with
        # the cursor; the catalogue comfortably fits in memory.
        yield from self.all_tracks()

    def get(self, track_id: str) -> Track | None:
        found = self._query("SELECT * FROM tracks WHERE id=?", (track_id,))
        return found[0] if found else None

    def get_many(self, track_ids: list[str]) -> list[Track]:
        """Tracks by id, in the order asked (missing ids are skipped)."""
        if not track_ids:
            return []
        marks = ",".join("?" for _ in track_ids)
        by_id = {t.id: t for t in self._query(f"SELECT * FROM tracks WHERE id IN ({marks})", track_ids)}
        return [by_id[i] for i in track_ids if i in by_id]

    def file_state(self) -> dict[str, tuple[float | None, int | None]]:
        """``{id: (mtime, size)}`` — lets a rescan skip files it already knows."""
        with self._lock:
            return {
                r["id"]: (r["mtime"], r["size"])
                for r in self._conn.execute("SELECT id, mtime, size FROM tracks")
            }

    def by_topic(self, topic: str, limit: int | None = None, *, shuffle: bool = False) -> list[Track]:
        """Songs whose main topic — or one of whose tags — is ``topic``."""
        order = "RANDOM()" if shuffle else "COALESCE(NULLIF(title, ''), filename) COLLATE NOCASE"
        sql = f"SELECT * FROM tracks WHERE topic=? OR tags LIKE ? ORDER BY {order}"
        params: list = [topic, _tag_pattern(topic)]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return self._query(sql, params)

    def topic_counts(self) -> dict[str, int]:
        """How many songs each topic has (main topic or tag)."""
        counts: dict[str, int] = {}
        with self._lock:
            rows = self._conn.execute("SELECT topic, tags FROM tracks").fetchall()
        for r in rows:
            seen = set(decode_tags(r["tags"]))
            if r["topic"]:
                seen.add(r["topic"])
            for t in seen:
                counts[t] = counts.get(t, 0) + 1
        return counts

    def recent_downloaded(self, limit: int = 25) -> list[Track]:
        return self._query(
            "SELECT * FROM tracks WHERE download_date IS NOT NULL ORDER BY download_date DESC LIMIT ?",
            (limit,),
        )

    def recent_released(self, limit: int = 25) -> list[Track]:
        return self._query(
            "SELECT * FROM tracks WHERE release_date IS NOT NULL AND release_date != '' "
            "ORDER BY release_date DESC LIMIT ?",
            (limit,),
        )

    def random(self, limit: int = 25) -> list[Track]:
        return self._query("SELECT * FROM tracks ORDER BY RANDOM() LIMIT ?", (limit,))

    def list_tracks(
        self,
        *,
        sort: str = "title",
        descending: bool = False,
        topic: str | None = None,
        text: str = "",
        favorites_only: bool = False,
        source: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> dict:
        """One page of the library table, with the total that matches."""
        where: list[str] = []
        params: list = []
        if source:
            where.append("source = ?")
            params.append(source)
        if topic == "__none__":
            where.append("(topic IS NULL OR topic = '')")
        elif topic:
            where.append("(topic=? OR tags LIKE ?)")
            params += [topic, _tag_pattern(topic)]
        if favorites_only:
            where.append("id IN (SELECT track_id FROM favorites)")
        if text.strip():
            like = f"%{text.strip()}%"
            where.append("(title LIKE ? OR artist LIKE ? OR album LIKE ? OR filename LIKE ?)")
            params += [like, like, like, like]
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        order = ", ".join(
            f"{expr} DESC" if descending else expr for expr in _SORTS.get(sort, _SORTS["title"])
        )
        with self._lock:
            total = self._conn.execute(f"SELECT COUNT(*) AS n FROM tracks {clause}", params).fetchone()["n"]
            rows = self._conn.execute(
                f"SELECT * FROM tracks {clause} ORDER BY {order} LIMIT ? OFFSET ?",
                [*params, max(1, min(int(limit), 1000)), max(0, int(offset))],
            ).fetchall()
        return {"total": total, "offset": offset, "tracks": self._rows_to_tracks(rows)}

    def stats(self) -> dict:
        with self._lock:
            r = self._conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(duration), 0) AS secs, "
                "SUM(CASE WHEN topic IS NULL OR topic = '' THEN 1 ELSE 0 END) AS untagged, "
                "SUM(CASE WHEN source != 'local' THEN 1 ELSE 0 END) AS downloaded "
                "FROM tracks"
            ).fetchone()
            favs = self._conn.execute("SELECT COUNT(*) AS n FROM favorites").fetchone()["n"]
        return {
            "tracks": r["n"],
            "seconds": float(r["secs"] or 0),
            "untagged": int(r["untagged"] or 0),
            "downloaded": int(r["downloaded"] or 0),
            "favorites": favs,
        }

    # -- favorites ---------------------------------------------------------
    def set_favorite(self, track_id: str, on: bool) -> bool:
        with self._lock:
            if on:
                self._conn.execute(
                    "INSERT OR IGNORE INTO favorites (track_id, added_at) VALUES (?, ?)",
                    (track_id, datetime.now().isoformat(timespec="seconds")),
                )
            else:
                self._conn.execute("DELETE FROM favorites WHERE track_id=?", (track_id,))
            self._conn.commit()
        return on

    def favorite_ids(self) -> set[str]:
        with self._lock:
            return {r["track_id"] for r in self._conn.execute("SELECT track_id FROM favorites")}

    def favorites(self, limit: int = 500) -> list[Track]:
        return self._query(
            "SELECT t.* FROM tracks t JOIN favorites f ON f.track_id = t.id "
            "ORDER BY f.added_at DESC LIMIT ?",
            (limit,),
        )

    # -- play history ------------------------------------------------------
    def record_play(self, track_id: str, when: datetime | None = None) -> None:
        stamp = (when or datetime.now()).isoformat(timespec="seconds")
        with self._lock:
            self._conn.execute("INSERT INTO plays (track_id, played_at) VALUES (?, ?)", (track_id, stamp))
            self._conn.commit()

    def history(self, limit: int = 50) -> list[Track]:
        """Recently played songs, most recent first, each song once."""
        return self._query(
            "SELECT t.* FROM tracks t JOIN ("
            "  SELECT track_id, MAX(played_at) AS last FROM plays GROUP BY track_id"
            ") p ON p.track_id = t.id ORDER BY p.last DESC LIMIT ?",
            (limit,),
        )

    def most_played(self, limit: int = 50) -> list[Track]:
        return self._query(
            "SELECT t.* FROM tracks t JOIN ("
            "  SELECT track_id, COUNT(*) AS n, MAX(played_at) AS last FROM plays GROUP BY track_id"
            ") p ON p.track_id = t.id ORDER BY p.n DESC, p.last DESC LIMIT ?",
            (limit,),
        )

    def play_counts(self, track_ids: list[str]) -> dict[str, int]:
        if not track_ids:
            return {}
        marks = ",".join("?" for _ in track_ids)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT track_id, COUNT(*) AS n FROM plays WHERE track_id IN ({marks}) GROUP BY track_id",
                track_ids,
            ).fetchall()
        return {r["track_id"]: r["n"] for r in rows}

    # -- meta --------------------------------------------------------------
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            r = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            self._conn.commit()
