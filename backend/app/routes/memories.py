"""Memory edits. Owner: any memory. Editor: own memories, or any when family setting editors_edit_others."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel

from ..auth import Session, current_session, require_role
from ..core import common, memories

router = APIRouter()
writer = require_role("owner", "editor")


class DateBody(BaseModel):
    year: int
    month: int
    day: Optional[int] = None


class NarrateBody(BaseModel):
    narrate_ok: bool


@router.get("/api/memories/{memory_id}")
async def get_memory(memory_id: str, s: Session = Depends(current_session)) -> dict:
    with common.http_errors():
        e = await memories.get_memory(s.family_id, memory_id)
        if s.is_guest:
            d = e["event_date"]
            common.guard_room(s, d["year"] or 0, d["month"])
    return e


@router.patch("/api/memories/{memory_id}")
async def edit_memory(memory_id: str, body: dict[str, Any], s: Session = Depends(writer)) -> dict:
    with common.http_errors():
        await memories.check_edit(s.family_id, s.member_id, s.role, memory_id)
        return await memories.edit_memory(s.family_id, memory_id, body)


@router.delete("/api/memories/{memory_id}")
async def delete_memory(memory_id: str, s: Session = Depends(writer)) -> Response:
    with common.http_errors():
        await memories.check_edit(s.family_id, s.member_id, s.role, memory_id)
        await memories.delete_memory(s.family_id, memory_id)
    return Response(status_code=204)


@router.post("/api/memories/{memory_id}/narrate_ok")
async def narrate_ok(memory_id: str, body: NarrateBody, s: Session = Depends(writer)) -> dict:
    with common.http_errors():
        await memories.check_edit(s.family_id, s.member_id, s.role, memory_id)
        return await memories.edit_memory(s.family_id, memory_id, {"narrate_ok": body.narrate_ok})


@router.post("/api/memories/{memory_id}/date")
@router.post("/api/memories/{memory_id}/move")
async def move_memory(memory_id: str, body: DateBody, s: Session = Depends(writer)) -> dict:
    with common.http_errors():
        await memories.check_edit(s.family_id, s.member_id, s.role, memory_id)
        await memories.move_memory(s.family_id, memory_id, body.year, body.month, body.day)
        return await memories.get_memory(s.family_id, memory_id)
