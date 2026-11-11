"""Hebrew natural-language intent engine (spec §8, the heart of the system).

The user types a free request in Hebrew and we turn it into a structured
:class:`Intent` — an action plus parameters — which the service layer then
executes against the local index.

This is a deliberately transparent, rule-based parser (no cloud model): it is
fast, offline, debuggable and easy to extend. It covers the request families
of spec §8.1 and the listening-habit requests added in 1.0:

* topic filter          — "תשמיע לי שירים של שבת"
* a span of time        — "שעה של שירי שבת", "חצי שעה של מוזיקה"
* recently downloaded   — "תשמיע את השירים האחרונים שהורדתי"
* recently released     — "תשמיע את השירים האחרונים שיצאו"
* favorites             — "השירים שאהבתי"
* listening history     — "מה ששמעתי לאחרונה"
* most played           — "השירים שאני הכי שומע"
* specific song search  — "תשמיע אמת של שמוליק סוכות"
* random / shuffle      — "תשמיע משהו", "אקראי"

When no structured pattern is recognised we fall back to a fuzzy song search
over the free text, which is the safest default.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from . import topics as topics_mod
from .text_normalize import contains_phrase, normalize, word_variants


class Action(str, Enum):
    PLAY_TOPIC = "play_topic"
    RECENT_DOWNLOADED = "recent_downloaded"
    RECENT_RELEASED = "recent_released"
    FAVORITES = "favorites"
    HISTORY = "history"
    MOST_PLAYED = "most_played"
    SEARCH_SONG = "search_song"
    RANDOM = "random"


@dataclass
class Intent:
    action: Action
    query: str = ""                       # free-text for song search
    topic: str | None = None              # topic key for PLAY_TOPIC
    limit: int | None = None              # requested count, if any
    raw: str = ""                         # the original request
    params: dict = field(default_factory=dict)

    @property
    def minutes(self) -> int | None:
        """Requested span of time ("שעה של …"), in minutes."""
        return self.params.get("minutes")

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "query": self.query,
            "topic": self.topic,
            "limit": self.limit,
            "minutes": self.minutes,
            "raw": self.raw,
            "params": self.params,
        }


def _n(words) -> set[str]:
    return {normalize(w) for w in words}


# Verb-like words that merely mean "play/queue" and carry no other meaning.
_PLAY_VERBS = _n({
    "תשמיע", "תשמיעי", "השמע", "נגן", "תנגן", "תנגני", "שים", "תשים", "תשימי", "הפעל", "תפעיל",
    "בוא", "בואו", "אני", "רוצה", "רוצים", "לשמוע", "תן", "תני", "תביא", "תביאי", "לי", "לנו",
    "את", "של", "שיר", "השיר", "שירים", "השירים", "שירי", "המוזיקה", "מוזיקה", "קצת", "משהו", "עכשיו",
    "בבקשה", "מוסיקה", "המוסיקה", "רשימה", "רשימת", "פלייליסט", "בא", "מתחשק", "תכין", "תכיני",
    "השמעה", "תשמעו", "לשמיעה",
})

_RECENT_WORDS = _n({"אחרון", "אחרונים", "אחרונות", "החדשים", "חדשים", "האחרונים", "האחרונות", "לאחרונה"})

# Hebrew number words for small counts ("חמישה שירים").
_NUMBER_WORDS = {
    "אחד": 1, "אחת": 1, "שני": 2, "שתי": 2, "שניים": 2, "שתיים": 2,
    "שלוש": 3, "שלושה": 3, "ארבע": 4, "ארבעה": 4, "חמש": 5, "חמישה": 5,
    "שש": 6, "שישה": 6, "שבע": 7, "שבעה": 7, "שמונה": 8, "תשע": 9, "תשעה": 9,
    "עשר": 10, "עשרה": 10, "עשרים": 20, "שלושים": 30, "ארבעים": 40, "חמישים": 50,
}
_NUMBER_WORDS_N = {normalize(k): v for k, v in _NUMBER_WORDS.items()}

# Spans of time, longest phrase first. Values are minutes.
_FIXED_SPANS = [
    ("שעה וחצי", 90), ("שעתיים וחצי", 150), ("שלוש שעות", 180), ("שעתיים", 120),
    ("שלושת רבעי שעה", 45), ("חצי שעה", 30), ("רבע שעה", 15), ("שעה", 60),
]
_FIXED_SPANS_N = [(normalize(p), m) for p, m in _FIXED_SPANS]
_MINUTES_RE = re.compile(r"(?:^| )(\d{1,3}|[^\s]+) (דקות|דקה|שעות)(?= |$)")

# Listening-habit triggers (normalized).
_FAVORITE_WORDS = _n({"אהבתי", "שאהבתי", "מועדפים", "המועדפים", "שסימנתי", "סימנתי", "האהובים",
                      "אהובים", "בלב", "שבלב"})
_HISTORY_WORDS = _n({"ששמעתי", "שמעתי", "היסטוריה", "ההיסטוריה", "שהשמעתי", "ששמענו"})
_MOST_PLAYED_PHRASES = [normalize(p) for p in (
    "הכי שומע", "הכי שומעת", "הכי שומעים", "הכי מושמעים", "הכי מושמעים", "הכי שמעתי",
    "שומע הכי הרבה", "שומעת הכי הרבה", "הכי הרבה פעמים", "הכי מנוגנים", "הכי פופולריים",
)]
_RANDOM_PHRASES = [normalize(p) for p in ("אקראי", "אקראיים", "רנדומלי", "ערבב", "ערבוב", "משהו כיף", "מה שבא", "הפתע")]


def _has_token(norm: str, words: set[str]) -> bool:
    return any(t in words for t in norm.split())


def _has_phrase(norm: str, phrase: str) -> bool:
    return f" {phrase} " in f" {norm} "


def _extract_minutes(norm: str) -> tuple[int | None, str]:
    """Find a span of time; return (minutes, text without that phrase)."""
    m = _MINUTES_RE.search(norm)
    if m:
        amount, unit = m.group(1), m.group(2)
        value = int(amount) if amount.isdigit() else _NUMBER_WORDS_N.get(amount)
        if value:
            minutes = value * 60 if unit == normalize("שעות") else value
            if 1 <= minutes <= 24 * 60:
                rest = (norm[: m.start()] + " " + norm[m.end():]).strip()
                return minutes, re.sub(r"\s+", " ", rest)
    for phrase, minutes in _FIXED_SPANS_N:
        if _has_phrase(norm, phrase):
            rest = f" {norm} ".replace(f" {phrase} ", " ", 1).strip()
            return minutes, re.sub(r"\s+", " ", rest)
    return None, norm


def _extract_limit(norm: str) -> int | None:
    m = re.search(r"\b(\d{1,3})\b", norm)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 500:
            return n
    for token in norm.split():
        if token in _NUMBER_WORDS_N and _NUMBER_WORDS_N[token] <= 10:
            return _NUMBER_WORDS_N[token]
    return None


def _find_topic(norm: str) -> str | None:
    """Detect an explicit topic mentioned in the (normalized) request."""
    best: str | None = None
    best_len = 0
    for topic, keywords in topics_mod.TOPIC_KEYWORDS.items():
        for kw in [topic, *keywords]:
            nkw = normalize(kw)
            if not nkw:
                continue
            if contains_phrase(norm, nkw) and len(nkw) > best_len:
                best, best_len = topic, len(nkw)
    return best


def _looks_recent_downloaded(norm: str) -> bool:
    return any(w in norm for w in ("הורדתי", "שהורדתי", "הורדנו", "הוספתי", "הוספנו")) and _has_recent(norm)


def _looks_recent_released(norm: str) -> bool:
    return any(w in norm for w in ("שיצאו", "יצאו", "שיצא", "חדשים שיצאו", "התחדשו")) and _has_recent(norm)


def _has_recent(norm: str) -> bool:
    return any(w in norm for w in _RECENT_WORDS) or "אחרונ" in norm or "חדש" in norm


def _strip_play_words(norm: str) -> str:
    kept = [t for t in norm.split() if t not in _PLAY_VERBS]
    return " ".join(kept).strip()


def parse(text: str) -> Intent:
    """Parse a free Hebrew request into a structured :class:`Intent`."""
    raw = text or ""
    full = normalize(raw)
    minutes, norm = _extract_minutes(full)
    params: dict = {"minutes": minutes} if minutes else {}
    limit = None if minutes else _extract_limit(norm)

    def make(action: Action, **kw) -> Intent:
        return Intent(action, raw=raw, limit=limit, params=dict(params, **kw.pop("extra", {})), **kw)

    if not norm:
        return make(Action.RANDOM)

    # Recently released takes precedence over downloaded when "יצאו" appears,
    # because "יצאו" (released) is a stronger, more specific signal.
    if _looks_recent_released(norm):
        return make(Action.RECENT_RELEASED)
    if _looks_recent_downloaded(norm):
        return make(Action.RECENT_DOWNLOADED)

    # Listening habits: most played before history ("הכי שמעתי" has "שמעתי").
    if any(_has_phrase(norm, p) for p in _MOST_PLAYED_PHRASES):
        return make(Action.MOST_PLAYED)
    if _has_token(norm, _HISTORY_WORDS):
        return make(Action.HISTORY)
    if _has_token(norm, _FAVORITE_WORDS):
        return make(Action.FAVORITES)

    # Explicit random request. Trigger words are normalized so final-letter
    # folding (e.g. "כיף" -> "כיפ") does not break the comparison.
    if any(p in norm for p in _RANDOM_PHRASES):
        return make(Action.RANDOM)

    # Topic filter: a topic keyword is present. But if there is meaningful
    # residual text beyond the topic + play words, treat it as a specific song
    # search (e.g. "אמת של שמוליק סוכות" mentions סוכות but is a song lookup).
    topic = _find_topic(norm)
    if topic is not None:
        residual = _strip_play_words(norm)
        for kw in [topic, *topics_mod.TOPIC_KEYWORDS.get(topic, [])]:
            nkw = normalize(kw)
            if nkw:
                residual = " ".join(
                    w for w in residual.split() if not any(v in nkw.split() for v in word_variants(w))
                )
        if limit is not None:
            residual = " ".join(t for t in residual.split() if not t.isdigit() and t not in _NUMBER_WORDS_N)
        if len(residual.split()) <= 1:
            # One leftover word may still name a song ("ירושלים של זהב"); the
            # service prefers a strong title match before playing the topic.
            extra = {"residual": residual, "song_query": _strip_play_words(norm)} if residual else {}
            return make(Action.PLAY_TOPIC, topic=topic, extra=extra)
        # Otherwise fall through to song search, but remember the topic hint.
        return make(Action.SEARCH_SONG, query=_strip_play_words(norm), topic=topic,
                    extra={"topic_hint": topic})

    query = _strip_play_words(norm)
    # "שעה של מוזיקה" / "תשמיע משהו" — nothing left to search for: random.
    if not query or (minutes and not query.strip()):
        return make(Action.RANDOM)

    # Default: fuzzy song search over the meaningful part of the request.
    return make(Action.SEARCH_SONG, query=query)
