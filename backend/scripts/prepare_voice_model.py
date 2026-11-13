#!/usr/bin/env python3
"""Fetch the Hebrew speech-recognition model (for requests by voice) into a folder.

ivrit.ai's zipformer2-66m-streaming-he (Yakov Kolani, CC-BY-4.0), int8 ONNX,
73 MB, at a pinned revision; every file is checked against its SHA-256
(hamenagen/voice.py). The offline editions carry it; the others download
the same files on the first press of the microphone button.

Usage::

    python backend/scripts/prepare_voice_model.py --out build/voice-models
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from hamenagen import voice


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="folder that will hold voice-he/")
    args = ap.parse_args()
    rec = voice.SpeechRecognizer([args.out])
    if rec.model_dir() is None:
        print(f"downloading {voice.SOURCE} @ {voice.REVISION[:10]}")
        voice.install(args.out)
    if not rec.load():
        print(f"the model does NOT load: {rec.load_error}", file=sys.stderr)
        return 1
    import numpy as np

    text = rec.recognize(np.zeros(16000, dtype=np.float32))
    print(f"model loads; silence reads as {text!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
