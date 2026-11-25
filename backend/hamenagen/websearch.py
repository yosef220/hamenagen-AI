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


# 1.7: a singer's channel, for networks that block YouTube's own search.
_CHANNEL = re.compile(r"(?:https?://)?(?:www\.|m\.)?youtube\.com/(@[\w.\-]+|channel/UC[\w-]{22}|c/[\w.\-]+|user/[\w.\-]+)",
                      re.UNICODE)
_NOT_A_CHANNEL = {"@youtube", "c/youtube", "user/youtube"}


_JS_ESCAPE = re.compile(r"\\u00([0-9a-fA-F]{2})|\\x([0-9a-fA-F]{2})")
# Bing hands its results out through its own address: ``…/ck/a?…&u=a1<the link in base64>``.
_BING_U = re.compile(r"[?&;]u=a1([A-Za-z0-9_\-]+)")


def decode_page(page: str) -> str:
    """A results page with the links it hides made plain (1.7.4): Google keeps
    its results in scripts (``\\u003d`` for ``=``), DuckDuckGo behind its own
    address (``uddg=https%3A%2F%2F…``), Bing in base64. What a browser reads
    when it follows a result is what is looked for in the text returned."""
    import base64

    text = html_mod.unescape(page or "")
    text = _JS_ESCAPE.sub(lambda m: chr(int(m.group(1) or m.group(2), 16)), text).replace("\\/", "/")
    extra = []
    for m in _BING_U.finditer(text):
        raw = m.group(1)
        try:
            extra.append(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "replace"))
        except (ValueError, TypeError):
            continue
    text = urllib.parse.unquote(urllib.parse.unquote(text))
    return "\n".join([text, *extra])


def extract_video_ids(page: str, count: int = 60) -> list[str]:
    """The YouTube videos a results page points to, in page order, each once."""
    out: list[str] = []
    for m in _VIDEO.finditer(decode_page(page)):
        if m.group(1) not in out:
            out.append(m.group(1))
            if len(out) >= count:
                break
    return out


def extract_channels(page: str, count: int = 5) -> list[str]:
    """Links to YouTube channels in a results page, in page order, each once
    (``https://www.youtube.com/@name`` or ``…/channel/UC…``)."""
    text = decode_page(page)
    out: list[str] = []
    for m in _CHANNEL.finditer(text):
        path = m.group(1).rstrip(".")
        if path.lower() in _NOT_A_CHANNEL:
            continue
        url = f"https://www.youtube.com/{path}"
        if url not in out:
            out.append(url)
        if len(out) >= count:
            break
    return out


def find_channels(name: str, count: int = 3, *, get=None) -> list[str]:
    """Channel links for a singer's name from the first engine that has any."""
    get = get or http_get
    q = urllib.parse.quote_plus(f"{name.strip()} ערוץ youtube")
    engines = (
        f"https://www.google.com/search?q={q}&num=10&hl=iw",
        f"https://www.bing.com/search?q={q}&count=10",
        f"https://html.duckduckgo.com/html/?q={q}",
    )
    for url in engines:
        try:
            found = extract_channels(get(url), count)
        except Exception:  # noqa: BLE001 - blocked, offline, a CAPTCHA: the next engine
            continue
        if found:
            return found
    return []
