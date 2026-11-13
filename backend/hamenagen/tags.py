"""Writing a song's details into the file itself (1.5).

Until 1.4 every correction (a singer's unified name, details from the web, a
fixed title) lived only inside the player, and an MP3 player or a phone saw
the old tags. Now the listener can write them into the file — one song from
its menu, or the whole library from the settings — and the copies made for an
MP3 player always carry them.

MP3 (ID3v2.4 + v1 for old players), M4A/MP4, FLAC, OGG/Opus and WMA, through
mutagen. Only what is given is written; nothing else in the file changes. A
cover is added only when the file has none (or ``cover_replace``).
"""

from __future__ import annotations

from pathlib import Path

WRITABLE = {".mp3", ".m4a", ".mp4", ".aac", ".flac", ".ogg", ".oga", ".opus", ".wma"}


def can_write(path) -> bool:
    return Path(path).suffix.lower() in WRITABLE


def _jpeg_or_png(data: bytes) -> str:
    return "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"


def write_tags(path, *, title: str | None = None, artist: str | None = None, album: str | None = None,
               year: str | None = None, track: int | None = None, cover: bytes | None = None,
               cover_replace: bool = False) -> tuple[bool, str]:
    """Write the given details into ``path``. Returns (ok, reason)."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext not in WRITABLE:
        return False, "format"
    try:
        import mutagen  # noqa: F401
    except Exception:
        return False, "no-mutagen"
    vals = {k: v for k, v in (("title", title), ("artist", artist), ("album", album), ("year", year)) if v}
    try:
        if ext == ".mp3":
            _mp3(p, vals, track, cover, cover_replace)
        elif ext in (".m4a", ".mp4", ".aac"):
            _mp4(p, vals, track, cover, cover_replace)
        elif ext == ".flac":
            _flac(p, vals, track, cover, cover_replace)
        elif ext in (".ogg", ".oga", ".opus"):
            _vorbis(p, vals, track)
        elif ext == ".wma":
            _asf(p, vals, track)
    except PermissionError:
        return False, "read-only"
    except Exception as exc:  # noqa: BLE001 - a file we cannot write stays as it was
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def _mp3(p: Path, vals: dict, track, cover, cover_replace) -> None:
    from mutagen.id3 import APIC, ID3, TALB, TDRC, TIT2, TPE1, TRCK, ID3NoHeaderError

    try:
        tags = ID3(p)
    except ID3NoHeaderError:
        tags = ID3()
    frames = {"title": TIT2, "artist": TPE1, "album": TALB, "year": TDRC}
    for key, frame in frames.items():
        if key in vals:
            tags.setall(frame.__name__, [frame(encoding=3, text=vals[key])])
    if track:
        tags.setall("TRCK", [TRCK(encoding=3, text=str(track))])
    if cover and (cover_replace or not tags.getall("APIC")):
        tags.delall("APIC")
        tags.add(APIC(encoding=3, mime=_jpeg_or_png(cover), type=3, desc="Cover", data=cover))
    # v2.4 for players that read it, and a v1 tag for old MP3 players.
    tags.save(p, v1=2, v2_version=4)


def _mp4(p: Path, vals: dict, track, cover, cover_replace) -> None:
    from mutagen.mp4 import MP4, MP4Cover

    audio = MP4(p)
    if audio.tags is None:
        audio.add_tags()
    keys = {"title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb", "year": "\xa9day"}
    for key, atom in keys.items():
        if key in vals:
            audio.tags[atom] = [vals[key]]
    if track:
        audio.tags["trkn"] = [(int(track), 0)]
    if cover and (cover_replace or "covr" not in audio.tags):
        fmt = MP4Cover.FORMAT_PNG if _jpeg_or_png(cover) == "image/png" else MP4Cover.FORMAT_JPEG
        audio.tags["covr"] = [MP4Cover(cover, imageformat=fmt)]
    audio.save()


def _vorbis_fields(tags, vals: dict, track) -> None:
    names = {"title": "title", "artist": "artist", "album": "album", "year": "date"}
    for key, name in names.items():
        if key in vals:
            tags[name] = [vals[key]]
    if track:
        tags["tracknumber"] = [str(track)]


def _flac(p: Path, vals: dict, track, cover, cover_replace) -> None:
    from mutagen.flac import FLAC, Picture

    audio = FLAC(p)
    if audio.tags is None:
        audio.add_tags()
    _vorbis_fields(audio.tags, vals, track)
    if cover and (cover_replace or not audio.pictures):
        audio.clear_pictures()
        pic = Picture()
        pic.type, pic.mime, pic.data = 3, _jpeg_or_png(cover), cover
        audio.add_picture(pic)
    audio.save()


def _vorbis(p: Path, vals: dict, track) -> None:
    import mutagen

    audio = mutagen.File(p)
    if audio is None:
        raise ValueError("unknown file")
    if audio.tags is None:
        audio.add_tags()
    _vorbis_fields(audio.tags, vals, track)
    audio.save()


def _asf(p: Path, vals: dict, track) -> None:
    from mutagen.asf import ASF

    audio = ASF(p)
    names = {"title": "Title", "artist": "Author", "album": "WM/AlbumTitle", "year": "WM/Year"}
    for key, name in names.items():
        if key in vals:
            audio[name] = [vals[key]]
    if track:
        audio["WM/TrackNumber"] = [str(track)]
    audio.save()


def read_tags(path) -> dict:
    """Title, artist and album as the file has them (for tests and checks)."""
    try:
        import mutagen

        audio = mutagen.File(Path(path), easy=True)
    except Exception:
        return {}
    if audio is None or not audio.tags:
        return {}

    def first(*names):
        for n in names:
            v = audio.tags.get(n)
            if v:
                return str(v[0])
        return ""

    return {"title": first("title", "Title"), "artist": first("artist", "Author"),
            "album": first("album", "WM/AlbumTitle")}
