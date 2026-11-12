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

# Geresh / gershayim (and their ASCII stand-ins) *inside* a Hebrew word mark
# an acronym or a numeral — ל״ג, רשב״י, תשפ״ז — so they are dropped rather
# than split the word: "ל״ג בעומר", "ל\"ג בעומר" and "לג בעומר" all become
# "לג בעומר".
_ACRONYM_MARK_RE = re.compile(r"(?<=[\u05d0-\u05ea])[\u05f3\u05f4\"'`’]+(?=[\u05d0-\u05ea])")

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
    text = _ACRONYM_MARK_RE.sub("", text)
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


# Hebrew attaches short words to the next one: ל+שבת, ב+חנוכה, ו+ה+כלה.
# Matching a keyword against a word may peel off one or two of these.
_PREFIX_LETTERS = set("והבלמשכ")
_DOUBLE_PREFIXES = {"וה", "וב", "ול", "ומ", "וש", "וכ", "שה", "שב", "של", "שמ", "מה", "לה", "בה", "כש", "וכש"}


def word_variants(token: str) -> set[str]:
    """``token`` plus the stems left after removing a Hebrew prefix.

    >>> sorted(word_variants("לשבת"))
    ['לשבת', 'שבת']
    """
    out = {token}
    if len(token) > 2 and token[0] in _PREFIX_LETTERS:
        out.add(token[1:])
    if len(token) > 3 and token[:2] in _DOUBLE_PREFIXES:
        out.add(token[2:])
    return out


def contains_phrase(norm_text: str, norm_phrase: str) -> bool:
    """Whether the (normalized) phrase occurs in the (normalized) text as
    whole words, allowing a Hebrew prefix on the phrase's first word."""
    words = norm_text.split()
    target = norm_phrase.split()
    if not target or len(target) > len(words):
        return False
    first, rest = target[0], target[1:]
    for i in range(len(words) - len(target) + 1):
        if first in word_variants(words[i]) and words[i + 1 : i + 1 + len(rest)] == rest:
            return True
    return False


# ---------------------------------------------------------------- broken Hebrew
# Old Israeli MP3s carry their tags in Windows-1255 while the tag says
# "Latin-1", so a reader shows "øöåòä" for "רצועה". Others were saved as UTF-8
# and read as Latin-1/Windows-1252, which shows "×¨×¦×•×¢×”". Both are undone
# here; real accented Latin text ("Café", "été") is left alone.
_WORD_RE = re.compile(r"[^\s\-_.,;:!?()\[\]{}/\\|\"'`0-9]+")


def _is_cp1255_letter(code: int) -> bool:
    # Hebrew letters (0xE0–0xFA) and points (0xC0–0xD2) as Latin-1 code points.
    return 0xE0 <= code <= 0xFA or 0xC0 <= code <= 0xD2


def _hebrew_share(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    return sum("א" <= ch <= "ת" for ch in letters) / len(letters)


def repair_hebrew(text: str) -> str:
    """Undo the two common ways Hebrew tags get garbled; otherwise return
    ``text`` unchanged."""
    if not text or any("֐" <= ch <= "׿" for ch in text):
        return text
    # UTF-8 bytes shown as Latin-1/Windows-1252: Hebrew starts with 0xD7 ("×").
    if text.count("×") >= 1:
        for encoding in ("cp1252", "latin-1"):
            try:
                fixed = text.encode(encoding).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
            if _hebrew_share(fixed) >= 0.5:
                return fixed
    # Windows-1255 shown as Latin-1: a word made only of à…ú letters, and no
    # word that mixes them with plain Latin letters (that is real French).
    words = _WORD_RE.findall(text)
    hebrew_word = False
    for word in words:
        high = sum(_is_cp1255_letter(ord(ch)) for ch in word)
        latin = sum(("a" <= ch.lower() <= "z") for ch in word)
        if high and latin:
            return text
        if high >= 2 and not latin:
            hebrew_word = True
    if not hebrew_word:
        return text
    for encoding in ("latin-1", "cp1252"):
        try:
            return text.encode(encoding).decode("cp1255")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return text
