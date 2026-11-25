"""Invites: create, list, call, guest join link, and host playback sync."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from .. import auth, bus, config, db, jobs
from ..auth import Session, current_session, require_role
from ..phone import invites as inv

log = logging.getLogger("memo.invites")
router = APIRouter()
BOT_AGENTS = ("telegrambot", "whatsapp", "facebookexternalhit", "twitterbot", "slackbot", "discordbot", "linkedinbot",
              "skypeuripreview", "googlebot", "bingpreview")


class InviteIn(BaseModel):
    contact_id: str
    year: int
    month: int = Field(ge=1, le=12)
    event_id: Optional[str] = None


class SyncIn(BaseModel):
    year: int
    month: int = Field(ge=1, le=12)
    index: int = Field(ge=0)
    playing: bool


@router.post("/api/invites", status_code=201)
async def create_invite(b: InviteIn, s: Session = Depends(require_role("owner", "editor"))) -> dict:
    try:
        return await inv.create_invite(s.family_id, s.member_id, b.contact_id, b.year, b.month, b.event_id)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/api/invites")
async def list_invites(s: Session = Depends(require_role("owner", "editor"))) -> dict:
    rows = await db.fetch(
        "SELECT i.*, c.name AS contact_name, c.language, "
        "cs.id AS cs_id, cs.status AS call_status, cs.outcome_summary, cs.message_text, cs.started_at AS call_started_at, "
        "cs.ended_at AS call_ended_at "
        "FROM invites i LEFT JOIN contacts c ON c.id=i.contact_id "
        "LEFT JOIN LATERAL (SELECT * FROM call_sessions WHERE invite_id=i.id ORDER BY started_at DESC LIMIT 1) cs ON true "
        "WHERE i.family_id=$1 ORDER BY i.created_at DESC LIMIT 100", s.family_id)
    out = []
    for r in rows:
        open_link = r["used_at"] is None and r["expires_at"].timestamp() > __import__("time").time()
        out.append({"id": str(r["id"]), "contact_id": str(r["contact_id"]) if r["contact_id"] else None,
                    "contact_name": r["contact_name"], "year": r["year"], "month": r["month"],
                    "event_id": str(r["event_id"]) if r["event_id"] else None, "status": r["status"],
                    "expires_at": r["expires_at"], "used_at": r["used_at"], "created_at": r["created_at"],
                    "link": inv.invite_link(str(r["id"])) if open_link else None,
                    "call": {"status": r["call_status"], "summary": r["outcome_summary"], "message": r["message_text"],
                             "started_at": r["call_started_at"], "ended_at": r["call_ended_at"]}
                    if r["cs_id"] else None})
    return {"invites": out}


@router.post("/api/invites/{invite_id}/call")
async def call_invite(invite_id: str, s: Session = Depends(require_role("owner", "editor"))) -> JSONResponse:
    """Called after the host said yes to the confirmation text."""
    try:
        res = await inv.place_call(s.family_id, invite_id)
    except inv.CallRefused as e:
        return JSONResponse({"placed": False, "reason": e.code, "message": e.message}, status_code=e.status)
    return JSONResponse({"placed": True, **res})


@router.get("/i/{token}")
async def join(token: str, request: Request):
    """Guest opens the link: single-use, viewer session scoped to the room, 24 h. Link-preview bots do not burn it."""
    ua = (request.headers.get("user-agent") or "").lower()
    row = await db.fetchrow("SELECT * FROM invites WHERE token_hash=$1", auth.hash_token(token))
    if not row:
        raise HTTPException(404, "This invite link is not valid.")
    if any(b in ua for b in BOT_AGENTS):
        return JSONResponse({"invite": "valid"})
    claimed = await db.fetchrow(
        "UPDATE invites SET used_at=now(), status='joined' WHERE id=$1 AND used_at IS NULL AND expires_at > now() "
        "RETURNING id, family_id, year, month", row["id"])
    if not claimed:
        msg = "This invite link has expired." if row["expires_at"].timestamp() < __import__("time").time() \
            else "This invite link was already used. Ask the host for a new one."
        raise HTTPException(410, msg)
    sid = await auth.new_session(str(claimed["family_id"]), None, "viewer", invite_id=str(claimed["id"]), days=1)
    await bus.publish(str(claimed["family_id"]), {"type": "call_progress", "invite_id": str(claimed["id"]),
                                                  "status": "joined"})
    resp = RedirectResponse(f"/?room={claimed['year']:04d}-{claimed['month']:02d}", status_code=302)
    resp.set_cookie(auth.COOKIE, sid, max_age=86400, httponly=True, samesite="lax",
                    secure=auth.request_is_https(request))
    return resp


@router.post("/api/sync")
async def sync(b: SyncIn, s: Session = Depends(require_role("owner", "editor"))) -> dict:
    """The host broadcasts the playback position; guests in that room follow it."""
    await bus.publish(s.family_id, {"type": "playback_sync", "year": b.year, "month": b.month, "index": b.index,
                                    "playing": b.playing})
    return {"ok": True}


async def _schedule_sweeps() -> None:
    for t in ("calls_sweep", "calls_purge"):
        if not await db.fetchval("SELECT 1 FROM jobs WHERE type=$1 AND status IN ('queued','running') LIMIT 1", t):
            await jobs.enqueue(t, {}, delay_s=30)

import sys as _sys

_m = _sys.modules.get("app.main")      # registered when the API boots (main imports routes after STARTUP_HOOKS exists)
if _m is not None and hasattr(_m, "STARTUP_HOOKS") and _schedule_sweeps not in _m.STARTUP_HOOKS:
    _m.STARTUP_HOOKS.append(_schedule_sweeps)
