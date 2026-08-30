from datetime import date

from hamenagen.hebrew_calendar import (
    HebrewDate,
    detect_occasion,
    from_gregorian,
    hebrew_to_fixed,
    gregorian_to_fixed,
    fixed_to_hebrew,
)


def test_known_rosh_hashana_anchors():
    # 1 Tishrei (month 7) of these Hebrew years.
    assert (from_gregorian(date(2024, 10, 3)).year, from_gregorian(date(2024, 10, 3)).month,
            from_gregorian(date(2024, 10, 3)).day) == (5785, 7, 1)
    assert (from_gregorian(date(2025, 9, 23)).year, from_gregorian(date(2025, 9, 23)).month,
            from_gregorian(date(2025, 9, 23)).day) == (5786, 7, 1)
    assert (from_gregorian(date(2023, 9, 16)).year, from_gregorian(date(2023, 9, 16)).month,
            from_gregorian(date(2023, 9, 16)).day) == (5784, 7, 1)


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


def test_occasion_detection():
    assert detect_occasion(date(2024, 12, 26)).key == "chanukah"   # 25 Kislev
    assert detect_occasion(date(2026, 4, 2)).key == "pesach"       # 15 Nisan
    assert detect_occasion(date(2026, 8, 30)).key == "elul"        # month of Elul


def test_shabbat_takes_priority_on_saturday():
    # 2023-09-16 was a Saturday and also Rosh Hashana; Shabbat wins by priority.
    assert detect_occasion(date(2023, 9, 16)).key == "shabbat"
