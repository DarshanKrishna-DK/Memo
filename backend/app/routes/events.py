"""Events: POST creates (name, kind, year+month or free words in `when`), GET finds by name/year."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import Session, current_session, require_role
from ..core import common, dates, events

router = APIRouter()


class EventBody(BaseModel):
    name: str
    kind: Optional[str] = None
    year: Optional[int] = None
    month: Optional[int] = None
    when: Optional[str] = None


@router.post("/api/events")
async def create_event(body: EventBody, s: Session = Depends(require_role("owner", "editor"))) -> dict:
    year, month = body.year, body.month
    if (year is None or month is None) and body.when:
        fam = await common.family(s.family_id)
        c = dates.resolve_when(body.when, fam["timezone"])
        if c and c[0]["month"]:
            year, month = c[0]["year"], c[0]["month"]
        elif c and year is None:
            year = c[0]["year"]
    if year is None or month is None:
        raise HTTPException(400, "An event needs a year and a month.")
    with common.http_errors():
        return await events.create_event(s.family_id, s.member_id, body.name, body.kind or "", year, month)


@router.get("/api/events")
async def list_events(name: Optional[str] = None, year: Optional[int] = None,
                      s: Session = Depends(current_session)) -> dict:
    found = await events.find_events(s.family_id, name, year)
    if s.is_guest:
        found = [e for e in found if (e["year"], e["month"]) == tuple(s.invite_room)]
    return {"events": found}


@router.get("/api/events/{event_id}")
async def get_event(event_id: str, s: Session = Depends(current_session)) -> dict:
    with common.http_errors():
        e = await events.get_event(s.family_id, event_id)
    common.guard_room(s, e["year"], e["month"])
    return e
