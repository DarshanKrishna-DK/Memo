"""Theater presence: seat assignment, expiry, guest scoping and SSE delivery. Real Postgres, throwaway family."""
from __future__ import annotations

import asyncio
import json
import secrets

import httpx
import pytest
import pytest_asyncio

from app import auth, db
from app.routes import presence, stream

pytestmark = pytest.mark.asyncio
BASE = "http://memo-test.local"


@pytest_asyncio.fixture
async def fam():
    db._pool = None
    await db.init_schema()
    fid = await db.fetchval("INSERT INTO families(name, invite_code) VALUES ('pytest-guests', $1) RETURNING id::text",
                            "pytest-" + secrets.token_hex(8))
    owner = await db.fetchval("INSERT INTO members(family_id,nickname,role) VALUES ($1,'Asha','owner') RETURNING id::text", fid)
    editor = await db.fetchval("INSERT INTO members(family_id,nickname,role) VALUES ($1,'Ravi','editor') RETURNING id::text", fid)
    ev = await db.fetchval("INSERT INTO events(family_id,name,kind,year,month) VALUES ($1,'Diwali','festival',2026,11) "
                           "RETURNING id::text", fid)

    async def guest(name: str, year=2026, month=11) -> str:
        cid = await db.fetchval("INSERT INTO contacts(family_id,name,phone_e164) VALUES ($1,$2,'+919800000000') "
                                "RETURNING id::text", fid, name)
        iid = await db.fetchval(
            "INSERT INTO invites(family_id,contact_id,event_id,year,month,token_hash,host_member_id,expires_at,used_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,now()+interval '1 day',now()) RETURNING id::text",
            fid, cid, ev if month == 11 else None, year, month, secrets.token_hex(16), owner)
        return await auth.new_session(fid, None, "viewer", invite_id=iid, days=1)

    w = {"id": fid, "owner": await auth.new_session(fid, owner, "owner"),
         "editor": await auth.new_session(fid, editor, "editor"), "guest": guest}
    yield w
    await db.execute("DELETE FROM families WHERE id=$1::uuid", fid)
    await db.close()


@pytest_asyncio.fixture
async def client():
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as c:
        yield c


def ck(sid: str) -> dict:
    return {auth.COOKIE: sid}


async def join(client, sid, avatar="man", **kw):
    r = await client.post("/api/presence/join", json={"year": 2026, "month": 11, "avatar": avatar, **kw}, cookies=ck(sid))
    assert r.status_code == 200, r.text
    return r.json()


async def test_seat_assignment(fam, client):
    g1 = await fam["guest"]("Priya")
    # a guest arriving first never takes the host's seat 0
    r = await join(client, g1, "woman", prefer_seat=0)
    assert r["me"]["index"] == 1 and r["me"]["name"] == "Priya" and r["me"]["is_guest"] is True
    r = await join(client, fam["owner"])
    assert r["me"]["index"] == 0 and r["me"]["name"] == "Asha" and r["me"]["is_guest"] is False
    r = await join(client, fam["editor"], "woman", prefer_seat=1)          # taken -> next free
    assert r["me"]["index"] == 2
    g2 = await fam["guest"]("Meera")
    r = await join(client, g2, name="  Meera   Aunty ")
    assert r["me"]["index"] == 3 and r["me"]["name"] == "Meera Aunty"
    g3 = await fam["guest"]("Kiran")
    r = await join(client, g3)
    assert r["me"]["index"] is None and [w["name"] for w in r["watchers"]] == ["Kiran"]   # full: watches without a seat
    assert [(p["index"], p["name"]) for p in r["seats"]] == [(0, "Asha"), (1, "Priya"), (2, "Ravi"), (3, "Meera Aunty")]
    # re-joining keeps the seat; leaving frees it for the watcher's next join
    assert (await join(client, fam["editor"], "woman"))["me"]["index"] == 2
    assert (await client.post("/api/presence/leave", content="", cookies=ck(fam["editor"]))).json()["left"] is True
    assert (await join(client, g3))["me"]["index"] == 2
    # the owner leaves: seat 0 is free again, but a guest still cannot take it
    await client.post("/api/presence/leave", cookies=ck(fam["owner"]))
    assert (await join(client, g1, "woman", prefer_seat=0))["me"]["index"] == 1
    assert (await join(client, fam["editor"], "woman"))["me"]["index"] == 0


async def test_expiry_and_heartbeat(fam, client):
    g = await fam["guest"]("Priya")
    await join(client, fam["owner"])
    await join(client, g, "woman")
    hb = (await client.post("/api/presence/heartbeat", cookies=ck(g))).json()
    assert hb["ok"] is True and hb["index"] == 1
    await db.execute("UPDATE theater_presence SET last_seen = now() - interval '46 seconds' WHERE session_id=$1",
                     auth.hash_token(g))
    st = (await client.get("/api/presence/2026/11", cookies=ck(fam["owner"]))).json()
    assert [p["name"] for p in st["seats"]] == ["Asha"] and st["seats"][0]["is_me"] is True
    assert (await client.post("/api/presence/heartbeat", cookies=ck(g))).json() == {"ok": False, "rejoin": True}
    assert (await join(client, g, "woman"))["me"]["index"] == 1


async def test_guest_scoped_to_invite_room(fam, client):
    g = await fam["guest"]("Priya")
    r = await client.post("/api/presence/join", json={"year": 2026, "month": 10, "avatar": "man"}, cookies=ck(g))
    assert r.status_code == 403
    assert (await client.get("/api/presence/2026/10", cookies=ck(g))).status_code == 403
    assert (await client.get("/api/presence/2026/11", cookies=ck(g))).status_code == 200
    # family members may sit anywhere
    assert (await client.post("/api/presence/join", json={"year": 2026, "month": 10, "avatar": "man"},
                              cookies=ck(fam["owner"]))).status_code == 200
    w = (await client.get("/api/guest/welcome", cookies=ck(g))).json()
    assert w == {**w, "is_guest": True, "contact_name": "Priya", "host_name": "Asha", "event_name": "Diwali",
                 "year": 2026, "month": 11}
    assert (await client.post("/api/presence/join", json={"year": 2026, "month": 11, "avatar": "robot"},
                              cookies=ck(g))).status_code == 422


class _Req:
    async def is_disconnected(self) -> bool:
        return False


async def _subscribe(sid: str):
    s = await auth.current_session(type("R", (), {"cookies": {auth.COOKIE: sid}, "headers": {}})())
    resp = await stream.stream(_Req(), s)
    it = resp.body_iterator
    assert "retry" in await it.__anext__()
    assert json.loads((await it.__anext__())[6:])["type"] == "hello"
    return it


async def _next_presence(it, timeout=5.0):
    async def go():
        while True:
            chunk = await it.__anext__()
            if chunk.startswith("data: "):
                ev = json.loads(chunk[6:])
                if ev["type"] == "presence":
                    return ev
    return await asyncio.wait_for(go(), timeout)


async def test_sse_delivers_presence_to_family_and_room_guests_only(fam, client):
    stream.hub.conn, stream.hub.subs = None, {}      # the listener belongs to this test's event loop
    g_here = await fam["guest"]("Priya")
    g_other = await fam["guest"]("Kiran", month=10)
    owner_it = await _subscribe(fam["owner"])
    here_it = await _subscribe(g_here)
    other_it = await _subscribe(g_other)
    try:
        await join(client, fam["owner"])
        ev = await _next_presence(owner_it)
        assert ev["change"]["kind"] == "joined" and ev["seats"][0]["is_me"] is True and "sid" not in ev["seats"][0]
        await join(client, g_here, "woman")
        ev = await _next_presence(owner_it)
        assert [(p["index"], p["name"], p["avatar"], p["is_guest"], p["is_me"]) for p in ev["seats"]] == \
            [(0, "Asha", "man", False, True), (1, "Priya", "woman", True, False)]
        # the guest of this room gets both events; its own seat is marked
        await _next_presence(here_it)
        ev = await _next_presence(here_it)
        assert ev["year"] == 2026 and ev["month"] == 11 and [p["is_me"] for p in ev["seats"]] == [False, True]
        assert all("sid" not in p for p in ev["seats"])
        # a guest invited to another room hears nothing
        with pytest.raises(asyncio.TimeoutError):
            await _next_presence(other_it, timeout=1.5)
        await client.post("/api/presence/leave", cookies=ck(g_here))
        ev = await _next_presence(owner_it)
        assert ev["change"]["kind"] == "left" and ev["change"]["name"] == "Priya" and len(ev["seats"]) == 1
    finally:
        for it in (owner_it, here_it, other_it):
            await it.aclose()
