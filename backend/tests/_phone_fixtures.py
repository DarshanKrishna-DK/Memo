"""Shared fixtures for the phone tests. Real Postgres; the only stub is the Twilio network call."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest_asyncio

from app import auth, config, db, flags
from app.phone import invites as inv

PUBLIC = "https://memo-test.example.com"


def tz_where_hour(pred) -> str:
    now = datetime.now(timezone.utc)
    for off in range(-12, 13):
        name = f"Etc/GMT{'+' if off < 0 else '-'}{abs(off)}" if off else "Etc/GMT"
        if pred(now.astimezone(ZoneInfo(name)).hour):
            return name
    raise RuntimeError("no tz")


def DAY_TZ() -> str:
    return tz_where_hour(lambda h: 10 <= h <= 18)


def NIGHT_TZ() -> str:
    return tz_where_hour(lambda h: h >= 22 or h < 6)


@pytest_asyncio.fixture
async def world(monkeypatch):
    flags._cache.clear()
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", PUBLIC)
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("TWILIO_VOICE_FROM", "+15005550006")
    monkeypatch.delenv("TWILIO_SMS_FROM", raising=False)
    placed: list[dict] = []

    async def fake_create(to, twiml_url, status_url):
        placed.append({"to": to, "url": twiml_url})
        return {"sid": "CA" + secrets.token_hex(8)}
    monkeypatch.setattr(inv, "_twilio_create_call", fake_create)   # network boundary only: no real call in tests

    fam = await db.fetchval(
        "INSERT INTO families(name, invite_code) VALUES ('Phone test family', $1) RETURNING id::text", secrets.token_hex(8))
    owner = await db.fetchval(
        "INSERT INTO members(family_id, nickname, role) VALUES ($1,'Asha','owner') RETURNING id::text", fam)
    cid = await db.fetchval(
        "INSERT INTO contacts(family_id,name,relation,phone_e164,language,consent_to_calls,consent_by,consent_at,timezone) "
        "VALUES ($1,'Priya','friend','+919876544417','en-IN',true,$2,now(),$3) RETURNING id::text", fam, owner, DAY_TZ())
    yield {"family": fam, "owner": owner, "contact": cid, "placed": placed}
    await db.execute("DELETE FROM flag_overrides WHERE family_id=$1", fam)
    await db.execute("DELETE FROM families WHERE id=$1", fam)
    flags._cache.clear()
    await db.close()


@pytest_asyncio.fixture
async def client():
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=PUBLIC) as c:
        yield c


async def owner_cookie(w) -> dict:
    sid = await auth.new_session(w["family"], w["owner"], "owner")
    return {auth.COOKIE: sid}
