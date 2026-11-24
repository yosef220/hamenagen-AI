"""A singer's songs on YouTube, and new ones from singers the listener follows (1.7).

Downloads page: a singer's name finds the singer's own channel — the one most
of the search results come from — and lists every song it uploaded, to tick
and download. Songs already on the computer are marked (by the YouTube id in
a downloaded file's name, or by the song's name).

Following: the channel's feed (YouTube's RSS, ``feeds/videos.xml``: the last
15 uploads, light, no yt-dlp) is read at most every few hours; what was not
there when the listener started following, and is not on the computer, is
new. Behind a filter that blocks the feed, the channel's page is read with
yt-dlp instead.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass

from .fetcher import SearchResult, clean_video_title
from .text_normalize import normalize

FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={id}"
CHECK_HOURS = 6
_NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
       "media": "http://search.yahoo.com/mrss/"}
_CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")


@dataclass
class Channel:
    id: str
    name: str
    url: str


def main_channel(results: list[SearchResult]) -> Channel | None:
    """The channel most results come from (at least two, and half of them)."""
    counts = Counter(r.channel_id for r in results if r.channel_id)
    if not counts:
        return None
    cid, n = counts.most_common(1)[0]
    if n < 2 or n < len(results) / 2:
        return None
    first = next(r for r in results if r.channel_id == cid)
    return Channel(cid, first.channel or first.uploader or "", first.channel_url or f"https://www.youtube.com/channel/{cid}")


def parse_feed(data: bytes) -> list[SearchResult]:
    """The uploads in a channel's RSS feed, newest first."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return []
    out = []
    for e in root.findall("a:entry", _NS):
        vid = (e.findtext("yt:videoId", "", _NS) or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
            continue
        title = (e.findtext("a:title", "", _NS) or "").strip()
        author = (e.findtext("a:author/a:name", "", _NS) or "").strip()
        published = (e.findtext("a:published", "", _NS) or "")[:10].replace("-", "")
        thumb = e.find("media:group/media:thumbnail", _NS)
        out.append(SearchResult("youtube", vid, title, f"https://www.youtube.com/watch?v={vid}", uploader=author,
                                channel=author, upload_date=published or None,
                                channel_id=(e.findtext("yt:channelId", "", _NS) or "").strip(),
                                thumbnail=thumb.get("url", "") if thumb is not None else ""))
    return out


class LibraryMatcher:
    """Whether a YouTube song is already on the computer: its id in a
    downloaded file's name, or the same song name (and singer, when both say one)."""

    def __init__(self, video_ids: set[str], tracks, artist_name=lambda a: a):
        self.ids = video_ids
        self.names: dict[str, set[str]] = {}
        for t in tracks:
            key = normalize(t.title or "")
            if key:
                self.names.setdefault(key, set()).add(normalize(artist_name(t.artist or "")))
        self.artist_name = artist_name

    def has(self, r: SearchResult) -> bool:
        if r.id in self.ids:
            return True
        artist, song = clean_video_title(r.title, r.channel or r.uploader)
        singers = self.names.get(normalize(song))
        if singers is None:
            return False
        who = normalize(self.artist_name(artist)) if artist else ""
        return not who or "" in singers or who in singers


def valid_channel_id(cid: str) -> bool:
    return bool(_CHANNEL_ID.match(cid or ""))
