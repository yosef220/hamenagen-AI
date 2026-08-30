"""Command-line interface for the core, for testing without the GUI.

Examples::

    python -m hamenagen.cli scan ~/Music
    python -m hamenagen.cli ask "תשמיע לי שירים של שבת"
    python -m hamenagen.cli suggest
"""

from __future__ import annotations

import argparse
import json
import sys

from .intent import parse as parse_intent
from .service import PlayerService


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hamenagen", description="נגן מוזיקה קהילתי חכם — CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="סרוק תיקיות ובנה אינדקס")
    p_scan.add_argument("roots", nargs="*", help="תיקיות לסריקה (ברירת מחדל: לפי ההגדרות)")

    p_ask = sub.add_parser("ask", help="בקשה בשפה טבעית")
    p_ask.add_argument("text", help="הבקשה, למשל: תשמיע לי שירים של שבת")

    p_intent = sub.add_parser("intent", help="הצג רק את פענוח הכוונה")
    p_intent.add_argument("text")

    sub.add_parser("suggest", help="הצעת פתיחה לפי התאריך העברי")
    sub.add_parser("radio", help="רשימת ערוצי הרדיו החי")
    sub.add_parser("classifier", help="הצג את מצב מודל הסיווג המקומי")
    sub.add_parser("reclassify", help="סווג מחדש את כל השירים במאגר")

    args = parser.parse_args(argv)
    service = PlayerService()
    try:
        if args.cmd == "scan":
            _print(service.rescan(args.roots or None))
        elif args.cmd == "ask":
            _print(service.handle_request(args.text))
        elif args.cmd == "intent":
            _print(parse_intent(args.text).to_dict())
        elif args.cmd == "suggest":
            _print(service.opening_suggestion() or {"suggestion": None})
        elif args.cmd == "radio":
            _print(service.radio_list())
        elif args.cmd == "classifier":
            _print(service.classifier_status())
        elif args.cmd == "reclassify":
            _print(service.reclassify_all())
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
