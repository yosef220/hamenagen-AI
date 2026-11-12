"""Offline Hebrew calendar + occasion detection (spec §7, §Hebrew Calendar).

We convert a Gregorian date to the Hebrew date entirely offline using the
classic fixed-day ("Rata Die") algorithm from Dershowitz & Reingold's
*Calendrical Calculations*. No network and no third-party package is needed,
which keeps the offline-first guarantee intact.

Month numbering follows the algorithm's convention: Nisan=1 … Adar=12, with
Tishrei=7. In a leap year month 12 is Adar I and month 13 is Adar II.

On top of the conversion we detect every "occasion" of a day (Erev Shabbat,
Chanukah, the Omer count, the Three Weeks, the month of Elul, …), format the
date the way it is written on a Jewish calendar ("א׳ בכסלו תשפ״ז"), and look
ahead for the next festival. The front-end uses this for the home "luach" and
the "play now" suggestion when the app opens.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

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


# --------------------------------------------------------------------------
# Hebrew numerals (gematria) and calendar-style formatting
# --------------------------------------------------------------------------

_GEM_ONES = ("", "א", "ב", "ג", "ד", "ה", "ו", "ז", "ח", "ט")
_GEM_TENS = ("", "י", "כ", "ל", "מ", "נ", "ס", "ע", "פ", "צ")
_GEM_HUNDREDS = ("", "ק", "ר", "ש", "ת")
GERESH = "׳"      # ׳
GERSHAYIM = "״"   # ״

_WEEKDAYS = ("יום שני", "יום שלישי", "יום רביעי", "יום חמישי", "יום שישי", "שבת", "יום ראשון")
_ORDINAL_DAYS = ("א׳", "ב׳", "ג׳", "ד׳", "ה׳", "ו׳", "ז׳", "ח׳")


def gematria(n: int, *, punctuate: bool = True) -> str:
    """Write ``n`` (1–999) in Hebrew letters: 15 → ט״ו, 787 → תשפ״ז.

    Thousands are dropped, as on a printed luach (5787 → תשפ״ז). 15 and 16
    use the customary ט״ו / ט״ז rather than spelling a divine name.
    """
    n = int(n) % 1000
    if n <= 0:
        return ""
    letters = ""
    hundreds = n // 100
    while hundreds > 4:
        letters += "ת"
        hundreds -= 4
    letters += _GEM_HUNDREDS[hundreds]
    rest = n % 100
    if rest == 15:
        letters += "טו"
    elif rest == 16:
        letters += "טז"
    else:
        letters += _GEM_TENS[rest // 10] + _GEM_ONES[rest % 10]
    if not punctuate:
        return letters
    if len(letters) == 1:
        return letters + GERESH
    return letters[:-1] + GERSHAYIM + letters[-1]


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

    @property
    def day_text(self) -> str:
        return gematria(self.day)

    @property
    def year_text(self) -> str:
        return gematria(self.year % 1000)

    @property
    def text(self) -> str:
        """The date as printed on a luach: "א׳ בכסלו תשפ״ז"."""
        return f"{self.day_text} ב{self.month_name} {self.year_text}"

    @property
    def fixed(self) -> int:
        return hebrew_to_fixed(self.year, self.month, self.day)

    def to_dict(self) -> dict:
        return {
            "year": self.year,
            "month": self.month,
            "day": self.day,
            "is_leap": self.is_leap,
            "month_name": self.month_name,
            "day_text": self.day_text,
            "year_text": self.year_text,
            "text": self.text,
        }

    def __str__(self) -> str:
        return self.text


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


def to_gregorian(fixed: int) -> date:
    """R.D. fixed days coincide with Python's proleptic Gregorian ordinals."""
    return date.fromordinal(fixed)


def weekday_name(g: date) -> str:
    return _WEEKDAYS[g.weekday()]


# --------------------------------------------------------------------------
# Occasions
# --------------------------------------------------------------------------

#: Topic used for a cappella music in the Omer count and the Three Weeks.
VOCAL_TOPIC = "ווקאלי"


@dataclass(frozen=True)
class Occasion:
    """A time-based occasion and the topic to suggest for it."""

    key: str                 # stable identifier, e.g. "chanukah"
    label: str               # Hebrew label for the UI
    topic: str | None        # topic to suggest; None = show, but suggest nothing
    priority: int            # higher wins when several apply at once
    kind: str = "holiday"    # "weekly" | "holiday" | "season" | "fast"
    detail: str = ""         # extra line, e.g. "יום ג׳" or "היום 23 לעומר"

    @property
    def suggests(self) -> bool:
        return self.topic is not None

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "topic": self.topic,
            "priority": self.priority,
            "kind": self.kind,
            "detail": self.detail,
            "suggests": self.suggests,
        }


def omer_day(h: HebrewDate) -> int | None:
    """Day of the Omer count (1–49) from 16 Nisan to 5 Sivan, else ``None``."""
    n = h.fixed - hebrew_to_fixed(h.year, 1, 16) + 1
    return n if 1 <= n <= 49 else None


def chanukah_day(h: HebrewDate) -> int | None:
    """Day of Chanukah (1–8), counted from 25 Kislev, else ``None``."""
    n = h.fixed - hebrew_to_fixed(h.year, 9, 25) + 1
    return n if 1 <= n <= 8 else None


def tisha_bav_fixed(year: int) -> int:
    """The observed fast of 9 Av: postponed to 10 Av when 9 Av is Shabbat."""
    fixed = hebrew_to_fixed(year, 5, 9)
    if to_gregorian(fixed).weekday() == 5:
        fixed += 1
    return fixed


def occasions_on(g: date | None = None, *, vocal_suggestions: bool = True) -> list[Occasion]:
    """Every occasion that applies on ``g``, highest priority first.

    A day can carry several (a Friday of Chanukah is both Erev Shabbat and
    Chanukah); the UI shows the first as the main suggestion and the rest as
    secondary ones. ``vocal_suggestions=False`` keeps the Omer / Three Weeks
    entries for display but stops them from suggesting vocal music.
    """
    if g is None:
        g = date.today()
    h = from_gregorian(g)
    fixed = h.fixed
    weekday = g.weekday()  # Monday=0 .. Friday=4, Saturday=5
    found: list[Occasion] = []

    # Weekly: prepare for Shabbat on Friday; Melave Malka on Saturday night.
    # A festival outranks the weekly suggestion (a Friday of Chanukah suggests
    # Chanukah first, with Shabbat songs offered beside it).
    if weekday == 4:
        found.append(Occasion("erev_shabbat", "ערב שבת", "שבת", 80, "weekly", "מתכוננים לשבת"))
    elif weekday == 5:
        found.append(Occasion("motzei_shabbat", "מוצאי שבת", "שבת", 80, "weekly", "מלווה מלכה"))

    # The fast of 9 Av: shown, but no music is suggested.
    if fixed == tisha_bav_fixed(h.year):
        found.append(Occasion("tisha_bav", "תשעה באב", None, 95, "fast", "צום החורבן"))

    # Festivals.
    if h.month == 7 and h.day in (1, 2):
        found.append(Occasion("rosh_hashana", "ראש השנה", "ראש השנה", 90,
                              detail=f"יום {_ORDINAL_DAYS[h.day - 1]}"))
    if h.month == 7 and h.day == 10:
        found.append(Occasion("yom_kippur", "יום כיפור", "יום כיפור", 90))
    if h.month == 7 and 15 <= h.day <= 21:
        found.append(Occasion("sukkot", "סוכות", "סוכות", 90,
                              detail=f"יום {_ORDINAL_DAYS[h.day - 15]} של סוכות"))
    if h.month == 7 and h.day == 22:
        found.append(Occasion("simchat_torah", "שמחת תורה", "סוכות", 90, detail="שמיני עצרת"))
    cday = chanukah_day(h)
    if cday:
        found.append(Occasion("chanukah", "חנוכה", "חנוכה", 90,
                              detail=f"יום {_ORDINAL_DAYS[cday - 1]} של חנוכה"))
    purim_month = 13 if h.is_leap else 12
    if h.month == purim_month and h.day in (14, 15):
        found.append(Occasion("purim", "פורים" if h.day == 14 else "שושן פורים", "פורים", 90))
    if h.month == 1 and 15 <= h.day <= 21:
        found.append(Occasion("pesach", "פסח", "פסח", 90,
                              detail=f"יום {_ORDINAL_DAYS[h.day - 15]} של פסח"))
    if h.month == 2 and h.day == 18:
        found.append(Occasion("lag_baomer", "ל״ג בעומר", "ל״ג בעומר", 90, detail="הילולת רשב״י"))
    if h.month == 3 and h.day in (6, 7):
        found.append(Occasion("shavuot", "שבועות", "שבועות", 90))
    if h.month == 11 and h.day == 15:
        found.append(Occasion("tu_bishvat", "ט״ו בשבט", "ט״ו בשבט", 90, detail="ראש השנה לאילנות"))
    # Rosh Chodesh: the 30th of a full month and the 1st of the next (the 1st
    # of Tishrei is Rosh Hashana). Below the weekly Shabbat suggestion, and
    # "monthly" so it never takes over the countdown to the next festival.
    if h.day == 30 or (h.day == 1 and h.month != 7):
        month = fixed_to_hebrew(fixed + 1 if h.day == 30 else fixed).month_name
        found.append(Occasion("rosh_chodesh", "ראש חודש", "ראש חודש", 70, "monthly",
                              f"ראש חודש {month}"))

    # Seasons.
    # The Omer and the Three Weeks suggest a cappella music every day (above
    # the weekly Shabbat suggestion), unless the user turned that off.
    vocal = VOCAL_TOPIC if vocal_suggestions else None
    vocal_priority = 85 if vocal_suggestions else 30
    omer = omer_day(h)
    if omer:
        found.append(Occasion("sefira", "ספירת העומר", vocal, vocal_priority, "season",
                              f"היום {omer} לעומר"))
    if hebrew_to_fixed(h.year, 4, 17) <= fixed <= hebrew_to_fixed(h.year, 5, 8):
        found.append(Occasion("bein_hametzarim", "בין המצרים", vocal, vocal_priority, "season",
                              "שלושת השבועות"))
    if h.month == 6:
        found.append(Occasion("elul", "חודש אלול", "אלול", 40, "season", "ימי רחמים וסליחות"))
    if h.month == 7 and 3 <= h.day <= 9:
        found.append(Occasion("aseret_yemei_teshuva", "עשרת ימי תשובה", "אלול", 40, "season"))

    found.sort(key=lambda o: o.priority, reverse=True)
    return found


def detect_occasion(g: date | None = None, *, vocal_suggestions: bool = True) -> Occasion | None:
    """The single most relevant occasion of ``g`` (``None`` on an ordinary day)."""
    found = occasions_on(g, vocal_suggestions=vocal_suggestions)
    return found[0] if found else None


def next_occasion(g: date | None = None, *, horizon: int = 120) -> dict | None:
    """The next festival that *starts* after ``g`` — for "חנוכה בעוד 24 ימים".

    Only festivals count (not the weekly Shabbat or the seasons), and one that
    is already running today is skipped. Returns ``None`` past the horizon.
    """
    if g is None:
        g = date.today()
    active = {o.key for o in occasions_on(g)}
    previous = active
    for days in range(1, horizon + 1):
        day = g + timedelta(days=days)
        here = occasions_on(day)
        for occ in here:
            if occ.kind != "holiday" or occ.key in previous or occ.key in active:
                continue
            h = from_gregorian(day)
            return {
                **occ.to_dict(),
                "days": days,
                "gregorian": day.isoformat(),
                "weekday": weekday_name(day),
                "hebrew": h.text,
            }
        previous = {o.key for o in here}
    return None


def today_info(g: date | None = None, *, vocal_suggestions: bool = True) -> dict:
    """Everything the home "luach" needs for one day, as plain JSON data."""
    if g is None:
        g = date.today()
    h = from_gregorian(g)
    found = occasions_on(g, vocal_suggestions=vocal_suggestions)
    primary = next((o for o in found if o.suggests), None)
    return {
        "gregorian": g.isoformat(),
        "weekday": weekday_name(g),
        "hebrew": h.to_dict(),
        "occasions": [o.to_dict() for o in found],
        "primary": primary.to_dict() if primary else None,
        "omer": omer_day(h),
        "parasha": parasha_of_week(g),
        "next": next_occasion(g),
    }


# --------------------------------------------------------------------------
# The weekly Torah portion (Israel), computed offline
# --------------------------------------------------------------------------

#: The 53 portions read on Shabbat, Bereshit … Ha'azinu (V'Zot HaBracha is
#: read on Simchat Torah, never on a Shabbat).
PARASHIYOT = (
    "בראשית", "נח", "לך לך", "וירא", "חיי שרה", "תולדות", "ויצא", "וישלח", "וישב", "מקץ",
    "ויגש", "ויחי", "שמות", "וארא", "בא", "בשלח", "יתרו", "משפטים", "תרומה", "תצוה",
    "כי תשא", "ויקהל", "פקודי", "ויקרא", "צו", "שמיני", "תזריע", "מצורע", "אחרי מות", "קדושים",
    "אמור", "בהר", "בחוקותי", "במדבר", "נשא", "בהעלותך", "שלח לך", "קרח", "חוקת", "בלק",
    "פנחס", "מטות", "מסעי", "דברים", "ואתחנן", "עקב", "ראה", "שופטים", "כי תצא", "כי תבוא",
    "נצבים", "וילך", "האזינו",
)

# Pairs that are read together when a stretch of the year has fewer Shabbatot
# than portions — in the order they are joined (the first is joined first).
_JOIN_BEFORE_PESACH = ((21, 22),)                     # ויקהל-פקודי
_JOIN_BEFORE_SHAVUOT = ((26, 27), (28, 29), (31, 32))  # תזריע-מצורע, אחרי מות-קדושים, בהר-בחוקותי
_JOIN_BEFORE_TISHA_BAV = ((41, 42), (38, 39))          # מטות-מסעי, חוקת-בלק


def _shabbatot(start: int, end: int) -> list[int]:
    """Fixed days of every Shabbat with ``start <= day < end``."""
    first = start + (6 - start % 7) % 7   # fixed % 7 == 6 is Saturday
    return list(range(first, end, 7))


def _assign(days: list[int], first: int, last: int, joins: tuple, out: dict) -> None:
    """Spread portions ``first..last`` over ``days``, joining pairs as needed."""
    need = (last - first + 1) - len(days)
    joined = {a for a, _ in sorted(joins[:max(need, 0)])}
    readings: list[tuple[int, ...]] = []
    i = first
    while i <= last:
        if i in joined:
            readings.append((i, i + 1))
            i += 2
        else:
            readings.append((i,))
            i += 1
    # A stretch never has more Shabbatot than portions; if the arithmetic
    # ever disagrees, leave the extra Shabbatot unnamed rather than guess.
    for day, reading in zip(days, readings):
        out[day] = reading


def _torah_cycle(year: int) -> dict[int, tuple[int, ...]]:
    """Shabbat (fixed day) → portion indexes, for the cycle that starts after
    Simchat Torah of Hebrew ``year`` and ends before Sukkot of ``year + 1``."""
    simchat_torah = hebrew_to_fixed(year, 7, 22)
    pesach = hebrew_to_fixed(year, 1, 15)
    shavuot = hebrew_to_fixed(year, 3, 6)
    tisha_bav = hebrew_to_fixed(year, 5, 9)
    rosh_hashana = hebrew_to_fixed(year + 1, 7, 1)
    sukkot = hebrew_to_fixed(year + 1, 7, 15)
    leap = hebrew_leap_year(year)

    out: dict[int, tuple[int, ...]] = {}
    festival = lambda d: pesach <= d < pesach + 7 or d == shavuot
    if leap:
        # A leap year has room for every portion; in some years Israel even
        # reads אחרי מות before Pesach and נשא before Shavuot. Only מטות-מסעי
        # may be joined, to reach דברים on Shabbat Chazon.
        days = [d for d in _shabbatot(simchat_torah + 1, tisha_bav + 1) if not festival(d)]
        _assign(days, 0, 43, _JOIN_BEFORE_TISHA_BAV, out)
    else:
        # A plain year reads צו before Pesach, במדבר before Shavuot and דברים
        # on Shabbat Chazon, joining pairs inside each stretch.
        _assign(_shabbatot(simchat_torah + 1, pesach), 0, 24, _JOIN_BEFORE_PESACH, out)
        _assign(_shabbatot(pesach + 7, shavuot), 25, 33, _JOIN_BEFORE_SHAVUOT, out)
        _assign(_shabbatot(shavuot + 1, tisha_bav + 1), 34, 43, _JOIN_BEFORE_TISHA_BAV, out)
    # Seven Shabbatot of consolation to Rosh Hashana, then Shabbat Shuva and
    # the Shabbat before Sukkot: נצבים-וילך are joined when only one is left.
    consolation = _shabbatot(tisha_bav + 1, rosh_hashana)
    after_rh = [d for d in _shabbatot(rosh_hashana + 2, sukkot) if d != rosh_hashana + 9]
    if len(after_rh) >= 2:
        _assign(consolation, 44, 50, (), out)
        _assign(after_rh[:2], 51, 52, (), out)
    else:
        _assign(consolation, 44, 51, ((50, 51),), out)
        _assign(after_rh, 52, 52, (), out)
    return out


def _cycle_year(fixed: int) -> int:
    """The Hebrew year whose Simchat Torah opened the cycle that ``fixed`` is in."""
    h = fixed_to_hebrew(fixed)
    year = h.year
    # Before Simchat Torah, the cycle is the one that began last year.
    if fixed <= hebrew_to_fixed(year, 7, 22):
        year -= 1
    return year


def parasha_of_shabbat(shabbat: date) -> str | None:
    """The portion read on the Shabbat ``shabbat`` in Israel.

    ``None`` when a festival's reading replaces it (Pesach, Shavuot, Rosh
    Hashana, Yom Kippur, Sukkot).
    """
    fixed = gregorian_to_fixed(shabbat.year, shabbat.month, shabbat.day)
    reading = _torah_cycle(_cycle_year(fixed)).get(fixed)
    if not reading:
        return None
    return "-".join(PARASHIYOT[i] for i in reading)


def coming_shabbat(g: date) -> date:
    """The Shabbat of the week ``g`` is in (``g`` itself on a Shabbat)."""
    return g + timedelta(days=(5 - g.weekday()) % 7)


def parasha_of_week(g: date | None = None) -> str | None:
    """The portion of the coming Shabbat — what a luach shows all week."""
    return parasha_of_shabbat(coming_shabbat(g or date.today()))
