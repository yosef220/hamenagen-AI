"""Offline Hebrew calendar + occasion detection (spec §7, §Hebrew Calendar).

We convert a Gregorian date to the Hebrew date entirely offline using the
classic fixed-day ("Rata Die") algorithm from Dershowitz & Reingold's
*Calendrical Calculations*. No network and no third-party package is needed,
which keeps the offline-first guarantee intact.

Month numbering follows the algorithm's convention: Nisan=1 … Adar=12, with
Tishrei=7. In a leap year month 12 is Adar I and month 13 is Adar II.

On top of the conversion we detect the current "occasion" (Shabbat, Chanukah,
the month of Elul, Purim, Pesach, …) which the front-end uses to surface a
"play now" suggestion when the app opens.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

HEBREW_EPOCH = -1373427  # R.D. of 1 Tishrei, Hebrew year 1

# Month names. Index by (month_number, is_leap_year).
_MONTH_NAMES = {
    1: "ניסן",
    2: "אייר",
    3: "סיוון",
    4: "תמוז",
    5: "אב",
    6: "אלול",
    7: "תשרי",
    8: "חשוון",
    9: "כסלו",
    10: "טבת",
    11: "שבט",
    12: "אדר",
    13: "אדר ב׳",
}


def _gregorian_is_leap(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


def gregorian_to_fixed(year: int, month: int, day: int) -> int:
    """Return the fixed day number (R.D.) for a Gregorian date."""
    prior = year - 1
    fixed = (
        365 * prior
        + prior // 4
        - prior // 100
        + prior // 400
        + (367 * month - 362) // 12
        + day
    )
    if month <= 2:
        correction = 0
    elif _gregorian_is_leap(year):
        correction = -1
    else:
        correction = -2
    return fixed + correction


def hebrew_leap_year(year: int) -> bool:
    return (7 * year + 1) % 19 < 7


def last_month_of_hebrew_year(year: int) -> int:
    return 13 if hebrew_leap_year(year) else 12


def _elapsed_days(year: int) -> int:
    months_elapsed = (235 * year - 234) // 19
    parts_elapsed = 12084 + 13753 * months_elapsed
    day = 29 * months_elapsed + parts_elapsed // 25920
    if (3 * (day + 1)) % 7 < 3:  # ADU rosh postponement (partial)
        day += 1
    return day


def _new_year_delay(year: int) -> int:
    ny0 = _elapsed_days(year - 1)
    ny1 = _elapsed_days(year)
    ny2 = _elapsed_days(year + 1)
    if ny2 - ny1 == 356:
        return 2
    if ny1 - ny0 == 382:
        return 1
    return 0


def hebrew_new_year(year: int) -> int:
    """Fixed day of 1 Tishrei of the given Hebrew year."""
    return HEBREW_EPOCH + _elapsed_days(year) + _new_year_delay(year)


def days_in_hebrew_year(year: int) -> int:
    return hebrew_new_year(year + 1) - hebrew_new_year(year)


def _long_heshvan(year: int) -> bool:
    return days_in_hebrew_year(year) % 10 == 5


def _short_kislev(year: int) -> bool:
    return days_in_hebrew_year(year) % 10 == 3


def last_day_of_hebrew_month(year: int, month: int) -> int:
    if month in (2, 4, 6, 10, 13):
        return 29
    if month == 12 and not hebrew_leap_year(year):
        return 29
    if month == 8 and not _long_heshvan(year):
        return 29
    if month == 9 and _short_kislev(year):
        return 29
    return 30


def hebrew_to_fixed(year: int, month: int, day: int) -> int:
    if month < 7:  # Nisan..end, comes *after* Tishrei within the civil year
        s = sum(
            last_day_of_hebrew_month(year, m)
            for m in range(7, last_month_of_hebrew_year(year) + 1)
        )
        s += sum(last_day_of_hebrew_month(year, m) for m in range(1, month))
    else:
        s = sum(last_day_of_hebrew_month(year, m) for m in range(7, month))
    return hebrew_new_year(year) + day - 1 + s


@dataclass(frozen=True)
class HebrewDate:
    year: int
    month: int
    day: int
    is_leap: bool

    @property
    def month_name(self) -> str:
        if self.month == 12 and self.is_leap:
            return "אדר א׳"
        return _MONTH_NAMES[self.month]

    def __str__(self) -> str:
        return f"{self.day} {self.month_name} {self.year}"


def fixed_to_hebrew(fixed: int) -> HebrewDate:
    approx = (fixed - HEBREW_EPOCH) // 366
    year = approx
    while hebrew_new_year(year + 1) <= fixed:
        year += 1
    # Before Nisan 1 the date is in the autumn part of the civil year, so we
    # start the month scan at Tishrei (7); on/after Nisan 1 we start at 1.
    start_month = 7 if fixed < hebrew_to_fixed(year, 1, 1) else 1
    month = start_month
    while fixed > hebrew_to_fixed(year, month, last_day_of_hebrew_month(year, month)):
        month += 1
    day = fixed - hebrew_to_fixed(year, month, 1) + 1
    return HebrewDate(year, month, day, hebrew_leap_year(year))


def from_gregorian(g: date) -> HebrewDate:
    return fixed_to_hebrew(gregorian_to_fixed(g.year, g.month, g.day))


# --------------------------------------------------------------------------
# Occasion detection
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Occasion:
    """A detected time-based occasion and the topic to suggest for it."""

    key: str          # stable identifier, e.g. "shabbat"
    label: str        # Hebrew label for the UI banner
    topic: str        # topic key used by the classifier / index filter
    priority: int     # higher wins when several apply at once


def _is_chanukah(h: HebrewDate) -> bool:
    # 25 Kislev (month 9) through 2 or 3 Tevet (month 10).
    if h.month == 9 and h.day >= 25:
        return True
    if h.month == 10 and h.day <= 3:
        # exact end depends on whether Kislev was short, but 1-2 Tevet is
        # always Chanukah, and day 3 is a harmless over-inclusion.
        return True
    return False


def detect_occasion(g: date | None = None) -> Occasion | None:
    """Return the most relevant occasion for the given Gregorian date.

    ``None`` means "no special occasion" and the UI should just show the
    generic search field without a suggestion banner.
    """
    if g is None:
        g = date.today()
    h = from_gregorian(g)
    weekday = g.weekday()  # Monday=0 .. Sunday=6; Friday=4, Saturday=5

    candidates: list[Occasion] = []

    # Shabbat: Friday (from candle-lighting) and Saturday.
    if weekday in (4, 5):
        candidates.append(Occasion("shabbat", "שבת", "שבת", priority=100))

    # Chanukah.
    if _is_chanukah(h):
        candidates.append(Occasion("chanukah", "חנוכה", "חנוכה", priority=90))

    # Purim — 14 Adar (month 12; Adar II / month 13 in a leap year).
    purim_month = 13 if h.is_leap else 12
    if h.month == purim_month and h.day in (14, 15):
        candidates.append(Occasion("purim", "פורים", "פורים", priority=90))

    # Pesach — 15–21 Nisan (month 1).
    if h.month == 1 and 15 <= h.day <= 21:
        candidates.append(Occasion("pesach", "פסח", "פסח", priority=90))

    # Shavuot — 6–7 Sivan (month 3).
    if h.month == 3 and h.day in (6, 7):
        candidates.append(Occasion("shavuot", "שבועות", "שבועות", priority=90))

    # Rosh Hashana — 1–2 Tishrei (month 7).
    if h.month == 7 and h.day in (1, 2):
        candidates.append(Occasion("rosh_hashana", "ראש השנה", "ראש השנה", priority=90))

    # Yom Kippur — 10 Tishrei.
    if h.month == 7 and h.day == 10:
        candidates.append(Occasion("yom_kippur", "יום כיפור", "יום כיפור", priority=90))

    # Sukkot — 15–21 Tishrei.
    if h.month == 7 and 15 <= h.day <= 21:
        candidates.append(Occasion("sukkot", "סוכות", "סוכות", priority=90))

    # Month of Elul (month 6) — lower priority "seasonal" suggestion.
    if h.month == 6:
        candidates.append(Occasion("elul", "חודש אלול", "אלול", priority=40))

    if not candidates:
        return None
    candidates.sort(key=lambda o: o.priority, reverse=True)
    return candidates[0]
