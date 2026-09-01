#!/usr/bin/env python3
"""Pre-download the local ONNX embedding model into the app's models cache.

Run this once on a machine WITH internet to populate the model, so it can be
bundled with the app / offline pack for fully-offline classification
(spec §6, §8.2). Uses fastembed (onnxruntime) — light, no PyTorch.

Usage:
    python scripts/prepare_model.py [--model NAME] [--out DIR]

Requires:
    pip install fastembed
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

DEFAULT_MODEL = "intfloat/multilingual-e5-small"


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
        from fastembed import TextEmbedding
    except ImportError:
        print("fastembed is not installed. Run: pip install fastembed", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"Downloading model '{args.model}' into {out} ...")
    model = TextEmbedding(model_name=args.model, cache_dir=str(out))
    # Warm up so cached artefacts are complete.
    list(model.embed(["query: שיר לשבת", "query: נרות חנוכה"]))
    print("Done. The model is ready for offline use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
