"""Hebrew-aware text normalization utilities.

Song and artist names on disk are written in wildly inconsistent ways:
underscores instead of spaces, doubled spaces, geresh/gershayim, final
letters, niqqud, and so on. Before we can fuzzy-match a user request against
the local library we normalize both sides through the same pipeline so that
``שמוליק_סוכות`` and ``שמוליק סוכות`` collapse to the same token set.

The functions here are pure and dependency-free so they are cheap to call on
every indexed row and easy to unit-test.
"""

from __future__ import annotations

import re
import unicodedata

# Hebrew niqqud (vowel points) and cantillation marks live in these ranges.
_NIQQUD_RE = re.compile(r"[֑-ׇ]")

# Characters we treat as word separators regardless of how the file was named.
_SEPARATORS_RE = re.compile(r"[\s_\-–—.,;:!?/\\|()\[\]{}\"'`׳״’‘“”]+")

# Map final (sofit) Hebrew letters to their regular form so "שלום"/"שלוﬦ"
# style variations and search tokens compare equal.
_FINAL_LETTERS = {
    "ך": "כ",
    "ם": "מ",
    "ן": "נ",
    "ף": "פ",
    "ץ": "צ",
}

# Common "junk" tokens that appear in downloaded file names and add no signal.
_STOPWORD_TOKENS = {
    "official",
    "video",
    "audio",
    "lyrics",
    "hd",
    "hq",
    "mp3",
    "mp4",
    "youtube",
    "clip",
    "קליפ",
    "רשמי",
    "אודיו",
}


def strip_niqqud(text: str) -> str:
    """Remove Hebrew vowel points and cantillation marks."""
    return _NIQQUD_RE.sub("", text)


def _fold_finals(text: str) -> str:
    return "".join(_FINAL_LETTERS.get(ch, ch) for ch in text)


def normalize(text: str) -> str:
    """Return a canonical, comparable form of ``text``.

    The result is lower-cased, NFC-normalized, stripped of niqqud, has final
    letters folded, and all separators collapsed to single spaces.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = strip_niqqud(text)
    text = text.lower()
    text = _SEPARATORS_RE.sub(" ", text)
    text = _fold_finals(text)
    return text.strip()


def tokens(text: str, *, drop_stopwords: bool = True) -> list[str]:
    """Split normalized ``text`` into a list of comparable tokens."""
    norm = normalize(text)
    if not norm:
        return []
    parts = norm.split(" ")
    if drop_stopwords:
        parts = [p for p in parts if p and p not in _STOPWORD_TOKENS]
    return [p for p in parts if p]


def token_set(text: str, *, drop_stopwords: bool = True) -> set[str]:
    """Return the unique token set of ``text`` (order independent)."""
    return set(tokens(text, drop_stopwords=drop_stopwords))
