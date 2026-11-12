"""Shabbat mode: the days of rest, their times and where the times come from."""

from datetime import date, datetime, timedelta, timezone

import pytest

from hamenagen import zmanim as z


def at(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def test_local_sunset_and_nightfall_match_the_site():
    # זמנים טובא, Jerusalem, Friday 13.11.2026: sunset 16:40:53, nightfall 8.5° 17:18:54.
    lat, lng, _ = z.CITIES["ירושלים"]
    t = z.local_times(lat, lng, [date(2026, 11, 13)])[date(2026, 11, 13)]
    assert abs((t.sunset - z.israel_local(date(2026, 11, 13), "16:40:53")).total_seconds()) < 60
    assert abs((t.tzeit - z.israel_local(date(2026, 11, 13), "17:18:54")).total_seconds()) < 60


def test_israel_daylight_rule_without_the_time_zone_database(monkeypatch):
    monkeypatch.setattr(z, "_ZONE", None)
    assert z.israel_offset(at("2026-03-26T23:30:00+00:00")) == timedelta(hours=2)
    assert z.israel_offset(at("2026-03-27T00:30:00+00:00")) == timedelta(hours=3)   # Friday before the last Sunday
    assert z.israel_offset(at("2026-10-24T22:30:00+00:00")) == timedelta(hours=3)
    assert z.israel_offset(at("2026-10-24T23:30:00+00:00")) == timedelta(hours=2)   # last Sunday of October
    assert z.israel_local(date(2026, 7, 3), "19:47").isoformat() == "2026-07-03T16:47:00+00:00"


def test_days_of_rest_in_israel():
    assert z.rest_of(date(2026, 11, 14))[0] == "shabbat"
    assert z.rest_of(date(2026, 11, 13)) is None
    assert z.rest_of(date(2026, 9, 21))[0] == "yom_kippur"       # 10 Tishrei 5787
    assert z.rest_of(date(2026, 10, 3))[0] == "shemini_atzeret"  # 22 Tishrei: one day in Israel
    assert z.rest_of(date(2026, 10, 4)) is None
    assert z.rest_of(date(2026, 4, 8))[0] == "pesach"            # 21 Nisan 5786
    assert z.rest_of(date(2026, 4, 9)) is None


def service(tmp_path, now, sources=()):
    s = z.ZmanimService(tmp_path / "zmanim.json", sources=list(sources), now=lambda: at(now))
    s.configure(city="ירושלים", stop_before=10)
    return s


def test_a_shabbat_window(tmp_path):
    s = service(tmp_path, "2026-11-12T10:00:00+00:00")
    st = s.status()
    assert st["current"] is None
    w = st["next"]
    assert w["days"] == ["2026-11-14"] and w["greeting"] == "שבת שלום" and w["detail"] == "פרשת תולדות"
    assert w["candle_text"] == "16:00" or w["candle_text"] == "16:01"     # sunset 16:40:53 − 40 minutes
    assert w["end_text"] in ("17:18", "17:19")                             # Saturday nightfall
    assert w["stop_ms"] == w["start_ms"] - 10 * 60 * 1000
    assert w["eve_weekday"] == "יום שישי" and w["source"] == "local"


def test_inside_the_window_and_after_it(tmp_path):
    # Friday 16:00 Israel time (14:00 UTC): stop_at is 15:50, so it is Shabbat for the player.
    s = service(tmp_path, "2026-11-13T14:00:00+00:00")
    assert s.status()["current"]["greeting"] == "שבת שלום"
    # Saturday 17:30 Israel time: after nightfall, the next window is next week.
    s = service(tmp_path, "2026-11-14T15:30:00+00:00")
    st = s.status()
    assert st["current"] is None and st["next"]["days"] == ["2026-11-21"]


def test_shabbat_and_festival_run_together(tmp_path):
    # Rosh Hashana 5787 is Shabbat 12.9 and Sunday 13.9: one window from Friday to Sunday night.
    s = service(tmp_path, "2026-09-10T10:00:00+00:00")
    w = s.status()["next"]
    assert w["days"] == ["2026-09-12", "2026-09-13"]
    assert w["kind"] == "both" and w["title"] == "ראש השנה" and "שנה טובה" in w["greeting"]
    assert w["end_weekday"] == "יום ראשון"


def test_city_custom_and_rabbeinu_tam(tmp_path):
    s = service(tmp_path, "2026-11-12T10:00:00+00:00")
    jerusalem = s.status()["next"]
    s.configure(city="תל אביב-יפו", stop_before=0, havdalah="rt")
    tel_aviv = s.status()["next"]
    assert tel_aviv["start_ms"] > jerusalem["start_ms"] + 20 * 60 * 1000     # 18 minutes, not 40
    assert tel_aviv["stop_ms"] == tel_aviv["start_ms"]
    assert tel_aviv["end_ms"] > jerusalem["end_ms"] + 25 * 60 * 1000         # 72 minutes after sunset
    s.configure(city="תל אביב-יפו", candle_minutes=30)
    assert s.status()["candle_minutes"] == 30


def fake_days(source):
    def fetch(lat, lng, start, end):
        days = {}
        d = start
        while d <= end:
            sunset = z.israel_local(d, "16:30")
            days[d] = z.DayTimes(sunset, sunset + timedelta(minutes=40), sunset + timedelta(minutes=72), source)
            d += timedelta(days=1)
        return days
    return fetch


def test_sources_in_order_and_the_cache(tmp_path):
    calls = []

    def blocked(lat, lng, start, end):
        calls.append("ketertorah")
        raise OSError("418 blocked")

    s = service(tmp_path, "2026-11-12T10:00:00+00:00", [("ketertorah", blocked), ("hebcal", fake_days("hebcal"))])
    assert s.needs_refresh()
    assert s.refresh() == "hebcal" and calls == ["ketertorah"]
    st = s.status()
    assert st["source"] == "hebcal" and st["next"]["candle_text"] == "15:50"   # 16:30 − 40
    assert not s.needs_refresh()
    # The cache is read back by a new instance, with no network at all.
    again = service(tmp_path, "2026-11-12T10:00:00+00:00", [])
    assert again.status()["next"]["candle_text"] == "15:50"
    # Another city does not use Jerusalem's cache.
    again.configure(city="חיפה")
    assert again.status()["source"] == "local"


def test_the_first_source_wins(tmp_path):
    s = service(tmp_path, "2026-11-12T10:00:00+00:00",
                [("ketertorah", fake_days("ketertorah")), ("hebcal", fake_days("hebcal"))])
    assert s.refresh() == "ketertorah"
    assert s.status()["source_label"].startswith("זמנים טובא")


def test_nothing_answers_the_calculation_stands_in(tmp_path):
    def down(*a):
        raise OSError("offline")
    s = service(tmp_path, "2026-11-12T10:00:00+00:00", [("ketertorah", down), ("hebcal", down)])
    assert s.refresh() == "" and "offline" in s.last_error
    assert s.status()["next"]["source"] == "local"
