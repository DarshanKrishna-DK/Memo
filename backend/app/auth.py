"""Session dependency. The family ALWAYS comes from the session cookie, never from a request parameter.

Usage in a route:  `async def f(s: Session = Depends(current_session))` -> s.family_id, s.member_id, s.role
`Depends(require_role("owner"))` / `require_role("owner","editor")` to gate writes.
Guests from a phone invite have role 'viewer' and s.invite_room = (year, month).
Sign-in links (/m/{token}) are created by `create_signin_link(family_id, member_id)` (used by the bot's /museum).
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request

from . import config, db

COOKIE = "memo_session"
SESSION_DAYS = 30


def request_is_https(request: Request) -> bool:
    """True when the browser reached us over https (directly, or via the tunnel/proxy's X-Forwarded-Proto).
    Used for the cookie Secure flag so plain-http localhost and https tunnels both work."""
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return (proto or request.url.scheme) == "https"


def hash_token(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


@dataclass
class Session:
    id: str
    family_id: str
    member_id: Optional[str]
    role: str
    invite_id: Optional[str] = None
    invite_room: Optional[tuple[int, int]] = None

    @property
    def is_guest(self) -> bool:
        return self.invite_id is not None


async def create_signin_link(family_id: str, member_id: str) -> str:
    token = secrets.token_urlsafe(32)
    await db.execute(
        "INSERT INTO signin_tokens(token_hash, family_id, member_id, expires_at) VALUES ($1,$2,$3,$4)",
        hash_token(token), family_id, member_id, datetime.now(timezone.utc) + timedelta(minutes=15))
    return f"{config.PUBLIC_BASE_URL}/m/{token}"


async def new_session(family_id: str, member_id: Optional[str], role: str,
                      invite_id: Optional[str] = None, days: int = SESSION_DAYS) -> str:
    sid = secrets.token_urlsafe(32)
    await db.execute(
        "INSERT INTO sessions(id, family_id, member_id, role, invite_id, expires_at) VALUES ($1,$2,$3,$4,$5,$6)",
        hash_token(sid), family_id, member_id, role, invite_id, datetime.now(timezone.utc) + timedelta(days=days))
    return sid


async def current_session(request: Request) -> Session:
    sid = request.cookies.get(COOKIE) or request.headers.get("x-memo-session")
    if not sid:
        raise HTTPException(401, "Not signed in. Send /museum to the Memo bot for a sign-in link.")
    row = await db.fetchrow(
        "SELECT s.*, i.year AS iy, i.month AS im FROM sessions s LEFT JOIN invites i ON i.id = s.invite_id "
        "WHERE s.id=$1 AND s.expires_at > now()", hash_token(sid))
    if not row:
        raise HTTPException(401, "Session expired. Send /museum to the Memo bot for a new link.")
    return Session(id=row["id"], family_id=str(row["family_id"]),
                   member_id=str(row["member_id"]) if row["member_id"] else None, role=row["role"],
                   invite_id=str(row["invite_id"]) if row["invite_id"] else None,
                   invite_room=(row["iy"], row["im"]) if row["invite_id"] else None)


def require_role(*roles: str):
    async def dep(s: Session = Depends(current_session)) -> Session:
        if s.role not in roles:
            raise HTTPException(403, f"This needs the {' or '.join(roles)} role.")
        return s
    return dep
