import pytest

from app import auth, bus, db
from _phone_fixtures import PUBLIC, client, owner_cookie, world  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _mk_invite(client, w, ck):
    r = await client.post("/api/invites", json={"contact_id": w["contact"], "year": 2026, "month": 11}, cookies=ck)
    assert r.status_code == 201
    return r.json()


async def test_guest_link_scoped_session_and_single_use(world, client):
    ck = await owner_cookie(world)
    body = await _mk_invite(client, world, ck)
    token = body["link"].rsplit("/i/", 1)[1]
    assert (await db.fetchval("SELECT token_hash FROM invites WHERE id=$1", body["invite"]["id"])) == auth.hash_token(token)

    # link-preview bots must not burn the single use
    bot = await client.get(f"/i/{token}", headers={"user-agent": "TelegramBot (like TwitterBot)"})
    assert bot.status_code == 200

    g = await client.get(f"/i/{token}", follow_redirects=False)
    assert g.status_code == 302 and g.headers["location"].endswith("/?room=2026-11")
    sid = g.headers["set-cookie"].split(f"{auth.COOKIE}=")[1].split(";")[0]
    assert "httponly" in g.headers["set-cookie"].lower()
    row = await db.fetchrow("SELECT * FROM sessions WHERE id=$1", auth.hash_token(sid))
    assert row["role"] == "viewer" and str(row["invite_id"]) == body["invite"]["id"] and str(row["family_id"]) == world["family"]
    assert (row["expires_at"] - row["created_at"]).total_seconds() <= 86400 + 5

    # the guest cannot manage invites
    assert (await client.get("/api/invites", cookies={auth.COOKIE: sid})).status_code == 403
    assert (await client.get(f"/i/{token}", follow_redirects=False)).status_code == 410   # single use
    assert (await client.get("/i/not-a-real-token")).status_code == 404


async def test_expired_link(world, client):
    ck = await owner_cookie(world)
    body = await _mk_invite(client, world, ck)
    await db.execute("UPDATE invites SET expires_at = now() - interval '1 hour' WHERE id=$1", body["invite"]["id"])
    assert (await client.get(body["link"].replace(PUBLIC, ""))).status_code == 410


async def test_contacts_validation_and_consent(world, client):
    ck = await owner_cookie(world)
    assert (await client.post("/api/contacts", json={"name": "Ravi", "phone": "98765"}, cookies=ck)).status_code == 422
    r = await client.post("/api/contacts", json={"name": "Ravi", "phone": "+91 98765 43210", "language": "hi-IN",
                                                 "consent_to_calls": True}, cookies=ck)
    c = r.json()["contact"]
    assert r.status_code == 201 and c["phone_e164"] == "+919876543210" and c["consent_to_calls"]
    row = await db.fetchrow("SELECT consent_by::text, consent_at FROM contacts WHERE id=$1", c["id"])
    assert row["consent_by"] == world["owner"] and row["consent_at"]
    nc = (await client.post("/api/contacts", json={"name": "Meera", "phone": "+919876500000"}, cookies=ck)).json()["contact"]
    assert nc["consent_to_calls"] is False
    p = await client.patch(f"/api/contacts/{nc['id']}", json={"consent_to_calls": True}, cookies=ck)
    assert p.json()["contact"]["consent_to_calls"] is True
    assert (await client.delete(f"/api/contacts/{c['id']}", cookies=ck)).status_code == 204
    names = {x["name"] for x in (await client.get("/api/contacts", cookies=ck)).json()["contacts"]}
    assert names == {"Priya", "Meera"}


async def test_call_route_returns_clear_refusal(world, client):
    ck = await owner_cookie(world)
    await db.execute("UPDATE contacts SET consent_to_calls=false WHERE id=$1", world["contact"])
    inv = await _mk_invite(client, world, ck)
    assert inv["call_refusal"]["code"] == "no_consent"
    r = await client.post(f"/api/invites/{inv['invite']['id']}/call", cookies=ck)
    assert r.status_code == 409 and r.json()["reason"] == "no_consent" and r.json()["placed"] is False


async def test_invite_list_has_latest_call_status(world, client):
    ck = await owner_cookie(world)
    inv = await _mk_invite(client, world, ck)
    assert (await client.post(f"/api/invites/{inv['invite']['id']}/call", cookies=ck)).json()["placed"] is True
    row = (await client.get("/api/invites", cookies=ck)).json()["invites"][0]
    assert row["call"]["status"] == "queued" and row["contact_name"] == "Priya" and row["link"]


async def test_sync_broadcast(world, client, monkeypatch):
    seen = []

    async def pub(fid, ev):
        seen.append((fid, ev))
    monkeypatch.setattr(bus, "publish", pub)
    ck = await owner_cookie(world)
    r = await client.post("/api/sync", json={"year": 2026, "month": 11, "index": 3, "playing": True}, cookies=ck)
    assert r.status_code == 200
    assert seen[0][1] == {"type": "playback_sync", "year": 2026, "month": 11, "index": 3, "playing": True}
    assert (await client.post("/api/sync", json={"year": 2026, "month": 11, "index": 3, "playing": True})).status_code == 401
