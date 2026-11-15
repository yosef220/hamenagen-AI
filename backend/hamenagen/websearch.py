"""YouTube songs found through a web search engine (1.5.8), for networks that block YouTube's own search.

Behind a filter such as NetFree the program cannot search YouTube (``ytsearch`` is refused, or its answer is
cut), while the search engines still answer. This is the way the download-from-YouTube program of the same
author finds songs there: ask Google (then Bing, then DuckDuckGo) for the words and "youtube", and read the
YouTube links out of the page, in the order the engine gave them — the order the listener sees in a browser.
Nothing here logs in or keeps anything; a page is read once and only the links and titles are taken.

Python verifies HTTPS with the operating system's store (see ``network``), so a filter's certificate is
trusted the way it is for the rest of the program; the check is never turned off.
"""

from __future__ import annotations

import gzip
import html as html_mod
import re
import urllib.parse
import urllib.request

from . import network

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/122.0 Safari/537.36")

_VIDEO = re.compile(
    r"(?:youtube\.com/watch\?v%3D|youtube\.com%2Fwatch%3Fv%3D|youtube\.com/watch\?v=|youtu\.be/|/watch%3Fv%3D)"
    r"([A-Za-z0-9_-]{11})"
)
_H3 = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S)
_TAG = re.compile(r"<[^>]+>")


def http_get(url: str, timeout: float = 8) -> str:
    network.use_system_trust()
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept-Language": "he,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            try:
                data = gzip.decompress(data)
            except Exception:  # noqa: BLE001 - already plain
                pass
        return data.decode("utf-8", "replace")


def _clean(text: str) -> str:
    return " ".join(html_mod.unescape(_TAG.sub("", text or "")).split())


def extract_videos(page: str, count: int) -> list[dict]:
    """``[{"id", "title"}]`` for the YouTube videos linked from a results page, in page order, each once.
    A title is the heading (``<h3>``) nearest to the link; none near — an empty title."""
    seen: set[str] = set()
    found: list[tuple[int, str]] = []
    for m in _VIDEO.finditer(page):
        vid = m.group(1)
        if vid not in seen:
            seen.add(vid)
            found.append((m.start(), vid))
    headings = [(m.start(), _clean(m.group(1))) for m in _H3.finditer(page)]
    out = []
    for pos, vid in found[:count]:
        title, best = "", 1 << 30
        for hpos, text in headings:
            if text and abs(hpos - pos) < best:
                best, title = abs(hpos - pos), text
        out.append({"id": vid, "title": title})
    return out


def search_youtube(query: str, count: int = 8, *, get=None) -> list[dict]:
    """YouTube videos for ``query`` from the first engine that has any: ``[{"id", "title"}]``."""
    get = get or http_get
    q = urllib.parse.quote_plus(f"{query.strip()} youtube")
    engines = (
        f"https://www.google.com/search?q={q}&num={count + 5}&hl=iw",
        f"https://www.bing.com/search?q={q}&count={count + 5}",
        f"https://html.duckduckgo.com/html/?q={q}",
    )
    for url in engines:
        try:
            found = extract_videos(get(url), count)
        except Exception:  # noqa: BLE001 - blocked, offline, a CAPTCHA: the next engine
            continue
        if found:
            return found
    return []
