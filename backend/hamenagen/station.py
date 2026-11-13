"""רדיו המנגן: a station that plays on and on from the listener's own songs.

Two kinds:

* **by the time of day** — morning songs in the morning, quieter ones in the
  evening and soft ones at night (by the energy and tempo the background
  listening measured, and the tender/lullaby/happy sound of the profile),
  with the Hebrew calendar on top: Shabbat songs on Friday, the festival's
  songs in its days, only vocal songs in the Omer count and the Three Weeks.
* **from a song** — songs that sound like it (sound.similarity), by the same
  singer, of the same topic, close in tempo and energy.

Either way the listener's taste counts (hearts, how often a song is played),
a song heard in the last hours does not come back, the same singer does not
play twice in a row, and neighbouring songs stay close in tempo. Spoken
recordings, disliked songs and folders kept apart never play
(MusicIndex.mixable_tracks). Pure Python; the service supplies the data.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime

from . import sound
from .rhythm import tempo_distance


@dataclass(frozen=True)
class Daypart:
    key: str
    title: str              # the station's name at this hour
    subtitle: str
    start: int              # hour (local time) it begins
    energy: tuple[float, float]
    moods: tuple[str, ...] = ()       # sound.FACETS that suit it
    max_tempo: float | None = None


DAYPARTS = (
    Daypart("night", "לילה רך", "שירים שקטים ורכים", 23, (0.0, 0.42), ("tender",), 112),
    Daypart("morning", "בוקר טוב", "שירים נעימים להתחלת היום", 5, (0.3, 0.65), ("happy", "tender")),
    Daypart("forenoon", "לפני הצהריים", "שירים עם קצב ושמחה", 9, (0.45, 0.85), ("happy", "exciting")),
    Daypart("afternoon", "אחר הצהריים", "שירים בקצב טוב", 13, (0.4, 0.78), ("happy",)),
    Daypart("dusk", "בין הערביים", "שירים רגועים לסוף היום", 17, (0.28, 0.6), ("tender",)),
    Daypart("evening", "ערב", "שירים נינוחים", 20, (0.2, 0.52), ("tender",), 125),
)


def daypart(now: datetime) -> Daypart:
    h = now.hour
    key = ("night" if h >= 23 or h < 5 else "morning" if h < 9 else "forenoon" if h < 13
           else "afternoon" if h < 17 else "dusk" if h < 20 else "evening")
    return next(p for p in DAYPARTS if p.key == key)


@dataclass
class Candidate:
    id: str
    artist: str = ""
    topic: str | None = None
    tags: tuple[str, ...] = ()
    energy: float | None = None
    tempo: float | None = None
    profile: object = None            # numpy vector or None (sound.unpack)
    favorite: bool = False
    plays: int = 0
    hours_since_played: float | None = None
    vocal: bool = False
    duration: float | None = None
    score: float = field(default=0.0, compare=False)

    def topics(self) -> set[str]:
        return {t for t in (self.topic, *self.tags) if t}


@dataclass
class Mood:
    """What the station plays right now: the time of day and the calendar."""
    part: Daypart
    topic: str | None = None          # the day's occasion (שבת, חנוכה…)
    topic_label: str = ""
    vocal_only: bool = False
    out_of_season: frozenset = frozenset()

    @property
    def title(self) -> str:
        if self.vocal_only:
            return "רדיו המנגן · ווקאלי"
        if self.topic:
            return f"רדיו המנגן · {self.topic_label or self.topic}"
        return f"רדיו המנגן · {self.part.title}"

    @property
    def subtitle(self) -> str:
        if self.vocal_only:
            return "רק שירה, בלי כלי נגינה, לפי השעה ביום"
        if self.topic:
            return f"שירי {self.topic_label or self.topic} ושירים שמתאימים לשעה"
        return self.part.subtitle


RECENT_HOURS = 3.0        # a song heard this recently does not come back
POOL = 40                 # pick among the best this many at each step


def _taste(c: Candidate) -> float:
    s = 1.0 + (1.2 if c.favorite else 0.0) + 0.35 * math.log1p(c.plays)
    if c.plays == 0:
        s += 0.25                          # a little discovery
    if c.hours_since_played is not None and c.hours_since_played < 48:
        s -= 0.4
    return s


def _fit_energy(c: Candidate, lo: float, hi: float) -> float:
    if c.energy is None:
        return 0.5
    if lo <= c.energy <= hi:
        return 1.0
    gap = lo - c.energy if c.energy < lo else c.energy - hi
    return max(0.0, 1.0 - 3.0 * gap)


def score_for_time(c: Candidate, mood: Mood) -> float | None:
    """How well a song suits the station now (None: not now)."""
    tops = c.topics()
    if mood.vocal_only and not c.vocal:
        return None
    if tops & mood.out_of_season and mood.topic not in tops:
        return None
    s = _taste(c) + 1.5 * _fit_energy(c, *mood.part.energy)
    if mood.part.max_tempo and c.tempo and c.tempo > mood.part.max_tempo:
        s -= 0.8
    if c.profile is not None and mood.part.moods:
        f = sound.facets(c.profile)
        s += 2.0 * max(f.get(m, 0.0) for m in mood.part.moods)
    if mood.topic and mood.topic in tops:
        s += 3.5
    return s


def score_for_seed(c: Candidate, seed: Candidate) -> float:
    """How well a song follows a chosen song."""
    s = 0.6 * _taste(c)
    s += 3.0 * sound.similarity(seed.profile, c.profile) if seed.profile is not None and c.profile is not None else 0.0
    if seed.artist and c.artist and seed.artist == c.artist:
        s += 1.2
    if seed.topics() & c.topics():
        s += 0.8
    if seed.energy is not None and c.energy is not None:
        s += 1.0 - min(1.0, 2.0 * abs(seed.energy - c.energy))
    s += max(0.0, 1.0 - tempo_distance(seed.tempo, c.tempo) / 30.0) * 0.6
    return s


def pick(candidates: list[Candidate], count: int, *, mood: Mood | None = None, seed: Candidate | None = None,
         history: list[str] = (), rng: random.Random | None = None) -> list[Candidate]:
    """The next ``count`` songs, after the ``history`` already played."""
    rng = rng or random.Random()
    played = set(history)
    pool = []
    for c in candidates:
        if c.id in played or (seed and c.id == seed.id):
            continue
        if c.hours_since_played is not None and c.hours_since_played < RECENT_HOURS:
            continue
        sc = score_for_seed(c, seed) if seed is not None else score_for_time(c, mood) if mood else _taste(c)
        if sc is None:
            continue
        c.score = sc * rng.uniform(0.8, 1.2)
        pool.append(c)
    pool.sort(key=lambda c: -c.score)
    out: list[Candidate] = []
    last_artists: list[str] = []
    prev = seed
    while pool and len(out) < count:
        window = pool[:POOL]
        best, best_val = None, -1e9
        for c in window:
            val = c.score
            if c.artist and c.artist in last_artists:
                val -= 2.5
            if prev is not None:
                val -= tempo_distance(prev.tempo, c.tempo) / 40.0
                if prev.energy is not None and c.energy is not None:
                    val -= abs(prev.energy - c.energy)
            val += rng.uniform(0, 0.6)
            if val > best_val:
                best, best_val = c, val
        pool.remove(best)
        out.append(best)
        prev = best
        if best.artist:
            last_artists = (last_artists + [best.artist])[-2:]
    return out


# ------------------------------------------------------------------ moods
# "משהו רגוע", "שעה של שירים שקטים", "שירים מרגשים", "שירי ילדים": songs
# ranked by how they sound (energy, tempo and the profile's soft styles).
# Lively and happy requests are a set (sets.py) and never reach here.
@dataclass(frozen=True)
class MoodRequest:
    key: str
    label: str                       # what the listener is told
    words: tuple[str, ...]
    energy: tuple[float, float]
    facets: tuple[str, ...] = ()
    max_tempo: float | None = None


MOODS = (
    MoodRequest("calm", "שירים רגועים", ("רגוע", "רגועים", "רגועה", "שקט", "שקטים", "שקטה", "רך", "רכים", "רכה",
                                         "נינוח", "נינוחים", "מרגיע", "מרגיעים", "להירגע", "לנוח", "לפני השינה"),
                (0.0, 0.45), ("tender",), 110),
    MoodRequest("moving", "שירים מרגשים", ("מרגש", "מרגשים", "מרגשת", "נוגה", "נוגים", "עצוב", "עצובים", "געגועים",
                                           "נשמה", "מהלב"), (0.1, 0.6), ("sad", "tender")),
    MoodRequest("children", "שירים לילדים", ("ילדים", "לילדים", "לקטנים", "לפעוטות", "שירי ילדים"),
                (0.0, 1.0), ("children",)),
)
_MOOD_FILLER = {"שיר", "שירים", "שירי", "משהו", "קצת", "מוזיקה", "מוסיקה", "לי", "תשמיע", "תנגן", "תפעיל", "תשים",
                "בבקשה", "של", "עם", "איזה", "כמה", "רוצה", "אפשר", "בא", "לשמוע", "ניגונים", "ניגון"}


def mood_request(text: str) -> MoodRequest | None:
    """The mood a request asks for, when it asks for nothing else."""
    from .text_normalize import normalize

    norm = f" {normalize(text)} "
    for mood in MOODS:
        hit = [w for w in mood.words if f" {normalize(w)} " in norm]
        if not hit:
            continue
        rest = norm
        for w in sorted(hit, key=len, reverse=True):
            rest = rest.replace(f" {normalize(w)} ", " ")
        if all(w in {normalize(f) for f in _MOOD_FILLER} for w in rest.split()):
            return mood
    return None


def score_for_mood(c: Candidate, mood: MoodRequest) -> float:
    s = 0.5 * _taste(c) + 2.0 * _fit_energy(c, *mood.energy)
    if mood.max_tempo and c.tempo and c.tempo > mood.max_tempo:
        s -= 1.0
    if c.profile is not None and mood.facets:
        f = sound.facets(c.profile)
        s += 4.0 * max(f.get(m, 0.0) for m in mood.facets)
    return s
