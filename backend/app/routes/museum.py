"""Museum reads: summary, a floor (12 rooms), a room (exhibits, cursor paging) and the Attic."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from .. import db, flags
from ..auth import Session, current_session
from ..core import common, memories, museum

router = APIRouter()


@router.get("/api/museum")
async def museum_summary(s: Session = Depends(current_session)) -> dict:
    fam = await common.family(s.family_id)
    nick = await db.fetchval("SELECT nickname FROM members WHERE id=$1::uuid", s.member_id) if s.member_id else None
    floors = await museum.floors(s.family_id, fam)
    counts = await museum.summary_counts(s.family_id)
    if s.is_guest:
        floors = [f for f in floors if f["year"] == s.invite_room[0]]
        counts = {"attic_count": 0, "latest": None}
    return {
        "family": common.family_public(fam),
        "me": {"member_id": s.member_id, "nickname": nick, "role": s.role, "is_guest": s.is_guest,
               "invite_room": {"year": s.invite_room[0], "month": s.invite_room[1]} if s.invite_room else None},
        "floors": floors,
        **counts,
        "flags": await flags.all_for(s.family_id),
        "bot_username": await common.bot_username(),
        "today": common.tz_today(fam["timezone"]).isoformat(),
    }


@router.get("/api/museum/{year}")
async def museum_floor(year: int, s: Session = Depends(current_session)) -> dict:
    common.guard_room(s, year)
    with common.http_errors():
        data = await museum.year_rooms(s.family_id, year)
    if s.is_guest:
        for r in data["rooms"]:
            if r["month"] != s.invite_room[1]:
                r.update(state="closed", memory_count=0, hero_thumb_url=None, festival=None, events=[],
                         board_text="This door is for the family.")
    return data


@router.get("/api/museum/{year}/{month}")
async def museum_room(year: int, month: int, cursor: Optional[str] = None, limit: int = 50,
                      event_id: Optional[str] = None, s: Session = Depends(current_session)) -> dict:
    if not 1 <= month <= 12:
        raise HTTPException(400, "Month must be 1 to 12.")
    common.guard_room(s, year, month)
    limit = max(1, min(200, limit))
    with common.http_errors():
        data = await museum.year_rooms(s.family_id, year)
        room = data["rooms"][month - 1]
        page = {"exhibits": [], "next_cursor": None}
        if room["state"] == "open":
            page = await memories.room_page(s.family_id, year, month, event_id=event_id, cursor=cursor, limit=limit)
    return {**room, "level": data["level"], **page}


@router.get("/api/attic")
async def attic(s: Session = Depends(current_session)) -> dict:
    if s.is_guest:
        raise HTTPException(403, "This invite opens one room only.")
    return {"memories": await memories.attic(s.family_id)}
