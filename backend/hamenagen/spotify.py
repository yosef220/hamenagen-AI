"""A Spotify link → its songs, found on YouTube to download (1.7).

A playlist, an album or a single song from Spotify: the public embed page
(``open.spotify.com/embed/<kind>/<id>``, no account or key) carries the names
of its songs, their singers and lengths. Each song is then downloaded as the
first YouTube result for "<singer> <song>" — yt-dlp's ``ytsearch1:`` — and its
length checks the match (a much shorter file is not kept, see
fetcher.looks_replaced). Behind a filter that blocks searching YouTube, this
cannot work; the link is read, and the page says so.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .fetcher import SearchResult

EMBED_URL = "https://open.spotify.com/embed/{kind}/{id}"
_LINK = re.compile(r"(?:open\.spotify\.com/(?:intl-[a-z]{2}(?:-[A-Za-z]{2})?/)?|spotify:)"
                   r"(track|album|playlist)[/:]([A-Za-z0-9]{22})")
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


@dataclass
class Song:
    title: str
    artists: str
    seconds: float | None
    spotify_id: str = ""


def parse_link(text: str) -> tuple[str, str] | None:
    """(kind, id) of a Spotify link in ``text``, or None."""
    m = _LINK.search(text or "")
    return (m.group(1), m.group(2)) if m else None


def parse_embed(html: str) -> tuple[str, list[Song]]:
    """(the list's name, its songs) from an embed page."""
    m = _NEXT_DATA.search(html or "")
    if not m:
        return "", []
    try:
        ent = json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    except (ValueError, KeyError, TypeError):
        return "", []
    if not isinstance(ent, dict):
        return "", []

    def seconds(ms):
        return round(ms / 1000.0, 1) if isinstance(ms, (int, float)) and ms > 0 else None

    def sid(uri):
        return (uri or "").rsplit(":", 1)[-1]

    if ent.get("type") == "track":
        artists = ", ".join(a.get("name", "") for a in ent.get("artists") or [] if isinstance(a, dict))
        title = ent.get("name") or ent.get("title") or ""
        return title, ([Song(title, artists, seconds(ent.get("duration")), sid(ent.get("uri")))] if title else [])
    songs = [Song(t.get("title") or "", t.get("subtitle") or "", seconds(t.get("duration")), sid(t.get("uri")))
             for t in ent.get("trackList") or [] if isinstance(t, dict) and t.get("title")]
    return ent.get("name") or ent.get("title") or "", songs


def first_artist(artists: str) -> str:
    return (artists or "").split(",")[0].strip()


def as_result(song: Song) -> SearchResult:
    """A song to download: the first YouTube result for its singer and name."""
    singer = first_artist(song.artists)
    query = " ".join(p for p in (singer, song.title) if p)
    return SearchResult("youtube", f"sp-{song.spotify_id or abs(hash(query))}", f"{singer} - {song.title}" if singer else song.title,
                        f"ytsearch1:{query}", uploader=singer, duration=song.seconds, channel=singer)
