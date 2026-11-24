"""The order of YouTube's player clients, from the project's GitHub (1.7).

When YouTube changes, one player client stops answering and another starts
to; which ones work changes faster than releases. ``engine.json`` at the root
of the repository lists them in the order to try, and the app reads it (at
most twice a day, with the update check) and keeps a copy for offline runs.
The client that last worked on this computer is tried first.

A profile is what goes after ``youtube:`` in yt-dlp's ``--extractor-args``:
"" for yt-dlp's own default, "android_vr,android,web" (clients only), or
"player_client=tv,web_embedded;skip=hls". Anything else in the file is ignored.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

URL = "https://raw.githubusercontent.com/yosef220/hamenagen-AI/main/engine.json"
CACHE = "engine_cfg.json"
STATE = "engine_state.json"
REFRESH_SECONDS = 12 * 3600
_PROFILE = re.compile(r"^[a-z0-9_]+(,[a-z0-9_]+)*$|^([a-z_]+=[a-z0-9_,]+)(;[a-z_]+=[a-z0-9_,]+)*$")


def clean_profiles(raw) -> list[str | None]:
    """Valid profiles in order ("" becomes None, yt-dlp's default); at most 12."""
    out: list[str | None] = []
    for p in raw if isinstance(raw, list) else []:
        if not isinstance(p, str) or len(p) > 120:
            continue
        p = p.strip()
        value = None if p == "" else p if _PROFILE.match(p) else False
        if value is not False and value not in out:
            out.append(value)
    return out[:12]


def load(data_dir: str | Path) -> list[str | None]:
    """The profiles kept from the last read ([] when none)."""
    try:
        return clean_profiles(json.loads((Path(data_dir) / CACHE).read_text(encoding="utf-8")).get("profiles"))
    except (OSError, ValueError, AttributeError):
        return []


def refresh(data_dir: str | Path, fetch, *, now: float | None = None) -> list[str | None]:
    """Read engine.json again when the copy is older than REFRESH_SECONDS.
    ``fetch(url) -> bytes | None``. Returns the profiles in use."""
    path = Path(data_dir) / CACHE
    now = time.time() if now is None else now
    try:
        fresh = now - path.stat().st_mtime < REFRESH_SECONDS
    except OSError:
        fresh = False
    if not fresh:
        try:
            data = fetch(URL)
            doc = json.loads(data.decode("utf-8")) if data else None
        except (ValueError, UnicodeDecodeError):
            doc = None
        if isinstance(doc, dict) and clean_profiles(doc.get("profiles")):
            tmp = path.with_suffix(".part")
            tmp.write_text(json.dumps({"rev": doc.get("rev"), "profiles": doc.get("profiles")}, ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(path)
    return load(data_dir)


def last_good(data_dir: str | Path) -> str | None | bool:
    """The profile that last worked here (None = yt-dlp's default); False when unknown."""
    try:
        doc = json.loads((Path(data_dir) / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    good = clean_profiles([doc.get("last_good", "")]) if isinstance(doc, dict) else []
    return good[0] if good else False


def remember(data_dir: str | Path, profile: str | None) -> None:
    try:
        (Path(data_dir) / STATE).write_text(json.dumps({"last_good": profile or ""}), encoding="utf-8")
    except OSError:
        pass
