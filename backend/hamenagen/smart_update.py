"""The smart update: download only the parts of the app that changed.

A release publishes, for each edition, the fingerprint of every part of the
app (update.json → app.parts.<edition>, made by scripts/parts.js and
scripts/make_parts.py). The installed app keeps its own list beside the
core, in resources/parts.json. Parts whose fingerprint differs are
downloaded, each as one ZIP; the ZIP is checked against its SHA-256, and
what it unpacks to against the part's fingerprint; then everything waits in
``data/update/staging``.

Swapping the parts in happens after the app closes (the files are in use
while it runs): Electron writes a small PowerShell script that waits for the
app to exit, moves each old part aside, moves the new one in, puts the old
ones back if anything fails, records the outcome in ``result.json`` and
starts the app again (electron/update-apply.ps1).

The AI model of the offline editions, Python and Electron change rarely, so
a usual update is a few megabytes instead of the whole edition.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

from . import __version__

CHUNK = 1 << 16


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def is_cache(rel: str) -> bool:
    """Python's compiled caches (``__pycache__``, ``.pyc``): Python writes them
    next to the code when it runs, so they are never part of a fingerprint or
    of a part's ZIP (the same rule as scripts/parts.js and make_parts.py)."""
    return rel.endswith(".pyc") or "__pycache__" in rel.split("/")


def content_hash(base: Path, entries: list[str], skip: set[str] | frozenset = frozenset()) -> str:
    """The fingerprint of the files under ``entries`` — one line per file,
    "path<TAB>size<TAB>sha256", sorted by UTF-8 bytes (as scripts/parts.js)."""
    files: list[Path] = []
    for entry in entries:
        p = base / entry
        if p.is_dir():
            files += [f for f in p.rglob("*") if f.is_file() and not is_cache(f.relative_to(base).as_posix())]
        elif p.is_file():
            files.append(p)
    rels = sorted((f.relative_to(base).as_posix() for f in files), key=lambda r: r.encode("utf-8"))
    lines = [f"{r}\t{(base / r).stat().st_size}\t{sha256_file(base / r)}\n" for r in rels if r not in skip]
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def default_resources_dir() -> Path | None:
    """Where the packaged app keeps its parts: the core runs from
    resources/backend, so resources is two folders up from this file."""
    here = Path(__file__).resolve().parents[2]
    return here if (here / "parts.json").is_file() else None


def _mb(n: int) -> str:
    mb = n / (1024 * 1024)
    return f"{mb:,.0f}MB" if mb >= 10 else f"{mb:.1f}MB"


class UpdateError(Exception):
    pass


class SmartUpdater:
    def __init__(self, data_dir: str | Path, resources: str | Path | None = None, *,
                 opener: Callable | None = None):
        self.work = Path(data_dir) / "update"
        self.resources = Path(resources) if resources else default_resources_dir()
        self.opener = opener or urllib.request.urlopen
        self.cancel = threading.Event()

    # ------------------------------------------------------------ what is installed
    @property
    def root(self) -> Path | None:
        return self.resources.parent if self.resources else None

    def installed(self) -> dict | None:
        if not self.resources:
            return None
        try:
            return json.loads((self.resources / "parts.json").read_text(encoding="utf-8"))
        except Exception:
            return None

    def writable(self) -> bool:
        """Can the app's own folders be changed by this user?"""
        for folder in (self.root, self.resources):
            if folder is None:
                return False
            probe = folder / ".hamenagen-update-probe"
            try:
                probe.write_text("ok", encoding="utf-8")
                probe.unlink()
            except OSError:
                return False
        return True

    # ------------------------------------------------------------ the plan
    def plan(self, release: dict | None) -> dict:
        """What a smart update to ``release`` (an app entry from update.json,
        with ``parts`` for this edition) would download."""
        mine = self.installed()
        remote = (release or {}).get("parts")
        if not release or not release.get("newer"):
            return {"possible": False, "reason": "up_to_date"}
        if not mine:
            return {"possible": False, "reason": "no_parts_here"}
        if not remote or not remote.get("parts"):
            return {"possible": False, "reason": "no_parts_in_release"}
        if remote.get("edition") and mine.get("edition") and remote["edition"] != mine["edition"]:
            return {"possible": False, "reason": "other_edition"}
        have = mine.get("parts") or {}
        changed = [n for n, p in remote["parts"].items() if (have.get(n) or {}).get("hash") != p.get("hash")]
        missing = [n for n in changed if not remote["parts"][n].get("url") or not remote["parts"][n].get("sha256")]
        if missing:
            return {"possible": False, "reason": "incomplete_release", "missing": missing}
        size = sum(int(remote["parts"][n].get("size") or 0) for n in changed)
        full = sum(int(p.get("size") or 0) for p in remote["parts"].values())
        if not self.writable():
            return {"possible": False, "reason": "read_only", "download": size}
        return {
            "possible": True, "version": release.get("latest"), "changed": changed,
            "kept": [n for n in remote["parts"] if n not in changed],
            "download": size, "download_text": _mb(size), "full": full, "full_text": _mb(full),
        }

    # ------------------------------------------------------------ download
    def _fetch(self, url: str, target: Path, expected: int, on_bytes: Callable[[int], None]) -> None:
        """Download ``url`` to ``target``, resuming a part already there."""
        have = target.stat().st_size if target.exists() else 0
        if expected and have == expected:
            on_bytes(have)
            return
        if expected and have > expected:
            target.unlink()
            have = 0
        headers = {"User-Agent": f"hamenagen/{__version__}"}
        if have:
            headers["Range"] = f"bytes={have}-"
        req = urllib.request.Request(url, headers=headers)
        with self.opener(req, timeout=30) as resp:
            status = getattr(resp, "status", 200)
            mode = "ab" if have and status == 206 else "wb"
            if mode == "wb":
                have = 0
            on_bytes(have)
            with open(target, mode) as out:
                while True:
                    if self.cancel.is_set():
                        raise UpdateError("cancelled")
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    have += len(chunk)
                    on_bytes(have)

    @staticmethod
    def _extract(zip_path: Path, dest: Path) -> None:
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        root = dest.resolve()
        with zipfile.ZipFile(zip_path) as z:
            for info in z.infolist():
                target = (dest / info.filename).resolve()
                if root not in target.parents and target != root:
                    raise UpdateError(f"unsafe path in {zip_path.name}: {info.filename}")
            z.extractall(dest)

    def download(self, release: dict, on_progress: Callable[[dict], None] | None = None) -> dict:
        """Download, check and unpack the changed parts; write the plan the
        apply script follows. Returns ``{"ok", "plan"}`` or ``{"ok": False,
        "message"}``."""
        plan = self.plan(release)
        if not plan.get("possible"):
            return {"ok": False, "reason": plan.get("reason"), "message": "עדכון חכם לא אפשרי כאן."}
        self.cancel.clear()
        remote = release["parts"]
        mine = self.installed() or {}
        parts_dir, staging = self.work / "parts", self.work / "staging"
        parts_dir.mkdir(parents=True, exist_ok=True)
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        total = plan["download"]
        done_before = 0
        steps = []
        try:
            for name in plan["changed"]:
                part = remote["parts"][name]
                target = parts_dir / part["file"]
                expected = int(part.get("size") or 0)

                def on_bytes(n, base=done_before):
                    if on_progress:
                        on_progress({"status": "downloading", "done": base + n, "total": total, "part": name})
                self._fetch(part["url"], target, expected, on_bytes)
                if sha256_file(target) != part["sha256"]:
                    target.unlink(missing_ok=True)
                    raise UpdateError(f"the download of {name} is damaged")
                done_before += expected
                if on_progress:
                    on_progress({"status": "checking", "done": done_before, "total": total, "part": name})
                self._extract(target, staging / name)
                if not part.get("fingerprint") and content_hash(staging / name, part["entries"]) != part["hash"]:
                    raise UpdateError(f"the files of {name} do not match the release")
                steps.append({
                    "name": name, "kind": part["kind"], "staging": str(staging / name),
                    "new": part["entries"],
                    "old": ((mine.get("parts") or {}).get(name) or {}).get("entries") or [],
                })
            for name in (mine.get("parts") or {}):
                if name not in remote["parts"]:   # a part this release no longer has
                    old = mine["parts"][name]
                    steps.append({"name": name, "kind": old["kind"], "staging": "", "new": [],
                                  "old": old.get("entries") or []})
        except UpdateError as err:
            return {"ok": False, "message": str(err)}
        except Exception as err:  # noqa: BLE001 - network, disk
            return {"ok": False, "message": f"{type(err).__name__}: {err}"}
        new_manifest = {k: v for k, v in remote.items() if k != "parts"}
        new_manifest["parts"] = {n: {k: v for k, v in p.items() if k not in ("url", "file", "sha256")}
                                 for n, p in remote["parts"].items()}
        new_manifest["version"] = release.get("latest") or new_manifest.get("version")
        (self.work / "parts.json").write_text(json.dumps(new_manifest, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
        apply_plan = {
            "version": release.get("latest"), "edition": mine.get("edition"),
            "root": str(self.root), "resources": str(self.resources), "work": str(self.work),
            "result": str(self.work / "result.json"), "parts_json": str(self.work / "parts.json"),
            "parts": steps,
        }
        plan_path = self.work / "plan.json"
        plan_path.write_text(json.dumps(apply_plan, ensure_ascii=False, indent=2), encoding="utf-8")
        if on_progress:
            on_progress({"status": "ready", "done": total, "total": total})
        return {"ok": True, "plan": str(plan_path), "version": release.get("latest")}

    # ------------------------------------------------------------ after the swap
    def result(self) -> dict | None:
        """What the last swap did (once), and tidy what it left behind."""
        path = self.work / "result.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            data = {"ok": False, "error": "unreadable result"}
        for leftover in ("staging", "backup", "parts"):
            shutil.rmtree(self.work / leftover, ignore_errors=True)
        for name in ("result.json", "plan.json", "parts.json", "apply.ps1"):
            try:
                os.remove(self.work / name)
            except OSError:
                pass
        return data
