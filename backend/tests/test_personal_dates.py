"""1.6: the listener's own days by the Hebrew date, every year."""

from datetime import date

from hamenagen import personal_dates as pd
from hamenagen.hebrew_calendar import (
    fixed_to_hebrew,
    hebrew_leap_year,
    last_day_of_hebrew_month,
)
from hamenagen.service import PlayerService
from hamenagen.settings import Settings


def _on(item, year):
    h = fixed_to_hebrew(pd.fixed_in_year(item, year))
    return h.month, h.day


def test_a_plain_day_comes_back_on_its_date():
    item = {"name": "שרה", "kind": "birthday", "month": "9", "day": 7}
    when, days = pd.next_date(item, date(2026, 11, 17))   # ז׳ בכסלו תשפ״ז
    assert (when, days) == (date(2026, 11, 17), 0)
    when, days = pd.next_date(item, date(2026, 11, 18))
    assert days > 300 and _on(item, 5788) == (9, 7)


def test_adar_in_a_leap_year():
    assert hebrew_leap_year(5787) and not hebrew_leap_year(5786)
    adar = {"name": "א", "kind": "birthday", "month": "12", "day": 14}
    adar1 = {"name": "ב", "kind": "yahrzeit", "month": "12a", "day": 14}
    adar2 = {"name": "ג", "kind": "birthday", "month": "13", "day": 14}
    assert _on(adar, 5787) == (13, 14) and _on(adar, 5786) == (12, 14)
    assert _on(adar1, 5787) == (12, 14) and _on(adar1, 5786) == (12, 14)
    assert _on(adar2, 5787) == (13, 14) and _on(adar2, 5786) == (12, 14)


def test_the_thirtieth_of_a_short_month():
    short = next(y for y in range(5780, 5800) if last_day_of_hebrew_month(y, 9) == 29)
    birthday = {"name": "א", "kind": "birthday", "month": "9", "day": 30}
    yahrzeit = {"name": "ב", "kind": "yahrzeit", "month": "9", "day": 30}
    assert _on(birthday, short) == (10, 1)       # the next day
    assert _on(yahrzeit, short) == (9, 29)       # stays in Kislev
    ordinary = 5786
    assert _on({"name": "ג", "kind": "yahrzeit", "month": "12a", "day": 30}, ordinary) == (11, 30)


def test_labels_and_the_week_ahead():
    items = [
        {"name": "שרה", "kind": "birthday", "month": "9", "day": 9},
        {"name": "סבא משה", "kind": "yahrzeit", "month": "9", "day": 8},
        {"name": "יום הנישואין שלנו", "kind": "anniversary", "month": "7", "day": 1},
        {"name": "", "kind": "birthday", "month": "9", "day": 9},              # no name: dropped
        {"name": "x", "kind": "birthday", "month": "14", "day": 9},            # no such month: dropped
    ]
    soon = pd.upcoming(items, date(2026, 11, 17))
    assert [(d["label"], d["days"]) for d in soon] == [("היארצייט של סבא משה", 1), ("יום ההולדת של שרה", 2)]
    assert soon[0]["request"] == "" and soon[1]["request"] == "סט ליום הולדת"
    assert soon[1]["hebrew"] == "ט׳ בכסלו"
    assert len(Settings(personal_dates=items).sanitized().personal_dates) == 3


def test_the_home_page_shows_them(tmp_path):
    service = PlayerService(data_dir=tmp_path / "data")
    try:
        service.update_settings({"personal_dates": [{"name": "שרה", "kind": "birthday", "month": "9", "day": 7,
                                                      "request": "השירים שאהבתי"}]})
        info = service.today(date(2026, 11, 17))
        assert info["personal"][0]["label"] == "יום ההולדת של שרה"
        assert info["personal"][0]["request"] == "השירים שאהבתי"
        assert service.today(date(2026, 12, 17))["personal"] == []
    finally:
        service.close()
