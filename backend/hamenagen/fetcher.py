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
from typing import Callable, Protocol

# A progress callback receives dicts like:
#   {"status": "downloading", "percent": 42.0, "downloaded": 1234, "total": 4567,
#    "speed": 120000, "eta": 8}
#   {"status": "postprocessing"}  |  {"status": "finished"}
ProgressHook = Callable[[dict], None]


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
    def download(
        self, result: SearchResult, dest_dir: str | Path, *, on_progress: ProgressHook | None = None
    ) -> FetchOutcome: ...
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

    @staticmethod
    def _translate_error(exc: Exception) -> str:
        """Map a raw yt-dlp error to a clear Hebrew message (spec §11 notes)."""
        msg = str(exc).lower()
        if "unavailable" in msg or "private" in msg or "removed" in msg:
            return "הסרטון אינו זמין (הוסר או פרטי)."
        if "geo" in msg or "not available in your country" in msg or "blocked" in msg:
            return "הסרטון חסום גאוגרפית."
        if "sign in" in msg or "age" in msg:
            return "הסרטון מוגבל (נדרשת התחברות / הגבלת גיל)."
        if "ffmpeg" in msg:
            return "נדרש ffmpeg כדי להמיר את האודיו — ודא שהוא מותקן."
        return f"ההורדה נכשלה: {exc}"

    def _make_hook(self, on_progress: ProgressHook | None):
        if on_progress is None:
            return None

        def hook(d: dict) -> None:  # pragma: no cover - invoked by yt-dlp
            status = d.get("status")
            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                percent = round(done / total * 100, 1) if total else None
                on_progress({
                    "status": "downloading",
                    "percent": percent,
                    "downloaded": done,
                    "total": total,
                    "speed": d.get("speed"),
                    "eta": d.get("eta"),
                })
            elif status == "finished":
                on_progress({"status": "postprocessing"})

        return hook

    def download(
        self, result: SearchResult, dest_dir: str | Path, *, on_progress: ProgressHook | None = None
    ) -> FetchOutcome:
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
        hook = self._make_hook(on_progress)
        if hook is not None:
            opts["progress_hooks"] = [hook]
        try:  # pragma: no cover - network
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(result.url, download=True)
                path = ydl.prepare_filename(info)
                mp3 = str(Path(path).with_suffix(".mp3"))
                final = mp3 if Path(mp3).exists() else path
                # Enrich the result with metadata for indexing (spec §10).
                if info:
                    result = SearchResult(
                        source=self.name,
                        id=info.get("id", result.id),
                        title=info.get("title", result.title),
                        url=result.url,
                        uploader=info.get("uploader") or info.get("channel") or result.uploader,
                        duration=info.get("duration", result.duration),
                        upload_date=info.get("upload_date", result.upload_date),
                    )
            if on_progress is not None:
                on_progress({"status": "finished"})
            return FetchOutcome(True, "ההורדה הושלמה.", path=final, result=result)
        except Exception as exc:  # pragma: no cover
            return FetchOutcome(False, self._translate_error(exc))


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

    def download(
        self, result: SearchResult, dest_dir: str | Path, *, on_progress: ProgressHook | None = None
    ) -> FetchOutcome:
        return self.source.download(result, dest_dir, on_progress=on_progress)
