#!/usr/bin/env python3
"""Build an offline installation pack (docs/OFFLINE_PACK.md, spec §6.2).

Bundle the AI model, curated lexicon and any binaries into a single verifiable
``assets.pack`` that end users drop next to the app for fully-offline setup.

Usage:
    python scripts/build_pack.py assets.pack \
        model:model=./data/models/embed-he-mini \
        lexicon:topics-lexicon=./topics.json

Each component is  TYPE:NAME=PATH  (PATH may be a file). Directories should be
zipped into a single file first; this helper bundles files.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hamenagen.offline_pack import build_pack  # noqa: E402


def parse_component(spec: str) -> tuple[str, str, str]:
    try:
        left, path = spec.split("=", 1)
        ctype, name = left.split(":", 1)
    except ValueError as exc:
        raise SystemExit(f"רכיב לא תקין: {spec!r} (צפוי TYPE:NAME=PATH)") from exc
    return name, ctype, path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build an offline .pack")
    parser.add_argument("out", help="output .pack path")
    parser.add_argument("components", nargs="+", help="TYPE:NAME=PATH entries")
    parser.add_argument("--app-min-version", default=None)
    args = parser.parse_args(argv)

    comps = [parse_component(c) for c in args.components]
    for _name, _type, path in comps:
        if not Path(path).is_file():
            raise SystemExit(f"קובץ לא נמצא: {path}")

    kwargs = {}
    if args.app_min_version:
        kwargs["app_min_version"] = args.app_min_version
    result = build_pack(args.out, comps, **kwargs)
    print(f"נבנתה חבילה: {result['pack']} ({result['count']} רכיבים)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
