"""Song details and covers from the web, when the listener asks for them.

The song menu offers "פרטים ותמונה מהרשת…": the app looks the song up and
shows a few candidates with their covers, and the listener picks the right
one (or none). Nothing is looked up on its own, and nothing is written into
the listener's files — the chosen details are kept in the library and laid
over the file's tags (see ``MusicIndex.details``).

Source: the iTunes Search API (no key). Measured in November 2026 on 14
well-known Hebrew songs: it found 6, MusicBrainz 2 and Deezer 3, so it is
the one used. It often spells Israeli artists in English ("Eli Herzlich"), so
a Hebrew name already in the library is never replaced by an English one.

Only the song's name, artist and length are sent; the request carries a
generic client name.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass

from .text_normalize import normalize

ITUNES_URL = "https://itunes.apple.com/search"
USER_AGENT = "song-details-lookup/1.2 (music player)"
_TIMEOUT = 12
_MAX_IMAGE = 4 * 1024 * 1024

# Words a store adds to a name that the song itself does not have.
_EDITION_RE = re.compile(r"\s*[(\[](?:live|לייב|.*?version|.*?remix|.*?edit|feat\.[^)\]]*|single)[^)\]]*[)\]]\s*",
                         re.IGNORECASE)


def has_hebrew(text: str) -> bool:
    return any("א" <= ch <= "ת" for ch in text or "")


@dataclass
class Candidate:
    title: str
    artist: str = ""
    album: str = ""
    year: str = ""
    duration: float | None = None
    cover_url: str = ""
    url: str = ""
    source: str = "itunes"
    score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def _similar(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    a, b = normalize(_EDITION_RE.sub(" ", a or "")), normalize(_EDITION_RE.sub(" ", b or ""))
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    return SequenceMatcher(None, a, b).ratio()


def _get_json(url: str, params: dict, timeout: float = _TIMEOUT) -> tuple[dict | None, str]:
    """GET a JSON answer. Returns ``(data, error)`` where error is "" or one
    of "blocked" (a filter refused it), "network" or "bad_answer"."""
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}",
                                 headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(2_000_000)
    except urllib.error.HTTPError as exc:
        text = ""
        try:
            text = exc.read(2000).decode("utf-8", "replace")
        except Exception:
            pass
        return None, "blocked" if exc.code == 418 or "netfree" in text.lower() else "network"
    except Exception:
        return None, "network"
    try:
        return json.loads(body.decode("utf-8")), ""
    except Exception:
        # A filter's page answered instead of the service.
        return None, "blocked" if b"netfree" in body.lower() else "bad_answer"


def _parse_itunes(data: dict) -> list[Candidate]:
    out = []
    for r in data.get("results", []) or []:
        if r.get("kind") not in (None, "song", "music-video"):
            continue
        art = r.get("artworkUrl100") or ""
        out.append(Candidate(
            title=r.get("trackName") or "",
            artist=r.get("artistName") or "",
            album=_EDITION_RE.sub(" ", r.get("collectionName") or "").replace(" - Single", "").strip(),
            year=(r.get("releaseDate") or "")[:4],
            duration=(r.get("trackTimeMillis") or 0) / 1000 or None,
            cover_url=art.replace("100x100bb", "600x600bb") if art else "",
            url=r.get("trackViewUrl") or r.get("collectionViewUrl") or "",
        ))
    return [c for c in out if c.title]


def score(candidate: Candidate, title: str, artist: str = "", duration: float | None = None) -> float:
    """How likely a candidate is the listener's song [0, 1]."""
    s = 0.6 * _similar(candidate.title, title)
    if artist and has_hebrew(artist) == has_hebrew(candidate.artist):
        s += 0.2 * _similar(candidate.artist, artist)
    else:
        s += 0.1  # cannot compare a Hebrew name with an English spelling
    if duration and candidate.duration:
        gap = abs(candidate.duration - duration)
        s += 0.2 if gap <= 3 else 0.12 if gap <= 8 else 0.0
    else:
        s += 0.08
    return round(s, 4)


def search(title: str, artist: str = "", duration: float | None = None, *, limit: int = 8,
           fetch=_get_json) -> tuple[list[Candidate], str]:
    """Candidates for a song, best first, and an error code ("" when the
    lookup worked, even with no results)."""
    title = (title or "").strip()
    if not title:
        return [], ""
    terms = [f"{artist} {title}".strip()] if artist else []
    terms.append(title)
    seen, found, error = set(), [], ""
    for term in terms:
        data, error = fetch(ITUNES_URL, {"term": term, "entity": "song", "country": "IL", "limit": limit})
        if data is None:
            if error == "blocked":
                break
            continue
        for c in _parse_itunes(data):
            key = (normalize(c.title), normalize(c.artist), normalize(c.album))
            if key in seen:
                continue
            seen.add(key)
            c.score = score(c, title, artist, duration)
            found.append(c)
        if found:
            error = ""
            break
    found.sort(key=lambda c: c.score, reverse=True)
    return found[:limit], error if not found else ""


def sure_match(candidate: Candidate, title: str, artist: str = "", duration: float | None = None) -> bool:
    """A match good enough to fill in without asking: the same name, the same
    singer (when the song names one, in the same script) and a length within
    three seconds. Anything less waits for the listener's choice."""
    from .text_normalize import normalize

    if not duration or not candidate.duration or abs(candidate.duration - duration) > 3:
        return False
    if normalize(candidate.title) != normalize(title) and _similar(candidate.title, title) < 0.95:
        return False
    if artist:
        if has_hebrew(artist) != has_hebrew(candidate.artist):
            return False
        if normalize(candidate.artist) != normalize(artist) and _similar(candidate.artist, artist) < 0.85:
            return False
    return True


def fetch_image(url: str, timeout: float = 15) -> bytes | None:
    """Download a cover picture (JPEG or PNG), or None."""
    if not url or not url.startswith("https://"):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(_MAX_IMAGE + 1)
    except Exception:
        return None
    if len(data) > _MAX_IMAGE or not (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"):
        return None
    return data


def merge(current: dict, chosen: Candidate | dict) -> dict:
    """What to take from a chosen candidate: empty or placeholder fields are
    filled, a name in English gives way to a Hebrew one, and a Hebrew name is
    never replaced by an English spelling."""
    from .scanner import is_placeholder_title

    c = chosen.to_dict() if isinstance(chosen, Candidate) else dict(chosen)
    out = {}
    for key in ("title", "artist", "album"):
        new, old = (c.get(key) or "").strip(), (current.get(key) or "").strip()
        if not new:
            continue
        if key == "album":
            new = _EDITION_RE.sub(" ", new).strip()
        weak = not old or (key == "title" and is_placeholder_title(old))
        if weak or (has_hebrew(new) and not has_hebrew(old)):
            out[key] = new
    year = (c.get("year") or "")[:4]
    if year.isdigit() and not (current.get("release_date") or "").strip():
        out["year"] = year
    return out
