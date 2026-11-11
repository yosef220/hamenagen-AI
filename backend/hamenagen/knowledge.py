"""The knowledge index: what the player knows about Jewish occasions, offline.

An embedding model knows Hebrew, but not the calendar: it cannot tell that
"עבדים היינו" is Pesach or "ונתנה תוקף" the High Holidays. This module adds
that knowledge from two data files, built once by
``backend/scripts/build_knowledge.py`` from Hebrew Wikipedia and Sefaria:

:class:`SongIndex` (``data/song_index.json``)
    Known songs and piyutim by occasion — "יה ריבון", "מעוז צור", "חד גדיא"
    — with other spellings. A song whose title is one of them gets its topic
    with high confidence, even when the title has no keyword at all.

:class:`TopicLexicon` (``data/topic_lexicon.json``)
    For every occasion, the words and word pairs that characterise it
    (TF-IDF over articles about the occasion, the names of its songs and its
    liturgy). A title is scored against every topic; the best topic is taken
    only when it is clearly ahead of the second.

Both are pure Python, load in a fraction of a second and answer in well
under a millisecond, so they run on every song of every scan. The data is
CC BY-SA 4.0 (derived from Wikipedia) — see ``data/LICENSE-DATA.md``.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .text_normalize import normalize

DATA_DIR = Path(__file__).with_name("data")
SONG_INDEX_FILE = DATA_DIR / "song_index.json"
LEXICON_FILE = DATA_DIR / "topic_lexicon.json"

# ------------------------------------------------------------------ tokens
_NIQQUD = re.compile(r"[֑-ׇ]")
# Geresh/gershayim inside a word mark an acronym (ל״ג, רשב״י): drop them.
_ACRONYM = re.compile(r"(?<=[א-ת])[׳״\"'`’]+(?=[א-ת])")
_HEBREW_WORD = re.compile(r"[א-ת]+")
_FINALS = str.maketrans("ךםןףץ", "כמנפצ")
# One-letter words Hebrew attaches to the next word: ו, ה, ב, כ, ל, מ, ש.
_PREFIXES = "והבכלמש"


def title_tokens(text: str) -> list[str]:
    """The Hebrew words of ``text``: no niqqud, no acronym marks, final
    letters folded, words of two letters or more."""
    text = unicodedata.normalize("NFC", text or "")
    text = _NIQQUD.sub("", text)
    text = _ACRONYM.sub("", text)
    text = text.translate(_FINALS)
    return [w for w in _HEBREW_WORD.findall(text) if len(w) >= 2]


def variants(token: str) -> list[str]:
    """The word, then the word without one and two attached prefixes
    (ובשבת → בשבת → שבת), as long as at least three letters remain."""
    out = [token]
    t = token
    for _ in range(2):
        if len(t) >= 4 and t[0] in _PREFIXES:
            t = t[1:]
            out.append(t)
        else:
            break
    return out


def features(text: str, *, pairs: bool = True) -> list[str]:
    """Lexicon features of a text: every variant of every word, and word
    pairs ("פך_שמנ") with the variants of the first word."""
    toks = title_tokens(text)
    out: list[str] = []
    for t in toks:
        out.extend(variants(t))
    if pairs:
        for a, b in zip(toks, toks[1:]):
            out.extend(v + "_" + b for v in variants(a))
    return out


# ------------------------------------------------------------------ song titles
# Words that describe a recording, not the song ("… - לייב", "(רמיקס)").
_NOISE_WORDS = {
    "לייב", "live", "רמיקס", "remix", "קאבר", "cover", "גרסה", "גרסת", "ווקאלי", "ווקאלית", "אקפלה",
    "אקאפלה", "acapella", "acappella", "הופעה", "בהופעה", "מחרוזת", "קליפ", "רשמי", "official",
    "video", "audio", "lyrics", "hd", "hq", "mp3", "מילים", "סינגל", "single", "חדש", "new",
}
# Spellings of the Name that differ between printings. The keys are in the
# form normalize() leaves them (final letters folded: אלוקים → אלוקימ).
_FOLD = {
    "אלוקימ": "אלהימ", "אלקימ": "אלהימ", "אלוקינו": "אלהינו", "אלקינו": "אלהינו", "אלוקי": "אלהי",
    "אלקי": "אלהי", "השמ": "ה", "ד": "ה", "קל": "אל", "קה": "יה",
}
# A song named after these words is not identified by them alone.
_GENERIC_FIRST_WORDS = {"שיר", "שירי", "מזמור", "ברכת", "תפילת", "שירת", "ניגונ", "ניגון", "פיוט", "סדר"}


def normalize_title(text: str) -> str:
    """A song title as an index key: bracketed notes and recording words
    dropped, spellings folded ("קה אכסוף" = "יה אכסוף", "ברוך א-ל עליון" =
    "ברוך קל עליון")."""
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", text or "")
    words = normalize(text).split()
    joined: list[str] = []
    i = 0
    while i < len(words):
        if words[i] == "א" and i + 1 < len(words) and words[i + 1] == "ל":  # א-ל
            joined.append("אל")
            i += 2
            continue
        joined.append(words[i])
        i += 1
    return " ".join(_FOLD.get(w, w) for w in joined if w not in _NOISE_WORDS)


@dataclass(frozen=True)
class IndexHit:
    title: str               # the song as the index knows it
    topics: tuple[str, ...]
    exact: bool              # the whole title matched, not only its start
    source: str              # "he.wikipedia" | "sefaria" | …


class SongIndex:
    """Known songs and piyutim by occasion."""

    def __init__(self, entries: list[dict], *, version: str = ""):
        self.version = version
        self._by_key: dict[str, dict] = {}
        for e in entries:
            topics = [t for t in e.get("topics", []) if t]
            if not topics:
                continue
            for name in [e.get("title", ""), *e.get("aliases", [])]:
                key = normalize_title(name)
                if key and key not in self._by_key:
                    self._by_key[key] = e
        # Keys by their first two words, for "the title is the start of a
        # longer name" (יה ריבון → יה ריבון עלם ועלמיא).
        self._by_start: dict[str, list[str]] = {}
        for key in self._by_key:
            words = key.split()
            if len(words) >= 2:
                self._by_start.setdefault(" ".join(words[:2]), []).append(key)

    def __len__(self) -> int:
        return len({id(e) for e in self._by_key.values()})

    @classmethod
    def load(cls, path: str | Path = SONG_INDEX_FILE) -> "SongIndex":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            return cls(data.get("entries", []), version=data.get("version", ""))
        except Exception:
            return cls([])

    def _hit(self, key: str, exact: bool) -> IndexHit:
        e = self._by_key[key]
        src = (e.get("src") or ["index"])[0]
        return IndexHit(e.get("title", key), tuple(e["topics"]), exact, src)

    def _lookup_one(self, text: str) -> IndexHit | None:
        key = normalize_title(text)
        if not key:
            return None
        if key in self._by_key:
            return self._hit(key, True)
        words = key.split()
        if len(words) < 2:
            return None
        # The title is the start of a known, longer name.
        longer = [k for k in self._by_start.get(" ".join(words[:2]), [])
                  if len(k.split()) > len(words) and k.split()[: len(words)] == words]
        if longer and len({self._by_key[k]["topics"][0] for k in longer}) == 1:
            return self._hit(min(longer, key=len), False)
        # A known song opens the title ("אשת חיל מי ימצא"); the longest wins.
        # Only names of songs and piyutim (Wikipedia articles) count here: a
        # prayer-book section name such as "לשנה הבאה" also opens ordinary
        # phrases ("לשנה הבאה בטוב").
        for n in range(len(words) - 1, 1, -1):
            prefix = " ".join(words[:n])
            entry = self._by_key.get(prefix)
            if entry and words[0] not in _GENERIC_FIRST_WORDS and "he.wikipedia" in (entry.get("src") or []):
                return self._hit(prefix, False)
        return None

    def lookup(self, title: str = "", filename: str = "") -> IndexHit | None:
        """Look a song up by its title, then by the parts of "זמר - שיר"
        style titles and file names."""
        tried: list[str] = []
        for text in (title, Path(filename).stem if filename else ""):
            if not text:
                continue
            tried.append(text)
            parts = re.split(r"\s+[-–—|]\s+|_-_", text)
            if len(parts) > 1:
                tried.extend(p for p in parts if p.strip())
        for text in tried:
            hit = self._lookup_one(text)
            if hit is not None:
                return hit
        return None


# ------------------------------------------------------------------ the lexicon
# Calibrated on backend/scripts/topic_eval_he.json for precision ≥ 0.9 and
# checked on the held-out set and on real song titles
# (backend/scripts/eval_knowledge.py). The weights are spread over thousands
# of features per topic, so a clear lead is a small number.
LEXICON_MIN_SCORE = 0.02
LEXICON_MIN_MARGIN = 0.02
# Album and folder names count, but less than the title itself.
CONTEXT_WEIGHT = 0.5


@dataclass(frozen=True)
class LexiconResult:
    topic: str | None
    score: float
    margin: float
    second: str | None
    words: tuple[str, ...] = ()   # the title words that weighed most for the topic
    top: tuple[str, ...] = ()     # the two leading topics (empty when no word is known)


class TopicLexicon:
    """Scores a text against the vocabulary of every topic."""

    def __init__(self, topics: dict[str, dict[str, float]], *, min_score: float = LEXICON_MIN_SCORE,
                 min_margin: float = LEXICON_MIN_MARGIN, version: str = "", sources: int = 0):
        self.topics = topics
        self.min_score = min_score
        self.min_margin = min_margin
        self.version = version
        self.sources = sources

    def __bool__(self) -> bool:
        return bool(self.topics)

    @classmethod
    def load(cls, path: str | Path = LEXICON_FILE, **kw) -> "TopicLexicon":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            return cls(data.get("topics", {}), version=data.get("version", ""),
                       sources=len(data.get("sources", [])), **kw)
        except Exception:
            return cls({}, **kw)

    def scores(self, text: str) -> dict[str, float]:
        toks = title_tokens(text)
        if not toks:
            return {t: 0.0 for t in self.topics}
        word_vars = [variants(t) for t in toks]
        out: dict[str, float] = {}
        for topic, w in self.topics.items():
            s = 0.0
            for vs in word_vars:  # every word counts once, by its best reading
                s += max((w.get(v, 0.0) for v in vs), default=0.0)
            for vs, b in zip(word_vars, toks[1:]):
                s += max((w.get(v + "_" + b, 0.0) for v in vs), default=0.0)
            out[topic] = s
        return out

    def key_words(self, text: str, topic: str, limit: int = 2) -> tuple[str, ...]:
        """The words of ``text`` that weigh most for ``topic`` (to explain a decision)."""
        w = self.topics.get(topic, {})
        words = re.findall(r"[\u05d0-\u05ea\u05f3\u05f4\"'\u0591-\u05c7]+", unicodedata.normalize("NFC", text or ""))
        scored = []
        for word in words:
            toks = title_tokens(word)
            if not toks:
                continue
            weight = max((w.get(v, 0.0) for v in variants(toks[0])), default=0.0)
            if weight > 0:
                scored.append((weight, _NIQQUD.sub("", word).strip("\"'")))
        scored.sort(key=lambda x: -x[0])
        out: list[str] = []
        for _, word in scored:
            if word not in out:
                out.append(word)
        return tuple(out[:limit])

    def classify(self, title: str, context: str = "") -> LexiconResult:
        s = self.scores(title)
        if context:
            for topic, v in self.scores(context).items():
                s[topic] = s.get(topic, 0.0) + CONTEXT_WEIGHT * v
        if not s:
            return LexiconResult(None, 0.0, 0.0, None)
        ranked = sorted(s.items(), key=lambda kv: -kv[1])
        (best, top), (second, nxt) = ranked[0], (ranked[1] if len(ranked) > 1 else (None, 0.0))
        margin = top - nxt
        leaders = tuple(t for t, v in ranked[:2] if v > 0)
        if top >= self.min_score and margin >= self.min_margin:
            return LexiconResult(best, top, margin, second, self.key_words(f"{title} {context}", best), leaders)
        return LexiconResult(None, top, margin, best, (), leaders)
