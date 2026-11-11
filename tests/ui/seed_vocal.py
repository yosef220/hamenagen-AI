"""Seed what the vocal detector would have heard, for the UI harness.

Scans the demo library into a data folder with the real core, then records
verdicts for a few songs, so the review list on the "ווקאלי" page has
something to show without the audio model. Usage:
    python tests/ui/seed_vocal.py <music-folder> <data-folder>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from hamenagen.service import PlayerService  # noqa: E402
from hamenagen.vocal import MODEL_NAME  # noqa: E402

HEARD = {
    "ניגון געגועים": ("vocal", 0.62),
    "תפילה לשלום": ("vocal", 0.41),
    "בוקר של אור": ("maybe", 0.05),
}


def main(music: str, data: str) -> int:
    service = PlayerService(data_dir=data)
    service.settings.use_embeddings = False  # no model download from a seeding script
    service.classifier.embedding = None
    service.rescan([str(Path(music).resolve())])
    seeded = 0
    for track in service.index.all_tracks():
        if track.title in HEARD:
            verdict, acapella = HEARD[track.title]
            service.index.save_analysis(track.id, {
                "model": MODEL_NAME, "verdict": verdict, "acapella": acapella, "instrument": 0.01,
                "windows": json.dumps([[acapella, 0.01, 0.0, 0.0]] * 3),
                "mtime": track.mtime, "size": track.size, "analyzed_at": "2026-11-11T12:00:00",
            })
            seeded += 1
    service.close()
    print(f"seeded {seeded} vocal verdicts")
    return 0 if seeded == len(HEARD) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
