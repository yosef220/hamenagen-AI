"""Curated topic lexicon (spec §8.2, layer 1).

This is the fast, high-confidence layer of the hybrid classifier. It maps
known song titles, artists and strong keywords to a topic. For community
music much of the catalogue already has a well-known association, so this
table alone resolves a large share of requests correctly and instantly.

The table is intentionally data — it is meant to be extended by hand and
refreshed from the network with the rest of the updates (spec §14). Matching
is done on *normalized* tokens (see :mod:`hamenagen.text_normalize`) so
spelling/spacing variants collapse together.

The classic example from the spec: the Shabbat zemer "מנוחה ושמחה" must be
classified as Shabbat even though the word "שבת" never appears in it. That
song is seeded below.

A song can carry more than one topic: the first match becomes its main topic
and every other match is kept as a tag (a Shabbat zemer on an a cappella
album is both "שבת" and "ווקאלי"). The order of :data:`TOPIC_KEYWORDS` is
therefore the order of precedence.
"""

from __future__ import annotations

import json
from pathlib import Path

# Canonical topic keys and their Hebrew display labels, in display order.
TOPIC_LABELS: dict[str, str] = {
    "שבת": "שבת",
    "ראש השנה": "ראש השנה",
    "יום כיפור": "יום כיפור",
    "סוכות": "סוכות",
    "חנוכה": "חנוכה",
    "פורים": "פורים",
    "פסח": "פסח",
    "ל״ג בעומר": "ל״ג בעומר",
    "שבועות": "שבועות",
    "אלול": "אלול וסליחות",
    "חתונה": "חתונה ושמחות",
    "ירושלים": "ירושלים",
    "אמונה": "אמונה וביטחון",
    "ווקאלי": "ווקאלי — בלי כלים",
}

# How a playlist of each topic is named in a sentence ("שעה של שירי שבת").
TOPIC_PHRASES: dict[str, str] = {
    "שבת": "שירי שבת",
    "ראש השנה": "שירים לראש השנה",
    "יום כיפור": "שירים ליום כיפור",
    "סוכות": "שירי סוכות",
    "חנוכה": "שירי חנוכה",
    "פורים": "שירי פורים",
    "פסח": "שירי פסח",
    "ל״ג בעומר": "שירים לל״ג בעומר",
    "שבועות": "שירים לשבועות",
    "אלול": "שירים לאלול ולסליחות",
    "חתונה": "שירי חתונה ושמחות",
    "ירושלים": "שירים על ירושלים",
    "אמונה": "שירי אמונה וביטחון",
    "ווקאלי": "מוזיקה ווקאלית",
}


def topic_phrase(topic: str) -> str:
    return TOPIC_PHRASES.get(topic) or f"שירים בנושא {TOPIC_LABELS.get(topic, topic)}"


# Strong keywords: if any appears (as a whole normalized token, or as a phrase
# for multi-word keywords) in the song's text, the topic applies. Earlier
# entries win the main topic; "ווקאלי" is last because it describes how a
# song is performed rather than what it is about.
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "שבת": ["שבת", "מנוחה", "לכה דודי", "קבלת שבת", "זמירות", "שלום עליכם", "מלווה מלכה",
             "סעודה שלישית", "אשת חיל", "ידיד נפש"],
    "ראש השנה": ["ראש השנה", "שנה טובה", "שופר", "תשליך", "תקיעת שופר"],
    "יום כיפור": ["יום כיפור", "יום הכיפורים", "כל נדרי", "נעילה", "ונתנה תוקף"],
    "סוכות": ["סוכות", "סוכה", "ארבעת המינים", "הושענא", "שמחת בית השואבה", "שמחת תורה",
               "ושאבתם מים", "אושפיזין"],
    "חנוכה": ["חנוכה", "מכבים", "מעוז צור", "סביבון", "לביבות", "הנרות הללו", "פך השמן"],
    "פורים": ["פורים", "מרדכי", "אסתר", "משלוח מנות", "ונהפוך הוא", "שושנת יעקב",
               "משנכנס אדר", "ליהודים היתה אורה"],
    "פסח": ["פסח", "הגדה", "מצה", "חד גדיא", "דיינו", "יציאת מצרים", "מה נשתנה",
             "אחד מי יודע", "והיא שעמדה", "ליל הסדר"],
    "ל״ג בעומר": ["ל״ג בעומר", "בר יוחאי", "רשב״י", "רבי שמעון", "מירון", "הילולא"],
    "שבועות": ["שבועות", "מתן תורה", "עצרת", "מגילת רות"],
    "אלול": ["אלול", "סליחות", "תשובה", "אבינו מלכנו", "תתעורר", "התעוררות", "ימים נוראים",
              "אנא בכוח"],
    "חתונה": ["חתונה", "חתן", "כלה", "מזל טוב", "ריקודים", "חופה", "קול ששון"],
    "ירושלים": ["ירושלים", "ציון", "הכותל", "עיר הקודש", "בית המקדש"],
    "אמונה": ["אמונה", "ביטחון", "בורא עולם", "תפילה", "השגחה"],
    "ווקאלי": ["ווקאלי", "ווקאלית", "ווקאל", "אקפלה", "אקאפלה", "acapella", "acappella",
                "a cappella", "vocal", "ספירה", "לספירה", "בין המצרים", "בלי כלים"],
}

# Explicit song-title → topic overrides for songs whose *title* gives no hint.
# Keys are normalized in the classifier before lookup.
SONG_TITLE_TOPICS: dict[str, str] = {
    # Shabbat zemirot and songs.
    "מנוחה ושמחה": "שבת",
    "מה ידידות": "שבת",
    "צור משלו": "שבת",
    "יה ריבון": "שבת",
    "דרור יקרא": "שבת",
    "כי אשמרה שבת": "שבת",
    "יום זה מכובד": "שבת",
    "יום שבתון": "שבת",
    "יום זה לישראל": "שבת",
    "ברוך א-ל עליון": "שבת",
    "ברוך קל עליון": "שבת",
    "כה אכסוף": "שבת",
    "קה אכסוף": "שבת",
    "מה יפית": "שבת",
    "אזמר בשבחין": "שבת",
    "אתקינו סעודתא": "שבת",
    "בני היכלא": "שבת",
    "מזמור לדוד": "שבת",
    "שלום עליכם": "שבת",
    "ידיד נפש": "שבת",
    "אשת חיל": "שבת",
    "לכה דודי": "שבת",
    # Festivals.
    "הנרות הללו": "חנוכה",
    "ימי החנוכה": "חנוכה",
    "אנו נושאים לפידים": "חנוכה",
    "שושנת יעקב": "פורים",
    "אדיר הוא": "פסח",
    "כי לו נאה": "פסח",
    "ושאבתם מים": "סוכות",
    "אמר רבי עקיבא": "ל״ג בעומר",
    "אנא בכוח": "אלול",
    "אבינו מלכנו": "אלול",
}

# Artist → default topic (weak signal, used only when nothing stronger hits).
ARTIST_TOPICS: dict[str, str] = {}


def topic_list() -> list[dict]:
    """Topics in display order, as ``[{key, label, phrase}]`` for the UI."""
    return [{"key": k, "label": v, "phrase": topic_phrase(k)} for k, v in TOPIC_LABELS.items()]


def load_override(path: str | Path) -> bool:
    """Merge a downloaded lexicon update (``topics_override.json``) in place.

    The file may carry any of ``keywords``, ``titles`` and ``artists``; each
    is merged into the bundled tables. Returns ``True`` when something was
    applied. A malformed file is ignored, so an update can never break the
    built-in lexicon.
    """
    p = Path(path)
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    applied = False
    for topic, words in (data.get("keywords") or {}).items():
        if isinstance(words, list):
            bucket = TOPIC_KEYWORDS.setdefault(topic, [])
            bucket.extend(w for w in words if isinstance(w, str) and w not in bucket)
            TOPIC_LABELS.setdefault(topic, topic)
            applied = True
    for table, key in ((SONG_TITLE_TOPICS, "titles"), (ARTIST_TOPICS, "artists")):
        entries = data.get(key) or {}
        if isinstance(entries, dict):
            table.update({k: v for k, v in entries.items() if isinstance(k, str) and isinstance(v, str)})
            applied = applied or bool(entries)
    return applied
