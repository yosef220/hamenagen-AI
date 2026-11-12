"""Library scanner (spec §5 Library Scanner, §9).

Walks the file system (the whole machine, or a configured set of roots),
finds media files, extracts what metadata it can, and yields :class:`Track`
objects for the index. Tag reading uses the optional :mod:`mutagen` package
when available; otherwise it degrades gracefully to filename parsing so the
core keeps working with no extra dependency.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import struct
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from .models import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, Track
from .text_normalize import repair_hebrew

try:  # optional richer tag reading
    import mutagen  # type: ignore

    _HAVE_MUTAGEN = True
except Exception:  # pragma: no cover
    mutagen = None
    _HAVE_MUTAGEN = False

# Directories we never descend into — noise, and often huge.
_SKIP_DIR_NAMES = {
    "$recycle.bin", "system volume information", "windows", "windows.old",
    "$windows.~bt", "$windows.~ws", "program files", "program files (x86)",
    "programdata", "appdata", "recovery", "msocache", "node_modules",
    ".git", "__pycache__", ".cache", "site-packages",
}

# Files this small are notification sounds and voice clips, not songs. Only
# applied while walking folders; an explicitly added file is always accepted.
MIN_SONG_BYTES = 64 * 1024
MIN_SONG_SECONDS = 20.0

# Raised when what the scanner reads from a file changes, so a library
# scanned by an older version is read again once (see service.rescan).
SCAN_VERSION = "2"

# Folder names that say nothing about the songs in them.
GENERIC_FOLDERS = {
    "music", "my music", "downloads", "download", "desktop", "documents", "my documents",
    "audio", "songs", "mp3", "new folder", "videos", "music videos", "media", "hamenagen",
    "מוזיקה", "הורדות", "שירים", "שולחן העבודה", "מסמכים", "תיקייה חדשה", "המנגן",
}

# Titles that are only a track number ("Track 19", "רצועה 19").
_PLACEHOLDER_RE = re.compile(
    r"^\s*(track|audio ?track|רצועה|untitled|unknown|לא ידוע|ללא שם|שיר)?\s*[-_.#]?\s*\d{0,3}\s*$",
    re.IGNORECASE,
)
# A track number in front of a file name: "03 שם", "03 - שם", "3. שם", "(03) שם".
_TRACK_NUMBER_RE = re.compile(r"^\s*(?:\(\d{1,3}\)|0\d{1,2}(?=[\s._\-)])|\d{1,3}(?=\s*[._\-)]))\s*[._\-)]*\s*(?=\S)")

# Pictures beside the songs, best name first.
_FOLDER_IMAGE_NAMES = ("cover", "folder", "front", "albumart", "album", "albumartsmall")
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")
_MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _stable_id(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8")).hexdigest()[:16]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def is_placeholder_title(title: str) -> bool:
    """"Track 19", "רצועה 19", "05" — a number, not a name."""
    return bool(title) and bool(_PLACEHOLDER_RE.match(title))


def strip_track_number(stem: str) -> str:
    """"03 ואם תבואי אלי" → "ואם תבואי אלי". A number that is part of the
    name ("100 אחוז", "7 דקות") stays."""
    out = _TRACK_NUMBER_RE.sub("", stem, count=1).strip()
    return out or stem.strip()


def _parse_filename(stem: str) -> tuple[str, str]:
    """Best-effort ``(artist, title)`` from a filename like 'Artist - Title'."""
    stem = strip_track_number(stem.replace("_", " ").strip())
    for sep in (" - ", " – ", " — ", "-"):
        if sep in stem:
            left, right = stem.split(sep, 1)
            left, right = left.strip(), strip_track_number(right.strip())
            if left and right and not left.isdigit():
                return left, right
    return "", stem.strip()


def display_folder(path: str | Path) -> str:
    """The song's folder name when it says something (an artist, an album)."""
    parent = Path(path).parent
    name = parent.name.strip()
    if not name or name.lower() in GENERIC_FOLDERS or len(name) <= 2:
        return ""
    return name


# ------------------------------------------------------------------ tags
def _first_text(value) -> str:
    """The first string of a tag value, whatever the format keeps it in."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        for v in value:
            text = _first_text(v)
            if text:
                return text
        return ""
    text = getattr(value, "text", None)  # ID3 frames
    if text is not None:
        return _first_text(text)
    value = getattr(value, "value", value)  # ASF attributes
    return str(value).strip() if not isinstance(value, bytes) else ""


def _clean_text(value) -> str:
    text = repair_hebrew(_first_text(value)).replace("\x00", "").strip()
    return text


def _asf_picture(blob: bytes) -> tuple[int, bytes] | None:
    """Parse a WM/Picture value: type, size, MIME and description (UTF-16,
    NUL-ended), then the image."""
    try:
        kind = blob[0]
        size = struct.unpack_from("<I", blob, 1)[0]
        pos = 5
        for _ in range(2):  # MIME type, description
            end = pos
            while blob[end:end + 2] != b"\x00\x00":
                end += 2
            pos = end + 2
        data = blob[pos:pos + size]
        return (kind, data) if data else None
    except Exception:
        return None


def _pick(pictures: list[tuple[int, bytes]]) -> bytes | None:
    """The front cover (type 3) if there is one, else the first picture."""
    pictures = [(k, d) for k, d in pictures if d and len(d) <= _MAX_IMAGE_BYTES]
    if not pictures:
        return None
    for kind, data in pictures:
        if kind == 3:
            return data
    return pictures[0][1]


def _read_tags(path: Path) -> dict:
    """Title, artist, album, date, length and the cover picture of a song,
    from ID3 (MP3, WAV), MP4 (M4A), ASF (WMA), Vorbis comments (FLAC, OGG,
    Opus) and APE tags."""
    info: dict = {}
    if not _HAVE_MUTAGEN:
        return info
    try:  # pragma: no cover - depends on optional dependency + real files
        audio = mutagen.File(path)
    except Exception:
        return info
    if audio is None:
        return info
    length = getattr(getattr(audio, "info", None), "length", None)
    if length and length > 0:  # a fragmented M4A may say 0: unknown, not short
        info["duration"] = float(length)
    tags = getattr(audio, "tags", None)
    pictures: list[tuple[int, bytes]] = []
    try:
        if tags is not None:
            keys = set(tags.keys())

            def get(*names):
                for name in names:
                    if name in keys:
                        text = _clean_text(tags[name])
                        if text:
                            return text
                return ""

            if any(k.startswith(("TIT2", "TPE1", "TALB", "APIC")) for k in keys):  # ID3
                info["title"] = get("TIT2")
                info["artist"] = get("TPE1", "TPE2")
                info["album"] = get("TALB")
                info["release_date"] = get("TDRC", "TYER", "TDOR", "TORY")
                pictures += [(getattr(tags[k], "type", 0), tags[k].data) for k in keys if k.startswith("APIC")]
            elif any(k.startswith("©") or k in ("covr", "aART") for k in keys):  # MP4
                info["title"] = get("©nam")
                info["artist"] = get("©ART", "aART")
                info["album"] = get("©alb")
                info["release_date"] = get("©day")
                pictures += [(3, bytes(c)) for c in (tags.get("covr") or [])]
            elif any(k.startswith("WM/") or k in ("Title", "Author") for k in keys):  # ASF (WMA)
                info["title"] = get("Title")
                info["artist"] = get("Author", "WM/AlbumArtist")
                info["album"] = get("WM/AlbumTitle")
                info["release_date"] = get("WM/Year")
                for value in tags.get("WM/Picture") or []:
                    pic = _asf_picture(bytes(getattr(value, "value", b"") or b""))
                    if pic:
                        pictures.append(pic)
            else:  # Vorbis comments and APE: plain names
                lower = {k.lower(): k for k in keys}

                def vget(*names):
                    for name in names:
                        if name in lower:
                            text = _clean_text(tags[lower[name]])
                            if text:
                                return text
                    return ""

                info["title"] = vget("title")
                info["artist"] = vget("artist", "albumartist", "album artist")
                info["album"] = vget("album")
                info["release_date"] = vget("date", "originaldate", "year")
                for raw in tags.get("metadata_block_picture", []) if hasattr(tags, "get") else []:
                    try:
                        from mutagen.flac import Picture  # type: ignore

                        pic = Picture(base64.b64decode(raw))
                        pictures.append((pic.type, pic.data))
                    except Exception:
                        pass
                ape_cover = lower.get("cover art (front)")
                if ape_cover:
                    value = getattr(tags[ape_cover], "value", b"")
                    if isinstance(value, bytes) and b"\x00" in value:
                        pictures.append((3, value.split(b"\x00", 1)[1]))
        pictures += [(p.type, p.data) for p in getattr(audio, "pictures", []) or []]  # FLAC
    except Exception:
        pass
    info = {k: v for k, v in info.items() if v}
    picture = _pick(pictures)
    if picture:
        info["picture"] = picture
    return info


def _image_ext(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:2] == b"BM":
        return "bmp"
    return ""


def store_cover(data: bytes, covers_dir: str | Path | None) -> str:
    """Keep a cover picture once (by its content) and return its key.

    The picture is written to ``covers/src``; the app shows a small copy it
    makes there the first time (``covers/<key>.jpg``)."""
    if not data or covers_dir is None:
        return ""
    ext = _image_ext(data)
    if not ext:
        return ""
    key = hashlib.sha1(data).hexdigest()[:20]
    root = Path(covers_dir)
    if (root / f"{key}.jpg").exists():
        return key
    src = root / "src" / f"{key}.{ext}"
    if not src.exists():
        try:
            src.parent.mkdir(parents=True, exist_ok=True)
            tmp = src.with_suffix(".part")
            tmp.write_bytes(data)
            os.replace(tmp, src)
        except OSError:
            return ""
    return key


def folder_picture(folder: str | Path, cache: dict | None = None) -> bytes | None:
    """cover.jpg / folder.jpg / front.jpg … beside the songs, if any."""
    folder = Path(folder)
    if cache is not None and folder in cache:
        return cache[folder]
    found = None
    try:
        images = {}
        for entry in os.scandir(folder):
            name = entry.name.lower()
            stem, ext = os.path.splitext(name)
            if ext in _IMAGE_EXTENSIONS and entry.is_file():
                images[stem] = entry.path
        for wanted in _FOLDER_IMAGE_NAMES:
            match = images.get(wanted) or next(
                (p for s, p in sorted(images.items()) if s.startswith(f"{wanted}_") and s.endswith("large")), None)
            if match:
                size = os.path.getsize(match)
                if 0 < size <= _MAX_IMAGE_BYTES:
                    found = Path(match).read_bytes()
                    break
    except OSError:
        found = None
    if cache is not None:
        cache[folder] = found
    return found


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


def is_media(path: str | Path, *, include_video: bool = False) -> bool:
    ext = Path(path).suffix.lower()
    return ext in AUDIO_EXTENSIONS or (include_video and ext in VIDEO_EXTENSIONS)


def track_id_for(path: str | Path) -> str:
    """The id a file gets in the index (stable while the file stays put)."""
    return _stable_id(str(Path(path).resolve()))


def scan_file(path: str | Path, *, include_video: bool = False, stat: os.stat_result | None = None,
              covers_dir: str | Path | None = None, folder_cache: dict | None = None) -> Track | None:
    p = Path(path)
    ext = p.suffix.lower()
    is_video = ext in VIDEO_EXTENSIONS
    if not is_media(p, include_video=include_video):
        return None
    try:
        stat = stat or p.stat()
    except OSError:
        return None

    abspath = str(p.resolve())
    tags = _read_tags(p)
    artist, title = _parse_filename(p.stem)
    tag_title = tags.get("title", "")
    if is_placeholder_title(tag_title) and title and not is_placeholder_title(title):
        tag_title = ""  # "Track 19" in the tag, a real name in the file name

    cover = ""
    if covers_dir is not None:
        picture = tags.get("picture") or folder_picture(p.parent, folder_cache)
        cover = store_cover(picture, covers_dir) if picture else ""

    return Track(
        id=_stable_id(abspath),
        path=abspath,
        mtime=stat.st_mtime,
        size=stat.st_size,
        title=tag_title or title,
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
        cover=cover,
    )


def iter_media_files(
    roots: list[str | Path],
    *,
    include_video: bool = False,
    follow_symlinks: bool = False,
) -> Iterator[tuple[Path, os.stat_result]]:
    """Yield ``(path, stat)`` for every likely song under the given roots.

    Cheap: no tags are read, so a rescan can skip files it already knows.
    """
    seen_dirs: set[str] = set()
    for root in roots:
        root_path = Path(root)
        if not root_path.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root_path, followlinks=follow_symlinks):
            key = os.path.normcase(os.path.abspath(dirpath))
            if key in seen_dirs:  # overlapping roots (e.g. home + a folder in it)
                dirnames[:] = []
                continue
            seen_dirs.add(key)
            dirnames[:] = [
                d for d in dirnames if d.lower() not in _SKIP_DIR_NAMES and not d.startswith((".", "$"))
            ]
            for name in filenames:
                if not is_media(name, include_video=include_video):
                    continue
                full = Path(dirpath) / name
                try:
                    st = full.stat()
                except OSError:
                    continue
                if st.st_size < MIN_SONG_BYTES:
                    continue
                yield full, st


def scan_roots(
    roots: list[str | Path],
    *,
    include_video: bool = False,
    follow_symlinks: bool = False,
    covers_dir: str | Path | None = None,
) -> Iterator[Track]:
    """Yield a :class:`Track` for every media file under the given roots."""
    folder_cache: dict = {}
    for path, st in iter_media_files(roots, include_video=include_video, follow_symlinks=follow_symlinks):
        track = scan_file(path, include_video=include_video, stat=st, covers_dir=covers_dir,
                          folder_cache=folder_cache)
        if track is not None and not is_too_short(track):
            yield track


def is_too_short(track: Track) -> bool:
    return track.duration is not None and track.duration < MIN_SONG_SECONDS


def default_roots() -> list[str]:
    """Where to look when the user chose no folders: the whole computer.

    The user's home folder (Music, Downloads, Desktop, Documents …) plus, on
    Windows, the root of every other fixed or removable drive (D:, E: …).
    """
    roots = [str(Path.home())]
    if os.name == "nt":  # pragma: no cover - Windows only
        try:
            import ctypes
            import string

            mask = ctypes.windll.kernel32.GetLogicalDrives()
            for i, letter in enumerate(string.ascii_uppercase):
                if not mask & (1 << i) or letter in ("A", "B", "C"):
                    continue
                drive = f"{letter}:\\"
                kind = ctypes.windll.kernel32.GetDriveTypeW(drive)
                if kind in (2, 3):  # DRIVE_REMOVABLE, DRIVE_FIXED
                    roots.append(drive)
        except Exception:
            pass
    return roots
