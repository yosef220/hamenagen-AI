#!/usr/bin/env python3
"""Fetch the vocal-detection model (CED-Tiny, int8 ONNX, 6 MB) into a folder.

The model comes from the sherpa-onnx release "audio-tagging-models"
(converted from https://github.com/RicherMans/CED, weights Apache-2.0).
Both the archive and the model inside it are checked against pinned SHA-256
digests, so every build ships exactly the same file.

Usage::

    python backend/scripts/prepare_audio_model.py --out build/audio-models
    python backend/scripts/prepare_audio_model.py --out data/models     # for a dev run
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from hamenagen.vocal import MODEL_FILE, MODEL_FOLDER, MODEL_NAME, MODEL_SHA256, VocalDetector  # noqa: E402

ARCHIVE_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/audio-tagging-models/"
               "sherpa-onnx-ced-tiny-audio-tagging-2024-04-19.tar.bz2")
ARCHIVE_SHA256 = "84baf315b57d61aa69480c4fee878dab54cbc7be3e877db334e65d8b087e23c3"
MEMBER = "sherpa-onnx-ced-tiny-audio-tagging-2024-04-19/model.int8.onnx"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="folder that will hold ced-tiny/model.int8.onnx")
    ap.add_argument("--archive", help="use an already downloaded archive instead of the network")
    args = ap.parse_args()

    target_dir = Path(args.out) / MODEL_FOLDER
    target = target_dir / MODEL_FILE
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == MODEL_SHA256:
        print(f"already there: {target}")
        return 0

    if args.archive:
        data = Path(args.archive).read_bytes()
    else:
        print(f"downloading {ARCHIVE_URL}")
        req = urllib.request.Request(ARCHIVE_URL, headers={"User-Agent": "hamenagen-build"})
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - pinned URL, checked below
            data = resp.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != ARCHIVE_SHA256:
        print(f"archive checksum mismatch: {digest}", file=sys.stderr)
        return 1

    with tarfile.open(fileobj=io.BytesIO(data), mode="r:bz2") as tar:
        member = tar.getmember(MEMBER)
        model = tar.extractfile(member).read()  # one known member; nothing else is extracted
    if hashlib.sha256(model).hexdigest() != MODEL_SHA256:
        print("model checksum mismatch", file=sys.stderr)
        return 1

    target_dir.mkdir(parents=True, exist_ok=True)
    target.write_bytes(model)
    (target_dir / "model.json").write_text(json.dumps({
        "name": MODEL_NAME,
        "source": ARCHIVE_URL,
        "upstream": "https://github.com/RicherMans/CED",
        "licence": "Apache-2.0",
        "sha256": MODEL_SHA256,
    }, indent=2), encoding="utf-8")

    detector = VocalDetector([args.out])
    if VocalDetector.libraries_present():
        ok = detector.load()
        print(f"model {'loads' if ok else 'does NOT load: ' + detector.load_error}")
        if not ok:
            return 1
    print(f"wrote {target} ({len(model) / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
