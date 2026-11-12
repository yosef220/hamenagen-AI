"""Online fetcher — search, read links and download from YouTube (§11).

The source plugin is YouTube via ``yt-dlp``, which always runs as its own
process (see :mod:`hamenagen.ytdlp_runner` for why, and for what NetFree
taught us). The design stays *pluggable*: any source that implements
:class:`SourcePlugin` can replace it (spec §4, §18).

What the app does with it:

* **search** — a few songs for a request. Behind NetFree this is refused
  (HTTP 418) and the outcome says so (``code="netfree"``); the app then opens
  the search in the listener's browser and takes the pasted link.
* **link_info** — what a pasted link is: one song, a playlist or a channel
  (with its songs, up to a limit).
* **download** — one song into the library, as MP3 with the cover inside
  when ffmpeg is available (it ships with the app), otherwise as M4A
  straight from YouTube; either way tagged with a clean song name, the
  artist and the YouTube picture.

Nothing here raises: every failure comes back as a :class:`FetchOutcome`
with a Hebrew message and a code the interface can act on.
"""

from __future__ import annotations

import inspect
import json
import re
import shutil
import threading
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import parse_qs, quote_plus, urlparse

from .ytdlp_runner import CLIENT_SETS, MESSAGES, YtDlpRunner, message_for

# A progress callback receives dicts like:
#   {"status": "downloading", "percent": 42.0} | {"status": "postprocessing"} | {"status": "finished"}
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
    channel: str = ""
    channel_id: str = ""
    channel_url: str = ""
    thumbnail: str = ""


@dataclass
class FetchOutcome:
    ok: bool
    message: str = ""
    path: str | None = None
    result: SearchResult | None = None
    results: list[SearchResult] = field(default_factory=list)
    code: str = ""                 # see ytdlp_runner.MESSAGES; "" when ok
    blocked: bool = False          # the network refused (NetFree and the like)
    kind: str = ""                 # link_info: "video" | "list"
    title: str = ""                # a clean song (or list) name
    artist: str = ""
    cover: bytes | None = None     # the picture that came with a download


class SourcePlugin(Protocol):
    name: str

    def available(self) -> bool: ...
    def search(self, query: str, *, limit: int = 5) -> FetchOutcome: ...
    def download(
        self, result: SearchResult, dest_dir: str | Path, *, on_progress: ProgressHook | None = None
    ) -> FetchOutcome: ...
    def search_url(self, query: str) -> str: ...


# ------------------------------------------------------------------ names
_NOISE_RE = re.compile(
    r"\s*[\(\[]?\s*(?:הקליפ הרשמי|קליפ רשמי|הקליפ|official\s+(?:music\s+)?(?:video|audio|clip|lyric video)|"
    r"official|lyric(?:s)?\s+video|lyrics|audio|video|clip|hd|4k|קליפ|אודיו|מילים|גרסה רשמית)\s*[\)\]]?\s*$",
    re.IGNORECASE,
)


def _has_hebrew(text: str) -> bool:
    return any("א" <= ch <= "ת" for ch in text or "")


def clean_video_title(title: str, channel: str = "") -> tuple[str, str]:
    """``(artist, song)`` from a YouTube title such as
    "אלי הרצליך - כל תפילותיי הקליפ הרשמי | Eli Herzlich - Kol Tefilotai"."""
    text = (title or "").strip()
    parts = [p.strip() for p in re.split(r"\s+[|｜]\s+", text) if p.strip()]
    if len(parts) > 1:
        hebrew = [p for p in parts if _has_hebrew(p)]
        text = hebrew[0] if hebrew else parts[0]
    for _ in range(3):
        cleaned = _NOISE_RE.sub("", text).strip(" -–—|")
        if cleaned == text:
            break
        text = cleaned
    artist = ""
    for sep in (" - ", " – ", " — "):
        if sep in text:
            left, right = (x.strip() for x in text.split(sep, 1))
            if left and right and len(left.split()) <= 6:
                artist, text = left, right
            break
    text = _NOISE_RE.sub("", text).strip(" -–—|") or (title or "").strip()
    if not artist and channel and channel.lower() not in ("various artists",) and not channel.lower().endswith(" - topic"):
        artist = channel
    elif not artist and channel.lower().endswith(" - topic"):
        artist = channel[: -len(" - topic")].strip()
    return artist, text


# ------------------------------------------------------------------ links
_VIDEO_ID = r"[A-Za-z0-9_-]{11}"


def parse_youtube_link(text: str) -> tuple[str, str] | None:
    """``(kind, url)`` for a YouTube link in ``text``: kind is "video",
    "playlist" or "channel"; the url is normalized. None if there is none."""
    m = re.search(r"https?://[^\s<>\"']+", text or "")
    raw = m.group(0) if m else (text or "").strip()
    if not raw:
        return None
    if not raw.startswith("http"):
        raw = "https://" + raw
    try:
        u = urlparse(raw)
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host == "youtu.be":
        vid = u.path.strip("/").split("/")[0]
        return ("video", f"https://www.youtube.com/watch?v={vid}") if re.fullmatch(_VIDEO_ID, vid) else None
    if host not in ("youtube.com", "m.youtube.com", "music.youtube.com"):
        return None
    q = parse_qs(u.query)
    path = u.path.rstrip("/")
    if path in ("/watch", "") and q.get("v") and re.fullmatch(_VIDEO_ID, q["v"][0]):
        return "video", f"https://www.youtube.com/watch?v={q['v'][0]}"
    m = re.match(rf"^/(?:shorts|live|embed)/({_VIDEO_ID})$", path)
    if m:
        return "video", f"https://www.youtube.com/watch?v={m.group(1)}"
    if path == "/playlist" and q.get("list"):
        return "playlist", f"https://www.youtube.com/playlist?list={q['list'][0]}"
    m = re.match(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)(/[^/]+)?$", path)
    if m:
        tab = m.group(2) or "/videos"
        if tab not in ("/videos", "/streams", "/shorts", "/playlists"):
            tab = "/videos"
        return "channel", f"https://www.youtube.com/{m.group(1)}{tab}"
    return None


def thumbnail_url(video_id: str, size: str = "hqdefault") -> str:
    return f"https://i.ytimg.com/vi/{video_id}/{size}.jpg"


def _fetch(url: str, timeout: float = 15, limit: int = 5_000_000) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(limit + 1)
        return data if 0 < len(data) <= limit else None
    except Exception:
        return None


def fetch_thumbnail(video_id: str) -> bytes | None:
    """The video's picture as JPEG (the large one when YouTube has it)."""
    for size in ("maxresdefault", "hqdefault"):
        data = _fetch(thumbnail_url(video_id, size))
        if data and data[:3] == b"\xff\xd8\xff" and len(data) > 2000:
            return data
    return None


def tag_file(path: str | Path, *, title: str = "", artist: str = "", year: str = "",
             cover: bytes | None = None, comment: str = "") -> bool:
    """Write a song name, artist, year and cover into a file we downloaded
    (MP3 or M4A). The listener's own files are never written."""
    try:
        import mutagen  # type: ignore
    except Exception:
        return False
    p = Path(path)
    try:
        if p.suffix.lower() == ".mp3":
            from mutagen.id3 import APIC, COMM, ID3, TDRC, TIT2, TPE1, ID3NoHeaderError  # type: ignore

            try:
                tags = ID3(p)
            except ID3NoHeaderError:
                tags = ID3()
            if title:
                tags.setall("TIT2", [TIT2(encoding=3, text=title)])
            if artist:
                tags.setall("TPE1", [TPE1(encoding=3, text=artist)])
            if year:
                tags.setall("TDRC", [TDRC(encoding=3, text=year)])
            if comment:
                tags.setall("COMM", [COMM(encoding=3, lang="heb", desc="", text=comment)])
            if cover and not tags.getall("APIC"):
                tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))
            tags.save(p)
            return True
        if p.suffix.lower() in (".m4a", ".mp4"):
            from mutagen.mp4 import MP4, MP4Cover  # type: ignore

            audio = MP4(p)
            if audio.tags is None:
                audio.add_tags()
            if title:
                audio.tags["©nam"] = [title]
            if artist:
                audio.tags["©ART"] = [artist]
            if year:
                audio.tags["©day"] = [year]
            if comment:
                audio.tags["©cmt"] = [comment]
            if cover and "covr" not in audio.tags:
                audio.tags["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()
            return True
    except Exception:
        return False
    return False


# ------------------------------------------------------------------ YouTube
_PCT_RE = re.compile(r"\[download\]\s+([\d.]+)%")
_SQUARE_COVER = ("ThumbnailsConvertor+ffmpeg_o:-c:v mjpeg -vf "
                 "crop=\"'if(gt(ih,iw),iw,ih)':'if(gt(iw,ih),ih,iw)'\"")


def _entry_result(e: dict, source: str = "youtube") -> SearchResult | None:
    vid = e.get("id") or ""
    if not re.fullmatch(_VIDEO_ID, vid):
        return None
    return SearchResult(
        source=source, id=vid, title=e.get("title") or vid,
        url=f"https://www.youtube.com/watch?v={vid}",
        uploader=e.get("uploader") or e.get("channel") or "",
        duration=e.get("duration"), upload_date=e.get("upload_date"),
        channel=e.get("channel") or e.get("uploader") or "",
        channel_id=e.get("channel_id") or "", channel_url=e.get("channel_url") or "",
        thumbnail=thumbnail_url(vid, "mqdefault"),
    )


class YouTubeSource:
    """YouTube through yt-dlp in its own process."""

    name = "youtube"

    def __init__(self, runner: YtDlpRunner | None = None):
        self.runner = runner or YtDlpRunner()

    def available(self) -> bool:
        return self.runner.available()

    def search_url(self, query: str) -> str:
        """The same search, for the listener's browser."""
        return f"https://www.youtube.com/results?search_query={quote_plus(query)}"

    @staticmethod
    def _failed(code: str, detail: str = "") -> FetchOutcome:
        return FetchOutcome(False, message_for(code, detail), code=code, blocked=code == "netfree")

    def search(self, query: str, *, limit: int = 5) -> FetchOutcome:
        if not self.available():
            return self._failed("not_installed")
        last = None
        for client in CLIENT_SETS[:2]:
            res = self.runner.run([f"ytsearch{int(limit)}:{query}", "--flat-playlist", "--dump-json"],
                                  timeout=30, client=client)
            items = [r for e in self.runner.json_lines(res) if (r := _entry_result(e))]
            if items:
                return FetchOutcome(True, "", result=items[0], results=items)
            last = res
            if res.code in ("netfree", "network", "certificate"):
                break  # another client will not change this
        if last is not None and last.ok:
            return FetchOutcome(False, "לא נמצאו תוצאות.", results=[], code="empty")
        code = last.code if last is not None else "other"
        if code == "extract":
            return FetchOutcome(False, "יוטיוב לא ענה לחיפוש כרגע. אפשר לנסות שוב, או לחפש בדפדפן ולהדביק כאן את הקישור.",
                                code="extract")
        return self._failed(code, last.err if last else "")

    def link_info(self, url: str, *, limit: int = 300) -> FetchOutcome:
        """What a link is: one song, or a list (playlist, channel) with its songs."""
        parsed = parse_youtube_link(url)
        if parsed is None:
            return self._failed("bad_link")
        if not self.available():
            return self._failed("not_installed")
        kind, url = parsed
        if kind == "video":
            res = self.runner.run([url, "--skip-download", "--no-playlist", "--flat-playlist", "--dump-single-json"],
                                  timeout=30)
            data = next(iter(self.runner.json_lines(res)), None)
            item = _entry_result(data) if data else None
            if not item:
                return self._failed(res.code or "other", res.err)
            artist, title = clean_video_title(item.title, item.channel)
            return FetchOutcome(True, "", result=item, results=[item], kind="video", title=title, artist=artist)
        res = self.runner.run([url, "--flat-playlist", "--dump-single-json", "--playlist-end", str(int(limit))],
                              timeout=90)
        data = next(iter(self.runner.json_lines(res)), None)
        if not data:
            return self._failed(res.code or "other", res.err)
        items = [r for e in data.get("entries") or [] if e and (r := _entry_result(e))]
        owner = data.get("channel") or data.get("uploader") or ""
        for it in items:
            it.channel = it.channel or owner
            it.uploader = it.uploader or owner
        title = (data.get("title") or owner or "").replace(" - Videos", "").strip()
        return FetchOutcome(True, "", results=items, kind="list", title=title, artist=owner)

    def download(self, result: SearchResult, dest_dir: str | Path, *, on_progress: ProgressHook | None = None,
                 cancel: threading.Event | None = None) -> FetchOutcome:
        if not self.available():
            return self._failed("not_installed")
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        mp3 = bool(self.runner.ffmpeg)
        args = [result.url, "-o", str(dest / "%(title)s [%(id)s].%(ext)s"),
                "--newline", "--progress", "--no-simulate", "--no-playlist", "--windows-filenames", "--no-mtime",
                "--retries", "3", "--concurrent-fragments", "4",
                "--print", "after_move:HMFILE:%(filepath)s",
                "--print", "after_move:HMINFO:%(.{id,title,uploader,channel,duration,upload_date})j"]
        if mp3:
            args += ["-f", "bestaudio/best", "-x", "--audio-format", "mp3", "--audio-quality", "192K",
                     "--embed-thumbnail", "--embed-metadata", "--convert-thumbnails", "jpg", "--ppa", _SQUARE_COVER]
        else:
            args += ["-f", "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio", "--fixup", "never"]

        state: dict = {"file": None, "info": {}, "pct": None}

        def on_line(line: str) -> None:
            if line.startswith("HMFILE:"):
                state["file"] = line[7:].strip()
            elif line.startswith("HMINFO:"):
                try:
                    state["info"] = json.loads(line[7:])
                except ValueError:
                    pass
            else:
                m = _PCT_RE.search(line)
                if m and on_progress:
                    pct = float(m.group(1))
                    on_progress({"status": "downloading", "percent": pct})
                    if pct >= 100 and mp3:
                        on_progress({"status": "postprocessing"})

        last = None
        attempts = list(CLIENT_SETS)
        tried_update = False
        while attempts:
            client = attempts.pop(0)
            res = self.runner.stream(args, on_line, stall=120, client=client, cancel=cancel)
            if state["file"] and Path(state["file"]).exists():
                last = None
                break
            last = res
            if res.code != "extract":
                break  # blocked, unavailable, no network …: another client will not help
            if not attempts and not tried_update and not self.runner.updated:
                tried_update = True  # YouTube changed: get the newest engine, try once more
                if self.runner.update_engine().get("updated"):
                    attempts = [None]
        if last is not None or not state["file"]:
            code = last.code if last is not None else "other"
            if code == "netfree":
                return FetchOutcome(False, "הסרטון הזה חסום ברשת שלך (נטפרי או סינון דומה), ולכן לא ירד.",
                                    code="netfree", blocked=True)
            return self._failed(code, last.err if last is not None else "")

        info = state["info"] or {}
        path = Path(state["file"])
        enriched = SearchResult(
            source=self.name, id=info.get("id") or result.id, title=info.get("title") or result.title,
            url=result.url, uploader=info.get("uploader") or info.get("channel") or result.uploader,
            duration=info.get("duration") or result.duration,
            upload_date=info.get("upload_date") or result.upload_date,
            channel=info.get("channel") or result.channel,
        )
        artist, title = clean_video_title(enriched.title, enriched.channel or enriched.uploader)
        cover = None if mp3 else fetch_thumbnail(enriched.id)
        year = (enriched.upload_date or "")[:4]
        tag_file(path, title=title, artist=artist, year=year, cover=cover, comment=result.url)
        if on_progress:
            on_progress({"status": "finished"})
        return FetchOutcome(True, "ההורדה הושלמה.", path=str(path), result=enriched, title=title,
                            artist=artist, cover=cover)


class OnlineFetcher:
    """Facade over the currently-selected source plugin."""

    def __init__(self, source: SourcePlugin | None = None, runner: YtDlpRunner | None = None):
        self.source: SourcePlugin = source or YouTubeSource(runner)

    def available(self) -> bool:
        return self.source.available()

    def search(self, query: str, *, limit: int = 5) -> FetchOutcome:
        return self.source.search(query, limit=limit)

    def search_url(self, query: str) -> str:
        return self.source.search_url(query)

    def link_info(self, url: str, *, limit: int = 300) -> FetchOutcome:
        fn = getattr(self.source, "link_info", None)
        if fn is None:
            return FetchOutcome(False, MESSAGES["bad_link"], code="bad_link")
        return fn(url, limit=limit)

    def download(
        self, result: SearchResult, dest_dir: str | Path, *, on_progress: ProgressHook | None = None,
        cancel: threading.Event | None = None,
    ) -> FetchOutcome:
        if "cancel" in inspect.signature(self.source.download).parameters:
            return self.source.download(result, dest_dir, on_progress=on_progress, cancel=cancel)
        return self.source.download(result, dest_dir, on_progress=on_progress)

    @property
    def runner(self) -> YtDlpRunner | None:
        return getattr(self.source, "runner", None)


def find_ffmpeg(bundled: str | Path | None = None) -> str:
    """ffmpeg.exe shipped with the app, else one on the PATH, else ""."""
    if bundled:
        p = Path(bundled)
        exe = p / ("ffmpeg.exe" if (p / "ffmpeg.exe").exists() else "ffmpeg") if p.is_dir() else p
        if exe.exists():
            return str(exe)
    return shutil.which("ffmpeg") or ""
