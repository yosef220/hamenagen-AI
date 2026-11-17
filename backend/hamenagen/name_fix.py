"""Names of songs downloaded from the web, made clean (1.6).

A file from a download site often carries the whole video title as its name
("ישי ריבו - מנוחה ושמחה (Official Video) | Ishay Ribo"), the singer inside the
song's name with a channel or a site in the singer's field, or a site's
address. Here each name is read and, when it is not clean, a fix is
suggested: noise removed (an official video, HD, a producer's credit, a web
address, the English half of a two-language title), the singer taken out of
the song's name. A live performance stays marked ("לייב", "Live").

A fix is only a suggestion. "sure" ones (noise removed, a singer split off
a name that had none) are offered checked; a guess (a singer's field that
looks like a channel, replaced by the name before the dash) is not. Applied
fixes are kept by the player (the details table), never written to the file
unless the listener writes the tags.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .text_normalize import normalize

# What a video title adds to a song's name.
_NOISE = (
    r"official(?:\s+(?:music|lyrics?|hd))?(?:\s+(?:video|audio|clip|visualizer))?|"
    r"(?:music|lyrics?)\s+video|lyrics?|audio(?:\s+only)?|video(?:\s*clip)?|clip|visuali[sz]er|"
    r"hd|hq|4k|1080p|720p|full\s+hd|"
    r"(?:ה)?קליפ(?:\s+(?:ה)?רשמי)?|(?:ה)?גרסה\s+(?:ה)?רשמית|אודיו|מילים|(?:ה)?סינגל(?:\s+(?:ה)?רשמי)?|"
    r"(?:ה)?סינגל\s+החדש|וידאו(?:\s+קליפ)?"
)
# Noise in brackets, anywhere in the name (and a producer's credit).
_BRACKETED = re.compile(
    r"\s*[\(\[\{]\s*(?:" + _NOISE + r"|"
    r"prod\.?(?:uced)?\s+by[^\)\]\}]*|מיוצר\s+על\s+ידי[^\)\]\}]*|הפקה\s+מוזיקלית[^\)\]\}]*"
    r")\s*[\)\]\}]",
    re.IGNORECASE,
)
# A part between dashes that is only noise ("זמר - הקליפ הרשמי - שיר").
_NOISE_PART = re.compile(r"^(?:" + _NOISE + r")$", re.IGNORECASE)
# The same words without brackets, at the end of the name.
_TRAILING = re.compile(
    r"(?:\s+[-–—|]\s*|\s+)(?:"
    r"official\s+(?:music\s+)?(?:video|audio|clip)|lyrics?\s+video|official\s+video|"
    r"(?:ה)?קליפ\s+(?:ה)?רשמי|הקליפ|גרסה\s+רשמית|hd|4k"
    r")\s*$",
    re.IGNORECASE,
)
_DOMAIN = re.compile(r"\s*[\(\[]?\s*(?:https?://)?(?:www\.)?[\w-]+\.(?:co\.il|org\.il|com|net|org|info|fm|tv)\b\S*\s*[\)\]]?",
                     re.IGNORECASE)
_DASHES = (" - ", " – ", " — ")

# A singer's field that names a channel, a label or a site rather than a singer.
_CHANNEL = re.compile(
    r"(?:\btopic\b|\bvevo\b|\bofficial\b|\brecords?\b|\brecordings\b|\bproductions?\b|\bmusic\s+group\b|"
    r"\bchannel\b|\btv\b|\bmusic\b|\bmedia\b|ערוץ|הפקות|אולפני|הערוץ\s+הרשמי|תקליטים|"
    r"\.(?:co\.il|com|net|org))",
    re.IGNORECASE,
)


@dataclass
class Fix:
    title: str
    artist: str
    sure: bool
    why: str


def _has_hebrew(text: str) -> bool:
    return any("א" <= ch <= "ת" for ch in text or "")


def clean_title(title: str) -> tuple[str, list[str]]:
    """The name without its noise, and what was taken out (in Hebrew words)."""
    text = (title or "").strip()
    why: list[str] = []
    # A two-language title: keep the Hebrew half.
    parts = [p.strip() for p in re.split(r"\s+[|｜]\s+|\s+//\s+", text) if p.strip()]
    if len(parts) > 1 and any(_has_hebrew(p) for p in parts) and not all(_has_hebrew(p) for p in parts):
        text = next(p for p in parts if _has_hebrew(p))
        why.append("החצי באנגלית")
    without_site = " ".join(_DOMAIN.sub(" ", text).split()).strip(" -–—|_")
    if without_site != text:
        why.append("כתובת של אתר")
        text = without_site
    for _ in range(3):
        cleaned = _BRACKETED.sub("", text)
        cleaned = _TRAILING.sub("", cleaned)
        pieces = re.split(r"\s+[-–—]\s+", cleaned)
        if len(pieces) > 1:
            cleaned = " - ".join(p for p in pieces if not _NOISE_PART.match(p.strip())) or cleaned
        cleaned = " ".join(cleaned.split()).strip(" -–—|_")
        if cleaned == text:
            break
        if "תוספות כמו „קליפ רשמי”" not in why:
            why.append("תוספות כמו „קליפ רשמי”")
        text = cleaned
    return text, why


def looks_like_channel(artist: str) -> bool:
    return bool(artist) and bool(_CHANNEL.search(artist))


def suggest(title: str, artist: str) -> Fix | None:
    """A cleaner (title, artist) for a song, or None when it is clean."""
    new_title, why = clean_title(title)
    if not new_title:
        return None
    new_artist = (artist or "").strip()
    sure = True
    for sep in _DASHES:
        if sep not in new_title:
            continue
        left, right = (x.strip() for x in new_title.split(sep, 1))
        if not left or not right or len(left.split()) > 5 or left.isdigit():
            break
        if new_artist and normalize(left) == normalize(new_artist):
            new_title = right
            why.append("שם הזמר בתוך שם השיר")
        elif not new_artist:
            new_artist, new_title = left, right
            why.append("הזמר הופרד משם השיר")
        elif looks_like_channel(new_artist):
            why.append(f"„{new_artist}” נראה כמו ערוץ ולא כמו זמר")
            new_artist, new_title = left, right
            sure = False
        break
    else:
        if new_artist and looks_like_channel(new_artist) and normalize(new_artist).endswith("topic"):
            new_artist = re.sub(r"\s*-\s*topic\s*$", "", new_artist, flags=re.IGNORECASE).strip()
            why.append("„Topic” של יוטיוב")
    if (new_title, new_artist) == ((title or "").strip(), (artist or "").strip()) or not new_title:
        return None
    return Fix(new_title, new_artist, sure, " · ".join(why))
