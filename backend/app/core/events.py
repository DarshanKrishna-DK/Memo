"""Events: a name, a kind, a year and a month. The year/month decide floor and room like any memory."""
from __future__ import annotations

import re

from .. import db
from . import common, museum

KINDS = ("festival", "trip", "birthday", "other")

# Curated list, used only to recognise a festival (never required). alias -> canonical name.
FESTIVALS = {
    "diwali": "Diwali", "deepavali": "Diwali", "deepawali": "Diwali", "holi": "Holi", "eid": "Eid",
    "eid al-fitr": "Eid", "eid ul-fitr": "Eid", "ramzan": "Eid", "bakrid": "Bakrid", "eid al-adha": "Bakrid",
    "christmas": "Christmas", "xmas": "Christmas", "pongal": "Pongal", "onam": "Onam", "navratri": "Navratri",
    "navaratri": "Navratri", "dussehra": "Dussehra", "dasara": "Dussehra", "dasra": "Dussehra",
    "durga puja": "Durga Puja", "ganesh chaturthi": "Ganesh Chaturthi", "ganeshotsav": "Ganesh Chaturthi",
    "ganesha chaturthi": "Ganesh Chaturthi", "raksha bandhan": "Raksha Bandhan", "rakhi": "Raksha Bandhan",
    "janmashtami": "Janmashtami", "ugadi": "Ugadi", "gudi padwa": "Gudi Padwa", "sankranti": "Sankranti",
    "makar sankranti": "Sankranti", "lohri": "Lohri", "baisakhi": "Baisakhi", "vaisakhi": "Baisakhi",
    "vishu": "Vishu", "bihu": "Bihu", "karwa chauth": "Karwa Chauth", "bhai dooj": "Bhai Dooj",
    "easter": "Easter", "new year": "New Year", "guru nanak jayanti": "Guru Nanak Jayanti",
    "mahashivratri": "Maha Shivaratri", "shivratri": "Maha Shivaratri",
}
# Month a festival falls in when the family has recorded nothing about it (fallback for the guided walk only).
FIXED_MONTH = {"Christmas": 12, "Pongal": 1, "Sankranti": 1, "Lohri": 1, "Baisakhi": 4, "Vishu": 4,
               "New Year": 1, "Holi": 3}
DIWALI_MONTH = {2018: 11, 2019: 10, 2020: 11, 2021: 11, 2022: 10, 2023: 11, 2024: 10, 2025: 10, 2026: 11,
                2027: 10, 2028: 10, 2029: 11, 2030: 10}


def festival_in(text: str) -> str | None:
    t = (text or "").lower()
    for alias in sorted(FESTIVALS, key=len, reverse=True):
        if re.search(r"\b" + re.escape(alias) + r"\b", t):
            return FESTIVALS[alias]
    return None


def festival_month(festival: str, year: int) -> int | None:
    if festival == "Diwali":
        return DIWALI_MONTH.get(year)
    return FIXED_MONTH.get(festival)


def _event(r) -> dict:
    return {"id": str(r["id"]), "name": r["name"], "kind": r["kind"], "year": r["year"], "month": r["month"],
            "created_by": common.sid(r["created_by"]), "created_at": r["created_at"].isoformat(),
            **({"memory_count": int(r["memory_count"])} if "memory_count" in r.keys() else {})}


async def get_event(family_id, event_id) -> dict:
    r = await db.fetchrow("SELECT e.*, (SELECT count(*) FROM memories m WHERE m.event_id=e.id AND m.status='saved') "
                          "AS memory_count FROM events e WHERE e.id=$1::uuid AND e.family_id=$2::uuid",
                          str(event_id), str(family_id))
    if not r:
        raise LookupError("That event isn't in this family's museum.")
    return _event(r)


async def create_event(family_id, member_id, name, kind, year, month) -> dict:
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not name or len(name) > 120:
        raise ValueError("An event needs a short name.")
    year, month = int(year), int(month)
    if not (1900 <= year <= 2200 and 1 <= month <= 12):
        raise ValueError("That isn't a valid year and month.")
    if kind not in KINDS:
        kind = "festival" if festival_in(name) else ("birthday" if "birthday" in name.lower() else "other")
    existing = await db.fetchrow(
        "SELECT * FROM events WHERE family_id=$1::uuid AND lower(name)=lower($2) AND year=$3 AND month=$4",
        str(family_id), name, year, month)
    row = existing or await db.fetchrow(
        "INSERT INTO events(family_id, name, kind, year, month, created_by) VALUES ($1::uuid,$2,$3,$4,$5,$6::uuid) "
        "RETURNING *", str(family_id), name, kind, year, month, common.sid(member_id))
    first, _ = await museum.year_span(str(family_id))
    st = await museum.room_state(str(family_id), year, month)
    return {"event": _event(row), "level": museum.floor_level(first, year), "room": {"year": year, "month": month},
            "room_state": st, "created": existing is None}


async def find_events(family_id, name: str | None, year: int | None = None) -> list[dict]:
    q = ("SELECT e.*, (SELECT count(*) FROM memories m WHERE m.event_id=e.id AND m.status='saved') AS memory_count "
         "FROM events e WHERE e.family_id=$1::uuid")
    args: list = [str(family_id)]
    if name:
        fest = festival_in(name)
        args.append(f"%{name.strip()}%")
        cond = f"e.name ILIKE ${len(args)}"
        if fest:
            args.append(f"%{fest}%")
            cond = f"({cond} OR e.name ILIKE ${len(args)})"
            # match any alias of the same festival (e.g. Deepavali for Diwali)
            for alias, canon in FESTIVALS.items():
                if canon == fest and alias != fest.lower():
                    args.append(f"%{alias}%")
                    cond = cond[:-1] + f" OR e.name ILIKE ${len(args)})"
        q += f" AND {cond}"
    if year:
        args.append(int(year))
        q += f" AND e.year=${len(args)}"
    q += " ORDER BY e.year DESC, e.month DESC, e.created_at DESC"
    return [_event(r) for r in await db.fetch(q, *args)]
