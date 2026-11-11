from datetime import date, timedelta

from hamenagen.hebrew_calendar import (
    detect_occasion,
    fixed_to_hebrew,
    from_gregorian,
    gematria,
    gregorian_to_fixed,
    hebrew_to_fixed,
    next_occasion,
    occasions_on,
    omer_day,
    tisha_bav_fixed,
    to_gregorian,
    today_info,
)


def _ymd(g):
    h = from_gregorian(g)
    return (h.year, h.month, h.day)


def test_known_rosh_hashana_anchors():
    # 1 Tishrei (month 7) of these Hebrew years.
    assert _ymd(date(2024, 10, 3)) == (5785, 7, 1)
    assert _ymd(date(2025, 9, 23)) == (5786, 7, 1)
    assert _ymd(date(2023, 9, 16)) == (5784, 7, 1)
    assert _ymd(date(2026, 9, 12)) == (5787, 7, 1)


def test_today_example_is_elul():
    h = from_gregorian(date(2026, 8, 30))
    assert h.year == 5786
    assert h.month == 6  # Elul


def test_roundtrip_conversion():
    for g in (date(2000, 1, 1), date(2024, 12, 26), date(2026, 4, 2), date(2030, 7, 15)):
        h = from_gregorian(g)
        fixed = gregorian_to_fixed(g.year, g.month, g.day)
        assert hebrew_to_fixed(h.year, h.month, h.day) == fixed
        assert fixed_to_hebrew(fixed) == h
        assert to_gregorian(fixed) == g


def test_gematria():
    assert gematria(1) == "א׳"
    assert gematria(15) == "ט״ו"
    assert gematria(16) == "ט״ז"
    assert gematria(25) == "כ״ה"
    assert gematria(30) == "ל׳"
    assert gematria(787) == "תשפ״ז"
    assert gematria(900) == "תת״ק"
    assert gematria(5787 % 1000, punctuate=False) == "תשפז"


def test_luach_formatting():
    h = from_gregorian(date(2026, 11, 11))
    assert h.text == "א׳ בכסלו תשפ״ז"
    assert str(h) == h.text
    # 5787 is a leap year: the second Adar is named.
    assert "אדר ב׳" in from_gregorian(date(2027, 3, 23)).text


def test_occasion_detection():
    assert detect_occasion(date(2024, 12, 26)).key == "chanukah"   # 25 Kislev
    assert detect_occasion(date(2026, 4, 2)).key == "pesach"       # 15 Nisan
    assert detect_occasion(date(2026, 8, 30)).key == "elul"        # month of Elul
    assert detect_occasion(date(2026, 11, 11)) is None             # ordinary Wednesday


def test_festival_outranks_the_weekly_suggestion():
    # 2023-09-16 was a Saturday and also Rosh Hashana.
    keys = [o.key for o in occasions_on(date(2023, 9, 16))]
    assert keys[0] == "rosh_hashana"
    assert "motzei_shabbat" in keys


def test_weekly_occasions():
    assert detect_occasion(date(2026, 11, 13)).key == "erev_shabbat"    # Friday
    assert detect_occasion(date(2026, 11, 14)).key == "motzei_shabbat"  # Saturday


def test_chanukah_on_shabbat_is_not_hidden():
    # 25 Kislev 5787 falls on Shabbat; both occasions are reported.
    keys = [o.key for o in occasions_on(date(2026, 12, 5))]
    assert "chanukah" in keys and "motzei_shabbat" in keys
    days = [o.detail for o in occasions_on(date(2026, 12, 12)) if o.key == "chanukah"]
    assert days == ["יום ח׳ של חנוכה"]
    assert all(o.key != "chanukah" for o in occasions_on(date(2026, 12, 13)))


def test_next_occasion_counts_down_to_chanukah():
    nxt = next_occasion(date(2026, 11, 11))
    assert nxt["key"] == "chanukah"
    assert nxt["days"] == 24
    assert nxt["hebrew"] == "כ״ה בכסלו תשפ״ז"
    # While Chanukah runs, the next festival is a later one.
    assert next_occasion(date(2026, 12, 6))["key"] == "purim"


def test_omer_count_and_vocal_suggestion():
    first = date(2027, 4, 23)  # 16 Nisan 5787
    assert omer_day(from_gregorian(first)) == 1
    assert omer_day(from_gregorian(first + timedelta(days=48))) == 49
    assert omer_day(from_gregorian(first + timedelta(days=49))) is None
    tuesday = first + timedelta(days=11)  # day 12, an ordinary weekday
    occ = detect_occasion(tuesday)
    assert occ.key == "sefira" and occ.topic == "ווקאלי" and occ.detail == "היום 12 לעומר"
    # Turned off: the count is still shown, but nothing is suggested.
    quiet = occasions_on(tuesday, vocal_suggestions=False)
    assert quiet[0].key == "sefira" and quiet[0].topic is None
    assert today_info(tuesday, vocal_suggestions=False)["primary"] is None


def test_lag_baomer_and_shavuot():
    assert detect_occasion(date(2027, 5, 25)).key == "lag_baomer"  # 18 Iyar 5787
    assert any(o.key == "shavuot" for o in occasions_on(date(2027, 6, 11)))  # 6 Sivan


def test_tisha_bav_is_postponed_from_shabbat():
    for year in range(5780, 5800):
        nine = hebrew_to_fixed(year, 5, 9)
        if to_gregorian(nine).weekday() == 5:
            assert tisha_bav_fixed(year) == nine + 1
            sunday = to_gregorian(nine + 1)
            occ = detect_occasion(sunday)
            assert occ.key == "tisha_bav" and occ.topic is None
            break
    else:  # pragma: no cover
        raise AssertionError("no Shabbat 9 Av in range")


def test_today_info_shape():
    info = today_info(date(2026, 11, 11))
    assert info["weekday"] == "יום רביעי"
    assert info["hebrew"]["text"] == "א׳ בכסלו תשפ״ז"
    assert info["occasions"] == [] and info["primary"] is None
    assert info["next"]["key"] == "chanukah"
