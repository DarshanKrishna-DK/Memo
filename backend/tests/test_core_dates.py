"""core-api: dates.resolve_when (pure)."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.dates import resolve_when  # noqa: E402

TODAY = date(2026, 11, 24)   # a Tuesday


def one(expr: str, today: date = TODAY) -> dict:
    c = resolve_when(expr, "Asia/Kolkata", today)
    assert len(c) == 1, f"{expr!r} -> {c}"
    return c[0]


def test_yesterday_today():
    y = one("yesterday")
    assert (y["year"], y["month"], y["day"]) == (2026, 11, 23)
    assert y["start"] == y["end"] == date(2026, 11, 23)
    assert y["label"] == "23 November 2026"
    t = one("photos from today")
    assert t["start"] == TODAY and t["day"] == 24
    assert one("day before yesterday")["start"] == date(2026, 11, 22)
    assert one("3 days ago")["start"] == date(2026, 11, 21)


def test_last_week_is_previous_calendar_week():
    w = one("last week")
    assert w["start"] == date(2026, 11, 16) and w["end"] == date(2026, 11, 22)
    assert w["day"] is None
    assert one("last 7 days")["start"] == date(2026, 11, 18)


def test_month_year():
    m = one("November 2026")
    assert (m["year"], m["month"], m["day"]) == (2026, 11, None)
    assert m["start"] == date(2026, 11, 1) and m["end"] == date(2026, 11, 30)
    assert m["label"] == "November 2026"
    assert one("open March 2025")["start"] == date(2025, 3, 1)
    assert one("2025-03")["month"] == 3
    assert one("last month")["month"] == 10
    assert one("this month")["start"] == date(2026, 11, 1)


def test_day_without_year_is_most_recent_past():
    d = one("Nov 23")
    assert d["start"] == date(2026, 11, 23)
    assert one("23rd November")["start"] == date(2026, 11, 23)
    assert one("Dec 5")["start"] == date(2025, 12, 5)          # Dec 5 2026 is still in the future
    assert one("5 December 2026")["start"] == date(2026, 12, 5)
    assert one("23/11/2026")["start"] == date(2026, 11, 23)     # Indian day/month order
    assert one("2026-11-23")["start"] == date(2026, 11, 23)


def test_years_and_relative_years():
    ly = one("last year's Holi")
    assert ly["year"] == 2025 and ly["month"] is None
    assert ly["start"] == date(2025, 1, 1) and ly["end"] == date(2025, 12, 31)
    assert one("this year")["year"] == 2026
    assert one("Diwali 2024")["year"] == 2024
    assert one("pichle saal")["year"] == 2025


def test_bare_and_qualified_months():
    assert (one("March")["year"], one("March")["month"]) == (2026, 3)
    assert one("December")["year"] == 2025
    assert one("November")["year"] == 2026
    assert one("last November")["year"] == 2025
    assert one("next March")["year"] == 2027


def test_ranges():
    r = one("from 1 Nov to 10 Nov")
    assert r["start"] == date(2026, 11, 1) and r["end"] == date(2026, 11, 10)
    assert r["day"] is None and "–" in r["label"]
    r = one("between March and May 2025")
    assert r["start"] == date(2025, 3, 1) and r["end"] == date(2025, 5, 31)
    r = one("Oct 2025 - Jan 2026")
    assert r["start"] == date(2025, 10, 1) and r["end"] == date(2026, 1, 31)
    r = one("Dec to Feb 2026")                                 # wraps the year end
    assert r["start"] == date(2025, 12, 1) and r["end"] == date(2026, 2, 28)


def test_nothing():
    assert resolve_when("", "Asia/Kolkata", TODAY) == []
    assert resolve_when("the bike photo", "Asia/Kolkata", TODAY) == []
    assert resolve_when("I may go", "Asia/Kolkata", TODAY) == []


def test_default_today_uses_timezone():
    c = resolve_when("today")
    assert c and c[0]["day"] is not None


@pytest.mark.parametrize("expr", ["yesterday", "November 2026", "last week", "Nov 23", "last year's"])
def test_shape(expr):
    c = one(expr)
    assert set(c) == {"year", "month", "day", "start", "end", "label"}


def test_words_around_a_date_are_not_a_range():
    c = one("take me to November 2026")
    assert (c["year"], c["month"], c["start"]) == (2026, 11, date(2026, 11, 1))
    assert one("go to last year's Holi")["year"] == 2025
