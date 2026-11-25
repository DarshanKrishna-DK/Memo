"""core-api routes through the real FastAPI app (ASGI transport) against the real Postgres."""
from __future__ import annotations

import io
import json
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
import pytest
import pytest_asyncio

from _core_fixtures import (add_memory, drop_family, fresh_pool, jpeg_bytes, make_family, run_job_now,
                            sharp_image)
from app import auth, db, storage
from app.core import common
from app.main import app

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def env():
    await fresh_pool()
    f = await make_family()
    y = common.tz_today().year
    f["y"] = y
    f["mine"] = await add_memory(f["id"], y - 1, 4, author=f["editor"], title="Ravi's story")
    f["theirs"] = await add_memory(f["id"], y - 1, 4, author=f["owner"], title="Asha's story", day=2)
    f["attic"] = await add_memory(f["id"], None, None, author=f["owner"], title="When was this?", status="attic")
    yield f
    await drop_family(f["id"])
    await db.close()


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")


@asynccontextmanager
async def signed_in(fid: str, member: str):
    link = await auth.create_signin_link(fid, member)
    async with client() as c:
        r = await c.get("/m/" + link.rsplit("/", 1)[1])
        assert r.status_code == 303 and r.headers["location"].endswith("/")
        assert "httponly" in r.headers["set-cookie"].lower() and "samesite=lax" in r.headers["set-cookie"].lower()
        yield c


async def test_signin_link_single_use(env):
    link = await auth.create_signin_link(env["id"], env["owner"])
    token = link.rsplit("/", 1)[1]
    async with client() as c:
        assert (await c.get("/m/" + token)).status_code == 303
        assert (await c.get("/m/" + token)).status_code == 410          # used
        assert (await c.get("/api/museum")).status_code == 200          # the cookie from the first use
    async with client() as anon:
        assert (await anon.get("/api/museum")).status_code == 401


async def test_museum_floor_room_attic(env):
    y = env["y"]
    async with signed_in(env["id"], env["owner"]) as c:
        me = (await c.get("/api/me")).json()
        assert me["role"] == "owner" and me["nickname"] == "Asha"
        m = (await c.get("/api/museum")).json()
        assert m["family"]["grandma_name"] == "Ajji" and m["attic_count"] == 1
        assert m["floors"][0]["year"] == y and m["floors"][-1]["level"] == 0
        assert "museum_3d" in m["flags"] and "bot_username" in m
        fl = (await c.get(f"/api/museum/{y - 1}")).json()
        assert len(fl["rooms"]) == 12 and fl["rooms"][3]["state"] == "open" and fl["rooms"][3]["memory_count"] == 2
        room = (await c.get(f"/api/museum/{y - 1}/4?limit=1")).json()
        assert room["state"] == "open" and len(room["exhibits"]) == 1 and room["next_cursor"] == "1"
        assert room["exhibits"][0]["title"] == "Asha's story"               # day 2 comes before undated
        page2 = (await c.get(f"/api/museum/{y - 1}/4?limit=1&cursor=1")).json()
        assert page2["exhibits"][0]["title"] == "Ravi's story" and page2["next_cursor"] is None
        att = (await c.get("/api/attic")).json()["memories"]
        assert [a["id"] for a in att] == [env["attic"]]
        r = await c.post(f"/api/memories/{env['attic']}/date", json={"year": y - 1, "month": 7})
        assert r.status_code == 200 and r.json()["status"] == "saved"
        assert (await c.get(f"/api/museum/{y - 1}")).json()["rooms"][6]["state"] == "open"


async def test_roles_on_edits(env):
    async with signed_in(env["id"], env["editor"]) as ed:
        assert (await ed.patch(f"/api/memories/{env['mine']}", json={"title": "Ravi's bike"})).json()["title"] \
            == "Ravi's bike"
        assert (await ed.patch(f"/api/memories/{env['theirs']}", json={"title": "x"})).status_code == 403
        assert (await ed.get("/api/ops/jobs")).status_code == 403
        assert (await ed.patch("/api/family", json={"name": "x"})).status_code == 403
    async with signed_in(env["id"], env["owner"]) as ow:
        r = await ow.patch("/api/family", json={"settings": {"editors_edit_others": True}})
        assert r.status_code == 200 and r.json()["settings"]["editors_edit_others"] is True
    async with signed_in(env["id"], env["editor"]) as ed:
        r = await ed.post(f"/api/memories/{env['theirs']}/narrate_ok", json={"narrate_ok": False})
        assert r.status_code == 200 and r.json()["narrate_ok"] is False


async def test_route_events_showcase_media(env):
    y = env["y"]
    async with signed_in(env["id"], env["owner"]) as c:
        r = (await c.post("/api/route", json={"text": f"open April {y - 1}"})).json()
        assert r["route"]["level"] == 0 and r["route"]["needs_lift"] is False and r["question"] is None
        e = (await c.post("/api/events", json={"name": "Holi", "when": f"March {y - 1}"})).json()
        assert e["event"]["kind"] == "festival" and e["room"] == {"year": y - 1, "month": 3}
        assert e["room_state"]["state"] == "locked"
        r = (await c.post("/api/route", json={"text": f"go to last year's Holi"})).json()
        assert r["route"]["event_id"] == e["event"]["id"] and r["route"]["room_state"] == "locked"
        assert r["route"]["waypoints"][-1]["kind"] == "door"
        sc = (await c.get(f"/api/showcase/{y - 1}/4")).json()
        assert [i["kind"] for i in sc["items"]] == ["title", "title"]
        rm = (await c.post(f"/api/rooms/{y - 1}/4/mode", json={"mode": "closed_with_care"})).json()
        assert rm["state"] == "closed" and rm["board_text"] == "Closed with care."
        assert (await c.get(f"/api/showcase/{y - 1}/4")).json()["items"] == []
        await c.post(f"/api/rooms/{y - 1}/4/mode", json={"mode": "auto"})
        # browser upload -> signed media url works; tampered signature does not
        data = jpeg_bytes(sharp_image(31), datetime(y - 1, 4, 3, 10, 0))
        r = await c.post("/api/gallery/scan", data={"meta": json.dumps([{"path": "picked/a.jpg"}])},
                         files=[("files", ("a.jpg", io.BytesIO(data), "image/jpeg"))])
        assert r.status_code == 200 and r.json()["new"] == 1
        q = (await c.post("/api/gallery/query", json={"folder": "picked"})).json()
        url = q["sample"][0]["thumb_url"]
        assert (await c.get(url)).status_code == 200
        assert (await c.get(url[:-4] + "0000")).status_code == 403
        imp = await c.post("/api/gallery/import", json={"preview_token": q["preview_token"],
                                                        "event_id": e["event"]["id"]})
        assert imp.status_code == 200 and imp.json()["count"] == 1
        await run_job_now(imp.json()["job_id"])
        st = (await c.get(f"/api/gallery/import/{imp.json()['job_id']}")).json()
        assert st["status"] == "done" and st["result"]["count"] == 1
        sc = (await c.get(f"/api/showcase/{y - 1}/3?event_id={e['event']['id']}")).json()
        assert [i["kind"] for i in sc["items"]] == ["photo"] and sc["room_state"] == "open"


async def test_ops_and_export(env):
    async with signed_in(env["id"], env["owner"]) as c:
        r = await c.post("/api/ops/flags", json={"key": "max_import_photos", "value": 50})
        assert r.status_code == 200 and r.json()["value"] == 50
        fl = (await c.get("/api/ops/flags")).json()
        assert fl["flags"]["max_import_photos"] == 50 and fl["overrides"][0]["scope"] == "family"
        assert (await c.post("/api/ops/flags", json={"key": "nope", "value": 1})).status_code == 400
        assert (await c.post("/api/ops/flags", json={"key": "museum_3d", "value": False,
                                                     "scope": "global"})).status_code == 403
        jobs = (await c.get("/api/ops/jobs?status=dead")).json()
        assert "jobs" in jobs
        ex = await c.get("/api/export")
        assert ex.status_code == 200 and ex.headers["content-type"] == "application/zip"
        import zipfile
        z = zipfile.ZipFile(io.BytesIO(ex.content))
        doc = json.loads(z.read("memo.json"))
        assert doc["family"]["id"] == env["id"] and len(doc["memories"]) >= 3
        assert any(n.startswith(f"media/{env['id']}/gallery/") for n in z.namelist())
        mem = (await c.get("/api/family/members")).json()["members"]
        assert {m["nickname"] for m in mem} == {"Asha", "Ravi"}
        r = await c.patch(f"/api/family/members/{env['editor']}", json={"role": "viewer"})
        assert r.json()["role"] == "viewer"
    assert storage.path(env["id"]).exists()
