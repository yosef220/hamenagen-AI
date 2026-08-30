#!/usr/bin/env python3
"""Pre-download the local embedding model into the app's models cache.

Run this once on a machine WITH internet to populate the model, so it can be
bundled into the offline pack (docs/OFFLINE_PACK.md) or shipped with the app
for fully-offline classification (spec §6, §8.2).

Usage:
    python scripts/prepare_model.py [--model NAME] [--out DIR]

Requires the optional dependency:
    pip install sentence-transformers
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

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-download the embedding model")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[2] / "data" / "models"),
        help="cache folder to download the model into",
    )
    args = parser.parse_args(argv)

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("sentence-transformers אינו מותקן. הרץ: pip install sentence-transformers", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"מוריד את המודל '{args.model}' אל {out} …")
    model = SentenceTransformer(args.model, cache_folder=str(out))
    # Warm up so cached artefacts are complete.
    model.encode(["שיר לשבת", "נרות חנוכה"])
    print("הושלם. המודל מוכן לשימוש אופליין.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
