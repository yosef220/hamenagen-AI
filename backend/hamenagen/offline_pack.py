"""Offline installation package (spec §6.2, §19.7).

Implements the ``*.pack`` format described in docs/OFFLINE_PACK.md: a single
ZIP file the user drops next to the app, which the app detects, verifies for
integrity (SHA-256 per component), and installs from — with no internet.

This module both **reads/installs** a pack and **builds** one, so the same
code path that the app trusts is the one used to produce packs (a nice
property for correctness). Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import time
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path

from . import __version__
from .versioning import compare

PACK_FORMAT = 1
MANIFEST_NAME = "manifest.json"


class PackError(Exception):
    """Raised when a pack is malformed, incompatible, or fails verification."""


@dataclass
class Component:
    name: str
    type: str          # "model" | "lexicon" | "calendar" | "bin" | ...
    target: str        # path inside the pack AND relative install destination
    sha256: str = ""
    size: int = 0


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def find_packs(folder: str | Path) -> list[Path]:
    """Return any ``*.pack`` files sitting in ``folder`` (spec §6.2 step 1)."""
    p = Path(folder)
    if not p.exists():
        return []
    return sorted(p.glob("*.pack"))


def read_manifest(pack_path: str | Path) -> dict:
    with zipfile.ZipFile(pack_path) as zf:
        try:
            raw = zf.read(MANIFEST_NAME)
        except KeyError as exc:
            raise PackError("החבילה אינה כוללת manifest.json") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise PackError("manifest.json פגום") from exc


def _check_compatible(manifest: dict) -> None:
    fmt = manifest.get("pack_format")
    if fmt != PACK_FORMAT:
        raise PackError(f"פורמט חבילה לא נתמך: {fmt} (נתמך {PACK_FORMAT})")
    min_ver = manifest.get("app_min_version")
    if min_ver and compare(__version__, min_ver) < 0:
        raise PackError(
            f"החבילה דורשת גרסת אפליקציה {min_ver} ומעלה (מותקן {__version__})"
        )


def install_pack(pack_path: str | Path, dest_dir: str | Path) -> dict:
    """Verify and install every component of ``pack_path`` into ``dest_dir``.

    Returns a summary dict. Raises :class:`PackError` on any incompatibility or
    integrity mismatch (nothing is left half-installed silently — we verify a
    component's bytes before writing them).
    """
    pack_path = Path(pack_path)
    dest = Path(dest_dir)
    manifest = read_manifest(pack_path)
    _check_compatible(manifest)

    installed: list[str] = []
    with zipfile.ZipFile(pack_path) as zf:
        names = set(zf.namelist())
        components = manifest.get("components", [])
        # First pass: verify everything before writing anything.
        for c in components:
            target = c.get("target")
            if not target or target not in names:
                raise PackError(f"רכיב חסר בחבילה: {target}")
            data = zf.read(target)
            expected = c.get("sha256")
            if expected and _sha256_bytes(data) != expected:
                raise PackError(f"בדיקת שלמות נכשלה עבור {c.get('name', target)}")
        # Second pass: extract.
        for c in components:
            target = c["target"]
            out_path = dest / target
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(zf.read(target))
            installed.append(target)

    # Record the installation so the app does not reinstall the same pack.
    marker = dest / "installed_packs.json"
    record = {
        "pack": pack_path.name,
        "pack_format": manifest.get("pack_format"),
        "created": manifest.get("created"),
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "components": installed,
    }
    existing = []
    if marker.exists():
        try:
            existing = json.loads(marker.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    existing.append(record)
    marker.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"ok": True, "pack": pack_path.name, "installed": installed, "count": len(installed)}


def build_pack(
    out_path: str | Path,
    components: list[tuple[str, str, str | Path]],
    *,
    app_min_version: str = __version__,
) -> dict:
    """Build a ``.pack`` from ``(name, type, source_path)`` tuples.

    The source file's basename becomes its ``target`` inside the pack. Computes
    each component's SHA-256 and size and writes the manifest, so the produced
    pack passes :func:`install_pack` verification.
    """
    out_path = Path(out_path)
    manifest_components: list[dict] = []
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, ctype, src in components:
            src = Path(src)
            data = src.read_bytes()
            target = f"{ctype}/{src.name}"
            zf.writestr(target, data)
            manifest_components.append(
                asdict(Component(name=name, type=ctype, target=target,
                                 sha256=_sha256_bytes(data), size=len(data)))
            )
        manifest = {
            "pack_format": PACK_FORMAT,
            "created": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "app_min_version": app_min_version,
            "components": manifest_components,
        }
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
    return {"ok": True, "pack": str(out_path), "count": len(manifest_components)}
