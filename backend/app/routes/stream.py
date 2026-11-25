"""GET /api/stream: Server-sent events for the theater.

One dedicated asyncpg connection per API process LISTENs on `memo_live` (app/bus.py) and fans events out to the
browsers of the event's family. Each message is `data: {json}` with a "type" field (use EventSource.onmessage).
A comment heartbeat goes out every 15 s. Guests receive only events for their invite room (matching year+month)
or their own invite_id.
"""
from __future__ import annotations

import asyncio
import json
import logging

import asyncpg
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from .. import bus, config
from ..auth import Session, current_session

router = APIRouter()
log = logging.getLogger("memo.stream")
HEARTBEAT_S = 15


class Hub:
    def __init__(self) -> None:
        self.conn: asyncpg.Connection | None = None
        self.subs: dict[str, set[asyncio.Queue]] = {}
        self.lock = asyncio.Lock()

    async def ensure(self) -> None:
        async with self.lock:
            if self.conn is not None and not self.conn.is_closed():
                return
            try:
                self.conn = await asyncpg.connect(config.DATABASE_URL)
                await self.conn.add_listener(bus.CHANNEL, self._on_notify)
                log.info("listening on %s", bus.CHANNEL)
            except Exception as e:  # noqa: BLE001
                self.conn = None
                log.warning("LISTEN %s failed: %s", bus.CHANNEL, e)

    def _on_notify(self, _conn, _pid, _channel, payload: str) -> None:
        try:
            ev = json.loads(payload)
        except (TypeError, ValueError):
            return
        for q in list(self.subs.get(str(ev.get("family_id")), ())):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                pass

    def subscribe(self, family_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.subs.setdefault(family_id, set()).add(q)
        return q

    def unsubscribe(self, family_id: str, q: asyncio.Queue) -> None:
        s = self.subs.get(family_id)
        if s:
            s.discard(q)
            if not s:
                self.subs.pop(family_id, None)


hub = Hub()


def _guest_may_see(s: Session, ev: dict) -> bool:
    if ev.get("invite_id") and ev.get("invite_id") == s.invite_id:
        return True
    try:
        return (int(ev.get("year")), int(ev.get("month"))) == tuple(s.invite_room or ())
    except (TypeError, ValueError):
        return False


def _presence_for(s: Session, ev: dict) -> dict:
    """presence events carry each person's hashed session id; turn it into `is_me` for this subscriber."""
    def strip(p: dict) -> dict:
        p = dict(p)
        p["is_me"] = p.pop("sid", None) == s.id
        return p
    return {**ev, "seats": [strip(p) for p in ev.get("seats") or []],
            "watchers": [strip(p) for p in ev.get("watchers") or []]}


@router.get("/api/stream")
async def stream(request: Request, s: Session = Depends(current_session)):
    await hub.ensure()
    q = hub.subscribe(s.family_id)

    async def gen():
        try:
            yield "retry: 3000\n\n"
            yield f"data: {json.dumps({'type': 'hello', 'family_id': s.family_id})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_S)
                except asyncio.TimeoutError:
                    await hub.ensure()          # reconnect the listener if Postgres dropped it
                    yield ": heartbeat\n\n"
                    continue
                if s.is_guest and not _guest_may_see(s, ev):
                    continue
                ev = {k: v for k, v in ev.items() if k != "family_id"}
                if ev.get("type") == "presence":       # guests addition: mark the subscriber's own seat, drop sids
                    ev = _presence_for(s, ev)
                yield f"data: {json.dumps(ev, default=str)}\n\n"
        finally:
            hub.unsubscribe(s.family_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})
