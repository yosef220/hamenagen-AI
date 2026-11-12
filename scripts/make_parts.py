"""Pack each part of a built app as its own ZIP, for the smart update.

    python scripts/make_parts.py dist/win-unpacked dist/parts

Reads resources/parts.json (written by scripts/parts.js while packaging) and
writes, into the output folder:

* ``hamenagen-part-<name>-<fingerprint[:16]>.zip`` — one per part, holding
  the part's files relative to where they go (the program's folder for the
  runtime, resources for the rest). The ZIPs are deterministic: the same
  files make the same bytes in every job, so a part shared by the editions
  is one file in the release.
* ``parts-<edition>.json`` — the edition's parts.json plus each part's ZIP
  name; scripts/release_notes.py adds the sizes, checksums and addresses.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

STAMP = (1980, 1, 1, 0, 0, 0)
STORE_SUFFIXES = {".onnx", ".zip", ".7z", ".gz", ".png", ".jpg", ".pak", ".dat"}


def _files(base: Path, entries: list[str]) -> list[str]:
    out: list[str] = []
    for entry in entries:
        p = base / entry
        if p.is_dir():
            out += [f.relative_to(base).as_posix() for f in p.rglob("*") if f.is_file()]
        elif p.is_file():
            out.append(entry)
    return sorted(out, key=lambda r: r.encode("utf-8"))


def pack(base: Path, entries: list[str], target: Path, skip: set[str] = frozenset()) -> int:
    count = 0
    with zipfile.ZipFile(target, "w", allowZip64=True) as z:
        for rel in _files(base, entries):
            if rel in skip:
                continue
            info = zipfile.ZipInfo(rel, date_time=STAMP)
            info.external_attr = 0o644 << 16
            info.create_system = 0
            store = Path(rel).suffix.lower() in STORE_SUFFIXES
            info.compress_type = zipfile.ZIP_STORED if store else zipfile.ZIP_DEFLATED
            with open(base / rel, "rb") as src, z.open(info, "w", force_zip64=True) as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
            count += 1
    return count


def main(unpacked: str, out_dir: str) -> int:
    root = Path(unpacked)
    resources = root / "resources"
    manifest = json.loads((resources / "parts.json").read_text(encoding="utf-8"))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, part in manifest["parts"].items():
        base = root if part["kind"] == "root" else resources
        file = f"hamenagen-part-{name}-{part['hash'][:16]}.zip"
        if not (out / file).exists():
            n = pack(base, part["entries"], out / file)
            print(f"{file}: {n} files, {(out / file).stat().st_size / 1048576:.1f}MB")
        part["file"] = file
    target = out / f"parts-{manifest['edition']}.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
