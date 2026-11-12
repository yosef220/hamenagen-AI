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
    assert detect_occasion(date(2026, 11, 12)) is None             # ordinary Thursday
    assert detect_occasion(date(2026, 11, 11)).key == "rosh_chodesh"   # 1 Kislev


def test_rosh_chodesh_tu_bishvat_and_simchat_torah():
    # 30 Cheshvan and 1 Kislev are both Rosh Chodesh Kislev.
    for d in (date(2026, 11, 10), date(2026, 11, 11)):
        rc = [o for o in occasions_on(d) if o.key == "rosh_chodesh"][0]
        assert rc.detail == "ראש חודש כסלו" and rc.topic == "ראש חודש"
    # 1 Tishrei is Rosh Hashana, not Rosh Chodesh.
    assert "rosh_chodesh" not in [o.key for o in occasions_on(date(2026, 9, 12))]
    # 30 Adar I opens Adar II in a leap year.
    assert [o.detail for o in occasions_on(date(2027, 3, 9)) if o.key == "rosh_chodesh"] == ["ראש חודש אדר ב׳"]
    assert detect_occasion(date(2027, 1, 22 + 1)).key == "tu_bishvat"     # 15 Shevat 5787
    assert detect_occasion(date(2026, 10, 3)).key == "simchat_torah"      # 22 Tishrei
    # Rosh Chodesh is "monthly": the countdown still points at the next festival.
    assert today_info(date(2026, 11, 8))["next"]["key"] == "chanukah"


def test_weekly_torah_portion_in_israel():
    from hamenagen.hebrew_calendar import parasha_of_shabbat, parasha_of_week
    # Checked against Hebcal (Israel) for 5740–5811: 3,548 of 3,548 Shabbatot.
    known = {
        date(2026, 11, 14): "תולדות",
        date(2026, 10, 10): "בראשית",
        date(2011, 4, 16): "אחרי מות",            # a leap year reads it before Pesach
        date(1992, 6, 6): "נשא",                  # …and here Naso before Shavuot
        date(2018, 5, 5): "בהר",                  # Israel reads Behar and Bechukotai apart
        date(2018, 5, 12): "בחוקותי",
        date(2018, 7, 14): "מטות-מסעי",
        date(2026, 3, 14): "ויקהל-פקודי",
        date(2024, 9, 28): "נצבים-וילך",           # Rosh Hashana on Thursday
        date(2025, 9, 20): "נצבים",                # …on Tuesday: read apart,
        date(2025, 9, 27): "וילך",                 # וילך on Shabbat Shuva
        date(2026, 9, 5): "נצבים-וילך",            # Rosh Hashana on Shabbat
        date(2026, 9, 19): "האזינו",
    }
    for day, name in known.items():
        assert parasha_of_shabbat(day) == name, (day, parasha_of_shabbat(day), name)
    # Festivals replace the portion.
    assert parasha_of_shabbat(date(2027, 4, 24)) is None      # Shabbat of Pesach
    # All week long the luach shows the coming Shabbat's portion.
    assert parasha_of_week(date(2026, 11, 8)) == "תולדות"
    assert today_info(date(2026, 11, 12))["parasha"] == "תולדות"


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
    assert next_occasion(date(2026, 12, 6))["key"] == "tu_bishvat"
    assert next_occasion(date(2027, 1, 24))["key"] == "purim"


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
    # 1 Kislev is Rosh Chodesh; the countdown still points at Chanukah.
    assert [o["key"] for o in info["occasions"]] == ["rosh_chodesh"]
    assert info["primary"]["key"] == "rosh_chodesh"
    assert info["next"]["key"] == "chanukah"
    assert info["parasha"] == "תולדות"
