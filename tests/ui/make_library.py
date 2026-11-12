"""Create a small demo music library for the UI harness.

Writes silent 8 kHz WAV files named "performer - title.wav" — real durations,
Hebrew names, a spread of topics — so the app has something to scan, sort,
classify and play. Usage: python make_library.py <folder>
"""

from __future__ import annotations

import math
import struct
import shutil
import sys
import wave
import zlib
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


# Album covers for some performers (the others keep the letter), drawn here
# so the harness needs no image library: a record on a coloured sleeve.
COVERS = {
    "מקהלת שירת הים": ((29, 91, 159), (169, 122, 31)),
    "קול ברמה": ((22, 54, 95), (216, 178, 94)),
    "אברהם ויוסף": ((120, 52, 44), (243, 214, 160)),
    "אחים כהן": ((47, 122, 79), (233, 238, 246)),
    "להקת הנרות": ((154, 106, 0), (255, 244, 214)),
    "תזמורת ניגון": ((74, 88, 112), (227, 237, 248)),
    "שמוליק סוכות": ((90, 46, 120), (240, 220, 250)),
}


def png(width: int, height: int, pixel) -> bytes:
    rows = b"".join(b"\x00" + bytes(c for x in range(width) for c in pixel(x, y)) for y in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def cover(sleeve: tuple, accent: tuple, size: int = 160) -> bytes:
    c = size / 2

    def pixel(x, y):
        d = math.hypot(x - c * 1.18, y - c * 0.95)
        if d < size * 0.06:
            return accent
        if d < size * 0.42:
            ring = int(d / 3) % 2
            return tuple(int(v * (0.16 if ring else 0.24)) for v in (255, 255, 255))
        band = (x + y) // 18 % 2
        return tuple(min(255, int(v * (1.0 if band else 0.86))) for v in sleeve)

    return png(size, size, pixel)


def embed_cover(path: Path, picture: bytes) -> None:
    try:
        from mutagen.id3 import APIC  # type: ignore
        from mutagen.wave import WAVE  # type: ignore
    except Exception:
        return  # no mutagen: songs without covers
    audio = WAVE(path)
    if audio.tags is None:
        audio.add_tags()
    audio.tags.add(APIC(encoding=3, mime="image/png", type=3, desc="", data=picture))
    audio.save()


def main(folder: str) -> int:
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    pictures = {name: cover(*colors) for name, colors in COVERS.items()}
    for performer, title, seconds in SONGS:
        target = out / f"{performer} - {title}.wav"
        if not target.exists():
            write_wav(target, seconds)
            if performer in pictures:
                embed_cover(target, pictures[performer])
    # The same song kept twice (a backup folder): the library shows it once.
    backup = out / "גיבוי"
    backup.mkdir(exist_ok=True)
    original = out / "מקהלת שירת הים - מנוחה ושמחה.wav"
    if not (backup / original.name).exists():
        shutil.copyfile(original, backup / original.name)
    print(f"{len(SONGS)} songs in {out}, one of them twice")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "demo-music"))
