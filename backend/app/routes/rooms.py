"""POST /api/rooms/{year}/{month}/mode {"mode": "auto" | "closed_with_care"}"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import Session, require_role
from ..core import common, museum, settings

router = APIRouter()


class ModeBody(BaseModel):
    mode: str


@router.post("/api/rooms/{year}/{month}/mode")
async def set_mode(year: int, month: int, body: ModeBody, s: Session = Depends(require_role("owner", "editor"))):
    with common.http_errors():
        if body.mode not in ("auto", "closed_with_care"):
            raise ValueError("mode must be auto or closed_with_care.")
        await settings.change_setting(s.family_id, "closed_with_care",
                                      {"year": year, "month": month, "closed": body.mode == "closed_with_care"})
        st = await museum.room_state(s.family_id, year, month)
    return {"year": year, "month": month, "mode": body.mode, **st}
