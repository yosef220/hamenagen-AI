"""Library scanner (spec §5 Library Scanner, §9).

Walks the file system (the whole machine, or a configured set of roots),
finds media files, extracts what metadata it can, and yields :class:`Track`
objects for the index. Tag reading uses the optional :mod:`mutagen` package
when available; otherwise it degrades gracefully to filename parsing so the
core keeps working with no extra dependency.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from .models import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, Track

try:  # optional richer tag reading
    import mutagen  # type: ignore

    _HAVE_MUTAGEN = True
except Exception:  # pragma: no cover
    mutagen = None
    _HAVE_MUTAGEN = False

# Directories we never descend into — noise, and often huge.
_SKIP_DIR_NAMES = {
    "$recycle.bin", "system volume information", "windows", "program files",
    "program files (x86)", "programdata", "appdata", "node_modules",
    ".git", "__pycache__", ".cache",
}


def _stable_id(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8")).hexdigest()[:16]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _parse_filename(stem: str) -> tuple[str, str]:
    """Best-effort ``(artist, title)`` from a filename like 'Artist - Title'."""
    for sep in (" - ", " – ", "_-_", " — "):
        if sep in stem:
            left, right = stem.split(sep, 1)
            return left.strip(), right.strip()
    return "", stem.strip()


def _read_tags(path: Path) -> dict:
    """Return a dict of tags, using mutagen when available."""
    info: dict = {}
    if not _HAVE_MUTAGEN:
        return info
    try:  # pragma: no cover - depends on optional dependency + real files
        audio = mutagen.File(path, easy=True)
        if audio is None:
            return info
        if getattr(audio, "tags", None):
            for key, dest in (("title", "title"), ("artist", "artist"), ("album", "album")):
                val = audio.tags.get(key)
                if val:
                    info[dest] = val[0] if isinstance(val, list) else str(val)
            date = audio.tags.get("date") or audio.tags.get("originaldate")
            if date:
                info["release_date"] = str(date[0] if isinstance(date, list) else date)
        if getattr(audio, "info", None) and getattr(audio.info, "length", None):
            info["duration"] = float(audio.info.length)
    except Exception:
        pass
    return info


def read_sidecar_lyrics(path: str | Path, *, max_chars: int = 4000) -> str:
    """Return lyrics from a sibling .lrc/.txt file next to the track, if any.

    Used by the topic classifier when ``classify_by_lyrics`` is on (spec §8.2,
    §19.3). Timestamps in .lrc files are stripped. Returns "" when none found.
    """
    p = Path(path)
    for ext in (".lrc", ".txt"):
        cand = p.with_suffix(ext)
        if cand.exists() and cand.is_file():
            try:
                text = cand.read_text(encoding="utf-8", errors="ignore")[:max_chars]
            except OSError:
                return ""
            if ext == ".lrc":  # drop [mm:ss.xx] timestamps
                import re

                text = re.sub(r"\[\d+:\d+(?:\.\d+)?\]", " ", text)
            return text.strip()
    return ""


def scan_file(path: str | Path, *, include_video: bool = False) -> Track | None:
    p = Path(path)
    ext = p.suffix.lower()
    is_video = ext in VIDEO_EXTENSIONS
    if ext not in AUDIO_EXTENSIONS and not (include_video and is_video):
        return None
    try:
        stat = p.stat()
    except OSError:
        return None

    abspath = str(p.resolve())
    tags = _read_tags(p)
    artist, title = _parse_filename(p.stem)

    return Track(
        id=_stable_id(abspath),
        path=abspath,
        title=tags.get("title") or title,
        artist=tags.get("artist") or artist,
        album=tags.get("album", ""),
        filename=p.name,
        duration=tags.get("duration"),
        is_video=is_video,
        source="local",
        # download_date := when the file landed on this machine.
        download_date=_iso(getattr(stat, "st_ctime", stat.st_mtime)),
        # release_date := from tags if present (may be back-filled later).
        release_date=tags.get("release_date"),
    )


def scan_roots(
    roots: list[str | Path],
    *,
    include_video: bool = False,
    follow_symlinks: bool = False,
) -> Iterator[Track]:
    """Yield a :class:`Track` for every media file under the given roots."""
    for root in roots:
        root_path = Path(root)
        if not root_path.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root_path, followlinks=follow_symlinks):
            dirnames[:] = [d for d in dirnames if d.lower() not in _SKIP_DIR_NAMES and not d.startswith(".")]
            for name in filenames:
                track = scan_file(Path(dirpath) / name, include_video=include_video)
                if track is not None:
                    yield track
