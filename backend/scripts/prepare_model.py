#!/usr/bin/env python3
"""Download the local embedding model into a models folder.

Run once on a machine WITH internet to fill the folder that ships inside the
offline edition (resources/models), or to pre-seed a data folder:

    python scripts/prepare_model.py --out build/models

The model and its pinned revision come from hamenagen.classifier.MODELS; the
app reads the same folder layout, so what this writes is what it loads.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# The Windows embedded Python defaults to a cp1252 console encoding, which
# cannot encode Hebrew — force UTF-8 so status prints don't crash the build.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hamenagen.classifier import DEFAULT_MODEL, MODELS, EmbeddingBackend, download_model  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download the embedding model")
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(MODELS))
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "data" / "models"))
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    last = {"pct": -1}

    def progress(p: dict) -> None:
        pct = int(p["downloaded"] * 100 / p["total"]) if p.get("total") else 0
        if pct // 10 != last["pct"] // 10:
            last["pct"] = pct
            print(f"  {p['file']}: {pct}%", flush=True)

    print(f"Downloading {args.model} into {out} ...")
    download_model(args.model, out, on_progress=progress)
    backend = EmbeddingBackend(args.model, cache_dir=str(out), allow_download=False)
    if not backend.load():
        print(f"The model did not load: {backend.load_error}", file=sys.stderr)
        return 1
    print("Check:", backend.classify("סופגניות ונרות", threshold=0.0))
    print("Done. The model is ready for offline use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
