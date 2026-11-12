"""A YouTube and a details service that answer from memory, for the UI
harness and for demonstrations without a network.

Turned on with ``HAMENAGEN_DEMO_ONLINE=1``. A request containing "חוסמת"
answers the way NetFree does (HTTP 418), so the blocked screen can be shown
too. Never used otherwise.
"""

from __future__ import annotations

import wave
from pathlib import Path

from .fetcher import FetchOutcome, SearchResult, clean_video_title, parse_youtube_link
from .metadata import Candidate
from .ytdlp_runner import message_for

CHANNEL = {"name": "Eli Herzlich", "id": "UCdemoChannel00000000000", "url": "https://www.youtube.com/@demo-singer/videos"}

_SONGS = [
    ("aaaaaaaaaa1", "אלי הרצליך - המלאך הקליפ הרשמי | Eli Herzlich - HaMalach Official Music Video", 306),
    ("aaaaaaaaaa2", "אלי הרצליך - כל תפילותיי הקליפ הרשמי", 316),
    ("aaaaaaaaaa3", "אלי הרצליך - רק לתת", 204),
    ("aaaaaaaaaa4", "אלי הרצליך - תזכה אותי", 279),
    ("aaaaaaaaaa5", "אלי הרצליך - בחכמה יבנה בית", 388),
    ("aaaaaaaaaa6", "אלי הרצליך - האדם", 288),
    ("aaaaaaaaaa7", "אלי הרצליך - מחרוזת סיום הש\"ס", 384),
    ("aaaaaaaaaa8", "אלי הרצליך ועדי רן - ושמרו | מופע השקה מלא", 3720),
    ("aaaaaaaaaa9", "אלי הרצליך - ותלמודו בידו", 242),
    ("aaaaaaaaab0", "קדימון לאלבום החדש", 38),
]


def _items(limit: int | None = None) -> list[SearchResult]:
    out = [SearchResult("youtube", vid, title, f"https://www.youtube.com/watch?v={vid}", CHANNEL["name"],
                        duration=dur, upload_date="20240101", channel=CHANNEL["name"], channel_id=CHANNEL["id"],
                        channel_url=CHANNEL["url"]) for vid, title, dur in _SONGS]
    return out[:limit] if limit else out


def _blocked(code: str = "netfree") -> FetchOutcome:
    return FetchOutcome(False, message_for(code), code=code, blocked=code == "netfree")


class DemoSource:
    name = "youtube"

    def available(self) -> bool:
        return True

    def search_url(self, query: str) -> str:
        from urllib.parse import quote_plus

        return f"https://www.youtube.com/results?search_query={quote_plus(query)}"

    def search(self, query: str, *, limit: int = 5) -> FetchOutcome:
        if "חוסמת" in query:
            return _blocked()
        items = _items(limit)
        return FetchOutcome(True, "", result=items[0], results=items)

    def link_info(self, url: str, *, limit: int = 300) -> FetchOutcome:
        parsed = parse_youtube_link(url)
        if parsed is None:
            return _blocked("bad_link")
        kind, url = parsed
        if kind == "video":
            item = next((i for i in _items() if i.id in url), _items(1)[0])
            artist, title = clean_video_title(item.title, item.channel)
            return FetchOutcome(True, "", result=item, results=[item], kind="video", title=title, artist=artist)
        return FetchOutcome(True, "", results=_items(), kind="list", title=CHANNEL["name"], artist=CHANNEL["name"])

    def download(self, result: SearchResult, dest_dir, *, on_progress=None, cancel=None) -> FetchOutcome:
        artist, title = clean_video_title(result.title, result.channel)
        path = Path(dest_dir) / f"{title} [{result.id}].wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(1)
            w.setframerate(8000)
            w.writeframes(b"\x80" * 8000 * 30)
        if on_progress:
            on_progress({"status": "downloading", "percent": 100.0})
            on_progress({"status": "finished"})
        return FetchOutcome(True, "ההורדה הושלמה.", path=str(path), result=result, title=title, artist=artist)


def _write_demo_audio(path: Path, seconds: int = 30) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(8000)
        w.writeframes(b"\x80" * 8000 * seconds)


def _fetch_audio(self, result: SearchResult, dest_dir, *, cancel=None) -> FetchOutcome:
    path = Path(dest_dir) / f"{result.id}.wav"
    if not path.exists():
        _write_demo_audio(path)
    return FetchOutcome(True, "", path=str(path), result=result)


DemoSource.fetch_audio = _fetch_audio


def demo_details(title: str) -> list[Candidate]:
    return [
        Candidate(title=title, artist="Kol B'Rama", album="שירי שבת", year="2019", duration=214),
        Candidate(title=f"{title} (Live)", artist="Kol B'Rama", album="הופעה חיה", year="2021", duration=262),
    ]
