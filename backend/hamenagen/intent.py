"""Hebrew natural-language intent engine (spec §8, the heart of the system).

The user types a free request in Hebrew and we turn it into a structured
:class:`Intent` — an action plus parameters — which the service layer then
executes against the local index.

This is a deliberately transparent, rule-based parser (no cloud model): it is
fast, offline, debuggable and easy to extend. It covers the request families
enumerated in spec §8.1:

* topic filter          — "תשמיע לי שירים של שבת"
* recently downloaded   — "תשמיע את השירים האחרונים שהורדתי"
* recently released     — "תשמיע את השירים האחרונים שיצאו"
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
from .text_normalize import normalize


class Action(str, Enum):
    PLAY_TOPIC = "play_topic"
    RECENT_DOWNLOADED = "recent_downloaded"
    RECENT_RELEASED = "recent_released"
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

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "query": self.query,
            "topic": self.topic,
            "limit": self.limit,
            "raw": self.raw,
            "params": self.params,
        }


# Verb-like words that merely mean "play/queue" and carry no other meaning.
_PLAY_VERBS = {
    "תשמיע", "תשמיעי", "השמע", "נגן", "תנגן", "שים", "תשים", "הפעל", "תפעיל",
    "בוא", "אני", "רוצה", "לשמוע", "תן", "תביא", "לי", "לנו", "את", "של",
    "שיר", "שירים", "השירים", "המוזיקה", "מוזיקה", "קצת", "משהו",
}

_RECENT_WORDS = {"אחרון", "אחרונים", "אחרונות", "החדשים", "חדשים", "האחרונים", "האחרונות"}

# Hebrew number words for small counts ("חמישה שירים").
_NUMBER_WORDS = {
    "אחד": 1, "אחת": 1, "שני": 2, "שתי": 2, "שניים": 2, "שתיים": 2,
    "שלוש": 3, "שלושה": 3, "ארבע": 4, "ארבעה": 4, "חמש": 5, "חמישה": 5,
    "שש": 6, "שישה": 6, "שבע": 7, "שבעה": 7, "שמונה": 8, "תשע": 9, "תשעה": 9,
    "עשר": 10, "עשרה": 10,
}


def _extract_limit(norm: str) -> int | None:
    m = re.search(r"\b(\d{1,3})\b", norm)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 500:
            return n
    for word, value in _NUMBER_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", norm):
            return value
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
            hit = nkw in norm if " " in nkw else re.search(rf"(?:^| ){re.escape(nkw)}(?: |$)", norm)
            if hit and len(nkw) > best_len:
                best, best_len = topic, len(nkw)
    return best


def _looks_recent_downloaded(norm: str) -> bool:
    return any(w in norm for w in ("הורדתי", "שהורדתי", "הורדנו", "הוספתי", "הוספנו")) and _has_recent(norm)


def _looks_recent_released(norm: str) -> bool:
    return any(w in norm for w in ("שיצאו", "יצאו", "שיצא", "חדשים שיצאו", "התחדשו")) and _has_recent(norm)


def _has_recent(norm: str) -> bool:
    return any(normalize(w) in norm for w in _RECENT_WORDS) or "אחרונ" in norm or "חדש" in norm


def _strip_play_words(norm: str) -> str:
    kept = [t for t in norm.split() if t not in {normalize(w) for w in _PLAY_VERBS}]
    return " ".join(kept).strip()


def parse(text: str) -> Intent:
    """Parse a free Hebrew request into a structured :class:`Intent`."""
    raw = text or ""
    norm = normalize(raw)
    limit = _extract_limit(norm)

    if not norm:
        return Intent(Action.RANDOM, raw=raw, limit=limit)

    # Recently released takes precedence over downloaded when "יצאו" appears,
    # because "יצאו" (released) is a stronger, more specific signal.
    if _looks_recent_released(norm):
        return Intent(Action.RECENT_RELEASED, raw=raw, limit=limit)
    if _looks_recent_downloaded(norm):
        return Intent(Action.RECENT_DOWNLOADED, raw=raw, limit=limit)

    # Explicit random request. Trigger words are normalized so final-letter
    # folding (e.g. "כיף" -> "כיפ") does not break the comparison.
    if any(normalize(w) in norm for w in ("אקראי", "רנדומלי", "ערבב", "משהו כיף", "מה שבא")):
        return Intent(Action.RANDOM, raw=raw, limit=limit)

    # Topic filter: a topic keyword is present. But if there is meaningful
    # residual text beyond the topic + play words, treat it as a specific song
    # search (e.g. "אמת של שמוליק סוכות" mentions סוכות but is a song lookup).
    topic = _find_topic(norm)
    if topic is not None:
        residual = _strip_play_words(norm)
        # Remove the topic tokens themselves from the residual.
        for tok in normalize(topic).split():
            residual = re.sub(rf"(?:^| ){re.escape(tok)}(?: |$)", " ", residual).strip()
        if len(residual.split()) <= 1:
            return Intent(Action.PLAY_TOPIC, topic=topic, raw=raw, limit=limit)
        # Otherwise fall through to song search, but remember the topic hint.
        return Intent(
            Action.SEARCH_SONG,
            query=_strip_play_words(norm),
            topic=topic,
            raw=raw,
            limit=limit,
            params={"topic_hint": topic},
        )

    # Default: fuzzy song search over the meaningful part of the request.
    query = _strip_play_words(norm) or norm
    return Intent(Action.SEARCH_SONG, query=query, raw=raw, limit=limit)
