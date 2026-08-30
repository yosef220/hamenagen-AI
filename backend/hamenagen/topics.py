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
"""

from __future__ import annotations

# Canonical topic keys and their Hebrew display labels.
TOPIC_LABELS: dict[str, str] = {
    "שבת": "שבת",
    "חנוכה": "חנוכה",
    "אלול": "אלול / סליחות",
    "סוכות": "סוכות",
    "פסח": "פסח",
    "פורים": "פורים",
    "שבועות": "שבועות",
    "ראש השנה": "ראש השנה",
    "יום כיפור": "יום כיפור",
    "חתונה": "חתונה / שמחות",
    "ירושלים": "ירושלים",
    "אמונה": "אמונה וביטחון",
}

# Strong keywords: if any appears (as a whole normalized token) in the song's
# text, the topic is assigned with high confidence.
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "שבת": ["שבת", "מנוחה", "לכה דודי", "קבלת שבת", "זמירות"],
    "חנוכה": ["חנוכה", "מכבים", "נרות", "מעוז צור", "סביבון", "לביבות"],
    "אלול": ["אלול", "סליחות", "תשובה", "אבינו מלכנו", "תתעורר", "התעוררות"],
    "סוכות": ["סוכות", "סוכה", "ארבעת המינים", "הושענא", "שמחת בית השואבה"],
    "פסח": ["פסח", "הגדה", "מצה", "חד גדיא", "דיינו", "יציאת מצרים"],
    "פורים": ["פורים", "משתה", "מרדכי", "אסתר", "משלוח מנות", "ונהפוך הוא"],
    "שבועות": ["שבועות", "מתן תורה", "רות", "עצרת"],
    "ראש השנה": ["ראש השנה", "שנה טובה", "שופר", "תשליך"],
    "יום כיפור": ["יום כיפור", "כל נדרי", "נעילה", "ונתנה תוקף"],
    "חתונה": ["חתונה", "חתן", "כלה", "מזל טוב", "שמחה", "ריקודים"],
    "ירושלים": ["ירושלים", "ציון", "הכותל", "עיר הקודש"],
    "אמונה": ["אמונה", "ביטחון", "השם", "בורא עולם", "תפילה"],
}

# Explicit song-title → topic overrides for songs whose *title* gives no hint.
# Keys are normalized in the classifier before lookup.
SONG_TITLE_TOPICS: dict[str, str] = {
    "מנוחה ושמחה": "שבת",
    "מה ידידות": "שבת",
    "צור משלו": "שבת",
    "יה ריבון": "שבת",
    "דרור יקרא": "שבת",
    "כי אשמרה שבת": "שבת",
    "ידיד נפש": "שבת",
    "אשת חיל": "שבת",
    "מזמור לדוד": "שבת",
    "הנרות הללו": "חנוכה",
    "ימי החנוכה": "חנוכה",
    "אנא בכוח": "אלול",
}

# Artist → default topic (weak signal, used only when nothing stronger hits).
ARTIST_TOPICS: dict[str, str] = {}
