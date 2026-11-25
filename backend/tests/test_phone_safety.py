import pytest

from app import config, db, flags
from app.phone import invites as inv
from _phone_fixtures import NIGHT_TZ, world  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _invite(w):
    r = await inv.create_invite(w["family"], w["owner"], w["contact"], 2026, 11)
    return r["invite"]["id"]


async def _refused(w, code):
    iid = await _invite(w)
    with pytest.raises(inv.CallRefused) as e:
        await inv.place_call(w["family"], iid)
    assert e.value.code == code
    assert w["placed"] == []                      # nothing reached Twilio


async def test_happy_path_places_one_call(world):
    iid = await _invite(world)
    res = await inv.place_call(world["family"], iid)
    assert res["status"] == "queued" and len(world["placed"]) == 1
    assert world["placed"][0]["url"].endswith(f"/twilio/voice/{res['call_session_id']}/twiml")
    row = await db.fetchrow("SELECT provider_call_id FROM call_sessions WHERE id=$1", res["call_session_id"])
    assert row["provider_call_id"].startswith("CA")


async def test_confirm_text_masks_number(world):
    r = await inv.create_invite(world["family"], world["owner"], world["contact"], 2026, 11)
    assert r["confirm_text"] == "Call Priya, number ending 4417, and invite them to November 2026?"
    assert "9876" not in r["confirm_text"]


async def test_no_consent(world):
    await db.execute("UPDATE contacts SET consent_to_calls=false WHERE id=$1", world["contact"])
    await _refused(world, "no_consent")


async def test_do_not_call(world):
    await db.execute("UPDATE contacts SET do_not_call=true WHERE id=$1", world["contact"])
    await _refused(world, "do_not_call")


async def test_quiet_hours(world):
    await db.execute("UPDATE contacts SET timezone=$2 WHERE id=$1", world["contact"], NIGHT_TZ())
    await _refused(world, "quiet_hours")


async def test_quiet_hours_switchable(world):
    await db.execute("UPDATE contacts SET timezone=$2 WHERE id=$1", world["contact"], NIGHT_TZ())
    await db.execute("UPDATE families SET settings = settings || '{\"call_quiet_hours\": false}' WHERE id=$1", world["family"])
    iid = await _invite(world)
    assert (await inv.place_call(world["family"], iid))["status"] == "queued"


async def test_hourly_limit(world):
    iid = await _invite(world)
    await inv.place_call(world["family"], iid)
    iid2 = await _invite(world)
    with pytest.raises(inv.CallRefused) as e:
        await inv.place_call(world["family"], iid2)
    assert e.value.code == "hourly_limit"
    assert len(world["placed"]) == 1


async def test_daily_cap(world):
    await flags.set_override("max_calls_per_day", 0, world["family"])
    await _refused(world, "daily_cap")


async def test_kill_switch(world):
    await flags.set_override("phone_calls_enabled", False, world["family"])
    await _refused(world, "kill_switch")


async def test_allowlist(world):
    await flags.set_override("phone_allowlist", False, world["family"])
    await _refused(world, "not_allowlisted")


async def test_public_url_required(world, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "http://localhost:8000")
    await _refused(world, "no_public_url")


async def test_expired_invite(world):
    iid = await _invite(world)
    await db.execute("UPDATE invites SET expires_at = now() - interval '1 minute' WHERE id=$1", iid)
    with pytest.raises(inv.CallRefused) as e:
        await inv.place_call(world["family"], iid)
    assert e.value.code == "invite_expired"


async def test_other_family_cannot_call(world):
    iid = await _invite(world)
    with pytest.raises(inv.CallRefused) as e:
        await inv.place_call("00000000-0000-0000-0000-000000000001", iid)
    assert e.value.code == "not_found"


async def test_find_contacts(world):
    assert [c["name"] for c in await inv.find_contacts(world["family"], "pri")] == ["Priya"]
    assert [c["name"] for c in await inv.find_contacts(world["family"], "friend")] == ["Priya"]
    assert await inv.find_contacts(world["family"], "zzz") == []
