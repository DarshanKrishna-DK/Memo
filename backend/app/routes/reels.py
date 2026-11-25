"""Video reels. POST creates a row + enqueues render_reel; poll GET /api/reels/{id} or listen for reel_ready."""
from __future__ import annotations

import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db, flags, jobs, storage
from ..auth import Session, current_session, require_role

router = APIRouter()


class ReelIn(BaseModel):
    year: int = Field(ge=1900, le=2200)
    month: int = Field(ge=1, le=12)
    event_id: Optional[str] = None
    narrated: bool = False
    aspect: Literal["16:9", "9:16"] = "16:9"


def _out(r) -> dict:
    return {"id": str(r["id"]), "year": r["year"], "month": r["month"],
            "event_id": str(r["event_id"]) if r["event_id"] else None, "status": r["status"],
            "narrated": r["narrated"], "aspect": r["aspect"], "duration_s": r["duration_s"], "error": r["error"],
            "url": storage.signed_url(r["storage_key"]) if r["status"] == "ready" else None,
            "created_at": r["created_at"].isoformat(), "updated_at": r["updated_at"].isoformat()}


def _can_read(s: Session, year: int, month: int) -> None:
    if s.is_guest and s.invite_room != (year, month):
        raise HTTPException(403, "This guest link only opens one room.")


@router.post("/api/reels", status_code=202)
async def create_reel(body: ReelIn, s: Session = Depends(require_role("owner", "editor"))):
    if not await flags.get("video_reels", s.family_id):
        raise HTTPException(403, "Video reels are switched off for this family.")
    if body.event_id:
        try:
            ok = await db.fetchval("SELECT 1 FROM events WHERE id=$1::uuid AND family_id=$2::uuid",
                                   body.event_id, s.family_id)
        except Exception:  # noqa: BLE001
            ok = None
        if not ok:
            raise HTTPException(404, "That event is not in this family.")
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE family_id=$1::uuid AND status='saved' AND event_year=$2 "
        "AND event_month=$3 AND ($4::uuid IS NULL OR event_id=$4::uuid)",
        s.family_id, body.year, body.month, body.event_id)
    if not n:
        raise HTTPException(400, "This room has no saved memories yet, so there is nothing to put in a reel.")
    busy = await db.fetchrow(
        "SELECT * FROM reels WHERE family_id=$1::uuid AND year=$2 AND month=$3 AND status IN ('queued','rendering') "
        "AND event_id IS NOT DISTINCT FROM $4::uuid AND aspect=$5 AND narrated=$6",
        s.family_id, body.year, body.month, body.event_id, body.aspect, body.narrated)
    if busy:
        return _out(busy)
    r = await db.fetchrow(
        "INSERT INTO reels(family_id, year, month, event_id, narrated, aspect, requested_by) "
        "VALUES ($1::uuid,$2,$3,$4::uuid,$5,$6,$7::uuid) RETURNING *",
        s.family_id, body.year, body.month, body.event_id, body.narrated, body.aspect, s.member_id)
    await jobs.enqueue("render_reel", {"reel_id": str(r["id"])}, max_attempts=2)
    return _out(r)


@router.get("/api/reels")
async def list_reels(year: Optional[int] = None, month: Optional[int] = None,
                     s: Session = Depends(current_session)):
    if s.is_guest:
        year, month = s.invite_room
    rows = await db.fetch(
        "SELECT * FROM reels WHERE family_id=$1::uuid AND ($2::int IS NULL OR year=$2) "
        "AND ($3::int IS NULL OR month=$3) ORDER BY created_at DESC LIMIT 100", s.family_id, year, month)
    return {"reels": [_out(r) for r in rows]}


async def _row(reel_id: str, s: Session):
    try:
        rid = str(uuid.UUID(reel_id))
    except ValueError:
        raise HTTPException(404, "Reel not found.") from None
    r = await db.fetchrow("SELECT * FROM reels WHERE id=$1::uuid AND family_id=$2::uuid", rid, s.family_id)
    if not r:
        raise HTTPException(404, "Reel not found.")
    return r


@router.get("/api/reels/{reel_id}")
async def get_reel(reel_id: str, s: Session = Depends(current_session)):
    r = await _row(reel_id, s)
    _can_read(s, r["year"], r["month"])
    return _out(r)


@router.delete("/api/reels/{reel_id}")
async def delete_reel(reel_id: str, s: Session = Depends(require_role("owner", "editor"))):
    r = await _row(reel_id, s)
    if r["status"] == "rendering":
        raise HTTPException(409, "This reel is rendering right now. Try again when it finishes.")
    storage.delete(r["storage_key"])
    await db.execute("DELETE FROM reels WHERE id=$1", r["id"])
    return {"ok": True}
