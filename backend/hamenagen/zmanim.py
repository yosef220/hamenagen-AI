"""Shabbat and festival times for the Shabbat mode.

Before candle lighting the music fades out and stops, and a "שבת שלום"
screen stays up until the end of Shabbat (or of the festival). For that the
player needs, for the listener's city, the sunset before each day of rest and
nightfall at its end.

Where the times come from, in order:

1. **זמנים טובא** (zmanim.ketertorah.co.il) — the calendar its own web page
   reads, for the city's coordinates.
2. **Hebcal** — the zmanim API, when the first is not reachable.
3. **A calculation on this computer** (NOAA solar position) — so the mode
   works with no internet at all. Sea-level sunset, like "שקיעה במישור".

Fetched times are cached in ``zmanim.json`` in the data folder for seven weeks
ahead, so the network is touched about once a week. Which days are days of
rest is decided here, offline, from the Hebrew calendar (Israel: one day of
Yom Tov, two of Rosh Hashana).

Candle lighting is the sunset minus the city's custom (40 minutes in
Jerusalem, 30 in Haifa, 18 elsewhere — Hebcal's defaults); the end is
nightfall with the sun 8.5° below the horizon, or Rabbeinu Tam (72 minutes)
if the listener chooses.
"""

from __future__ import annotations

import http.cookiejar
import json
import math
import os
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import hebrew_calendar as hc

KETER_URL = "https://zmanim.ketertorah.co.il/api.php"
HEBCAL_URL = "https://www.hebcal.com/zmanim"
USER_AGENT = "music-player-shabbat-mode/1.3"
TZ_NAME = "Asia/Jerusalem"

# zmanim.ketertorah.co.il time ids: sea-level sunset, nightfall 8.5°, Rabbeinu Tam.
KETER_SUNSET, KETER_TZEIT, KETER_RT = 290, 61, 57

#: City → (latitude, longitude, minutes of candle lighting before sunset).
CITIES: dict[str, tuple[float, float, int]] = {
    "ירושלים": (31.778, 35.235, 40),
    "בני ברק": (32.081, 34.834, 18),
    "תל אביב-יפו": (32.085, 34.782, 18),
    "חיפה": (32.794, 34.990, 30),
    "באר שבע": (31.252, 34.791, 18),
    "פתח תקווה": (32.084, 34.888, 18),
    "בית שמש": (31.747, 34.988, 18),
    "מודיעין עילית": (31.933, 35.044, 18),
    "ביתר עילית": (31.697, 35.116, 40),
    "אלעד": (32.052, 34.951, 18),
    "אשדוד": (31.804, 34.655, 18),
    "נתניה": (32.329, 34.857, 18),
    "ראשון לציון": (31.964, 34.804, 18),
    "חולון": (32.011, 34.774, 18),
    "בת ים": (32.023, 34.751, 18),
    "רמת גן": (32.068, 34.824, 18),
    "גבעתיים": (32.072, 34.811, 18),
    "רחובות": (31.894, 34.811, 18),
    "אשקלון": (31.669, 34.571, 18),
    "הרצליה": (32.166, 34.844, 18),
    "כפר סבא": (32.175, 34.907, 18),
    "רעננה": (32.184, 34.871, 18),
    "הוד השרון": (32.150, 34.889, 18),
    "רמלה": (31.929, 34.873, 18),
    "לוד": (31.951, 34.889, 18),
    "יבנה": (31.877, 34.739, 18),
    "מודיעין": (31.898, 35.010, 18),
    "מעלה אדומים": (31.777, 35.298, 40),
    "גבעת זאב": (31.861, 35.169, 40),
    "קרית ארבע וחברון": (31.531, 35.122, 18),
    "אריאל": (32.106, 35.187, 18),
    "עמנואל": (32.161, 35.135, 18),
    "צפת": (32.965, 35.496, 18),
    "טבריה": (32.795, 35.531, 18),
    "נוף הגליל": (32.710, 35.320, 18),
    "עפולה": (32.608, 35.289, 18),
    "כרמיאל": (32.919, 35.296, 18),
    "עכו": (32.928, 35.076, 18),
    "נהריה": (33.006, 35.095, 18),
    "קרית שמונה": (33.207, 35.570, 18),
    "קצרין": (32.993, 35.692, 18),
    "בית שאן": (32.497, 35.497, 18),
    "זכרון יעקב": (32.571, 34.952, 30),
    "חדרה": (32.434, 34.919, 18),
    "קרית אתא": (32.809, 35.106, 18),
    "רכסים": (32.749, 35.097, 18),
    "קרית גת": (31.610, 34.764, 18),
    "קרית מלאכי": (31.731, 34.746, 18),
    "נתיבות": (31.421, 34.588, 18),
    "אופקים": (31.314, 34.620, 18),
    "שדרות": (31.525, 34.596, 18),
    "דימונה": (31.067, 35.033, 18),
    "ערד": (31.259, 35.213, 18),
    "אילת": (29.558, 34.952, 18),
}
DEFAULT_CITY = "ירושלים"
HAVDALAH_CHOICES = ("tzeit", "rt")

# Days of rest in Israel, by Hebrew (month, day); Nisan = 1, Tishrei = 7.
_FESTIVALS: dict[tuple[int, int], tuple[str, str, str]] = {
    (7, 1): ("rosh_hashana", "ראש השנה", "שנה טובה"),
    (7, 2): ("rosh_hashana", "ראש השנה", "שנה טובה"),
    (7, 10): ("yom_kippur", "יום כיפור", "גמר חתימה טובה"),
    (7, 15): ("sukkot", "סוכות", "חג שמח"),
    (7, 22): ("shemini_atzeret", "שמיני עצרת ושמחת תורה", "חג שמח"),
    (1, 15): ("pesach", "פסח", "חג כשר ושמח"),
    (1, 21): ("pesach", "שביעי של פסח", "חג שמח"),
    (3, 6): ("shavuot", "שבועות", "חג שמח"),
}

FETCH_DAYS = 48          # how far ahead a fetch covers (7 weeks)
STALE_AFTER = 7 * 86400  # refetch when the cache is older than this…
MIN_AHEAD = 21           # …or covers fewer days ahead than this


# --------------------------------------------------------------------------
# Israel time
# --------------------------------------------------------------------------

def _israel_zone():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(TZ_NAME)
    except Exception:   # Windows without the tzdata package
        return None


_ZONE = _israel_zone()


def _last_sunday(year: int, month: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def israel_offset(moment: datetime) -> timedelta:
    """UTC offset of Israel at ``moment`` (aware). Daylight time runs from the
    Friday before the last Sunday of March to the last Sunday of October (the
    rule since 2013) when the time zone database is not available."""
    if _ZONE is not None:
        return moment.astimezone(_ZONE).utcoffset() or timedelta(hours=2)
    utc = moment.astimezone(timezone.utc).replace(tzinfo=None)
    # 02:00 standard time on that Friday is 00:00 UTC; 02:00 daylight time on
    # the last Sunday of October is 23:00 UTC on the Saturday.
    start = datetime.combine(_last_sunday(utc.year, 3) - timedelta(days=2), datetime.min.time())
    end = datetime.combine(_last_sunday(utc.year, 10), datetime.min.time()) - timedelta(hours=1)
    return timedelta(hours=3) if start <= utc < end else timedelta(hours=2)


def to_israel(moment: datetime) -> datetime:
    return moment.astimezone(timezone(israel_offset(moment)))


def israel_local(day: date, clock: str) -> datetime:
    """``HH:MM[:SS]`` in Israel on ``day`` → an aware UTC datetime."""
    parts = [int(p) for p in clock.split(":")]
    h, m, s = (parts + [0, 0, 0])[:3]
    naive = datetime(day.year, day.month, day.day, h, m, s)
    guess = naive.replace(tzinfo=timezone.utc) - timedelta(hours=2)
    offset = israel_offset(guess)
    return (naive - offset).replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# The sun, calculated here (NOAA solar position)
# --------------------------------------------------------------------------

def _sun_declination_eot(jd: float) -> tuple[float, float]:
    t = (jd - 2451545.0) / 36525.0
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    mr = math.radians(m)
    c = (math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(2 * mr) * (0.019993 - 0.000101 * t) + math.sin(3 * mr) * 0.000289)
    omega = math.radians(125.04 - 1934.136 * t)
    lam = math.radians(l0 + c - 0.00569 - 0.00478 * math.sin(omega))
    eps0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    eps = math.radians(eps0 + 0.00256 * math.cos(omega))
    decl = math.asin(math.sin(eps) * math.sin(lam))
    y = math.tan(eps / 2) ** 2
    l0r = math.radians(l0)
    eot = 4 * math.degrees(y * math.sin(2 * l0r) - 2 * e * math.sin(mr) + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
                           - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * mr))
    return decl, eot


def sun_below(day: date, lat: float, lng: float, degrees: float) -> datetime | None:
    """When the sun goes ``degrees`` below the horizon on the evening of ``day``
    (0.833 = sunset with refraction; 8.5 = nightfall), as aware UTC."""
    jd0 = date.toordinal(day) + 1721424.5
    minutes = 720.0 - 4 * lng   # first guess: solar noon
    for _ in range(3):
        decl, eot = _sun_declination_eot(jd0 + minutes / 1440.0)
        latr = math.radians(lat)
        cos_h = (math.cos(math.radians(90 + degrees)) / (math.cos(latr) * math.cos(decl))
                 - math.tan(latr) * math.tan(decl))
        if not -1 <= cos_h <= 1:
            return None
        ha = math.degrees(math.acos(cos_h))
        minutes = 720.0 - 4 * lng - eot + 4 * ha
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(minutes=minutes)


# --------------------------------------------------------------------------
# Day times from each source
# --------------------------------------------------------------------------

@dataclass
class DayTimes:
    sunset: datetime
    tzeit: datetime
    rt: datetime
    source: str

    def to_json(self) -> dict:
        return {"sunset": self.sunset.isoformat(), "tzeit": self.tzeit.isoformat(),
                "rt": self.rt.isoformat(), "source": self.source}

    @classmethod
    def from_json(cls, d: dict) -> "DayTimes":
        return cls(datetime.fromisoformat(d["sunset"]), datetime.fromisoformat(d["tzeit"]),
                   datetime.fromisoformat(d["rt"]), d.get("source", "local"))


def local_times(lat: float, lng: float, days: list[date]) -> dict[date, DayTimes]:
    out = {}
    for d in days:
        sunset = sun_below(d, lat, lng, 0.833)
        tzeit = sun_below(d, lat, lng, 8.5)
        if sunset and tzeit:
            out[d] = DayTimes(sunset, tzeit, sunset + timedelta(minutes=72), "local")
    return out


def _request(url: str, *, headers: dict | None = None, opener=None, timeout: float = 15) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                               **(headers or {})})
    open_ = opener.open if opener else urllib.request.urlopen
    with open_(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_ketertorah(lat: float, lng: float, start: date, end: date) -> dict[date, DayTimes]:
    """Times from זמנים טובא: the week calendar its web page shows (the month
    view carries only sunrise and sunset; a week carries every time)."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    init = _request(f"{KETER_URL}?action=init", opener=opener)
    token = init.get("csrf") or ""
    out: dict[date, DayTimes] = {}
    anchor = start - timedelta(days=(start.weekday() + 1) % 7)   # the Sunday of start's week
    while anchor <= end:
        query = urllib.parse.urlencode({"action": "calendar", "mode": "week", "anchor": anchor.isoformat(),
                                        "lat": f"{lat:.4f}", "lng": f"{lng:.4f}", "tz": TZ_NAME, "country": "IL"})
        data = _request(f"{KETER_URL}?{query}", headers={"X-Zmanim-Csrf": token}, opener=opener)
        if not data.get("ok"):
            raise RuntimeError(data.get("message") or "zmanim: no data")
        for day in data.get("days") or []:
            try:
                d = date.fromisoformat(day["date"])
            except Exception:
                continue
            times = {t.get("id"): t.get("time") for t in day.get("times") or [] if t.get("time")}
            if KETER_SUNSET in times and KETER_TZEIT in times:
                sunset = israel_local(d, times[KETER_SUNSET])
                rt = israel_local(d, times[KETER_RT]) if KETER_RT in times else sunset + timedelta(minutes=72)
                out[d] = DayTimes(sunset, israel_local(d, times[KETER_TZEIT]), rt, "ketertorah")
        anchor += timedelta(days=7)
        time.sleep(0.2)
    return {d: v for d, v in out.items() if start <= d <= end}


def fetch_hebcal(lat: float, lng: float, start: date, end: date) -> dict[date, DayTimes]:
    query = urllib.parse.urlencode({"cfg": "json", "latitude": f"{lat:.4f}", "longitude": f"{lng:.4f}",
                                    "tzid": TZ_NAME, "start": start.isoformat(), "end": end.isoformat()})
    data = _request(f"{HEBCAL_URL}?{query}")
    times = data.get("times") or {}
    sunsets = times.get("seaLevelSunset") or times.get("sunset") or {}
    tzeits = times.get("tzeit85deg") or {}
    rts = times.get("tzeit72min") or {}
    out = {}
    for key, value in sunsets.items():
        if key in tzeits:
            d = date.fromisoformat(key)
            sunset = datetime.fromisoformat(value)
            rt = datetime.fromisoformat(rts[key]) if key in rts else sunset + timedelta(minutes=72)
            out[d] = DayTimes(sunset, datetime.fromisoformat(tzeits[key]), rt, "hebcal")
    return out


SOURCE_LABELS = {"ketertorah": "זמנים טובא (כתר תורה)", "hebcal": "Hebcal", "local": "חישוב במחשב"}


# --------------------------------------------------------------------------
# Days of rest and their windows
# --------------------------------------------------------------------------

def rest_of(day: date) -> tuple[str, str, str] | None:
    """(key, title, greeting) when ``day`` is a day of rest in Israel."""
    h = hc.from_gregorian(day)
    festival = _FESTIVALS.get((h.month, h.day))
    if festival:
        return festival
    if day.weekday() == 5:
        return ("shabbat", "שבת", "שבת שלום")
    return None


@dataclass
class RestWindow:
    days: list[date]
    start: datetime      # candle lighting
    end: datetime        # nightfall at the end
    stop_at: datetime    # when the music stops
    title: str
    greeting: str
    detail: str
    kind: str            # "shabbat" | "festival" | "both"
    source: str

    def to_dict(self) -> dict:
        def clock(m: datetime) -> str:
            return to_israel(m).strftime("%H:%M")
        eve = self.days[0] - timedelta(days=1)
        return {
            "start": self.start.isoformat(), "end": self.end.isoformat(), "stop_at": self.stop_at.isoformat(),
            "start_ms": int(self.start.timestamp() * 1000), "end_ms": int(self.end.timestamp() * 1000),
            "stop_ms": int(self.stop_at.timestamp() * 1000),
            "candle_text": clock(self.start), "end_text": clock(self.end), "stop_text": clock(self.stop_at),
            "eve_weekday": hc.weekday_name(eve), "end_weekday": hc.weekday_name(self.days[-1]),
            "days": [d.isoformat() for d in self.days],
            "title": self.title, "greeting": self.greeting, "detail": self.detail, "kind": self.kind,
            "end_label": ("צאת השבת" if self.kind == "shabbat"
                          else "צאת השבת והחג" if self.days[-1].weekday() == 5 else "צאת החג"),
            "hebrew": hc.from_gregorian(self.days[0]).text,
            "source": self.source, "source_label": SOURCE_LABELS.get(self.source, self.source),
        }


def _describe(days: list[date]) -> tuple[str, str, str, str]:
    """(title, greeting, detail, kind) for a run of days of rest."""
    rests = [rest_of(d) for d in days]
    festivals = [r for r in rests if r and r[0] != "shabbat"]
    has_shabbat = any(d.weekday() == 5 for d in days)
    if not festivals:
        parasha = hc.parasha_of_shabbat(days[-1])
        return "שבת", "שבת שלום", f"פרשת {parasha}" if parasha else "", "shabbat"
    key, title, greeting = festivals[0]
    if has_shabbat:
        greeting = "שבת שלום וחג שמח" if greeting == "חג שמח" else f"שבת שלום · {greeting}"
        return title, greeting, "שבת וחג", "both"
    return title, greeting, "", "festival"


class ZmanimService:
    """The windows of rest for the listener's city, from the best source."""

    def __init__(self, cache_path: str | Path, *, sources: list[tuple[str, Callable]] | None = None,
                 now: Callable[[], datetime] | None = None):
        self.cache_path = Path(cache_path)
        self.sources = sources if sources is not None else [("ketertorah", fetch_ketertorah),
                                                            ("hebcal", fetch_hebcal)]
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.city = DEFAULT_CITY
        self.candle_minutes = 0
        self.stop_before = 10
        self.havdalah = "tzeit"
        self._lock = threading.Lock()
        self._refreshing = False
        self.last_error = ""
        self._cache = self._load()

    # ----------------------------------------------------------- settings
    def configure(self, *, city: str = "", candle_minutes: int = 0, stop_before: int = 10,
                  havdalah: str = "tzeit") -> None:
        self.city = city if city in CITIES else DEFAULT_CITY
        self.candle_minutes = int(candle_minutes or 0)
        self.stop_before = max(0, min(int(stop_before or 0), 120))
        self.havdalah = havdalah if havdalah in HAVDALAH_CHOICES else "tzeit"

    @property
    def place(self) -> tuple[float, float, int]:
        return CITIES[self.city]

    def candle_offset(self) -> int:
        return self.candle_minutes if self.candle_minutes > 0 else self.place[2]

    # -------------------------------------------------------------- cache
    def _load(self) -> dict:
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.cache_path)
        except Exception:
            pass

    def _cached_days(self) -> dict[date, DayTimes]:
        lat, lng, _ = self.place
        c = self._cache
        if not c or abs(c.get("lat", 0) - lat) > 1e-3 or abs(c.get("lng", 0) - lng) > 1e-3:
            return {}
        out = {}
        for key, value in (c.get("days") or {}).items():
            try:
                out[date.fromisoformat(key)] = DayTimes.from_json(value)
            except Exception:
                continue
        return out

    def needs_refresh(self) -> bool:
        cached = self._cached_days()
        today = to_israel(self.now()).date()
        if not cached or max(cached) < today + timedelta(days=MIN_AHEAD):
            return True
        return time.time() - float(self._cache.get("fetched_at", 0)) > STALE_AFTER

    def refresh(self) -> str:
        """Fetch seven weeks ahead from the first source that answers.
        Returns the source used ("" when none did; the calculation stands in)."""
        lat, lng, _ = self.place
        today = to_israel(self.now()).date()
        start, end = today - timedelta(days=1), today + timedelta(days=FETCH_DAYS)
        errors = []
        for name, fetch in self.sources:
            try:
                days = fetch(lat, lng, start, end)
            except Exception as err:   # blocked, offline, changed — try the next one
                errors.append(f"{name}: {err}")
                continue
            if len(days) >= 7:
                with self._lock:
                    self._cache = {"lat": lat, "lng": lng, "city": self.city, "source": name,
                                   "fetched_at": time.time(),
                                   "days": {d.isoformat(): v.to_json() for d, v in sorted(days.items())}}
                    self._save()
                self.last_error = ""
                return name
            errors.append(f"{name}: {len(days)} days")
        self.last_error = "; ".join(errors)
        return ""

    def refresh_in_background(self) -> None:
        if self._refreshing or not self.needs_refresh():
            return
        self._refreshing = True

        def run():
            try:
                self.refresh()
            finally:
                self._refreshing = False
        threading.Thread(target=run, name="zmanim", daemon=True).start()

    # ------------------------------------------------------------ windows
    def day_times(self, days: list[date]) -> dict[date, DayTimes]:
        cached = self._cached_days()
        missing = [d for d in days if d not in cached]
        if missing:
            lat, lng, _ = self.place
            cached.update(local_times(lat, lng, missing))
        return cached

    def windows(self, start: date, horizon: int = 30) -> list[RestWindow]:
        days = [start + timedelta(days=i) for i in range(-2, horizon + 1)]
        runs: list[list[date]] = []
        for d in days:
            if rest_of(d):
                if runs and runs[-1][-1] == d - timedelta(days=1):
                    runs[-1].append(d)
                else:
                    runs.append([d])
        needed = sorted({d for run in runs for d in (run[0] - timedelta(days=1), run[-1])})
        times = self.day_times(needed)
        out = []
        for run in runs:
            eve, last = run[0] - timedelta(days=1), run[-1]
            if eve not in times or last not in times:
                continue
            start_at = times[eve].sunset - timedelta(minutes=self.candle_offset())
            end_at = times[last].rt if self.havdalah == "rt" else times[last].tzeit
            title, greeting, detail, kind = _describe(run)
            out.append(RestWindow(run, start_at, end_at, start_at - timedelta(minutes=self.stop_before),
                                  title, greeting, detail, kind, times[eve].source))
        return out

    def status(self, *, enabled: bool = True) -> dict:
        now = self.now()
        today = to_israel(now).date()
        wins = [w for w in self.windows(today) if w.end > now]
        current = next((w for w in wins if w.stop_at <= now < w.end), None)
        upcoming = next((w for w in wins if w.stop_at > now), None)
        cached = self._cache if self._cached_days() else {}
        return {
            "enabled": enabled,
            "city": self.city,
            "candle_minutes": self.candle_offset(),
            "city_minutes": self.place[2],
            "stop_before": self.stop_before,
            "havdalah": self.havdalah,
            "now_ms": int(now.timestamp() * 1000),
            "current": current.to_dict() if current else None,
            "next": upcoming.to_dict() if upcoming else None,
            "source": cached.get("source", "local") if cached else "local",
            "source_label": SOURCE_LABELS.get(cached.get("source", "local") if cached else "local"),
            "fetched_at": cached.get("fetched_at") if cached else None,
            "cities": list(CITIES),
        }
