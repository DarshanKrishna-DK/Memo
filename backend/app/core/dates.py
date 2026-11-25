"""Turn spoken/typed date words into concrete dates in the family's timezone.

resolve_when("yesterday") -> [{"year":2026,"month":11,"day":23,"start":date,"end":date,"label":"23 November 2026"}]
Handles: today / yesterday / day before yesterday / tomorrow / N days|weeks|months|years ago / last N days /
this|last week / last weekend / this|last|next month / this|last|next year (incl. "last year's") /
"November 2026" / "Nov 23" / "23 Nov 2026" / "last March" / bare month / bare year / ISO and dd/mm/yyyy /
ranges ("from 1 Nov to 10 Nov", "between March and May 2025", "Oct 2025 - Jan 2026") / a few romanised Hindi words.
A day or month without a year means its most recent occurrence that is not in the future.
Returns [] when nothing date-like is found.
"""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5,
    "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
MONTH_NAMES = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September",
               "October", "November", "December"]
_M = r"(january|february|march|april|may|june|july|august|september|october|november|december|" \
     r"jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)"
_YEAR = r"((?:19|20|21)\d{2})"
_NUMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
         "ten": 10, "a": 1, "an": 1}


def _month_end(y: int, m: int) -> date:
    return date(y, m, monthrange(y, m)[1])


def _add_months(y: int, m: int, k: int) -> tuple[int, int]:
    t = y * 12 + (m - 1) + k
    return t // 12, t % 12 + 1


def _day_label(d: date) -> str:
    return f"{d.day} {MONTH_NAMES[d.month]} {d.year}"


def _day(d: date) -> dict:
    return {"year": d.year, "month": d.month, "day": d.day, "start": d, "end": d, "label": _day_label(d)}


def _month(y: int, m: int) -> dict:
    return {"year": y, "month": m, "day": None, "start": date(y, m, 1), "end": _month_end(y, m),
            "label": f"{MONTH_NAMES[m]} {y}"}


def _year(y: int) -> dict:
    return {"year": y, "month": None, "day": None, "start": date(y, 1, 1), "end": date(y, 12, 31), "label": str(y)}


def _range(start: date, end: date) -> dict:
    if start == end:
        return _day(start)
    if start.day == 1 and end == _month_end(end.year, end.month):
        if (start.year, start.month) == (end.year, end.month):
            return _month(start.year, start.month)
        if start.month == 1 and end.month == 12 and start.year == end.year:
            return _year(start.year)
        a = f"{MONTH_NAMES[start.month]}" + ("" if start.year == end.year else f" {start.year}")
        label = f"{a} – {MONTH_NAMES[end.month]} {end.year}"
    elif start.year == end.year:
        label = f"{start.day} {MONTH_NAMES[start.month]} – {_day_label(end)}"
    else:
        label = f"{_day_label(start)} – {_day_label(end)}"
    return {"year": start.year, "month": start.month, "day": None, "start": start, "end": end, "label": label}


def _recent_month(m: int, today: date, strictly_before: bool = False) -> tuple[int, int]:
    y = today.year
    if m > today.month or (strictly_before and m == today.month):
        y -= 1
    return y, m


def _recent_day(m: int, d: int, today: date) -> date:
    y = today.year
    cand = date(y, m, d) if d <= monthrange(y, m)[1] else None
    if cand is None or cand > today:
        y -= 1
        cand = date(y, m, min(d, monthrange(y, m)[1])) if d <= monthrange(y, m)[1] else None
    if cand is None:
        raise ValueError("no such day")
    return cand


def _num(tok: str) -> int:
    return int(tok) if tok.isdigit() else _NUMS[tok]


def _normalise(expr: str) -> str:
    s = expr.lower().replace("’", "'").replace("`", "'")
    s = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", s)
    s = s.replace(",", " ").replace("?", " ").replace("!", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _single(s: str, today: date) -> dict | None:  # noqa: C901 - a flat list of patterns reads best
    def f(p: str):
        return re.search(p, s)

    # ISO and numeric dates
    if m := f(r"\b" + _YEAR + r"-(\d{1,2})-(\d{1,2})\b"):
        try:
            return _day(date(int(m[1]), int(m[2]), int(m[3])))
        except ValueError:
            return None
    if m := f(r"\b(\d{1,2})[/.-](\d{1,2})[/.-]" + _YEAR + r"\b"):        # dd/mm/yyyy (Indian order)
        try:
            return _day(date(int(m[3]), int(m[2]), int(m[1])))
        except ValueError:
            return None
    if m := f(r"\b" + _YEAR + r"-(\d{1,2})\b"):
        if 1 <= int(m[2]) <= 12:
            return _month(int(m[1]), int(m[2]))
    if m := f(r"\b(\d{1,2})/" + _YEAR + r"\b"):
        if 1 <= int(m[1]) <= 12:
            return _month(int(m[2]), int(m[1]))

    # relative days
    if f(r"\bday before yesterday\b") or f(r"\bparson\b"):
        return _day(today - timedelta(days=2))
    if f(r"\byesterday\b"):
        return _day(today - timedelta(days=1))
    if f(r"\b(today|tonight|this morning|this evening|this afternoon|aaj)\b"):
        return _day(today)
    if f(r"\btomorrow\b"):
        return _day(today + timedelta(days=1))
    if m := f(r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|a|an) (day|week|month|year)s? ago\b"):
        n, unit = _num(m[1]), m[2]
        if unit == "day":
            return _day(today - timedelta(days=n))
        if unit == "week":
            mon = today - timedelta(days=today.weekday()) - timedelta(weeks=n)
            return _range(mon, mon + timedelta(days=6))
        if unit == "month":
            y, mo = _add_months(today.year, today.month, -n)
            return _month(y, mo)
        return _year(today.year - n)
    if m := f(r"\b(?:last|past|previous) (\d+|two|three|four|five|six|seven|eight|nine|ten) (day|week|month)s\b"):
        n, unit = _num(m[1]), m[2]
        if unit == "day":
            return _range(today - timedelta(days=n - 1), today)
        if unit == "week":
            return _range(today - timedelta(days=7 * n - 1), today)
        y, mo = _add_months(today.year, today.month, -(n - 1))
        return _range(date(y, mo, 1), today)
    if f(r"\b(last|previous|past) weekend\b"):
        sat = today - timedelta(days=today.weekday()) - timedelta(days=2)
        return _range(sat, sat + timedelta(days=1))
    if f(r"\b(last|previous) week\b") or f(r"\bpichle hafte\b"):
        mon = today - timedelta(days=today.weekday()) - timedelta(weeks=1)
        return _range(mon, mon + timedelta(days=6))
    if f(r"\bthis week\b"):
        return _range(today - timedelta(days=today.weekday()), today)
    if f(r"\b(last|previous) month\b") or f(r"\bpichle mahine\b"):
        return _month(*_add_months(today.year, today.month, -1))
    if f(r"\bthis month\b") or f(r"\bis mahine\b"):
        return _month(today.year, today.month)
    if f(r"\bnext month\b"):
        return _month(*_add_months(today.year, today.month, 1))

    # month + day (+ year)
    if m := f(r"\b(\d{1,2}) " + _M + r"(?: of)? " + _YEAR + r"\b"):
        try:
            return _day(date(int(m[3]), MONTHS[m[2]], int(m[1])))
        except ValueError:
            return None
    if m := f(r"\b" + _M + r" (\d{1,2}) " + _YEAR + r"\b"):
        try:
            return _day(date(int(m[3]), MONTHS[m[1]], int(m[2])))
        except ValueError:
            return None
    # month + year
    if m := f(r"\b" + _M + r"(?: of| in)? " + _YEAR + r"\b"):
        return _month(int(m[2]), MONTHS[m[1]])
    if m := f(r"\b" + _YEAR + r" " + _M + r"\b"):
        return _month(int(m[1]), MONTHS[m[2]])
    if m := f(r"\b" + _M + r" '(\d{2})\b"):
        return _month(2000 + int(m[2]), MONTHS[m[1]])
    # month + day, no year -> most recent occurrence
    for p, mi, di in ((r"\b(\d{1,2}) " + _M + r"\b", 2, 1), (r"\b" + _M + r" (\d{1,2})\b", 1, 2)):
        if m := f(p):
            try:
                return _day(_recent_day(MONTHS[m[mi]], int(m[di]), today))
            except ValueError:
                return None
    # qualified month
    if m := f(r"\b(last|previous) " + _M + r"\b"):
        return _month(*_recent_month(MONTHS[m[2]], today, strictly_before=True))
    if m := f(r"\bthis " + _M + r"\b"):
        return _month(today.year, MONTHS[m[1]])
    if m := f(r"\bnext " + _M + r"\b"):
        mo = MONTHS[m[1]]
        return _month(today.year if mo > today.month else today.year + 1, mo)

    # years
    if f(r"\b(last|previous) year'?s?\b") or f(r"\bpichle saal\b"):
        return _year(today.year - 1)
    if f(r"\bthis year'?s?\b") or f(r"\bis saal\b"):
        return _year(today.year)
    if f(r"\bnext year'?s?\b"):
        return _year(today.year + 1)
    if f(r"\byear before last\b"):
        return _year(today.year - 2)

    # bare month, then bare year
    if m := f(r"\b" + _M + r"\b"):
        tok = m[1]
        if tok == "may" and not re.search(r"\b(in|of|during|since|from|to|till|until|until) may\b|^may$", s):
            pass  # "may" is usually the verb
        else:
            return _month(*_recent_month(MONTHS[tok], today))
    if m := f(r"\b" + _YEAR + r"\b"):
        return _year(int(m[1]))
    return None


def _has_year(s: str) -> bool:
    return bool(re.search(r"\b" + _YEAR + r"\b", s))


def _parse_range(s: str, today: date) -> dict | None:
    m = re.search(r"\bbetween (.+?) and (.+)$", s)
    if not m:
        m = re.search(r"(?:\bfrom )?(.+?)\s+(?:to|till|until|through|thru|-|–|—)\s+(.+)$", s)
    if not m:
        return None
    left, right = m[1].strip(), m[2].strip()
    left = re.sub(r"^.*\bfrom ", "", left)
    r = _single(right, today)
    if not r:
        return None
    lt = left
    # the left side must be date-like by itself ("take me to March 2025" is not a range)
    if not re.search(r"\b(\d{1,4}|" + _M[1:-1] + r"|today|yesterday|last|this|next)\b", left):
        return None
    inherit = not _has_year(left) and _has_year(right)
    if inherit:
        lt = f"{left} {r['end'].year}"
    lc = _single(lt, today)
    if not lc and inherit:
        lc = _single(left, today)
    if not lc:
        return None
    start, end = lc["start"], r["end"]
    if start > end and inherit:
        lc2 = _single(f"{left} {r['end'].year - 1}", today)
        if lc2:
            start = lc2["start"]
    if start > end:
        return None
    return _range(start, end)


def resolve_when(expr: str, tz: str = "Asia/Kolkata", today: date | None = None) -> list[dict]:
    if not expr or not expr.strip():
        return []
    today = today or datetime.now(ZoneInfo(tz or "Asia/Kolkata")).date()
    s = _normalise(expr)
    cand = _parse_range(s, today) or _single(s, today)
    return [cand] if cand else []
