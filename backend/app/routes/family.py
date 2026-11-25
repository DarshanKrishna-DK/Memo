"""Family settings and members.
GET/PATCH /api/family, GET /api/family/members, PATCH /api/family/members/{id} (owner), POST /api/family/transfer
(owner), DELETE /api/family {"confirm": "<family name>"} (owner; rows + stored media)."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import auth, db, storage
from ..auth import Session, current_session, require_role
from ..core import common, settings

router = APIRouter()
owner = require_role("owner")


def _member(r) -> dict:
    return {"id": str(r["id"]), "nickname": r["nickname"], "role": r["role"], "language": r["language"],
            "voice_keep_default": r["voice_keep_default"], "quiet": r["quiet"], "joined_at": r["joined_at"].isoformat(),
            "on_telegram": r["telegram_user_id"] is not None}


@router.get("/api/family")
async def get_family(s: Session = Depends(current_session)) -> dict:
    if s.is_guest:
        raise HTTPException(403, "Guests can't see family settings.")
    fam = await common.family(s.family_id)
    out = settings.family_view(fam)
    if s.role == "owner":
        bot = await common.bot_username()
        out["invite_code"] = fam["invite_code"]
        out["invite_link"] = f"https://t.me/{bot}?start={fam['invite_code']}" if bot else None
    return out


class FamilyPatch(BaseModel):
    name: Optional[str] = None
    language: Optional[str] = None
    grandma_name: Optional[str] = None
    settings: Optional[dict[str, Any]] = None


@router.patch("/api/family")
async def patch_family(body: FamilyPatch, s: Session = Depends(owner)) -> dict:
    with common.http_errors():
        if body.name is not None:
            await settings.change_setting(s.family_id, "name", body.name)
        if body.language is not None:
            await settings.change_setting(s.family_id, "language", body.language)
        if body.grandma_name is not None:
            await settings.change_setting(s.family_id, "grandma_name", body.grandma_name)
        for k, v in (body.settings or {}).items():
            if k in settings.BOOL_SETTINGS:
                await settings.change_setting(s.family_id, k, v)
            elif k == "closed_with_care":
                await settings.change_setting(s.family_id, k, v)
            else:
                raise ValueError(f"Unknown setting '{k}'.")
    return await get_family(s)


@router.get("/api/family/members")
async def members(s: Session = Depends(current_session)) -> dict:
    if s.is_guest:
        raise HTTPException(403, "Guests can't see the member list.")
    rows = await db.fetch("SELECT * FROM members WHERE family_id=$1::uuid ORDER BY joined_at", s.family_id)
    return {"members": [_member(r) for r in rows]}


class MemberPatch(BaseModel):
    role: Optional[str] = None
    nickname: Optional[str] = None


@router.patch("/api/family/members/{member_id}")
async def patch_member(member_id: str, body: MemberPatch, s: Session = Depends(owner)) -> dict:
    r = await db.fetchrow("SELECT * FROM members WHERE id=$1::uuid AND family_id=$2::uuid", member_id, s.family_id)
    if not r:
        raise HTTPException(404, "No such member in this family.")
    if body.role is not None:
        if body.role not in ("editor", "viewer"):
            raise HTTPException(400, "Role must be editor or viewer. To hand over ownership use /api/family/transfer.")
        if member_id == s.member_id:
            raise HTTPException(400, "Transfer ownership first, then change your own role.")
        await db.execute("UPDATE members SET role=$2 WHERE id=$1::uuid", member_id, body.role)
        await db.execute("UPDATE sessions SET role=$2 WHERE member_id=$1::uuid AND invite_id IS NULL",
                         member_id, body.role)
    if body.nickname is not None:
        nick = body.nickname.strip()
        if not nick or len(nick) > 60:
            raise HTTPException(400, "Nickname should be 1 to 60 characters.")
        await db.execute("UPDATE members SET nickname=$2 WHERE id=$1::uuid", member_id, nick)
    r = await db.fetchrow("SELECT * FROM members WHERE id=$1::uuid", member_id)
    return _member(r)


class TransferBody(BaseModel):
    member_id: str


@router.post("/api/family/transfer")
async def transfer(body: TransferBody, s: Session = Depends(owner)) -> dict:
    if body.member_id == s.member_id:
        raise HTTPException(400, "You already own this family.")
    async with db.acquire() as c:
        async with c.transaction():
            t = await c.fetchrow("SELECT id FROM members WHERE id=$1::uuid AND family_id=$2::uuid",
                                 body.member_id, s.family_id)
            if not t:
                raise HTTPException(404, "No such member in this family.")
            await c.execute("UPDATE members SET role='owner' WHERE id=$1::uuid", body.member_id)
            await c.execute("UPDATE members SET role='editor' WHERE id=$1::uuid", s.member_id)
            await c.execute("UPDATE sessions SET role='owner' WHERE member_id=$1::uuid AND invite_id IS NULL",
                            body.member_id)
            await c.execute("UPDATE sessions SET role='editor' WHERE member_id=$1::uuid AND invite_id IS NULL",
                            s.member_id)
    return {"owner_id": body.member_id, "your_role": "editor"}


class DeleteBody(BaseModel):
    confirm: str


@router.delete("/api/family")
async def delete_family(body: DeleteBody, s: Session = Depends(owner)) -> JSONResponse:
    fam = await common.family(s.family_id)
    if body.confirm.strip() != fam["name"]:
        raise HTTPException(400, "Type the family name exactly to confirm deleting everything.")
    await db.execute("DELETE FROM families WHERE id=$1::uuid", s.family_id)
    storage.delete_prefix(s.family_id)
    resp = JSONResponse({"deleted": True})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp
