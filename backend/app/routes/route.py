"""POST /api/route: {year, month, event_id?} or {text: "Diwali 2026"} -> {route, question, candidates}."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db
from ..auth import Session, current_session
from ..core import common, routing

router = APIRouter()


class RouteBody(BaseModel):
    year: Optional[int] = None
    month: Optional[int] = None
    event_id: Optional[str] = None
    text: Optional[str] = None


@router.post("/api/route")
async def plan(body: RouteBody, s: Session = Depends(current_session)) -> dict:
    with common.http_errors():
        if body.year is not None and body.month is not None:
            common.guard_room(s, body.year, body.month)
            r = await routing.plan_route(s.family_id, body.year, body.month, body.event_id)
            out = {"route": r, "question": None, "candidates": []}
        elif body.event_id:
            e = await db.fetchrow("SELECT year, month FROM events WHERE id=$1::uuid AND family_id=$2::uuid",
                                  body.event_id, s.family_id)
            if not e:
                raise LookupError("That event isn't in this family's museum.")
            common.guard_room(s, e["year"], e["month"])
            r = await routing.plan_route(s.family_id, e["year"], e["month"], body.event_id)
            out = {"route": r, "question": None, "candidates": []}
        elif body.text:
            res = await routing.resolve_place(s.family_id, body.text)
            cands = res["candidates"]
            if s.is_guest:
                cands = [c for c in cands if (c["year"], c["month"]) == tuple(s.invite_room)]
            if len(cands) == 1 and not res["question"]:
                c = cands[0]
                r = await routing.plan_route(s.family_id, c["year"], c["month"], c["event_id"])
                out = {"route": r, "question": None, "candidates": cands}
            else:
                out = {"route": None, "question": res["question"] or "Which room should I take you to?",
                       "candidates": cands}
        else:
            raise HTTPException(400, "Send a year and month, an event_id, or text.")
    if out["route"]:
        await db.execute("INSERT INTO audit_events(family_id, member_id, type, data) VALUES ($1::uuid,$2::uuid,"
                         "'route_planned',$3::jsonb)", s.family_id, s.member_id,
                         {"year": out["route"]["year"], "month": out["route"]["month"]})
    return out
