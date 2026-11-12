"""Fuzzy, multi-field song matching (spec §8.3).

Given a free-text query such as ``"אמת של שמוליק סוכות"`` we need to find the
right file even when it is stored as ``שמוליק_סוכות`` on disk, or when the
song title, artist and album live in *different* metadata fields.

The rule since 1.2: **every word of the request must be found** — in the
title, the artist, the album, the song's folder or the file name. One shared
word is not a match: "אלי הרצליך" must not bring every song with "אלי" in
its name. A word may still be found with

* a Hebrew prefix letter on either side ("ואלי", "לשבת"),
* a typo in a longer word ("הרצליך" / "הרצלך"),
* final-letter, niqqud and separator differences (see text_normalize).

When nothing matches every word, a request of three words or more may get
"near" results that miss exactly one word; the service shows those as near,
not as the answer.

Ranking: the field a word was found in (title and artist first), how cleanly
it was found, and whether the request appears as a phrase in one field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .text_normalize import normalize, tokens, word_variants

try:  # optional acceleration; core works fine without it
    from rapidfuzz.distance import Levenshtein as _rf_lev  # type: ignore

    _HAVE_RAPIDFUZZ = True
except Exception:  # pragma: no cover - exercised only when rapidfuzz absent
    _rf_lev = None
    _HAVE_RAPIDFUZZ = False

# Words a request carries that no song is named by ("את שמוליק", "של זמר").
_QUERY_FILLER = {normalize(w) for w in ("של", "את", "ה", "עם")}

# Where a word was found, and how much that counts.
_FIELD_WEIGHT = {"title": 1.0, "artist": 1.0, "album": 0.85, "folder": 0.8, "filename": 0.75}

# A word counts as found at or above this (before the field weight).
WORD_MIN = 0.6


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if _HAVE_RAPIDFUZZ:
        return _rf_lev.normalized_similarity(a, b)
    return SequenceMatcher(None, a, b).ratio()


def query_words(query: str) -> list[str]:
    """The words of a request that a song must answer, in order."""
    words = tokens(query)
    kept = [w for w in words if w not in _QUERY_FILLER]
    return kept or words


def token_set_overlap(query: str, candidate: str) -> float:
    """Fraction of query words found in the candidate text [0, 1]."""
    q = query_words(query)
    if not q:
        return 0.0
    words = set(tokens(candidate))
    return sum(_word_score(w, words) >= WORD_MIN for w in q) / len(q)


def _word_score(q: str, words: set[str]) -> float:
    """How well one query word is found among a field's words [0, 1]."""
    if not words:
        return 0.0
    if q in words:
        return 1.0
    q_variants = word_variants(q)
    for w in words:
        if q in word_variants(w) or w in q_variants:
            return 0.92
    if len(q) >= 4:
        best = 0.0
        for w in words:
            if len(w) >= 3 and abs(len(w) - len(q)) <= 2:
                best = max(best, _ratio(q, w))
        if best >= 0.8:
            return 0.85 * best
    return 0.0


@dataclass(frozen=True)
class MatchCandidate:
    """A searchable record. All fields are optional except ``id``."""

    id: str
    title: str = ""
    artist: str = ""
    album: str = ""
    filename: str = ""
    folder: str = ""   # the song's folder (often the artist or the album)

    def combined_text(self) -> str:
        return " ".join(p for p in (self.title, self.artist, self.album, self.folder, self.filename) if p)

    def fields(self) -> dict[str, str]:
        return {"title": self.title, "artist": self.artist, "album": self.album,
                "folder": self.folder, "filename": self.filename}


@dataclass(frozen=True)
class ScoredMatch:
    candidate: MatchCandidate
    score: float
    found: int = 0          # how many query words were found
    words: int = 0          # how many words the query had
    by_artist: bool = False  # the whole query is the artist's name
    missing: tuple[str, ...] = field(default_factory=tuple)

    @property
    def complete(self) -> bool:
        return self.found == self.words


def _prepared(candidate: MatchCandidate) -> dict[str, tuple[str, set[str]]]:
    out = {}
    for name, value in candidate.fields().items():
        if value:
            norm = normalize(value)
            out[name] = (norm, set(norm.split()))
    return out


def match(query: str, candidate: MatchCandidate) -> ScoredMatch:
    """Score how well ``candidate`` answers ``query``."""
    q_words = query_words(query)
    if not q_words:
        return ScoredMatch(candidate, 0.0)
    fields = _prepared(candidate)
    if not fields:
        return ScoredMatch(candidate, 0.0, 0, len(q_words))

    found, total, missing = 0, 0.0, []
    for w in q_words:
        best_raw, best = 0.0, 0.0
        for name, (_, words) in fields.items():
            raw = _word_score(w, words)
            if raw:
                best_raw = max(best_raw, raw)
                best = max(best, raw * _FIELD_WEIGHT[name])
        if best_raw >= WORD_MIN:
            found += 1
            total += best
        else:
            missing.append(w)

    q_norm = " ".join(q_words)
    phrase = 0.0
    by_artist = False
    for name in ("title", "artist", "album"):
        if name not in fields:
            continue
        norm = fields[name][0]
        if norm == q_norm:
            phrase = 1.0
            by_artist = by_artist or name == "artist"
        elif f" {q_norm} " in f" {norm} ":
            phrase = max(phrase, 0.9)
        else:
            phrase = max(phrase, 0.6 * _ratio(q_norm, norm))
    if not by_artist and "artist" in fields:
        by_artist = _ratio(q_norm, fields["artist"][0]) >= 0.9

    quality = total / len(q_words)
    score = round(0.85 * quality + 0.15 * phrase, 6)
    return ScoredMatch(candidate, score, found, len(q_words), by_artist, tuple(missing))


def score_candidate(query: str, candidate: MatchCandidate) -> float:
    """Score in [0, 1]; 0 unless every word of the query was found."""
    m = match(query, candidate)
    return m.score if m.complete else 0.0


def search(
    query: str,
    candidates: list[MatchCandidate],
    *,
    limit: int = 25,
    min_score: float = 0.34,
    allow_missing: int = 0,
) -> list[ScoredMatch]:
    """Songs that answer every word of ``query``, best first.

    ``allow_missing=1`` also accepts songs missing one word, for requests of
    three words or more (see :func:`near_matches`)."""
    if not query.strip() or not candidates:
        return []
    out = []
    for c in candidates:
        m = match(query, c)
        if m.words and m.found >= m.words - allow_missing and m.found and m.score >= min_score:
            out.append(m)
    out.sort(key=lambda s: (s.found, s.score, -len(s.candidate.combined_text())), reverse=True)
    return out[:limit]


def near_matches(query: str, candidates: list[MatchCandidate], *, limit: int = 25) -> list[ScoredMatch]:
    """When nothing answers every word: songs missing exactly one word of a
    request of three words or more. Shorter requests get nothing."""
    if len(query_words(query)) < 3:
        return []
    return [m for m in search(query, candidates, limit=limit, allow_missing=1) if not m.complete]


def best_match(
    query: str,
    candidates: list[MatchCandidate],
    *,
    min_score: float = 0.34,
) -> ScoredMatch | None:
    """Return the single best match, or ``None`` if nothing clears the bar."""
    results = search(query, candidates, limit=1, min_score=min_score)
    return results[0] if results else None
