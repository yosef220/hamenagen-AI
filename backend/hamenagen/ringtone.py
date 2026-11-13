"""A ringtone from a song (1.5).

The listener picks where it starts (the player suggests the loudest stretch
after the opening, from the analysis it already has, or simply 0:30) and how
long it is; ffmpeg cuts it, fades it in and out, and saves it as MP3 (every
phone) or M4R (iPhone) in Music/Hamenagen/צלצולים. The song itself is not
touched.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

LENGTHS = (20, 30, 40)
FORMATS = ("mp3", "m4r")
FADE_IN = 1.0
FADE_OUT = 2.0


def suggest_start(duration: float | None, lead: float = 0.0) -> float:
    """Where a ringtone usually sounds right: past the opening, before the
    middle. Short songs start near their beginning."""
    if not duration or duration <= 45:
        return round(max(0.0, lead), 1)
    return round(min(max(30.0, lead), duration * 0.4), 1)


def output_path(folder: Path, name: str, fmt: str) -> Path:
    from .export import clean_name

    folder.mkdir(parents=True, exist_ok=True)
    base = clean_name(name, "צלצול")
    out = folder / f"{base}.{fmt}"
    k = 2
    while out.exists():
        out = folder / f"{base} ({k}).{fmt}"
        k += 1
    return out


def command(ffmpeg: str, src: Path, out: Path, start: float, length: float, fmt: str) -> list[str]:
    fade_out_at = max(0.0, length - FADE_OUT)
    af = f"afade=t=in:st=0:d={FADE_IN},afade=t=out:st={fade_out_at:.2f}:d={FADE_OUT}"
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.2f}", "-t", f"{length:.2f}",
           "-i", str(src), "-vn", "-af", af]
    if fmt == "m4r":
        cmd += ["-c:a", "aac", "-b:a", "192k", "-f", "ipod"]
    else:
        cmd += ["-c:a", "libmp3lame", "-b:a", "192k", "-id3v2_version", "3"]
    return cmd + [str(out)]


def make(ffmpeg: str, src, folder, *, name: str, start: float, length: float = 30, fmt: str = "mp3",
         duration: float | None = None) -> dict:
    if not ffmpeg:
        return {"ok": False, "message": "חסר רכיב ההמרה (ffmpeg), ולכן אי אפשר ליצור צלצול."}
    src = Path(src)
    if not src.is_file():
        return {"ok": False, "message": "הקובץ של השיר לא נמצא."}
    fmt = fmt if fmt in FORMATS else "mp3"
    length = float(min(max(5.0, float(length or 30)), 60.0))
    start = max(0.0, float(start or 0))
    if duration and start + length > duration:
        start = max(0.0, duration - length)
    out = output_path(Path(folder), name, fmt)
    flags = 0x08000000 if sys.platform == "win32" else 0
    try:
        subprocess.run(command(ffmpeg, src, out, start, length, fmt), check=True, capture_output=True,
                       timeout=120, creationflags=flags)
    except subprocess.CalledProcessError as exc:
        out.unlink(missing_ok=True)
        err = (exc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        return {"ok": False, "message": "יצירת הצלצול נכשלה" + (f": {err[-1]}" if err else ".")}
    except Exception as exc:  # noqa: BLE001
        out.unlink(missing_ok=True)
        return {"ok": False, "message": f"יצירת הצלצול נכשלה: {exc}"}
    if fmt == "mp3":
        from . import tags as tags_mod

        tags_mod.write_tags(out, title=f"{name} (צלצול)")
    return {"ok": True, "path": str(out), "folder": str(out.parent), "start": start, "length": length,
            "format": fmt}
