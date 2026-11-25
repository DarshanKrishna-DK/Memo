"""The guided walk. The server resolves words to a room and draws the route; the client only plays it.

MuseumRoute (web/src/contract.ts): {year, month, event_id, level, needs_lift, room_state, board_text,
waypoints:[{kind: desk|lift|ride|corridor|door|seat, level, door_index?}], walk_seconds}
"""
from __future__ import annotations

import re

from .. import db, flags
from . import common, dates, events, museum

MONTH_NAMES = dates.MONTH_NAMES


def _walk_seconds(flag, needs_lift: bool) -> int:
    """cinematic_walk = {"enabled": bool, "seconds": n}. Off -> 0 (a straight cut). On: a ground-floor walk takes
    5 s; a walk with the lift takes the flag's seconds clamped to 5..10 (default 10)."""
    enabled, secs = True, 10
    if isinstance(flag, dict):
        enabled = bool(flag.get("enabled", True))
        secs = flag.get("seconds", 10)
    elif isinstance(flag, bool):
        enabled = flag
    elif isinstance(flag, (int, float)):
        enabled, secs = flag > 0, flag
    if not enabled:
        return 0
    try:
        secs = int(round(float(secs)))
    except (TypeError, ValueError):
        secs = 10
    lift = max(5, min(10, secs))
    return lift if needs_lift else min(5, lift)


async def plan_route(family_id, year, month, event_id=None) -> dict:
    year, month = int(year), int(month)
    if not (1 <= month <= 12):
        raise ValueError("Month must be 1 to 12.")
    family_id = str(family_id)
    fam = await common.family(family_id)
    if event_id:
        ev = await events.get_event(family_id, event_id)
        if (ev["year"], ev["month"]) != (year, month):
            raise ValueError("That event belongs to a different room.")
    first, last = await museum.year_span(family_id, fam)
    if year < first or year > last:
        raise LookupError(f"The museum has no floor for {year} yet. Floors run from {first} to {last}.")
    level = museum.floor_level(first, year)
    st = await museum.room_state(family_id, year, month)
    needs_lift = level > 0
    door = month - 1
    wps: list[dict] = [{"kind": "desk", "level": 0}]
    if needs_lift:
        wps += [{"kind": "lift", "level": 0}, {"kind": "ride", "level": level}]
    wps += [{"kind": "corridor", "level": level}, {"kind": "door", "level": level, "door_index": door}]
    if st["state"] == "open":
        wps.append({"kind": "seat", "level": level, "door_index": door})
    return {
        "year": year, "month": month, "event_id": str(event_id) if event_id else None, "level": level,
        "needs_lift": needs_lift, "room_state": st["state"], "board_text": st["board_text"], "waypoints": wps,
        "walk_seconds": _walk_seconds(await flags.get("cinematic_walk", family_id), needs_lift),
    }


_FILLER = re.compile(
    r"\b(please|take me to|take me|bring me to|go to|go|open up|open|show me|show|walk me to|let's go to|visit|"
    r"the|room|rooms|floor|door|museum|of|for|to|my|our|memories|memory|photos|pics|in|on|from|at|please)\b")
_DATE_WORDS = re.compile(
    r"\b(last|this|next|previous|year'?s?|years|month'?s?|week|ago|today|yesterday|tomorrow|"
    r"(?:19|20|21)\d{2}|\d{1,2}|" + dates._M[1:-1] + r")\b")


def _label(year: int, month: int, name: str | None = None) -> str:
    base = f"{MONTH_NAMES[month]} {year}"
    return f"{name} ({base})" if name else base


async def resolve_place(family_id, text: str) -> dict:
    """Free words -> {"candidates":[{year,month,event_id,label}], "question": str|None}.
    One candidate = go. Several or none = ask the question (one clarifying question at most)."""
    family_id = str(family_id)
    fam = await common.family(family_id)
    raw = (text or "").strip()
    if not raw:
        return {"candidates": [], "question": "Which room should I take you to?"}
    low = raw.lower().replace("’", "'")
    when = dates.resolve_when(low, fam["timezone"])
    w = when[0] if when else None
    # the name part: what is left after removing filler and date words
    rest = _DATE_WORDS.sub(" ", _FILLER.sub(" ", low))
    rest = re.sub(r"[^\w\s'-]", " ", rest)
    rest = re.sub(r"\s+", " ", rest).strip(" '-")
    fest = events.festival_in(low)
    name = fest or (rest if len(rest) >= 3 else None)

    if not name:
        if w and w["month"]:
            return {"candidates": [{"year": w["year"], "month": w["month"], "event_id": None,
                                    "label": _label(w["year"], w["month"])}], "question": None}
        if w:
            return {"candidates": [], "question": f"Which month of {w['label']}?"}
        return {"candidates": [], "question": "Which room should I take you to? Say a month and year, or an event."}

    year = w["year"] if w else None
    month = w["month"] if (w and w["month"] and (w["start"].year, w["start"].month)
                           == (w["end"].year, w["end"].month)) else None
    cands: dict[tuple, dict] = {}
    for e in await events.find_events(family_id, name, year):
        if month and e["month"] != month:
            continue
        cands[(e["year"], e["month"], e["id"])] = {"year": e["year"], "month": e["month"], "event_id": e["id"],
                                                     "label": _label(e["year"], e["month"], e["name"])}
    # memories tagged with the festival but not tied to an event
    pat = f"%{fest or name}%"
    rows = await db.fetch(
        "SELECT DISTINCT event_year, event_month FROM memories WHERE family_id=$1::uuid AND status='saved' "
        "AND event_year IS NOT NULL AND event_month IS NOT NULL AND (festival ILIKE $2 OR title ILIKE $2) "
        "AND ($3::int IS NULL OR event_year=$3) ORDER BY event_year DESC, event_month DESC", family_id, pat, year)
    have = {(c["year"], c["month"]) for c in cands.values()}
    for r in rows:
        ym = (r["event_year"], r["event_month"])
        if ym in have or (month and ym[1] != month):
            continue
        have.add(ym)
        cands[(ym[0], ym[1], None)] = {"year": ym[0], "month": ym[1], "event_id": None,
                                       "label": _label(ym[0], ym[1], fest or name.title())}
    out = sorted(cands.values(), key=lambda c: (-c["year"], -c["month"]))
    display = fest or name.title()
    if not out and fest and year:
        fm = month or events.festival_month(fest, year)
        if fm:
            out = [{"year": year, "month": fm, "event_id": None, "label": _label(year, fm, fest)}]
        else:
            return {"candidates": [], "question": f"Which month was {fest} in {year}?"}
    if not out and w and w["month"]:
        # unknown name but a clear month: go to the month
        return {"candidates": [{"year": w["year"], "month": w["month"], "event_id": None,
                                "label": _label(w["year"], w["month"])}], "question": None}
    if not out:
        q = f"Which year of {display}?" if fest else f"I couldn't find {display}. Which month and year was it?"
        return {"candidates": [], "question": q}
    if len(out) == 1:
        return {"candidates": out, "question": None}
    years = sorted({c["year"] for c in out}, reverse=True)
    if len(years) > 1:
        q = f"Which year of {display}? " + ", ".join(str(y) for y in years[:5]) + "?"
    else:
        q = "Which one: " + " or ".join(c["label"] for c in out[:4]) + "?"
    return {"candidates": out, "question": q}
