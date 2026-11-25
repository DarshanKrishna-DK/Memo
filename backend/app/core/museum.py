"""The museum is computed from saved memories: floors from years, rooms from months, boards from state.

Floors use one FIXED calendar for every family (and every public link): the ground floor, beside the lobby, is
2002 and each later year is one floor up. level = year - 2002 (0 = ground / lobby level, what the 3D lift uses);
the floor number people see = year - 2001 (2002 = floor 1, the ground floor; 2026 = floor 25). Years before 2002
go below ground as basements (2001 = basement 1, 2000 = basement 2, ...): the same formula, no special case.
Floors run up to the current year + 1. Only years that hold something (plus the ground and the current year) are
listed as floors; any other year in range still has a floor (all doors shut) when a route asks for it.

States: open (>=1 saved memory) / locked (past, empty) / not_yet (future) / current_empty / closed (closed_with_care).
Board text is deterministic per family+year+month+state (sha256 pick), so a room shows the same line every visit.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .. import db, storage
from . import common

LOCKED = [
    "Nothing happened here. Or nobody told me.",
    "Life got boring. Allegedly.",
    "No memories, no door. Rules are rules.",
    "Dust only. Tell me something and I'll open up.",
    "A whole month and not one story? Bold.",
]
NOT_YET = ["Hasn't happened yet. Stop peeking.", "Come back after you've lived it."]
CURRENT_EMPTY = ["This month is still loading. Give it a few days."]
FLOOR_EMPTY = "A whole year with nothing. Impressive, honestly."
CLOSED = "Closed with care."
NEUTRAL = "No memories here yet."
PROMPT = "Tell {grandma} on Telegram to open this door."


GROUND_YEAR = 2002
MIN_YEAR = 1900


def floor_level(year: int) -> int:
    """0 = the ground floor (2002, beside the lobby); 24 = 2026; negative = basement (before 2002)."""
    return int(year) - GROUND_YEAR


def floor_number(year: int) -> int:
    """The floor number people see: 2002 -> 1 (the ground floor), 2026 -> 25. <= 0 before 2002 (basements)."""
    return int(year) - (GROUND_YEAR - 1)


def floor_name(year: int) -> str:
    """English label: 'the ground floor' (2002), 'floor 25' (2026), 'basement 1' (2001)."""
    lvl = floor_level(year)
    if lvl == 0:
        return "the ground floor"
    return f"floor {floor_number(year)}" if lvl > 0 else f"basement {-lvl}"


def last_year(fam: dict) -> int:
    """The highest floor: the current year + 1 (a planned trip next year can have its room)."""
    return common.tz_today(fam["timezone"]).year + 1


def _pick(lines: list[str], family_id: Any, year: int, month: int, state: str) -> str:
    h = hashlib.sha256(f"{family_id}|{year}|{month}|{state}".encode()).hexdigest()
    return lines[int(h, 16) % len(lines)]


def board_text(family_id, year, month, state, grandma_name, sarcasm_on, floor_empty: bool = False) -> str | None:
    """Deterministic board line. floor_empty=True (a past year with no memory at all) uses the whole-floor line."""
    g = grandma_name or "Grandma"
    prompt = PROMPT.format(grandma=g)
    if state == "open":
        return None
    if state == "closed":
        return CLOSED
    if not sarcasm_on:
        return NEUTRAL if state == "not_yet" else f"{NEUTRAL} {prompt}"
    if state == "not_yet":
        return _pick(NOT_YET, family_id, year, month, state)
    if state == "current_empty":
        return f"{_pick(CURRENT_EMPTY, family_id, year, month, state)} {prompt}"
    if floor_empty:
        return f"{FLOOR_EMPTY} {prompt}"
    return f"{_pick(LOCKED, family_id, year, month, state)} {prompt}"


def _state(count: int, closed: bool, year: int, month: int, cur: tuple[int, int]) -> str:
    if closed:
        return "closed"
    if count > 0:
        return "open"
    if (year, month) > cur:
        return "not_yet"
    if (year, month) == cur:
        return "current_empty"
    return "locked"


async def floor_years(family_id: str, fam: dict | None = None) -> list[int]:
    """Years listed as floors, newest first: the ground (2002), the current year, and every year (<= current + 1)
    that holds a saved memory or an event. Empty years in between are skipped (no geometry, no lift button)."""
    fam = fam or await common.family(family_id)
    cur = common.tz_today(fam["timezone"]).year
    top = cur + 1
    rows = await db.fetch(
        "SELECT DISTINCT event_year AS y FROM memories WHERE family_id=$1::uuid AND status='saved' "
        "AND event_year IS NOT NULL UNION SELECT DISTINCT year FROM events WHERE family_id=$1::uuid", family_id)
    years = {GROUND_YEAR, cur} | {int(r["y"]) for r in rows if MIN_YEAR <= int(r["y"]) <= top}
    return sorted(years, reverse=True)


async def year_rooms(family_id: str, year: int, fam: dict | None = None) -> dict:
    """All 12 rooms of one floor (Room dicts per web/src/contract.ts) plus the floor's level and board."""
    fam = fam or await common.family(family_id)
    today = common.tz_today(fam["timezone"])
    cur = (today.year, today.month)
    sarcasm = await common.sarcasm_on(family_id, fam)
    counts = {r["event_month"]: r for r in await db.fetch(
        "SELECT event_month, count(*) AS n, "
        "       bool_or(sensitivity <> 'none') AS sensitive, "
        "       mode() WITHIN GROUP (ORDER BY festival) FILTER (WHERE festival IS NOT NULL) AS festival "
        "FROM memories WHERE family_id=$1::uuid AND status='saved' AND event_year=$2 GROUP BY event_month",
        family_id, year)}
    closed = {r["month"] for r in await db.fetch(
        "SELECT month FROM room_settings WHERE family_id=$1::uuid AND year=$2 AND mode='closed_with_care'",
        family_id, year)}
    heroes = {r["event_month"]: r["thumb_key"] for r in await db.fetch(
        "SELECT DISTINCT ON (m.event_month) m.event_month, md.thumb_key "
        "FROM memories m JOIN media md ON md.memory_id=m.id "
        "WHERE m.family_id=$1::uuid AND m.status='saved' AND m.event_year=$2 AND md.type IN ('photo','video') "
        "      AND md.thumb_key IS NOT NULL "
        "ORDER BY m.event_month, md.is_blurry, m.event_day NULLS LAST, md.sort_order, md.created_at",
        family_id, year)}
    events: dict[int, list] = {}
    for e in await db.fetch("SELECT id, name, kind, month FROM events WHERE family_id=$1::uuid AND year=$2 "
                            "ORDER BY created_at", family_id, year):
        events.setdefault(e["month"], []).append({"id": str(e["id"]), "name": e["name"], "kind": e["kind"]})
    total = sum(r["n"] for r in counts.values())
    floor_empty = total == 0 and year < today.year
    # P1 kindness: a year that holds a sensitive memory gets neutral boards on its empty months.
    year_sensitive = any(r["sensitive"] for r in counts.values())
    rooms = []
    for month in range(1, 13):
        r = counts.get(month)
        n = int(r["n"]) if r else 0
        st = _state(n, month in closed, year, month, cur)
        rooms.append({
            "year": year, "month": month, "state": st, "memory_count": n if st != "closed" else 0,
            "hero_thumb_url": storage.signed_url(heroes.get(month)) if st == "open" else None,
            "festival": (r["festival"] if r else None) if st == "open" else None,
            "board_text": board_text(family_id, year, month, st, fam["grandma_name"],
                                     sarcasm and not year_sensitive, floor_empty=floor_empty),
            "events": events.get(month, []) if st != "closed" else [],
        })
    open_n = sum(1 for x in rooms if x["state"] == "open")
    floor_board = None
    if floor_empty:
        floor_board = FLOOR_EMPTY if sarcasm else NEUTRAL
    return {"year": year, "level": floor_level(year), "floor_number": floor_number(year), "open": open_n, "total": 12,
            "floor_board": floor_board, "rooms": rooms}


async def room_state(family_id, year, month) -> dict:
    fam = await common.family(family_id)
    data = await year_rooms(family_id, int(year), fam)
    r = data["rooms"][int(month) - 1]
    return {"state": r["state"], "memory_count": r["memory_count"], "board_text": r["board_text"]}


async def floors(family_id: str, fam: dict | None = None) -> list[dict]:
    """FloorSummary list, newest first: the ground (2002), the current year and every year holding something."""
    fam = fam or await common.family(family_id)
    years = await floor_years(family_id, fam)
    closed = {(r["year"], r["month"]) for r in await db.fetch(
        "SELECT year, month FROM room_settings WHERE family_id=$1::uuid AND mode='closed_with_care'", family_id)}
    opened: dict[int, set] = {}
    for r in await db.fetch(
            "SELECT DISTINCT event_year, event_month FROM memories WHERE family_id=$1::uuid AND status='saved' "
            "AND event_year IS NOT NULL AND event_month IS NOT NULL", family_id):
        if (r["event_year"], r["event_month"]) not in closed:
            opened.setdefault(r["event_year"], set()).add(r["event_month"])
    return [{"year": y, "open": len(opened.get(y, ())), "total": 12, "level": floor_level(y),
             "floor_number": floor_number(y)} for y in years]


async def summary_counts(family_id: str) -> dict:
    attic = await db.fetchval("SELECT count(*) FROM memories WHERE family_id=$1::uuid AND status='attic'", family_id)
    latest = await db.fetchrow(
        "SELECT m.id, coalesce(m.title, m.summary, left(m.text_original, 60)) AS title, m.event_year, m.event_month, "
        "  (SELECT md.thumb_key FROM media md WHERE md.memory_id=m.id AND md.type IN ('photo','video') "
        "   ORDER BY md.sort_order, md.created_at LIMIT 1) AS thumb_key "
        "FROM memories m WHERE m.family_id=$1::uuid AND m.status='saved' "
        "AND NOT EXISTS (SELECT 1 FROM room_settings rs WHERE rs.family_id=m.family_id AND rs.year=m.event_year "
        "                AND rs.month=m.event_month AND rs.mode='closed_with_care') "
        "ORDER BY m.created_at DESC LIMIT 1", family_id)
    return {
        "attic_count": int(attic or 0),
        "latest": {"id": str(latest["id"]), "title": latest["title"] or "", "year": latest["event_year"],
                   "month": latest["event_month"], "thumb_url": storage.signed_url(latest["thumb_key"])}
        if latest else None,
    }
