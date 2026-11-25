"""GET /api/showcase/{year}/{month}?event_id= -> {"items": [ShowcaseItem], "total_s", ...}"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from ..auth import Session, current_session
from ..core import common, museum, showcase

router = APIRouter()


@router.get("/api/showcase/{year}/{month}")
async def get_showcase(year: int, month: int, event_id: Optional[str] = None,
                       s: Session = Depends(current_session)) -> dict:
    if not 1 <= month <= 12:
        raise HTTPException(400, "Month must be 1 to 12.")
    common.guard_room(s, year, month)
    with common.http_errors():
        st = await museum.room_state(s.family_id, year, month)
        items = await showcase.build_showcase(s.family_id, year, month, event_id) if st["state"] == "open" else []
    return {"year": year, "month": month, "event_id": event_id, "room_state": st["state"], "items": items,
            "total_s": sum(i["duration_s"] for i in items)}
