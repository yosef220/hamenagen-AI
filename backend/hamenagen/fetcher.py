"""Online fetcher — search / stream / download from an external source (§11).

The current source plugin is YouTube via ``yt-dlp``. The design is
*pluggable*: any source that implements :class:`SourcePlugin` can be dropped
in without touching the rest of the app (spec §4 "מקור חיצוני מתחלף"), which
is what makes a future move to a licensed source cheap (spec §18).

``yt-dlp`` is treated as an optional, continuously-updated dependency
(spec §11 notes, §14): if it is not installed every method degrades to a
clear, structured "unavailable" result instead of raising, so the offline
core is never affected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class SearchResult:
    source: str
    id: str
    title: str
    url: str
    uploader: str = ""
    duration: float | None = None
    upload_date: str | None = None  # 'YYYYMMDD' from the source, used as release_date


@dataclass
class FetchOutcome:
    ok: bool
    message: str = ""
    path: str | None = None
    result: SearchResult | None = None
    results: list[SearchResult] = field(default_factory=list)


class SourcePlugin(Protocol):
    name: str

    def available(self) -> bool: ...
    def search(self, query: str, *, limit: int = 5) -> FetchOutcome: ...
    def download(self, result: SearchResult, dest_dir: str | Path) -> FetchOutcome: ...
    def search_url(self, query: str) -> str: ...


class YouTubeSource:
    """YouTube source plugin backed by yt-dlp."""

    name = "youtube"

    def __init__(self) -> None:
        self._ytdlp = None

    def _load(self):
        if self._ytdlp is None:
            import yt_dlp  # type: ignore  # pragma: no cover - optional dep

            self._ytdlp = yt_dlp
        return self._ytdlp

    def available(self) -> bool:
        try:
            self._load()
            return True
        except Exception:
            return False

    def search_url(self, query: str) -> str:
        """A ready-to-open results URL (spec §11 step 4 fallback)."""
        from urllib.parse import quote_plus

        return f"https://www.youtube.com/results?search_query={quote_plus(query)}"

    def search(self, query: str, *, limit: int = 5) -> FetchOutcome:
        try:
            yt_dlp = self._load()
        except Exception:
            return FetchOutcome(False, "yt-dlp אינו מותקן — לא ניתן לחפש כרגע.")
        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": True}
        try:  # pragma: no cover - network
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            entries = info.get("entries", []) if info else []
            results = [
                SearchResult(
                    source=self.name,
                    id=e.get("id", ""),
                    title=e.get("title", ""),
                    url=e.get("url") or f"https://www.youtube.com/watch?v={e.get('id','')}",
                    uploader=e.get("uploader", "") or e.get("channel", ""),
                    duration=e.get("duration"),
                    upload_date=e.get("upload_date"),
                )
                for e in entries
                if e
            ]
            if not results:
                return FetchOutcome(False, "לא נמצאו תוצאות.", results=[])
            return FetchOutcome(True, "", result=results[0], results=results)
        except Exception as exc:  # pragma: no cover
            return FetchOutcome(False, f"החיפוש נכשל: {exc}")

    def download(self, result: SearchResult, dest_dir: str | Path) -> FetchOutcome:
        try:
            yt_dlp = self._load()
        except Exception:
            return FetchOutcome(False, "yt-dlp אינו מותקן — לא ניתן להוריד כרגע.")
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        outtmpl = str(dest / "%(title)s [%(id)s].%(ext)s")
        opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
            ],
        }
        try:  # pragma: no cover - network
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(result.url, download=True)
                path = ydl.prepare_filename(info)
                mp3 = str(Path(path).with_suffix(".mp3"))
                final = mp3 if Path(mp3).exists() else path
            return FetchOutcome(True, "ההורדה הושלמה.", path=final, result=result)
        except Exception as exc:  # pragma: no cover
            msg = str(exc).lower()
            if "unavailable" in msg or "private" in msg:
                friendly = "הסרטון אינו זמין (הוסר או פרטי)."
            elif "geo" in msg or "country" in msg:
                friendly = "הסרטון חסום גאוגרפית."
            else:
                friendly = f"ההורדה נכשלה: {exc}"
            return FetchOutcome(False, friendly)


class OnlineFetcher:
    """Facade over the currently-selected source plugin."""

    def __init__(self, source: SourcePlugin | None = None):
        self.source: SourcePlugin = source or YouTubeSource()

    def available(self) -> bool:
        return self.source.available()

    def search(self, query: str, *, limit: int = 5) -> FetchOutcome:
        return self.source.search(query, limit=limit)

    def search_url(self, query: str) -> str:
        return self.source.search_url(query)

    def download(self, result: SearchResult, dest_dir: str | Path) -> FetchOutcome:
        return self.source.download(result, dest_dir)
