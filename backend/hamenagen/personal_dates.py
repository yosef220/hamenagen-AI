"""The listener's own days, by the Hebrew date, every year (1.6).

A birthday, a wedding anniversary, a yahrzeit: kept in the settings as a
Hebrew day and month, and found again each year. The home page shows the day
when it comes (and a few days before), with what to play for it — a request
in the listener's own words ("סט ליום הולדת", the name of a saved playlist).

The months that are not in every year follow the rules in Reingold and
Dershowitz, *Calendrical Calculations* (hebrew-birthday, yahrzeit):

* **Adar.** A day of Adar in an ordinary year (or of Adar II in a leap year)
  falls in the last Adar of every year: Adar in an ordinary year, Adar II in a
  leap year. A day of Adar I stays in the first Adar (Adar, in an ordinary
  year). For a yahrzeit some keep the first Adar; the listener can choose
  "אדר א׳" for that.
* **The 30th of a month that has 29 days this year.** A birthday or an
  anniversary moves to the next day (the first of the next month); a
  yahrzeit stays in its month, on the 29th (Heshvan and Kislev, whose length
  changes from year to year) — and the 30th of Adar I, in an ordinary year,
  is kept on the 30th of Shevat.
"""

from __future__ import annotations

from datetime import date

from .hebrew_calendar import (
    from_gregorian,
    gematria,
    gregorian_to_fixed,
    hebrew_leap_year,
    hebrew_to_fixed,
    last_day_of_hebrew_month,
    last_month_of_hebrew_year,
    to_gregorian,
)

KINDS = {
    "birthday": "יום הולדת",
    "anniversary": "יום נישואין",
    "yahrzeit": "יארצייט",
    "other": "יום מיוחד",
}

# What plays on the day unless the listener chose otherwise (a yahrzeit
# suggests nothing by itself).
DEFAULT_REQUEST = {
    "birthday": "סט ליום הולדת",
    "anniversary": "סט לשמחה",
    "yahrzeit": "",
    "other": "",
}

# Month keys as the settings keep them: "12" is Adar of an ordinary year (the
# last Adar in a leap year), "12a" Adar I, "13" Adar II.
MONTHS = (
    ("7", "תשרי"), ("8", "חשוון"), ("9", "כסלו"), ("10", "טבת"), ("11", "שבט"),
    ("12", "אדר"), ("12a", "אדר א׳"), ("13", "אדר ב׳"),
    ("1", "ניסן"), ("2", "אייר"), ("3", "סיוון"), ("4", "תמוז"), ("5", "אב"), ("6", "אלול"),
)
MONTH_LABELS = dict(MONTHS)

# The days before the day itself when it already shows on the home page.
AHEAD_DAYS = 7


def sanitize(items) -> list[dict]:
    """Keep only well-formed entries (settings.json may be edited by hand)."""
    out = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()[:60]
        kind = raw.get("kind") if raw.get("kind") in KINDS else "other"
        month = str(raw.get("month") or "")
        try:
            day = int(raw.get("day"))
        except (TypeError, ValueError):
            continue
        if not name or month not in MONTH_LABELS or not 1 <= day <= 30:
            continue
        request = raw.get("request")
        request = DEFAULT_REQUEST[kind] if request is None else str(request).strip()[:120]
        out.append({"name": name, "kind": kind, "month": month, "day": day, "request": request})
    return out[:100]


def _month_in(year: int, month: str) -> int:
    """The month number a month key means in a given Hebrew year."""
    if month in ("12", "13"):
        return last_month_of_hebrew_year(year)
    if month == "12a":
        return 12
    return int(month)


def fixed_in_year(item: dict, year: int) -> int:
    """The day (R.D.) of a personal date in a Hebrew year."""
    day = int(item["day"])
    month = _month_in(year, item["month"])
    last = last_day_of_hebrew_month(year, month)
    if day <= last:
        return hebrew_to_fixed(year, month, day)
    if item.get("kind") == "yahrzeit":
        if item["month"] == "12a" and not hebrew_leap_year(year):
            return hebrew_to_fixed(year, 11, 30)      # 30 Adar I → 30 Shevat
        return hebrew_to_fixed(year, month, last)
    return hebrew_to_fixed(year, month, 1) + day - 1  # the next day: 1 of the next month


def next_date(item: dict, today: date | None = None) -> tuple[date, int]:
    """When the day comes next (today counts), and in how many days."""
    today = today or date.today()
    now = gregorian_to_fixed(today.year, today.month, today.day)
    year = from_gregorian(today).year
    for y in (year - 1, year, year + 1):
        fixed = fixed_in_year(item, y)
        if fixed >= now:
            return to_gregorian(fixed), fixed - now
    raise ValueError("no date")  # pragma: no cover - two years always hold one


def label(item: dict) -> str:
    """"יום ההולדת של שרה" — or the name as written when it already says it."""
    name = item["name"]
    kind = item.get("kind", "other")
    if kind == "other" or any(w in name for w in ("יום", "הולדת", "נישואין", "יארצייט", "אזכרה")):
        return name
    return {"birthday": "יום ההולדת של", "anniversary": "יום הנישואין של", "yahrzeit": "היארצייט של"}[kind] + f" {name}"


def hebrew_text(item: dict) -> str:
    return f"{gematria(int(item['day']))} ב{MONTH_LABELS[item['month']]}"


def upcoming(items, today: date | None = None, *, ahead: int = AHEAD_DAYS) -> list[dict]:
    """The personal days from today up to ``ahead`` days on, the nearest first."""
    out = []
    for item in sanitize(items):
        when, days = next_date(item, today)
        if days <= ahead:
            out.append({**item, "label": label(item), "kind_label": KINDS[item["kind"]], "days": days,
                        "gregorian": when.isoformat(), "hebrew": hebrew_text(item)})
    out.sort(key=lambda d: d["days"])
    return out
