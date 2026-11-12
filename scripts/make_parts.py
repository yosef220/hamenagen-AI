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

Python's compiled caches (``__pycache__``) are never packed: the build runs
the packaged core to check it, and the caches it leaves behind are not part
of the fingerprint. Each ZIP is then read back and checked against the
fingerprint, exactly as the installed app checks it after downloading — a
part that would be refused there stops the build here.
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

STAMP = (1980, 1, 1, 0, 0, 0)
STORE_SUFFIXES = {".onnx", ".zip", ".7z", ".gz", ".png", ".jpg", ".pak", ".dat"}


def is_cache(rel: str) -> bool:
    """Python's compiled caches (as smart_update.is_cache)."""
    return rel.endswith(".pyc") or "__pycache__" in rel.split("/")


def _files(base: Path, entries: list[str]) -> list[str]:
    out: list[str] = []
    for entry in entries:
        p = base / entry
        if p.is_dir():
            out += [r for r in (f.relative_to(base).as_posix() for f in p.rglob("*") if f.is_file())
                    if not is_cache(r)]
        elif p.is_file():
            out.append(entry)
    return sorted(out, key=lambda r: r.encode("utf-8"))


def zip_hash(target: Path) -> tuple[str, int]:
    """The fingerprint of what a part's ZIP unpacks to, computed the way the
    installed app computes it (smart_update.content_hash): one line per file,
    "path<TAB>size<TAB>sha256", sorted by UTF-8 bytes. Every file counts, as
    in 1.3.0, which did not yet leave Python's caches out."""
    lines: list[tuple[bytes, str]] = []
    with zipfile.ZipFile(target) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            h = hashlib.sha256()
            with z.open(info) as f:
                while chunk := f.read(1 << 20):
                    h.update(chunk)
            lines.append((info.filename.encode("utf-8"), f"{info.filename}\t{info.file_size}\t{h.hexdigest()}\n"))
    lines.sort(key=lambda x: x[0])
    return hashlib.sha256("".join(line for _, line in lines).encode("utf-8")).hexdigest(), len(lines)


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
    bad: list[str] = []
    for name, part in manifest["parts"].items():
        base = root if part["kind"] == "root" else resources
        file = f"hamenagen-part-{name}-{part['hash'][:16]}.zip"
        if not (out / file).exists():
            n = pack(base, part["entries"], out / file)
            print(f"{file}: {n} files, {(out / file).stat().st_size / 1048576:.1f}MB")
        part["file"] = file
        if not part.get("fingerprint"):
            # The installed app refuses a part whose files differ from the
            # fingerprint; so does the build.
            got, n = zip_hash(out / file)
            if got != part["hash"]:
                bad.append(f"{name}: the ZIP holds {n} files whose fingerprint is {got[:16]}, "
                           f"not {part['hash'][:16]} ({part.get('files')} files when packaged)")
    if bad:
        print("parts that would be refused by the smart update:\n  " + "\n  ".join(bad), file=sys.stderr)
        return 1
    target = out / f"parts-{manifest['edition']}.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
