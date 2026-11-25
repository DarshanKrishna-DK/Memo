"""Theater presence: who sits in which of a room's four seats (family members and invited guests).

POST /api/presence/join {year, month, avatar, name?, prefer_seat?}  -> {me, seats, watchers}
POST /api/presence/heartbeat {}                                      -> {ok, rejoin?}   (every 15 s)
POST /api/presence/leave {}                                          -> {ok}            (also sendBeacon on pagehide)
GET  /api/presence/{year}/{month}                                    -> {year, month, seats, watchers, me}
GET  /api/guest/welcome                                              -> who invited the guest, to which room

Seats: the first family member to sit keeps seat 0; family members and guests get 1-3; when all four are taken
the viewer still watches, without a seat (`watchers`). Rows expire 45 s after the last heartbeat. Every change is
published on the bus as `{type:"presence", year, month, seats, watchers, change}`; GET /api/stream adds `is_me`
per subscriber and only lets a guest see their own invite room.
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import bus, db
from ..auth import Session, current_session

log = logging.getLogger("memo.presence")
router = APIRouter()

EXPIRE_S = 45
SEATS = (0, 1, 2, 3)


class JoinIn(BaseModel):
    year: int = Field(ge=1900, le=2200)
    month: int = Field(ge=1, le=12)
    avatar: Literal["man", "woman"]
    name: Optional[str] = Field(default=None, max_length=60)
    prefer_seat: Optional[int] = Field(default=None, ge=0, le=3)


def _check_room(s: Session, year: int, month: int) -> None:
    if s.is_guest and (year, month) != tuple(s.invite_room or ()):
        raise HTTPException(403, "Your invite is for one room only.")


def _person(r, sid: Optional[str] = None) -> dict:
    d = {"id": str(r["id"]), "index": r["seat"], "name": r["name"], "avatar": r["avatar"], "is_guest": r["is_guest"]}
    if sid is not None:
        d["is_me"] = r["session_id"] == sid
    return d


async def _prune(conn, family_id: str, year: int, month: int) -> list:
    return await conn.fetch(
        "DELETE FROM theater_presence WHERE family_id=$1::uuid AND year=$2 AND month=$3 "
        f"AND last_seen < now() - interval '{EXPIRE_S} seconds' RETURNING *", family_id, year, month)


async def room_state(family_id: str, year: int, month: int, sid: Optional[str] = None) -> dict:
    rows = await db.fetch(
        "SELECT * FROM theater_presence WHERE family_id=$1::uuid AND year=$2 AND month=$3 "
        f"AND last_seen >= now() - interval '{EXPIRE_S} seconds' ORDER BY seat NULLS LAST, joined_at",
        family_id, year, month)
    seats = [_person(r, sid) for r in rows if r["seat"] is not None]
    watchers = [_person(r, sid) for r in rows if r["seat"] is None]
    out = {"year": year, "month": month, "seats": seats, "watchers": watchers}
    if sid is not None:
        me = next((p for p in seats + watchers if p.get("is_me")), None)
        out["me"] = me
    return out


async def publish(family_id: str, year: int, month: int, change: Optional[dict] = None) -> None:
    """Bus event. `sid` (hashed session id) rides along so /api/stream can mark `is_me` per subscriber; the stream
    strips it before anything reaches a browser."""
    rows = await db.fetch(
        "SELECT * FROM theater_presence WHERE family_id=$1::uuid AND year=$2 AND month=$3 "
        f"AND last_seen >= now() - interval '{EXPIRE_S} seconds' ORDER BY seat NULLS LAST, joined_at",
        family_id, year, month)
    def p(r):
        return {**_person(r), "sid": r["session_id"]}
    await bus.publish(family_id, {
        "type": "presence", "year": year, "month": month,
        "seats": [p(r) for r in rows if r["seat"] is not None],
        "watchers": [p(r) for r in rows if r["seat"] is None],
        "change": change})


def _change(kind: str, r) -> dict:
    return {"kind": kind, "id": str(r["id"]), "name": r["name"], "avatar": r["avatar"], "is_guest": r["is_guest"],
            "index": r["seat"]}


async def _default_name(s: Session) -> str:
    if s.is_guest:
        n = await db.fetchval("SELECT c.name FROM invites i LEFT JOIN contacts c ON c.id=i.contact_id WHERE i.id=$1::uuid",
                              s.invite_id)
        return n or "Guest"
    if s.member_id:
        n = await db.fetchval("SELECT nickname FROM members WHERE id=$1::uuid", s.member_id)
        if n:
            return n
    return "Family"


async def _prune_and_publish(family_id: str, year: int, month: int) -> int:
    async with db.acquire() as c:
        gone = await _prune(c, family_id, year, month)
    for r in gone:
        await publish(family_id, year, month, _change("left", r))
    return len(gone)


@router.post("/api/presence/join")
async def join(b: JoinIn, s: Session = Depends(current_session)) -> dict:
    _check_room(s, b.year, b.month)
    name = " ".join((b.name or "").split())[:40] or await _default_name(s)
    lock = f"presence:{s.family_id}:{b.year}:{b.month}"
    async with db.acquire() as c:
        async with c.transaction():
            await c.execute("SELECT pg_advisory_xact_lock(hashtext($1))", lock)
            gone = await _prune(c, s.family_id, b.year, b.month)
            old = await c.fetchrow("SELECT * FROM theater_presence WHERE session_id=$1", s.id)
            same_room = bool(old) and str(old["family_id"]) == s.family_id and \
                (old["year"], old["month"]) == (b.year, b.month)
            taken = {r["seat"] for r in await c.fetch(
                "SELECT seat FROM theater_presence WHERE family_id=$1::uuid AND year=$2 AND month=$3 "
                "AND seat IS NOT NULL AND session_id<>$4", s.family_id, b.year, b.month, s.id)}
            allowed = [i for i in SEATS if not (s.is_guest and i == 0)]
            free = [i for i in allowed if i not in taken]
            if b.prefer_seat is not None and b.prefer_seat in free:
                seat = b.prefer_seat
            elif same_room and old["seat"] is not None and old["seat"] in free:
                seat = old["seat"]
            else:
                seat = free[0] if free else None
            row = await c.fetchrow(
                "INSERT INTO theater_presence(session_id, family_id, year, month, member_id, invite_id, is_guest, name, "
                "avatar, seat) VALUES ($1,$2::uuid,$3,$4,$5::uuid,$6::uuid,$7,$8,$9,$10) "
                "ON CONFLICT (session_id) DO UPDATE SET family_id=EXCLUDED.family_id, year=EXCLUDED.year, "
                "month=EXCLUDED.month, name=EXCLUDED.name, avatar=EXCLUDED.avatar, seat=EXCLUDED.seat, last_seen=now(), "
                "joined_at=CASE WHEN theater_presence.year=EXCLUDED.year AND theater_presence.month=EXCLUDED.month "
                "THEN theater_presence.joined_at ELSE now() END RETURNING *",
                s.id, s.family_id, b.year, b.month, s.member_id, s.invite_id, s.is_guest, name, b.avatar, seat)
    for r in gone:
        await publish(s.family_id, b.year, b.month, _change("left", r))
    if old and not same_room:
        await publish(str(old["family_id"]), old["year"], old["month"], _change("left", old))
    changed = not same_room or (old["seat"], old["name"], old["avatar"]) != (row["seat"], row["name"], row["avatar"])
    if changed:
        await publish(s.family_id, b.year, b.month, _change("joined" if not same_room else "moved", row))
    return await room_state(s.family_id, b.year, b.month, s.id)


@router.post("/api/presence/heartbeat")
async def heartbeat(s: Session = Depends(current_session)) -> dict:
    row = await db.fetchrow(
        "UPDATE theater_presence SET last_seen=now() WHERE session_id=$1 "
        f"AND last_seen >= now() - interval '{EXPIRE_S} seconds' RETURNING *", s.id)
    if not row:
        # expired (or never joined): drop a stale row so the client's rejoin starts clean
        stale = await db.fetchrow("DELETE FROM theater_presence WHERE session_id=$1 RETURNING *", s.id)
        if stale:
            await publish(str(stale["family_id"]), stale["year"], stale["month"], _change("left", stale))
        return {"ok": False, "rejoin": True}
    await _prune_and_publish(s.family_id, row["year"], row["month"])
    return {"ok": True, "year": row["year"], "month": row["month"], "index": row["seat"]}


@router.post("/api/presence/leave")
async def leave(request: Request, s: Session = Depends(current_session)) -> dict:
    """Body is optional (sendBeacon sends text/plain); the session decides whose seat is freed."""
    try:
        await request.body()
    except Exception:  # noqa: BLE001
        pass
    row = await db.fetchrow("DELETE FROM theater_presence WHERE session_id=$1 RETURNING *", s.id)
    if row:
        await publish(str(row["family_id"]), row["year"], row["month"], _change("left", row))
    return {"ok": True, "left": bool(row)}


@router.get("/api/presence/{year}/{month}")
async def get_room(year: int, month: int, s: Session = Depends(current_session)) -> dict:
    if not 1 <= month <= 12:
        raise HTTPException(422, "month must be 1-12")
    _check_room(s, year, month)
    await _prune_and_publish(s.family_id, year, month)
    return await room_state(s.family_id, year, month, s.id)


@router.get("/api/guest/welcome")
async def welcome(s: Session = Depends(current_session)) -> dict:
    """The guest landing: who invited you, to which room/event, and the name the host saved for you."""
    if not s.is_guest:
        name = await _default_name(s)
        return {"is_guest": False, "name": name}
    r = await db.fetchrow(
        "SELECT i.year, i.month, c.name AS contact_name, m.nickname AS host_name, e.name AS event_name, "
        "f.name AS family_name, f.grandma_name FROM invites i JOIN families f ON f.id=i.family_id "
        "LEFT JOIN contacts c ON c.id=i.contact_id LEFT JOIN members m ON m.id=i.host_member_id "
        "LEFT JOIN events e ON e.id=i.event_id WHERE i.id=$1::uuid", s.invite_id)
    if not r:
        raise HTTPException(404, "Invite not found.")
    return {"is_guest": True, "year": r["year"], "month": r["month"], "contact_name": r["contact_name"],
            "host_name": r["host_name"] or r["family_name"], "event_name": r["event_name"],
            "family_name": r["family_name"], "grandma_name": r["grandma_name"]}

