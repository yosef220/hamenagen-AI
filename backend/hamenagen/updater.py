"""Update layer (spec §14).

When online (and subject to the ``auto_update`` setting), the app can check a
central manifest — hosted by the organisation — and report/apply updates to:

* the application itself,
* the AI model and the curated lexicon,
* the download library (``yt-dlp``, which breaks often and must stay fresh),
* the Hebrew-calendar data and the radio list.

The manifest is a small JSON document::

    {
      "app":     {"version": "0.2.0", "url": "https://.../hamenagen-0.2.0.exe"},
      "lexicon": {"version": "3",      "url": "https://.../topics.json"},
      "ytdlp":   {"version": "2026.8.1"},
      "model":   {"name": "...", "url": "https://.../model.pack"},
      "radio":   {"url": "https://kcm.fm/Live/"}
    }

The comparison logic (:func:`diff_versions`) is pure and unit-tested; the
network fetch and the apply actions are thin wrappers that degrade gracefully
offline so nothing here can break the offline-first core.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

from . import __version__
from .versioning import is_newer

# Components whose "latest" is expressed as a version string to compare.
_VERSIONED = ("app", "lexicon", "ytdlp", "model")


def current_ytdlp_version() -> str | None:
    try:  # pragma: no cover - depends on optional dependency
        import yt_dlp  # type: ignore

        return getattr(yt_dlp.version, "__version__", None) or getattr(yt_dlp, "__version__", None)
    except Exception:
        return None


def diff_versions(current: dict, manifest: dict) -> list[dict]:
    """Return the list of components that have a newer version available.

    ``current`` maps component -> installed version string (or ``None``).
    Each result item is ``{component, current, latest, action, url}``.
    """
    updates: list[dict] = []
    for comp in _VERSIONED:
        entry = manifest.get(comp)
        if not entry:
            continue
        latest = entry.get("version") or entry.get("name")
        cur = current.get(comp)
        if latest is None:
            continue
        # If we do not know the current version, offer it; else compare.
        if cur is None or is_newer(str(latest), str(cur)):
            updates.append({
                "component": comp,
                "current": cur,
                "latest": latest,
                "action": _action_for(comp),
                "url": entry.get("url"),
            })
    return updates


def _action_for(comp: str) -> str:
    return {
        "ytdlp": "auto",       # can self-update via pip
        "lexicon": "auto",     # can fetch + save the JSON
        "app": "manual",       # user downloads the new installer
        "model": "manual",     # large; via prepare_model / offline pack
    }.get(comp, "manual")


class Updater:
    def __init__(
        self,
        manifest_url: str,
        data_dir: str | Path,
        *,
        app_version: str = __version__,
    ):
        self.manifest_url = manifest_url
        self.data_dir = Path(data_dir)
        self.app_version = app_version

    def current_versions(self) -> dict:
        lexicon_ver = "0"
        lv = self.data_dir / "lexicon_version.txt"
        if lv.exists():
            lexicon_ver = lv.read_text(encoding="utf-8").strip() or "0"
        return {
            "app": self.app_version,
            "ytdlp": current_ytdlp_version(),
            "lexicon": lexicon_ver,
            "model": None,
        }

    def fetch_manifest(self, *, timeout: float = 8.0) -> dict:
        req = urllib.request.Request(
            self.manifest_url, headers={"User-Agent": "hamenagen/0.1"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))

    def check(self) -> dict:
        """Check for updates. Never raises: offline -> ``online: False``."""
        if not self.manifest_url:
            return {"online": False, "reason": "no manifest url", "updates": []}
        try:
            manifest = self.fetch_manifest()
        except Exception as exc:
            return {"online": False, "reason": str(exc), "updates": []}
        updates = diff_versions(self.current_versions(), manifest)
        return {"online": True, "manifest_url": self.manifest_url, "updates": updates}

    # -- apply actions -----------------------------------------------------
    def apply_ytdlp(self) -> dict:
        """Self-update yt-dlp via pip (spec §11/§14 — must stay current)."""
        try:  # pragma: no cover - network + environment dependent
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
                capture_output=True, text=True, timeout=300,
            )
            ok = proc.returncode == 0
            return {"ok": ok, "message": (proc.stdout or proc.stderr)[-800:]}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def apply_lexicon(self, url: str, version: str) -> dict:
        """Fetch an updated topic lexicon JSON and store it for next start."""
        if not url:
            return {"ok": False, "message": "אין כתובת למילון"}
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hamenagen/0.1"})
            with urllib.request.urlopen(req, timeout=8.0) as resp:  # noqa: S310
                data = resp.read()
            json.loads(data.decode("utf-8"))  # validate
            self.data_dir.mkdir(parents=True, exist_ok=True)
            (self.data_dir / "topics_override.json").write_bytes(data)
            (self.data_dir / "lexicon_version.txt").write_text(str(version), encoding="utf-8")
            return {"ok": True, "message": f"המילון עודכן לגרסה {version}"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def apply(self, component: str, *, url: str | None = None, version: str = "") -> dict:
        if component == "ytdlp":
            return self.apply_ytdlp()
        if component == "lexicon":
            return self.apply_lexicon(url or "", version)
        return {"ok": False, "message": f"עדכון '{component}' דורש פעולה ידנית."}
