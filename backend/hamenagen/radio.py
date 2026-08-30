"""Live radio channels (spec §13).

Provides a managed list of online radio channels for the "רדיו" tab. The
current managed source is **קול חי מיוזיק** (Kol Chai Music): its live page
embeds a ``var ServerModel = {...}`` blob whose ``live`` array lists every
channel with a streamable URL, current title and artwork. We fetch and parse
that when online, cache it to disk, and fall back to a small bundled seed when
offline — matching the spec's "managed list + update" default.

Only the standard library is used (``urllib``), so nothing here breaks the
offline-first guarantee: a failed fetch simply yields the cache or the seed.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path

DEFAULT_SOURCE_URL = "https://kcm.fm/Live/"
DEFAULT_PICS_URL = "https://kcm.fm/upload/pictures/"

_SERVER_MODEL_RE = re.compile(r"var\s+ServerModel\s*=\s*(\{.*?\})\s*;", re.S)


@dataclass
class Station:
    id: int
    title: str
    url: str
    now_playing: str = ""
    description: str = ""
    image_url: str = ""
    category: int = 0
    order: int = 0
    editor: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _image_url(image_id: int, pics_url: str) -> str:
    if not image_id:
        return ""
    # Kol Chai stores pictures under /upload/pictures/{id//1000}/{id}.jpg
    folder = image_id // 1000
    return f"{pics_url}{folder}/{image_id}.jpg"


def parse_server_model(html: str) -> dict:
    """Extract and parse the embedded ``ServerModel`` JSON from the live page."""
    m = _SERVER_MODEL_RE.search(html)
    if not m:
        raise ValueError("ServerModel not found in page")
    return json.loads(m.group(1))


def stations_from_model(model: dict, *, pics_url: str = DEFAULT_PICS_URL) -> list[Station]:
    stations: list[Station] = []
    for s in model.get("live", []):
        if not s or not s.get("url") or not s.get("visible", 1):
            continue
        stations.append(
            Station(
                id=int(s.get("id", 0)),
                title=(s.get("title") or "").strip() or f"ערוץ {s.get('id')}",
                url=s["url"],
                now_playing=(s.get("playing") or "").strip(),
                description=(s.get("short") or "").strip(),
                image_url=_image_url(int(s.get("image") or 0), pics_url),
                category=int(s.get("cat") or 0),
                order=int(s.get("order") or 0),
                editor=(s.get("name") or "").strip(),
            )
        )
    # The site surfaces higher "order" first, then a stable title tie-break.
    stations.sort(key=lambda st: (-st.order, st.title))
    return stations


def fetch_stations(url: str = DEFAULT_SOURCE_URL, *, timeout: float = 8.0) -> list[Station]:
    """Fetch the live page and return its channels. Raises on network error."""
    req = urllib.request.Request(url, headers={"User-Agent": "hamenagen/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed managed host
        html = resp.read().decode("utf-8", errors="replace")
    return stations_from_model(parse_server_model(html))


class RadioProvider:
    def __init__(
        self,
        source_url: str = DEFAULT_SOURCE_URL,
        *,
        cache_path: str | Path | None = None,
        seed_path: str | Path | None = None,
    ):
        self.source_url = source_url or DEFAULT_SOURCE_URL
        self.cache_path = Path(cache_path) if cache_path else None
        self.seed_path = (
            Path(seed_path)
            if seed_path
            else Path(__file__).with_name("data") / "radio_seed.json"
        )

    def _load_json(self, path: Path | None) -> list[Station]:
        if not path or not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return [Station(**s) for s in raw]
        except Exception:
            return []

    def _save_cache(self, stations: list[Station]) -> None:
        if not self.cache_path:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps([s.to_dict() for s in stations], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def list(self, *, refresh: bool = True) -> dict:
        """Return the channel list with an ``online`` flag and its source.

        Tries the live source first (when ``refresh``); on any failure falls
        back to the on-disk cache, then to the bundled seed.
        """
        if refresh:
            try:
                stations = fetch_stations(self.source_url)
                if stations:
                    self._save_cache(stations)
                    return {
                        "online": True,
                        "source": self.source_url,
                        "count": len(stations),
                        "stations": [s.to_dict() for s in stations],
                    }
            except Exception as exc:  # offline / unreachable / parse error
                error = str(exc)
            else:
                error = "no stations returned"
        else:
            error = "refresh disabled"

        cached = self._load_json(self.cache_path)
        if cached:
            return {"online": False, "source": "cache", "error": error,
                    "count": len(cached), "stations": [s.to_dict() for s in cached]}
        seed = self._load_json(self.seed_path)
        return {"online": False, "source": "seed", "error": error,
                "count": len(seed), "stations": [s.to_dict() for s in seed]}
