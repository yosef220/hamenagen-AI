"""Fuzzy, multi-field song matching (spec §8.3).

Given a free-text query such as ``"אמת של שמוליק סוכות"`` we need to find the
right file even when it is stored as ``שמוליק_סוכות`` on disk, or when the
song title, artist and album live in *different* metadata fields.

The scorer here is deliberately dependency-free (it uses only
:mod:`difflib` and our own token-set logic) so it runs everywhere and in
tests without extra packages. It combines two ideas:

* **token-set overlap** — how many of the query tokens appear somewhere in
  the candidate's combined fields (this is what makes cross-field matches
  like title="אמת", album="שמוליק סוכות" work);
* **ordered similarity** — a character-level ratio that rewards correct
  spelling/order and tolerates small typos.

If the optional :mod:`rapidfuzz` package is installed we transparently use
its (much faster, C-backed) ``token_set_ratio`` for the ordered component,
but the pure-python path produces equivalent rankings.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from .text_normalize import normalize, token_set, tokens

try:  # optional acceleration; core works fine without it
    from rapidfuzz import fuzz as _rf_fuzz  # type: ignore

    _HAVE_RAPIDFUZZ = True
except Exception:  # pragma: no cover - exercised only when rapidfuzz absent
    _rf_fuzz = None
    _HAVE_RAPIDFUZZ = False


def _ratio(a: str, b: str) -> float:
    """Ordered similarity between two strings in the range [0, 1]."""
    if not a or not b:
        return 0.0
    if _HAVE_RAPIDFUZZ:
        return _rf_fuzz.token_set_ratio(a, b) / 100.0
    return SequenceMatcher(None, a, b).ratio()


def token_set_overlap(query: str, candidate: str) -> float:
    """Fraction of query tokens found in the candidate token set [0, 1]."""
    q = token_set(query)
    if not q:
        return 0.0
    c = token_set(candidate)
    if not c:
        return 0.0
    return len(q & c) / len(q)


@dataclass(frozen=True)
class MatchCandidate:
    """A searchable record. All fields are optional except ``id``."""

    id: str
    title: str = ""
    artist: str = ""
    album: str = ""
    filename: str = ""

    def combined_text(self) -> str:
        return " ".join(p for p in (self.title, self.artist, self.album, self.filename) if p)


@dataclass(frozen=True)
class ScoredMatch:
    candidate: MatchCandidate
    score: float


def score_candidate(query: str, candidate: MatchCandidate) -> float:
    """Score how well ``candidate`` answers ``query`` in the range [0, 1].

    We take the token overlap against the *combined* text (cross-field) and
    blend it with the best ordered ratio across the individual fields, so a
    query that lines up cleanly with one field still ranks highly.
    """
    combined = candidate.combined_text()
    if not combined:
        return 0.0

    overlap = token_set_overlap(query, combined)

    q_norm = normalize(query)
    field_ratio = max(
        _ratio(q_norm, normalize(candidate.title)),
        _ratio(q_norm, normalize(candidate.artist)),
        _ratio(q_norm, normalize(candidate.album)),
        _ratio(q_norm, normalize(candidate.filename)),
        _ratio(q_norm, normalize(combined)),
    )

    # Overlap is the dominant signal (it handles cross-field + reordering);
    # the ordered ratio breaks ties and rewards exact spelling.
    return round(0.7 * overlap + 0.3 * field_ratio, 6)


def search(
    query: str,
    candidates: list[MatchCandidate],
    *,
    limit: int = 25,
    min_score: float = 0.34,
) -> list[ScoredMatch]:
    """Rank ``candidates`` against ``query``; best match first.

    Results below ``min_score`` are dropped so an unrelated query returns
    nothing rather than a random "best of a bad bunch".
    """
    if not query.strip() or not candidates:
        return []
    scored = [ScoredMatch(c, score_candidate(query, c)) for c in candidates]
    scored = [s for s in scored if s.score >= min_score]
    scored.sort(key=lambda s: (s.score, -len(tokens(s.candidate.combined_text()))), reverse=True)
    return scored[:limit]


def best_match(
    query: str,
    candidates: list[MatchCandidate],
    *,
    min_score: float = 0.34,
) -> ScoredMatch | None:
    """Return the single best match, or ``None`` if nothing clears the bar."""
    results = search(query, candidates, limit=1, min_score=min_score)
    return results[0] if results else None
