"""Sets: a list built to flow, for a celebration or for dancing.

"תפעיל לי סט שירים לברית", "סט לשמחה", "מוזיקה לריקודים", "סט שירי שבת" —
the songs of the occasion, arranged to warm up, build to a peak and ease off
a little at the end, with neighbouring songs close in tempo. The player plays
a set with a soft crossfade.

Each celebration has words that name it (to understand the request), words
that mark its own songs ("אליהו הנביא" for a brit), topics whose songs fit,
and searches for YouTube when the computer has too few songs. Tempo and
energy come from rhythm.py, heard in the background; before they are known
the set is built from the topics alone.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .rhythm import tempo_distance
from .text_normalize import normalize

# Topics whose songs never belong in a celebration set.
SOLEMN_TOPICS = {"יום כיפור", "אלול"}
# Songs of a day in the calendar: right for that day's set, not for a brit
# (unless their own title marks them for the occasion).
SEASONAL_TOPICS = {"שבת", "ראש השנה", "סוכות", "חנוכה", "פורים", "פסח", "ל״ג בעומר", "שבועות",
                   "ראש חודש", "ט״ו בשבט"}


@dataclass(frozen=True)
class Event:
    key: str
    label: str                    # "ברית"
    phrase: str                   # "סט לברית"
    words: tuple[str, ...]        # how a request names it
    marks: tuple[str, ...] = ()   # words in a song's title that make it the event's own
    topics: tuple[str, ...] = ("חתונה",)
    queries: tuple[str, ...] = ()  # YouTube searches when the computer has too few
    style_word: str = "שמחה"      # "<a singer you like> שמחה"
    lively: bool = True            # dancing music: energy matters


EVENTS: dict[str, Event] = {e.key: e for e in (
    Event("brit", "ברית", "סט לברית", ("ברית", "ברית מילה", "לברית", "הברית", "שלום זכר"),
          ("ברית", "אליהו הנביא", "כסא של אליהו", "סימן טוב", "מזל טוב", "שלום זכר"),
          queries=("שירים לברית מילה", "סימן טוב ומזל טוב שירי שמחה")),
    Event("bar_mitzvah", "בר מצווה", "סט לבר מצווה", ("בר מצווה", "בר מצוה", "בר-מצווה", "לבר מצווה", "הנחת תפילין"),
          ("בר מצווה", "בר מצוה", "תפילין", "מזל טוב", "סימן טוב"),
          queries=("שירים לבר מצווה", "שירי שמחה לבר מצווה")),
    Event("bat_mitzvah", "בת מצווה", "סט לבת מצווה", ("בת מצווה", "בת מצוה", "לבת מצווה"),
          ("בת מצווה", "מזל טוב", "סימן טוב"), queries=("שירים לבת מצווה",)),
    Event("wedding", "חתונה", "סט לחתונה", ("חתונה", "לחתונה", "החתונה", "חופה", "לחופה"),
          ("חתן", "כלה", "קול ששון", "מזל טוב", "חופה", "אשת חיל", "ששון ושמחה"),
          queries=("שירי חתונה ריקודים", "סט ריקודים לחתונה")),
    Event("sheva_brachot", "שבע ברכות", "סט לשבע ברכות", ("שבע ברכות", "לשבע ברכות"),
          ("חתן", "כלה", "קול ששון", "מזל טוב"), queries=("שירים לשבע ברכות",)),
    Event("engagement", "אירוסין", "סט לאירוסין", ("אירוסין", "לאירוסין", "ווארט", "וורט", "תנאים", "לחיים"),
          ("מזל טוב", "סימן טוב", "חתן", "כלה"), queries=("שירים לאירוסין", "שירי מזל טוב")),
    Event("chanukat_habayit", "חנוכת בית", "סט לחנוכת בית", ("חנוכת בית", "חנוכת הבית", "לחנוכת בית"),
          ("חנוכת הבית", "מזמור שיר", "בית"), queries=("שירים לחנוכת בית",)),
    Event("siyum", "סיום", "סט לסיום מסכת", ("סיום מסכת", "לסיום מסכת", "סיום הש״ס", "סיום", "לסיום"),
          ("הדרן", "ותן חלקנו", "תורה", "אשרינו"), topics=("חתונה", "אמונה"), queries=("שירים לסיום מסכת",)),
    Event("hachnasat_sefer_torah", "הכנסת ספר תורה", "סט להכנסת ספר תורה",
          ("הכנסת ספר תורה", "להכנסת ספר תורה", "הכנסת ס״ת"), ("ספר תורה", "תורה", "שישו ושמחו", "עץ חיים"),
          queries=("שירים להכנסת ספר תורה",)),
    Event("birthday", "יום הולדת", "סט ליום הולדת", ("יום הולדת", "ליום הולדת", "יומולדת", "ליומולדת"),
          ("יום הולדת", "מזל טוב"), queries=("שירי יום הולדת שמחים",)),
    Event("simcha", "שמחה", "סט לשמחה", ("לשמחה", "שמחות", "לשמחות", "ריקודים", "לריקודים", "רוקדים", "קצבי",
                                          "קצביים", "שמחים", "שירים שמחים", "מוזיקה שמחה", "לרקוד", "שמח"),
          ("מזל טוב", "סימן טוב", "ריקוד", "רוקדים", "שמחה"), queries=("שירים שמחים לריקודים", "סט ריקודים")),
)}

DEFAULT_EVENT = "simcha"
_SET_WORDS = {normalize(w) for w in ("סט", "הסט", "סטים", "מחרוזת", "רצף")}


def event_in(norm: str) -> Event | None:
    """The celebration a (normalized) request names, longest name first."""
    best: tuple[int, Event] | None = None
    padded = f" {norm} "
    for event in EVENTS.values():
        for word in event.words:
            w = normalize(word)
            if w and f" {w} " in padded and (best is None or len(w) > best[0]):
                best = (len(w), event)
    return best[1] if best else None


def wants_set(norm: str) -> bool:
    return any(t in _SET_WORDS for t in norm.split())


@dataclass
class SetSong:
    track: object
    tempo: float | None
    energy: float | None
    score: float = 0.0
    marked: bool = False
    fits: bool = False
    reasons: list[str] = field(default_factory=list)


def _target(position: float, low: float, high: float) -> float:
    """The energy a set should have at ``position`` (0–1): a warm-up that
    builds to the peak at four fifths, then eases off a little."""
    if position <= 0.8:
        return low + (high - low) * (position / 0.8)
    return high - (high - low) * 0.35 * ((position - 0.8) / 0.2)


def arrange(songs: list[SetSong], seed: int | None = None) -> list[SetSong]:
    """Order songs along the energy curve, each next song close in tempo to
    the one before. Songs whose energy is unknown keep the middle of the set."""
    if len(songs) <= 2:
        return list(songs)
    rng = random.Random(seed)
    known = [s for s in songs if s.energy is not None]
    unknown = [s for s in songs if s.energy is None]
    rng.shuffle(unknown)
    if not known:
        return unknown
    energies = sorted(s.energy for s in known)
    low, high = energies[max(0, len(energies) // 10)], energies[-1]
    out: list[SetSong] = []
    left = list(known)
    n = len(known)
    for i in range(n):
        want = _target(i / max(1, n - 1), low, high)
        prev = out[-1] if out else None

        def cost(s: SetSong) -> float:
            c = abs(s.energy - want) * 3.0
            if prev is not None:
                c += tempo_distance(prev.tempo, s.tempo) / 40.0
            return c
        pick = min(left, key=cost)
        left.remove(pick)
        out.append(pick)
    # Songs without a known energy go in the middle, where the set is warm.
    middle = len(out) // 2
    return out[:middle] + unknown + out[middle:]


def score_song(song: SetSong, event: Event, *, title: str, topic: str | None, tags: list[str],
               lively: bool) -> float:
    """How well a song fits the set: its own event words, then its topic,
    then (for dancing) its energy and a danceable tempo."""
    score = 0.0
    text = normalize(title)
    if any(normalize(m) and normalize(m) in text for m in event.marks):
        score += 1.0
        song.marked = True
        song.reasons.append("שיר של האירוע")
    if topic in event.topics or any(t in event.topics for t in tags):
        score += 0.6
        song.fits = True
    if lively and song.energy is not None:
        score += 0.8 * song.energy
        if song.tempo and 95 <= song.tempo <= 165:
            score += 0.2
    return score


def top_artists(rows: list[tuple[str, float]], limit: int = 4) -> list[str]:
    """The singers someone listens to most, from (artist, weight) pairs."""
    weights: dict[str, float] = {}
    shown: dict[str, str] = {}
    for artist, weight in rows:
        name = " ".join((artist or "").split())
        key = normalize(name)
        if not key or key in {normalize(x) for x in ("שונים", "various artists", "unknown", "לא ידוע")}:
            continue
        weights[key] = weights.get(key, 0.0) + weight
        shown.setdefault(key, name)
    return [shown[k] for k, _ in sorted(weights.items(), key=lambda kv: -kv[1])[:limit]]


def online_queries(event: Event, artists: list[str], *, topic_phrase: str = "") -> list[str]:
    """What to search on YouTube: the occasion, then the occasion in the
    style of the singers the listener plays most."""
    base = list(event.queries) or [topic_phrase or event.phrase]
    styled = [f"{a} {event.style_word}" for a in artists[:3]]
    out: list[str] = []
    for q in base[:1] + styled + base[1:]:
        if q and q not in out:
            out.append(q)
    return out[:5]
