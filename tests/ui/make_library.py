"""Create a small demo music library for the UI harness.

Writes silent 8 kHz WAV files named "performer - title.wav" — real durations,
Hebrew names, a spread of topics — so the app has something to scan, sort,
classify and play. Usage: python make_library.py <folder>
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

SONGS = [
    ("מקהלת שירת הים", "מנוחה ושמחה", 214), ("קול ברמה", "יה ריבון", 251),
    ("מקהלת שירת הים", "צור משלו", 198), ("אברהם ויוסף", "לכה דודי", 287),
    ("קול ברמה", "שלום עליכם", 176), ("זמירות שבת", "יום זה מכובד", 233),
    ("אחים כהן", "ידיד נפש", 262), ("להקת הנרות", "מעוז צור", 189),
    ("ילדי השכונה", "סביבון", 151), ("קול ברמה", "הנרות הללו", 204),
    ("מקהלת שירת הים", "ימי החנוכה", 222), ("שמוליק סוכות", "אמת", 241),
    ("קול ברמה", "ושאבתם מים", 268), ("תזמורת ניגון", "שמחת בית השואבה", 305),
    ("משפחת לוי", "אחד מי יודע", 318), ("משפחת לוי", "חד גדיא", 245),
    ("קול ברמה", "והיא שעמדה", 276), ("תזמורת ניגון", "שושנת יעקב", 193),
    ("ילדי השכונה", "משנכנס אדר", 167), ("קול ברמה", "אבינו מלכנו", 296),
    ("מקהלת שירת הים", "אנא בכוח", 239), ("אברהם ויוסף", "בר יוחאי", 284),
    ("תזמורת ניגון", "קול ששון", 211), ("להקת השמחה", "מזל טוב", 186),
    ("מקהלת שירת הים", "ירושלים של זהב", 302), ("אחים כהן", "שיר לציון", 227),
    ("קול ברמה", "בורא עולם", 258), ("אברהם ויוסף", "תפילה לשלום", 244),
    ("אקפלה", "ניגון ספירה", 199), ("אחים כהן", "ניגון געגועים", 273),
    ("תזמורת ניגון", "בוקר של אור", 207), ("להקת השמחה", "רוקדים במעגל", 192),
]

RATE = 8000


def write_wav(path: Path, seconds: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(RATE)
        w.writeframes(b"\x80" * (RATE * seconds))  # 8-bit silence


def main(folder: str) -> int:
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    for performer, title, seconds in SONGS:
        target = out / f"{performer} - {title}.wav"
        if not target.exists():
            write_wav(target, seconds)
    print(f"{len(SONGS)} songs in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "demo-music"))
