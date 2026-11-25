"""Sign-in: GET /m/{token} (single-use, 15 min, from the bot's /museum) -> cookie memo_session -> WEB_BASE_URL.
Also /api/me, /api/logout and the dev-only POST /api/dev/signin (MEMO_DEV=1 AND a localhost request)."""
from __future__ import annotations

import html
import ipaddress

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from .. import auth, config, db
from ..auth import Session, current_session

router = APIRouter()


def set_session_cookie(resp: Response, sid: str, days: int = auth.SESSION_DAYS, request: Request | None = None) -> None:
    secure = auth.request_is_https(request) if request is not None else config.WEB_BASE_URL.startswith("https://")
    resp.set_cookie(auth.COOKIE, sid, max_age=days * 86400, httponly=True, samesite="lax", secure=secure, path="/")


def _page(title: str, msg: str, status: int) -> HTMLResponse:
    body = (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><body style='font-family:system-ui;background:#14110f;color:#f3e9dc;"
            f"display:grid;place-items:center;min-height:100vh;margin:0'><div style='max-width:420px;padding:24px'>"
            f"<h1 style='font-size:22px'>{html.escape(title)}</h1><p>{html.escape(msg)}</p></div></body>")
    return HTMLResponse(body, status_code=status)


@router.get("/m/{token}")
async def signin_link(token: str, request: Request):
    row = await db.fetchrow(
        "UPDATE signin_tokens SET used_at=now() WHERE token_hash=$1 AND used_at IS NULL AND expires_at > now() "
        "RETURNING family_id, member_id", auth.hash_token(token))
    if not row:
        return _page("This link has expired", "Sign-in links work once and last 15 minutes. "
                     "Send /museum to the Memo bot on Telegram for a fresh one.", 410)
    m = await db.fetchrow("SELECT role FROM members WHERE id=$1 AND family_id=$2", row["member_id"], row["family_id"])
    if not m:
        return _page("You're not in this family any more", "Ask the family owner to invite you again.", 403)
    sid = await auth.new_session(str(row["family_id"]), str(row["member_id"]), m["role"])
    # Relative redirect: /m is served on the web app's own origin (Vite proxy / same host in prod), so the cookie
    # lands on the origin the user is actually on (localhost or the public tunnel).
    resp = RedirectResponse("/", status_code=303)
    set_session_cookie(resp, sid, request=request)
    return resp


@router.get("/api/me")
async def me(s: Session = Depends(current_session)) -> dict:
    nick = None
    if s.member_id:
        nick = await db.fetchval("SELECT nickname FROM members WHERE id=$1::uuid", s.member_id)
    return {"family_id": s.family_id, "member_id": s.member_id, "nickname": nick, "role": s.role,
            "is_guest": s.is_guest,
            "invite_room": {"year": s.invite_room[0], "month": s.invite_room[1]} if s.invite_room else None}


@router.post("/api/logout")
async def logout(s: Session = Depends(current_session)) -> Response:
    await db.execute("DELETE FROM sessions WHERE id=$1", s.id)
    resp = Response(status_code=204)
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


def _is_local(request: Request) -> bool:
    hosts = [request.client.host if request.client else ""]
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        hosts += [h.strip() for h in fwd.split(",")]
    for h in hosts:
        if h == "localhost":
            continue
        try:
            if not ipaddress.ip_address(h).is_loopback:
                return False
        except ValueError:
            return False
    return True


def _dev_guard(request: Request) -> None:
    if config.env("MEMO_DEV") != "1" or not _is_local(request):
        raise HTTPException(404, "Not found")


class DevSignin(BaseModel):
    member_id: str


@router.post("/api/dev/signin")
async def dev_signin(body: DevSignin, request: Request) -> Response:
    _dev_guard(request)
    m = await db.fetchrow("SELECT id, family_id, role, nickname FROM members WHERE id=$1::uuid", body.member_id)
    if not m:
        raise HTTPException(404, "No such member.")
    sid = await auth.new_session(str(m["family_id"]), str(m["id"]), m["role"])
    resp = JSONResponse({"ok": True, "family_id": str(m["family_id"]), "member_id": str(m["id"]),
                         "role": m["role"], "nickname": m["nickname"]})
    set_session_cookie(resp, sid, request=request)
    return resp


@router.get("/api/dev/members")
async def dev_members(request: Request) -> dict:
    _dev_guard(request)
    rows = await db.fetch("SELECT m.id, m.nickname, m.role, f.id AS family_id, f.name AS family_name FROM members m "
                          "JOIN families f ON f.id=m.family_id ORDER BY f.created_at, m.joined_at")
    return {"members": [{"id": str(r["id"]), "nickname": r["nickname"], "role": r["role"],
                         "family_id": str(r["family_id"]), "family_name": r["family_name"]} for r in rows]}
