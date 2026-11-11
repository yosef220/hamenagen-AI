#!/usr/bin/env python3
"""Build the knowledge index: the topic lexicon and the song index.

The embedding model knows Hebrew but not the Jewish calendar: it cannot tell
that "עבדים היינו" belongs to Pesach or "ונתנה תוקף" to the High Holidays.
This script gathers that knowledge once, at development time, from open
sources, and writes two small data files that the app reads offline:

``data/topic_lexicon.json``
    For every topic, the words and word pairs that characterise it, weighted
    by TF-IDF: Hebrew Wikipedia articles about the occasion, the names of its
    songs and piyutim, and the liturgy said on it (Sefaria). A song title is
    scored against every topic by summing the weights of its words.

``data/song_index.json``
    Known songs and piyutim by occasion — Hebrew Wikipedia categories such as
    "זמירות ופיוטים לשבת" or "שירי חנוכה", with their redirects as alternative
    spellings, plus the section names of the Siddur and the Haggadah.

Sources and licences
    * Hebrew Wikipedia — CC BY-SA 4.0. The derived files are therefore
      distributed under CC BY-SA 4.0 with attribution (see ``LICENSE-DATA.md``).
    * Sefaria — every text version carries its own licence; only versions marked
      Public Domain, CC0, CC-BY or CC-BY-SA are used (the chosen version and its
      licence are recorded in the output).

Everything fetched is cached under ``--cache`` so a rebuild is reproducible
and does not hit the network again. Requests are few and slow on purpose
(a delay between calls, ``Retry-After`` honoured).

Usage::

    python backend/scripts/build_knowledge.py                 # fetch (cached) + build
    python backend/scripts/build_knowledge.py --offline       # build from the cache only
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from hamenagen.knowledge import features, normalize_title, title_tokens  # noqa: E402
from hamenagen.topics import TOPIC_LABELS  # noqa: E402

WIKI_API = "https://he.wikipedia.org/w/api.php"
SEFARIA_API = "https://www.sefaria.org/api"
SEFARIA_EXPORT = "https://storage.googleapis.com/sefaria-export/json"
# A generic agent string: no names, no addresses — this runs from anywhere.
USER_AGENT = "song-topic-index-builder/1.1 (offline music player; low-volume, read-only)"

OK_LICENCES = {"public domain", "pd", "cc0", "cc-by", "cc-by-sa"}

# The topics the lexicon covers ("ווקאלי" is about how a song is performed,
# not what it is about — it has no lexicon).
TOPICS = [t for t in TOPIC_LABELS if t != "ווקאלי"]

# Hebrew Wikipedia articles describing each occasion (redirects are followed).
WIKI_ARTICLES: dict[str, list[str]] = {
    "שבת": ["שבת", "זמירות שבת", "קבלת שבת", "סעודות שבת", "הבדלה", "מלווה מלכה", "לכה דודי"],
    "ראש השנה": ["ראש השנה", "תקיעת שופר", "תשליך", "סימני ראש השנה", "מלכויות, זכרונות ושופרות"],
    "יום כיפור": ["יום הכיפורים", "כל נדרי", "תפילת נעילה", "סדר העבודה", "וידוי"],
    "סוכות": ["סוכות", "סוכה", "ארבעת המינים", "שמחת בית השואבה", "הושענא רבה", "שמחת תורה", "אושפיזין", "הושענות"],
    "חנוכה": ["חנוכה", "נר חנוכה", "מעוז צור", "מרד החשמונאים", "סביבון", "הנרות הללו"],
    "פורים": ["פורים", "מגילת אסתר", "משלוח מנות", "עדלאידע", "שושנת יעקב"],
    "פסח": ["פסח", "ליל הסדר", "הגדה של פסח", "מצה", "יציאת מצרים", "חד גדיא", "דיינו"],
    "ל״ג בעומר": ['ל"ג בעומר', "שמעון בר יוחאי", "הילולת רבי שמעון בר יוחאי במירון", "בר יוחאי (פיוט)"],
    "שבועות": ["שבועות", "מתן תורה", "מגילת רות", "אקדמות", "ביכורים", "תיקון ליל שבועות"],
    "אלול": ["אלול", "סליחות", "עשרת ימי תשובה", "תשובה (יהדות)", "ימים נוראים"],
    "חתונה": ["חתונה יהודית", "חופה", "שבע ברכות", "קידושין", "בדחן"],
    "ירושלים": ["ירושלים", "הכותל המערבי", "בית המקדש", "יום ירושלים", "שיבת ציון", "ירושלים של זהב"],
    "אמונה": ["אמונה ביהדות", "ביטחון בה'", "השגחה פרטית", "שלושה עשר עיקרים", "אני מאמין (פיוט)"],
}

# Hebrew Wikipedia categories that list the songs and piyutim of each
# occasion. Sub-categories are followed one level down.
WIKI_CATEGORIES: dict[str, list[str]] = {
    "שבת": ["זמירות ופיוטים לשבת"],
    "ראש השנה": ["פיוטי ראש השנה", "שירי ראש השנה"],
    "יום כיפור": ["פיוטי יום הכיפורים"],
    "אלול": ["סליחות"],
    "סוכות": ["פיוטים לסוכות", "שירי סוכות", "שירים ופיוטים לשמחת תורה", "פיוטים לשמיני עצרת"],
    "חנוכה": ["שירי חנוכה", "פיוטים לחנוכה"],
    "פורים": ["פיוטים ושירים לפורים", "שירי פורים"],
    "פסח": ["שירי פסח", "פיוטים לפסח", "פיוטי הגדה של פסח"],
    "ל״ג בעומר": ['שירי ל"ג בעומר', "ניגוני מירון"],
    "שבועות": ["שירי שבועות", "פיוטים לשבועות"],
    "חתונה": ["פיוטים לנישואין"],
    "ירושלים": ["שירים על ירושלים", "שירי יום ירושלים"],
}

# Sefaria texts said or sung on each occasion: (topic, book, preferred
# versions, selection). A selection is a list of schema paths for a complex
# text (Siddur, Haggadah), or of (chapter, first verse, last verse) for a
# biblical book; None takes the whole text.
SEFARIA_SOURCES: list[tuple[str, str, list[str], list | None]] = [
    ("שבת", "Siddur Ashkenaz", ["Daat Siddur Ashkenaz"],
     [["Shabbat", "Kabbalat Shabbat"], ["Shabbat", "Shabbat Evening"], ["Shabbat", "Daytime Meal"],
      ["Shabbat", "Third Meal"], ["Shabbat", "Havdalah"]]),
    ("שבת", "Siddur Edot HaMizrach", ["Torat Emet 357"],
     [["Shabbat Candle Lighting"], ["Kabbalat Shabbat"], ["Shabbat Evening"], ["Third Meal"], ["Havdalah"]]),
    ("שבת", "Yedid Nefesh", ["Original version with nikkud"], None),
    ("ראש השנה", "Machzor Rosh Hashanah Ashkenaz", [], None),
    ("ראש השנה", "Psalms", ["Tanach with Text Only"], [(47, 1, 10), (81, 1, 17)]),
    ("ראש השנה", "Leviticus", ["Tanach with Text Only"], [(23, 23, 25)]),
    ("ראש השנה", "Numbers", ["Tanach with Text Only"], [(29, 1, 6)]),
    ("ראש השנה", "I Samuel", ["Tanach with Text Only"], [(1, 1, 28), (2, 1, 10)]),
    ("יום כיפור", "Jonah", ["Tanach with Text Only"], None),
    ("יום כיפור", "Leviticus", ["Tanach with Text Only"], [(16, 1, 34), (23, 26, 32)]),
    ("יום כיפור", "Isaiah", ["Tanach with Text Only"], [(57, 14, 21), (58, 1, 14)]),
    ("אלול", "Siddur Ashkenaz", ["Daat Siddur Ashkenaz"], [["Festivals", "Selichot"]]),
    ("אלול", "Selichot Nusach Ashkenaz Lita", [], None),
    ("אלול", "Psalms", ["Tanach with Text Only"], [(27, 1, 14)]),
    ("סוכות", "Siddur Ashkenaz", ["Daat Siddur Ashkenaz"], [["Festivals", "Sukkot"]]),
    ("סוכות", "Leviticus", ["Tanach with Text Only"], [(23, 33, 44)]),
    ("סוכות", "Deuteronomy", ["Tanach with Text Only"], [(16, 13, 15)]),
    ("חנוכה", "Siddur Ashkenaz", ["Daat Siddur Ashkenaz"], [["Festivals", "Chanukah"]]),
    ("חנוכה", "Siddur Edot HaMizrach", ["Torat Emet 357"], [["Hanukkah"]]),
    ("פורים", "Siddur Edot HaMizrach", ["Torat Emet 357"], [["Purim"]]),
    ("פורים", "Esther", ["Tanach with Text Only"], None),
    ("פסח", "Pesach Haggadah", [], None),
    ("פסח", "Exodus", ["Tanach with Text Only"], [(12, 1, 28), (15, 1, 21)]),
    ("שבועות", "Ruth", ["Tanach with Text Only"], None),
    ("שבועות", "Exodus", ["Tanach with Text Only"], [(19, 1, 25), (20, 1, 23)]),
    ("שבועות", "Deuteronomy", ["Tanach with Text Only"], [(16, 9, 12)]),
    ("חתונה", "Siddur Edot HaMizrach", ["Torat Emet 357"],
     [["Assorted Blessings and Prayers", "Marriage"], ["Assorted Blessings and Prayers", "Sheva Berachot"]]),
    ("חתונה", "Jeremiah", ["Tanach with Text Only"], [(33, 10, 11)]),
    ("חתונה", "Psalms", ["Tanach with Text Only"], [(128, 1, 6)]),
    ("ירושלים", "Psalms", ["Tanach with Text Only"],
     [(48, 1, 15), (87, 1, 7), (122, 1, 9), (125, 1, 5), (126, 1, 6), (137, 1, 9)]),
    ("ירושלים", "Isaiah", ["Tanach with Text Only"], [(52, 1, 12), (60, 1, 22), (62, 1, 12)]),
    ("ירושלים", "Zechariah", ["Tanach with Text Only"], [(8, 1, 23)]),
    ("אמונה", "Psalms", ["Tanach with Text Only"],
     [(23, 1, 6), (37, 1, 11), (62, 1, 13), (91, 1, 16), (121, 1, 8), (146, 1, 10)]),
    ("אמונה", "Siddur Edot HaMizrach", ["Torat Emet 357"], [["Additions for Shacharit", "Thirteen Principles of Faith"]]),
]

# Section names worth adding to the song index (they are what many songs are
# called). Only named sections inside these schema paths are used.
SEFARIA_TITLE_SOURCES: list[tuple[str, str, list[list[str]]]] = [
    ("שבת", "Siddur Ashkenaz", [["Shabbat", "Shabbat Evening"], ["Shabbat", "Daytime Meal"],
                                ["Shabbat", "Third Meal"], ["Shabbat", "Havdalah"], ["Shabbat", "Kabbalat Shabbat"]]),
    ("שבת", "Siddur Edot HaMizrach", [["Shabbat Evening"], ["Third Meal"], ["Havdalah"]]),
    ("פסח", "Pesach Haggadah", [[]]),
    ("חנוכה", "Siddur Ashkenaz", [["Festivals", "Chanukah"]]),
    ("סוכות", "Siddur Ashkenaz", [["Festivals", "Sukkot"]]),
]

# Titles that name a whole category, an index page or something too general
# to identify one song.
_NOT_A_SONG = re.compile(
    r"^(שירי |פיוטי |זמירות ופיוטים|שירים ופיוטים|פיוטים |קטגוריה|רשימת |סדר |סליחות$|קינות)"
)


# -------------------------------------------------------------------- network
class Fetcher:
    def __init__(self, cache: Path, offline: bool, delay: float):
        self.cache = cache
        self.offline = offline
        self.delay = delay
        self.cache.mkdir(parents=True, exist_ok=True)
        self.requests = 0

    def _path(self, url: str) -> Path:
        return self.cache / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".json")

    def json(self, url: str, params: dict | None = None):
        if params:
            url = url + "?" + urllib.parse.urlencode(params)
        path = self._path(url)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        if self.offline:
            raise FileNotFoundError(f"not in the cache (offline): {url}")
        last: Exception | None = None
        for attempt in range(15):
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:  # noqa: S310 - fixed hosts
                    data = json.loads(resp.read().decode("utf-8"))
                self.requests += 1
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                time.sleep(self.delay)
                return data
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code in (429, 502, 503):
                    # Asked to slow down: wait as long as the server says, and
                    # a little more each time it has to ask again.
                    wait = exc.headers.get("Retry-After")
                    base = float(wait) if wait and wait.isdigit() else 5.0
                    time.sleep(base + 5.0 * attempt)
                    continue
                if exc.code == 404:
                    path.write_text("null", encoding="utf-8")
                    return None
                raise
            except (urllib.error.URLError, TimeoutError) as exc:
                last = exc
                time.sleep(3.0 * (attempt + 1))
        raise RuntimeError(f"failed: {url}: {last}")


# -------------------------------------------------------------------- Wikipedia
def wiki(f: Fetcher, **params):
    return f.json(WIKI_API, {**params, "format": "json", "formatversion": "2"})


def wiki_article(f: Fetcher, title: str) -> tuple[str, str]:
    d = wiki(f, action="query", prop="extracts", explaintext="1", redirects="1", titles=title)
    pages = (d or {}).get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return "", ""
    return pages[0].get("title", title), pages[0].get("extract", "") or ""


def wiki_category(f: Fetcher, category: str, depth: int = 1) -> dict[str, str]:
    """Article title → the category it was found in (sub-categories too)."""
    out: dict[str, str] = {}

    def walk(cat: str, level: int, seen: set[str]) -> None:
        params = {"action": "query", "list": "categorymembers", "cmtitle": f"קטגוריה:{cat}",
                  "cmlimit": "max", "cmtype": "page|subcat"}
        while True:
            d = wiki(f, **params) or {}
            for m in d.get("query", {}).get("categorymembers", []):
                if m.get("ns") == 0:
                    out.setdefault(m["title"], cat)
                elif m.get("ns") == 14 and level < depth:
                    sub = m["title"].split(":", 1)[1]
                    if sub not in seen:
                        walk(sub, level + 1, seen | {sub})
            if "continue" in d:
                params = {**params, **d["continue"]}
            else:
                break

    walk(category, 0, {category})
    return out


def wiki_redirects(f: Fetcher, titles: list[str]) -> dict[str, list[str]]:
    """Article title → the titles that redirect to it (other spellings)."""
    out: dict[str, list[str]] = defaultdict(list)
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        params = {"action": "query", "prop": "redirects", "rdlimit": "max", "rdnamespace": "0",
                  "titles": "|".join(batch)}
        while True:
            d = wiki(f, **params) or {}
            for p in d.get("query", {}).get("pages", []):
                for r in p.get("redirects", []) or []:
                    out[p["title"]].append(r["title"])
            if "continue" in d:
                params = {**params, **d["continue"]}
            else:
                break
    return out


def wiki_background(f: Fetcher, count: int) -> list[str]:
    """Intros of random articles: what ordinary Hebrew looks like (for IDF).
    Random batches are cached by number, so a rebuild reuses the same ones."""
    docs: list[str] = []
    batch = 0
    while len(docs) < count:
        params = {"action": "query", "generator": "random", "grnnamespace": "0", "grnlimit": "20",
                  "prop": "extracts", "explaintext": "1", "exintro": "1", "exlimit": "20",
                  "_batch": str(batch)}  # not an API parameter: it only keys the cache
        d = wiki(f, **params) or {}
        got = [p.get("extract", "") for p in d.get("query", {}).get("pages", []) if p.get("extract")]
        docs.extend(got)
        batch += 1
        if batch > count:  # the API returned nothing for too long
            break
    return docs[:count]


# -------------------------------------------------------------------- Sefaria
def sefaria_usable_versions(f: Fetcher, book: str) -> list[dict]:
    versions = f.json(f"{SEFARIA_API}/texts/versions/{urllib.parse.quote(book)}") or []
    hebrew = [v for v in versions if v.get("language") == "he"]
    return [v for v in hebrew if str(v.get("license", "")).strip().lower() in OK_LICENCES]


def sefaria_version(f: Fetcher, book: str, preferred: list[str]) -> tuple[str, str] | None:
    """(version title, licence) of a Hebrew version we may use."""
    usable = sefaria_usable_versions(f, book)
    for name in preferred:
        for v in usable:
            if v.get("versionTitle", "").strip() == name.strip():
                return v["versionTitle"], v["license"]
    if usable:
        # Prefer public domain, then the most permissive licence.
        order = {"public domain": 0, "pd": 0, "cc0": 1, "cc-by": 2, "cc-by-sa": 3}
        v = min(usable, key=lambda v: order.get(str(v.get("license")).lower(), 9))
        return v["versionTitle"], v["license"]
    return None


def sefaria_book(f: Fetcher, book: str, version: str) -> tuple[dict | list | None, dict | None]:
    index = f.json(f"{SEFARIA_API}/v2/raw/index/{urllib.parse.quote(book)}")
    cats = "/".join(urllib.parse.quote(c) for c in (index or {}).get("categories", []))
    folder = f"{SEFARIA_EXPORT}/{cats}/{urllib.parse.quote(book)}/Hebrew"
    data = f.json(f"{folder}/{urllib.parse.quote(version)}.json")
    if data is None:
        # Some versions are exported only inside merged.json. Use it when
        # every version merged into it is one we may use.
        merged = f.json(f"{folder}/merged.json")
        allowed = {v.get("versionTitle", "").strip() for v in sefaria_usable_versions(f, book)}
        merged_from = {str(v[0]).strip() for v in (merged or {}).get("versions", []) if v}
        if merged and merged_from and merged_from <= allowed:
            data = merged
    return (data or {}).get("text"), index


def _flatten(node) -> list[str]:
    if node is None:
        return []
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        out = []
        for v in node.values():
            out.extend(_flatten(v))
        return out
    out = []
    for v in node:
        out.extend(_flatten(v))
    return out


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"[֑-ׇ]", "", text)  # niqqud and cantillation


def sefaria_select(text, selection) -> list[str]:
    if selection is None:
        return _flatten(text)
    out: list[str] = []
    for sel in selection:
        if isinstance(sel, tuple):  # (chapter, first verse, last verse) of a biblical book
            ch, a, b = sel
            chapter = text[ch - 1] if isinstance(text, list) and len(text) >= ch else []
            out.extend(_flatten(chapter[a - 1:b]))
        else:
            node = text
            for key in sel:
                node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                print(f"    (missing section: {' > '.join(sel)})", file=sys.stderr)
            out.extend(_flatten(node))
    return [_clean(t) for t in out if t]


def schema_titles(index: dict, path: list[str]) -> list[str]:
    """Hebrew names of the named sections under a schema path."""
    node = (index or {}).get("schema") or {}

    def en(n):
        for t in n.get("titles", []) or []:
            if t.get("lang") == "en" and t.get("primary"):
                return t["text"]
        return n.get("title", "")

    for key in path:
        node = next((c for c in node.get("nodes", []) or [] if en(c) == key), None)
        if node is None:
            return []
    names: list[str] = []

    def walk(n, top):
        for c in n.get("nodes", []) or []:
            he = next((t["text"] for t in c.get("titles", []) or [] if t.get("lang") == "he" and t.get("primary")), "")
            if he and not c.get("default"):
                names.append(he)
            walk(c, False)

    walk(node, True)
    return names


# -------------------------------------------------------------------- the song index
def clean_song_title(title: str) -> tuple[str, str]:
    """("song title", "artist hint") from a Wikipedia article title."""
    artist = ""
    m = re.search(r"\s*\(([^)]*)\)\s*$", title)
    if m:
        inner = m.group(1)
        title = title[:m.start()].strip()
        am = re.match(r"(?:שיר|פיוט|אלבום|ניגון)\s+של\s+(.+)", inner)
        if am:
            artist = am.group(1).strip()
    return title.strip(), artist


def is_song_title(title: str) -> bool:
    if not title or re.search(r"[A-Za-z]", title):
        return False  # foreign-language songs are not what this index is for
    if _NOT_A_SONG.search(title):
        return False
    words = title_tokens(title)
    return bool(words) and len(" ".join(words)) >= 3


def build_song_index(f: Fetcher, log) -> dict:
    entries: dict[str, dict] = {}
    order = {t: i for i, t in enumerate(TOPICS)}

    def add(title: str, topic: str, source: str, artist: str = "", aliases=()):
        key = normalize_title(title)
        if not key:
            return
        e = entries.setdefault(key, {"title": title, "topics": [], "aliases": [], "artist": artist, "src": []})
        if topic not in e["topics"]:
            e["topics"].append(topic)
        if source not in e["src"]:
            e["src"].append(source)
        for a in aliases:
            if normalize_title(a) and normalize_title(a) != key and a not in e["aliases"]:
                e["aliases"].append(a)
        if artist and not e["artist"]:
            e["artist"] = artist

    pages_by_topic: dict[str, dict[str, str]] = {}
    for topic, cats in WIKI_CATEGORIES.items():
        found: dict[str, str] = {}
        for cat in cats:
            found.update(wiki_category(f, cat))
        pages_by_topic[topic] = found
        log(f"  wiki categories · {topic}: {len(found)} pages")

    all_pages = sorted({p for pages in pages_by_topic.values() for p in pages})
    redirects = wiki_redirects(f, all_pages)
    for topic, pages in pages_by_topic.items():
        for page in pages:
            title, artist = clean_song_title(page)
            if not is_song_title(title):
                continue
            aliases = []
            for r in redirects.get(page, []):
                rt, _ = clean_song_title(r)
                if is_song_title(rt):
                    aliases.append(rt)
            add(title, topic, "he.wikipedia", artist, aliases)

    for topic, book, paths in SEFARIA_TITLE_SOURCES:
        index = f.json(f"{SEFARIA_API}/v2/raw/index/{urllib.parse.quote(book)}")
        for path in paths:
            for name in schema_titles(index, path):
                name = re.sub(r"\s*\(.*?\)\s*", " ", name).strip()
                # A one-word section name ("קדש", "מגיד") is a step of the
                # seder, not a song title; keep names of two words or more.
                if len(title_tokens(name)) >= 2 and is_song_title(name):
                    add(name, topic, "sefaria")

    # Sort topics of each entry by the topic order, and the entries by title.
    out = []
    for key, e in sorted(entries.items()):
        e["topics"].sort(key=lambda t: order.get(t, 99))
        out.append({k: v for k, v in e.items() if v})
    return {"entries": out}


# -------------------------------------------------------------------- the lexicon
def build_lexicon(docs: dict[str, list[str]], background: list[str], keep: int) -> dict[str, dict[str, float]]:
    tfs: dict[str, Counter] = {}
    df: Counter = Counter()
    for topic, texts in docs.items():
        c: Counter = Counter()
        for t in texts:
            c.update(features(t, pairs=True))
        tfs[topic] = c
        df.update(set(c))
    for text in background:
        df.update(set(features(text, pairs=True)))
    n = len(docs) + len(background)
    lexicon: dict[str, dict[str, float]] = {}
    for topic, c in tfs.items():
        weights = {}
        for feat, tf in c.items():
            if df[feat] > 0.5 * n:
                continue  # as common as a stop word
            if "_" not in feat and len(feat) < 2:
                continue
            weights[feat] = (1.0 + math.log(tf)) * math.log(n / df[feat])
        top = sorted(weights.items(), key=lambda kv: -kv[1])[:keep]
        norm = math.sqrt(sum(v * v for _, v in top)) or 1.0
        lexicon[topic] = {k: round(v / norm, 5) for k, v in top}
    return lexicon


# -------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", default=str(HERE.parent.parent / "build" / "knowledge-cache"))
    ap.add_argument("--out", default=str(HERE.parent / "hamenagen" / "data"))
    ap.add_argument("--offline", action="store_true", help="use only what is already cached")
    ap.add_argument("--background", type=int, default=1500, help="random articles for IDF")
    ap.add_argument("--keep", type=int, default=6000, help="features kept per topic")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    args = ap.parse_args()

    f = Fetcher(Path(args.cache), args.offline, args.delay)
    log = lambda msg: print(msg, file=sys.stderr, flush=True)  # noqa: E731

    sources: list[dict] = []
    docs: dict[str, list[str]] = {t: [] for t in TOPICS}

    log("Wikipedia articles")
    for topic, titles in WIKI_ARTICLES.items():
        for title in titles:
            real, text = wiki_article(f, title)
            if not text:
                log(f"  ! missing: {title}")
                continue
            docs[topic].append(text)
            sources.append({"topic": topic, "source": "he.wikipedia", "title": real, "licence": "CC BY-SA 4.0",
                            "url": "https://he.wikipedia.org/wiki/" + urllib.parse.quote(real.replace(" ", "_"))})
        log(f"  {topic}: {sum(len(t) for t in docs[topic]):,} chars")

    log("Sefaria")
    for topic, book, preferred, selection in SEFARIA_SOURCES:
        picked = sefaria_version(f, book, preferred)
        if not picked:
            log(f"  ! no openly licensed Hebrew version: {book}")
            continue
        version, licence = picked
        text, _ = sefaria_book(f, book, version)
        if text is None:
            log(f"  ! could not download: {book} / {version}")
            continue
        parts = sefaria_select(text, selection)
        docs[topic].append("\n".join(parts))
        sources.append({"topic": topic, "source": "sefaria", "title": book, "version": version, "licence": licence,
                        "url": "https://www.sefaria.org/" + urllib.parse.quote(book.replace(" ", "_"))})
        log(f"  {topic} · {book} ({version}, {licence}): {sum(len(p) for p in parts):,} chars")

    log("Song index")
    index = build_song_index(f, log)
    # The names of an occasion's songs are part of its vocabulary too.
    for e in index["entries"]:
        for topic in e["topics"]:
            docs[topic].append(" ".join([e["title"], *e.get("aliases", [])]))
    log(f"  {len(index['entries'])} songs")

    log("Background")
    background = wiki_background(f, args.background)
    log(f"  {len(background)} random articles")

    lexicon = build_lexicon(docs, background, args.keep)
    built = date.today().isoformat()
    attribution = ("נבנה מוויקיפדיה העברית (CC BY-SA 4.0) ומטקסטים של ספריא ברישיונות פתוחים; "
                   "מופץ ברישיון CC BY-SA 4.0. Built from Hebrew Wikipedia (CC BY-SA 4.0) and openly "
                   "licensed Sefaria texts; distributed under CC BY-SA 4.0.")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "topic_lexicon.json").write_text(json.dumps({
        "version": built,
        "licence": "CC BY-SA 4.0",
        "attribution": attribution,
        "method": {"features": "words with up to two one-letter prefixes removed, and word pairs",
                   "weights": "(1+log tf)·log(N/df), top features per topic, L2-normalised",
                   "background_docs": len(background), "kept_per_topic": args.keep},
        "sources": sources,
        "topics": lexicon,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out / "song_index.json").write_text(json.dumps({
        "version": built,
        "licence": "CC BY-SA 4.0",
        "attribution": attribution,
        **index,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"wrote {out / 'topic_lexicon.json'} and {out / 'song_index.json'} ({f.requests} network requests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
