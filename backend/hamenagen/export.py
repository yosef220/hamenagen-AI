"""Copying songs to an MP3 player or a USB stick (1.5).

The community's players (M36 and its kin, kosher MP3 players, a stick in the
car) play files from folders: what reaches them is what the folders and the
file names say. So the player chooses the songs the way it plays them — a
request, a topic, a set, a saved list — and copies them:

* into folders by singer, by topic, or one folder in the order chosen
  (numbered, for players that play by name);
* with clean names ("זמר - שם השיר.mp3"): no characters FAT forbids, no
  names Windows reserves, not too long;
* as MP3 (M4A, FLAC, OGG, WMA… are converted with the bundled ffmpeg), with
  the details written into the copy — the singer's one name included — while
  the listener's own files stay as they are;
* only as much as fits: the free space (less a small reserve) or a limit the
  listener set; songs already on the player are not copied again.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from . import tags as tags_mod

PLAYER_FRIENDLY = {".mp3"}
CONVERTIBLE = {".m4a", ".mp4", ".aac", ".flac", ".ogg", ".oga", ".opus", ".wma", ".wav", ".webm", ".mka", ".aiff"}
MP3_KBPS = 192
RESERVE = 50 * 1024 * 1024          # never fill a player to the last byte
NAME_MAX = 90

_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
LAYOUTS = ("singer", "topic", "flat")


def clean_name(text: str, fallback: str = "שיר") -> str:
    """A file or folder name every player and Windows accept."""
    s = _FORBIDDEN.sub(" ", str(text or ""))
    s = re.sub(r"\s+", " ", s).strip().rstrip(". ")
    if len(s) > NAME_MAX:
        s = s[:NAME_MAX].rstrip(". ")
    if not s:
        s = fallback
    if s.split(".")[0].upper() in _RESERVED:
        s = f"{s}_"
    return s


@dataclass
class Item:
    id: str
    src: str
    rel: str                # path inside the target folder
    size: int               # bytes it will take
    convert: bool
    title: str = ""
    artist: str = ""
    album: str = ""
    exists: bool = False    # already on the player (copied before)


@dataclass
class Plan:
    dest: str
    folder: str
    items: list[Item] = field(default_factory=list)
    left_out: list[dict] = field(default_factory=list)     # did not fit
    budget: int = 0
    total: int = 0

    def to_dict(self) -> dict:
        return {
            "dest": self.dest, "folder": self.folder, "budget": self.budget, "total": self.total,
            "count": len(self.items), "already": sum(1 for i in self.items if i.exists),
            "convert": sum(1 for i in self.items if i.convert and not i.exists),
            "left_out": self.left_out[:200], "left_out_count": len(self.left_out),
        }


def estimate_size(src: Path, duration: float | None, convert: bool) -> int:
    if convert and duration:
        return int(duration * MP3_KBPS * 1000 / 8) + 64 * 1024
    try:
        return src.stat().st_size
    except OSError:
        return 0


def free_space(dest) -> int:
    try:
        return shutil.disk_usage(dest).free
    except OSError:
        return 0


def make_plan(songs: list[dict], dest, *, folder: str, layout: str = "flat", numbered: bool = True,
              convert: bool = True, limit_bytes: int | None = None) -> Plan:
    """Where each song goes and what fits. ``songs`` are dicts with id, path,
    title, artist (the name shown), topic_label, duration — in the order
    they should play."""
    dest = Path(dest)
    layout = layout if layout in LAYOUTS else "flat"
    folder = clean_name(folder, "המנגן")
    base = dest / folder
    budget = max(0, free_space(dest) - RESERVE)
    if limit_bytes:
        budget = min(budget, int(limit_bytes)) if budget else int(limit_bytes)
    plan = Plan(dest=str(dest), folder=folder, budget=budget)
    used: set[str] = set()
    width = max(3, len(str(len(songs))))
    n = 0
    for s in songs:
        src = Path(s.get("path") or "")
        if not src.is_file():
            continue
        ext = src.suffix.lower()
        conv = convert and ext in CONVERTIBLE
        out_ext = ".mp3" if conv else ext
        title = clean_name(s.get("title") or src.stem)
        artist = clean_name(s.get("artist") or "", "")
        name = f"{artist} - {title}" if artist and layout != "singer" else title
        if layout == "singer":
            sub = artist or "זמרים שונים"
        elif layout == "topic":
            sub = clean_name(s.get("topic_label") or "", "בלי נושא")
        else:
            sub = ""
        n += 1
        if numbered and layout == "flat":
            name = f"{n:0{width}d} {name}"
        rel = str(Path(sub) / f"{name}{out_ext}") if sub else f"{name}{out_ext}"
        k = 2
        while rel.lower() in used:            # two songs with one name
            stem = f"{name} ({k})"
            rel = str(Path(sub) / f"{stem}{out_ext}") if sub else f"{stem}{out_ext}"
            k += 1
        used.add(rel.lower())
        size = estimate_size(src, s.get("duration"), conv)
        target = base / rel
        # Copies are written to a ".part" name and renamed when whole, so a
        # file under the final name is a finished copy (its size differs from
        # the source: the details were written into it).
        exists = target.is_file() and target.stat().st_size > 0
        item = Item(id=s.get("id", ""), src=str(src), rel=rel, size=size, convert=conv, title=s.get("title") or "",
                    artist=s.get("artist") or "", album=folder if layout == "flat" else (sub or folder),
                    exists=exists)
        cost = 0 if exists else size
        if plan.total + cost > budget:
            plan.left_out.append({"id": item.id, "title": item.title, "size": size})
            continue
        plan.total += cost
        plan.items.append(item)
    return plan


def _convert(ffmpeg: str, src: Path, out: Path) -> None:
    flags = 0x08000000 if sys.platform == "win32" else 0      # CREATE_NO_WINDOW
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-vn", "-map_metadata", "0",
           "-codec:a", "libmp3lame", "-b:a", f"{MP3_KBPS}k", "-id3v2_version", "3", str(out)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=600, creationflags=flags)


def run(plan: Plan, *, ffmpeg: str | None = None, on_progress=None, cancel: threading.Event | None = None) -> dict:
    """Copy (or convert) every song in the plan, in its order."""
    base = Path(plan.dest) / plan.folder
    copied = skipped = 0
    failed: list[dict] = []
    done_bytes = 0
    for n, item in enumerate(plan.items, 1):
        if cancel is not None and cancel.is_set():
            break
        target = base / item.rel
        if item.exists:
            skipped += 1
        else:
            part = target.with_name(target.name + ".part")
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if item.convert and ffmpeg:
                    tmp = target.with_name(target.stem + ".part.mp3")
                    _convert(ffmpeg, Path(item.src), tmp)
                    os.replace(tmp, target)
                else:
                    if item.convert:            # no ffmpeg: the file as it is
                        target = target.with_suffix(Path(item.src).suffix.lower())
                        part = target.with_name(target.name + ".part")
                    shutil.copyfile(item.src, part)
                    os.replace(part, target)
                tags_mod.write_tags(target, title=item.title or None, artist=item.artist or None,
                                    album=item.album or None, track=n if plan.items else None)
                copied += 1
                done_bytes += item.size
            except Exception as exc:  # noqa: BLE001 - one song does not stop the rest
                for leftover in (part, target.with_name(target.stem + ".part.mp3")):
                    try:
                        leftover.unlink(missing_ok=True)
                    except OSError:
                        pass
                failed.append({"id": item.id, "title": item.title, "reason": str(exc)[:200]})
                if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:   # the player is full
                    break
        if on_progress:
            on_progress({"done": n, "total": len(plan.items), "title": item.title, "bytes": done_bytes})
    return {"ok": not failed, "copied": copied, "already": skipped, "failed": failed[:50],
            "failed_count": len(failed), "cancelled": bool(cancel is not None and cancel.is_set()),
            "folder": str(base), "left_out_count": len(plan.left_out)}


# ------------------------------------------------------------------ drives
def removable_drives() -> list[dict]:
    """Plugged-in players and sticks: Windows' removable drives (elsewhere,
    what is mounted under /media)."""
    out = []
    if sys.platform == "win32":
        import ctypes
        import string

        k32 = ctypes.windll.kernel32
        mask = k32.GetLogicalDrives()
        for i, letter in enumerate(string.ascii_uppercase):
            if not mask & (1 << i):
                continue
            root = f"{letter}:\\"
            if k32.GetDriveTypeW(ctypes.c_wchar_p(root)) != 2:      # DRIVE_REMOVABLE
                continue
            label = ctypes.create_unicode_buffer(261)
            fs = ctypes.create_unicode_buffer(261)
            ok = k32.GetVolumeInformationW(ctypes.c_wchar_p(root), label, 261, None, None, None, fs, 261)
            if not ok:
                continue                                           # no medium
            out.append(_drive(root, label.value, fs.value))
    else:
        for base in (Path("/media"), Path("/run/media")):
            if base.is_dir():
                for user in base.iterdir():
                    for m in (user.iterdir() if user.is_dir() else []):
                        if m.is_dir():
                            out.append(_drive(str(m), m.name, ""))
    return out


def _drive(root: str, label: str, fs: str) -> dict:
    try:
        u = shutil.disk_usage(root)
        total, free = u.total, u.free
    except OSError:
        total = free = 0
    return {"path": root, "label": label or root, "fs": fs, "total": total, "free": free}
