"""Playlists in and out of the player (1.6).

In: an M3U/M3U8 or PLS file from another player, a CSV (a column for the
song's name, and the singer's if there is one — Exportify, other players), or
the ZIP Google Takeout makes of YouTube and YouTube Music, whose playlists
list only video ids. Each line is matched to a song in the library — by its
file (where it was, or the same file name elsewhere), by the YouTube id in
the name of a song the player downloaded, or by its name and singer — and
what is not found is counted and said, never dropped quietly.

Out: an M3U8 (UTF-8) that other players and phones read, beside the music
when it can be: a song under the playlist's folder is written by its relative
path, so the folder can move together.
"""

from __future__ import annotations

import csv
import io
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from .text_normalize import normalize

EXTENSIONS = (".m3u", ".m3u8", ".pls", ".csv", ".zip", ".txt")
MAX_ITEMS = 5000
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_ID_IN_NAME = re.compile(r"\[([A-Za-z0-9_-]{11})\]\.[A-Za-z0-9]+$")


@dataclass
class Entry:
    """One line of a playlist from outside, as much as it says."""
    path: str = ""
    title: str = ""
    artist: str = ""
    duration: float | None = None
    video_id: str = ""


@dataclass
class Parsed:
    name: str
    entries: list[Entry]


# ---------------------------------------------------------------- reading
def _decode(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="ignore")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1255", errors="ignore")


def _split_name(text: str) -> tuple[str, str]:
    """"Artist - Title" → (artist, title); a name with no dash is a title."""
    for sep in (" - ", " – ", " — "):
        if sep in text:
            a, t = text.split(sep, 1)
            return a.strip(), t.strip()
    return "", text.strip()


def _local_path(ref: str, base: Path | None) -> str:
    """A playlist line as a path: absolute as written (Windows or not), or
    relative to the playlist's own folder; a web address as it is."""
    ref = ref.strip()
    if ref.lower().startswith("file://"):
        from urllib.parse import unquote

        ref = unquote(ref[7:])
        if re.match(r"^/[A-Za-z]:", ref):
            ref = ref[1:]
    if re.match(r"^[a-z][a-z0-9+.-]+://", ref, re.IGNORECASE):
        return ref
    if re.match(r"^[A-Za-z]:[\\/]", ref) or ref.startswith(("\\\\", "/")):
        return ref
    rel = ref.replace("\\", "/")
    return str(base / rel) if base is not None else rel


def parse_m3u(text: str, base: Path | None = None) -> list[Entry]:
    out: list[Entry] = []
    info: tuple[float | None, str, str] | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.upper().startswith("#EXTINF:"):
            head, _, name = line[8:].partition(",")
            try:
                secs = float(head.split()[0])
            except (ValueError, IndexError):
                secs = None
            artist, title = _split_name(name)
            info = (secs if secs and secs > 0 else None, artist, title)
            continue
        if line.startswith("#"):
            continue
        e = Entry(path=_local_path(line, base))
        if info:
            e.duration, e.artist, e.title = info
        out.append(e)
        info = None
    return out


def parse_pls(text: str, base: Path | None = None) -> list[Entry]:
    rows: dict[int, Entry] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*(File|Title|Length)(\d+)\s*=\s*(.*)$", line, re.IGNORECASE)
        if not m:
            continue
        key, n, value = m.group(1).lower(), int(m.group(2)), m.group(3).strip()
        e = rows.setdefault(n, Entry())
        if key == "file":
            e.path = _local_path(value, base)
        elif key == "title":
            e.artist, e.title = _split_name(value)
        else:
            try:
                e.duration = float(value) if float(value) > 0 else None
            except ValueError:
                pass
    return [rows[n] for n in sorted(rows) if rows[n].path or rows[n].title]


_TITLE_COLUMNS = ("title", "song", "song title", "track", "track name", "name", "שם", "שם השיר", "שיר", "כותרת")
_ARTIST_COLUMNS = ("artist", "artist name", "artist name(s)", "artists", "singer", "זמר", "אמן", "מבצע")
_ID_COLUMNS = ("video id", "video_id", "videoid")
_PATH_COLUMNS = ("path", "file", "location", "נתיב", "קובץ")


def parse_csv(text: str) -> list[Entry]:
    """A CSV with a header row. Google Takeout's older playlists begin with a
    few lines about the playlist; the header is the row that names a column
    we know."""
    rows = list(csv.reader(io.StringIO(text)))
    header_at = None
    for i, row in enumerate(rows[:12]):
        names = {c.strip().lower() for c in row}
        if names & set(_TITLE_COLUMNS + _ID_COLUMNS + _PATH_COLUMNS):
            header_at = i
            break
    if header_at is None:
        return []
    header = [c.strip().lower() for c in rows[header_at]]

    def col(names) -> int | None:
        for n in names:
            if n in header:
                return header.index(n)
        return None

    ti, ai, vi, pi = col(_TITLE_COLUMNS), col(_ARTIST_COLUMNS), col(_ID_COLUMNS), col(_PATH_COLUMNS)
    out = []
    for row in rows[header_at + 1:]:
        def cell(i):
            return row[i].strip() if i is not None and i < len(row) else ""

        e = Entry(title=cell(ti), artist=cell(ai).split(";")[0].split(",")[0].strip(), path=cell(pi))
        vid = cell(vi)
        if _VIDEO_ID.match(vid):
            e.video_id = vid
        if e.title and not e.artist:
            e.artist, e.title = _split_name(e.title)
        if e.title or e.video_id or e.path:
            out.append(e)
    return out


def _parse_one(name: str, raw: bytes, base: Path | None) -> list[Entry]:
    text = _decode(raw)
    ext = Path(name).suffix.lower()
    if ext == ".pls" or text.lstrip().lower().startswith("[playlist]"):
        return parse_pls(text, base)
    if ext == ".csv":
        return parse_csv(text)
    return parse_m3u(text, base)


def _playlist_name(file_name: str) -> str:
    stem = PureWindowsPath(file_name).stem
    stem = re.sub(r"[-_ ]videos$", "", stem, flags=re.IGNORECASE)
    return stem.replace("_", " ").strip() or "רשימה מיובאת"


def read_file(path: str | Path) -> list[Parsed]:
    """The playlists in a file (a ZIP may hold many)."""
    p = Path(path)
    if p.suffix.lower() == ".zip":
        out = []
        with zipfile.ZipFile(p) as z:
            for info in z.infolist():
                low = info.filename.lower()
                if info.is_dir() or not low.endswith((".csv", ".m3u", ".m3u8", ".pls")):
                    continue
                # Takeout: only the playlists, not the subscriptions or the history.
                if low.endswith(".csv") and "playlist" not in low and "פלייליסט" not in low:
                    continue
                if info.file_size > 20 * 1024 * 1024:
                    continue
                entries = _parse_one(info.filename, z.read(info), None)
                if entries:
                    out.append(Parsed(_playlist_name(info.filename), entries[:MAX_ITEMS]))
        return out
    raw = p.read_bytes()[: 20 * 1024 * 1024]
    entries = _parse_one(p.name, raw, p.parent)
    return [Parsed(_playlist_name(p.name), entries[:MAX_ITEMS])] if entries else []


# ---------------------------------------------------------------- matching
class Matcher:
    """Finds the library's song for a line of an outside playlist."""

    def __init__(self, tracks, artist_name=lambda a: a):
        self.by_path: dict[str, str] = {}
        self.by_file: dict[str, list] = {}
        self.by_video: dict[str, str] = {}
        self.by_title: dict[str, list] = {}
        self.artist_name = artist_name
        for t in tracks:
            if t.dup_of:
                continue
            self.by_path[os.path.normcase(os.path.normpath(t.path))] = t.id
            self.by_file.setdefault(Path(t.path).name.lower(), []).append(t)
            m = _ID_IN_NAME.search(t.path or "")
            if m:
                self.by_video[m.group(1)] = t.id
            key = normalize(t.title or Path(t.path).stem)
            if key:
                self.by_title.setdefault(key, []).append(t)

    def _same_artist(self, a: str, b: str) -> bool:
        if not a or not b:
            return True
        return normalize(self.artist_name(a)) == normalize(self.artist_name(b))

    def find(self, e: Entry) -> str | None:
        if e.video_id and e.video_id in self.by_video:
            return self.by_video[e.video_id]
        if e.path:
            hit = self.by_path.get(os.path.normcase(os.path.normpath(e.path)))
            if hit:
                return hit
            name = PureWindowsPath(e.path).name.lower()
            files = self.by_file.get(name) or []
            if len(files) == 1:
                return files[0].id
            if files:  # the same name in two folders: the one whose singer and length agree
                for t in files:
                    if self._same_artist(e.artist, t.artist) and (
                            not e.duration or not t.duration or abs(t.duration - e.duration) <= 3):
                        return t.id
            m = _ID_IN_NAME.search(e.path)
            if m and m.group(1) in self.by_video:
                return self.by_video[m.group(1)]
            if not e.title:
                guess, e.title = _split_name(PureWindowsPath(e.path).stem)
                e.artist = e.artist or guess
        title = normalize(e.title)
        if not title:
            return None
        for t in self.by_title.get(title, []):
            if self._same_artist(e.artist, t.artist) and (
                    not e.duration or not t.duration or abs(t.duration - e.duration) <= 5):
                return t.id
        return None


# ---------------------------------------------------------------- writing
def write_m3u8(tracks, dest: str | Path, *, artist_name=lambda a: a) -> Path:
    """Write the songs to ``dest`` (a .m3u8 file) and return its path."""
    dest = Path(dest)
    base = dest.parent.resolve()
    lines = ["#EXTM3U"]
    for t in tracks:
        artist = artist_name(t.artist) if t.artist else ""
        name = f"{artist} - {t.title}" if artist and t.title else (t.title or Path(t.path).stem)
        lines.append(f"#EXTINF:{int(round(t.duration)) if t.duration else -1},{name}")
        path = Path(t.path)
        try:
            rel = path.resolve().relative_to(base)
            lines.append(str(rel))
        except ValueError:
            lines.append(str(path))
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, dest)
    return dest


def safe_file_name(name: str) -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", name).strip(" .") or "רשימה"
    return " ".join(clean.split())[:100]
