import hashlib
import hmac
import json
import xml.etree.ElementTree as ET

import pytest

from app import bus, config, db
from app.phone import call_flow as cf
from app.phone import invites as inv
from _phone_fixtures import PUBLIC, client, world  # noqa: F401

pytestmark = []


async def _call(w, lang="en-IN"):
    await db.execute("UPDATE contacts SET language=$2 WHERE id=$1", w["contact"], lang)
    iid = (await inv.create_invite(w["family"], w["owner"], w["contact"], 2026, 11))["invite"]["id"]
    return (await inv.place_call(w["family"], iid))["call_session_id"]


async def _post(client, cs, leaf, form=None, sign=True):
    path = f"/twilio/voice/{cs}/{leaf}"
    form = form or {}
    h = {"x-twilio-signature": cf.twilio_signature("test-token", PUBLIC + path, list(form.items()))} if sign else {}
    return await client.post(path, data=form, headers=h)


@pytest.fixture
def tts_off(monkeypatch):
    async def none(*a, **k):
        return None
    monkeypatch.setattr(cf, "speech_url", none)


def capture_bus(monkeypatch):
    events = []

    async def pub(fid, ev):
        events.append(ev)
    monkeypatch.setattr(bus, "publish", pub)
    return events


async def test_bad_signature_rejected(world, client):
    cs = await _call(world)
    assert (await _post(client, cs, "twiml", sign=False)).status_code == 403
    r = await client.post(f"/twilio/voice/{cs}/twiml", headers={"x-twilio-signature": "nope"})
    assert r.status_code == 403


@pytest.mark.parametrize("lang", ["en-IN", "hi-IN", "kn-IN"])
async def test_twiml_gather_wraps_line_in_language(world, client, tts_off, lang):
    cs = await _call(world, lang)
    r = await _post(client, cs, "twiml")
    assert r.status_code == 200
    g = ET.fromstring(r.text).find("Gather")
    assert g.get("input") == "speech" and g.get("language") == lang
    say = g.find("Say")                              # opener is INSIDE the gather (guest can talk over it)
    assert say is not None and say.get("language") == lang
    assert g.get("action").split("?")[0].endswith(f"/twilio/voice/{cs}/turn") and "?t=" in g.get("action")
    if lang == "en-IN":
        assert "automated assistant calling for Memo" in say.text and "Asha" in say.text and "November 2026" in say.text
    assert (await db.fetchval("SELECT status FROM call_sessions WHERE id=$1", cs)) == "talking"


async def test_twiml_uses_play_when_audio_ready(world, client, monkeypatch):
    async def url(*a, **k):
        return "https://memo-test.example.com/media/x.mp3?exp=1&sig=2"
    monkeypatch.setattr(cf, "speech_url", url)
    cs = await _call(world)
    g = ET.fromstring((await _post(client, cs, "twiml")).text).find("Gather")
    assert g.find("Play").text.endswith("x.mp3?exp=1&sig=2")


async def test_context_is_host_event_month_year_only(world):
    cs = await _call(world)
    ctx = cf.context(await cf.load_call(cs))
    assert set(ctx) == {"lang", "guest", "host", "event", "month_en", "month", "year"}
    assert ctx["host"] == "Asha" and ctx["year"] == 2026 and ctx["month_en"] == "November"


@pytest.mark.parametrize("phrase", ["Please stop calling me", "don't call me again", "do not call", "कॉल करना बंद करो", "ಕರೆ ಮಾಡಬೇಡಿ"])
async def test_stop_calling_me(world, client, tts_off, phrase):
    cs = await _call(world)
    r = await _post(client, cs, "turn", {"SpeechResult": phrase})
    assert "<Hangup/>" in r.text
    assert (await db.fetchval("SELECT do_not_call FROM contacts WHERE id=$1", world["contact"])) is True
    assert (await db.fetchval("SELECT status FROM call_sessions WHERE id=$1", cs)) == "declined"


async def test_turn_cap(world, client, tts_off, monkeypatch):
    async def ask(ctx, tr, speech):
        return {"reply": "It is on the sixth.", "intent": "question", "message": ""}
    monkeypatch.setattr(cf, "answer", ask)
    cs = await _call(world)
    for i in range(cf.MAX_TURNS - 1):
        r = await _post(client, cs, "turn", {"SpeechResult": f"when {i}"})
        assert "<Gather" in r.text and "<Hangup/>" not in r.text
    r = await _post(client, cs, "turn", {"SpeechResult": "and when?"})
    assert "<Hangup/>" in r.text and "<Gather" not in r.text
    row = await db.fetchrow("SELECT status, turns, ended_at FROM call_sessions WHERE id=$1", cs)
    assert row["turns"] == cf.MAX_TURNS and row["status"] == "no_answer" and row["ended_at"]


async def test_accept_gives_host_the_link_when_no_channel(world, client, tts_off, monkeypatch):
    async def ask(ctx, tr, speech):
        return {"reply": "Great.", "intent": "accept", "message": ""}
    monkeypatch.setattr(cf, "answer", ask)
    events = capture_bus(monkeypatch)
    cs = await _call(world)
    r = await _post(client, cs, "turn", {"SpeechResult": "yes please"})
    assert "<Hangup/>" in r.text
    out = [e for e in events if e["type"] == "call_outcome"][0]
    assert out["status"] == "accepted" and out["delivery"] == "host_must_share" and "/i/" in out["link"]


async def test_message_stored_and_published(world, client, tts_off, monkeypatch):
    async def ask(ctx, tr, speech):
        return {"reply": "ok", "intent": "message", "message": "Tell Asha I will be late"}
    monkeypatch.setattr(cf, "answer", ask)
    events = capture_bus(monkeypatch)
    cs = await _call(world)
    await _post(client, cs, "turn", {"SpeechResult": "tell her I will be late"})
    assert [e["text"] for e in events if e["type"] == "guest_message"] == ["Tell Asha I will be late"]
    row = await db.fetchrow("SELECT status, message_text FROM call_sessions WHERE id=$1", cs)
    assert row["status"] == "message_left" and "late" in row["message_text"]


def test_reply_capped_at_22_words():
    assert len(cf.cap_reply("Word " * 60).split()) <= cf.MAX_REPLY_WORDS


async def test_status_callbacks(world, client):
    cs = await _call(world)
    await _post(client, cs, "status", {"CallStatus": "ringing"})
    assert (await db.fetchval("SELECT status FROM call_sessions WHERE id=$1", cs)) == "ringing"
    await _post(client, cs, "status", {"CallStatus": "no-answer"})
    assert (await db.fetchval("SELECT status FROM call_sessions WHERE id=$1", cs)) == "no_answer"


async def test_stuck_call_sweep_and_purge(world):
    from app.tasks import calls
    cs = await _call(world)
    await db.execute("UPDATE call_sessions SET started_at = now() - interval '20 minutes' WHERE id=$1", cs)
    assert await calls.sweep_stuck_calls() >= 1
    assert (await db.fetchval("SELECT status FROM call_sessions WHERE id=$1", cs)) == "failed"
    await db.execute("UPDATE call_sessions SET started_at = now() - interval '31 days' WHERE id=$1", cs)
    await calls.purge_old_calls()
    assert await db.fetchval("SELECT count(*) FROM call_sessions WHERE id=$1", cs) == 0


async def test_voice_agent_webhook_signed(world, client):
    cs = await _call(world)
    body = json.dumps({"call_session_id": cs, "outcome": "declined", "summary": "Not this time"}).encode()
    bad = await client.post("/webhooks/voice-agent", content=body, headers={"x-memo-signature": "sha256=00"})
    assert bad.status_code == 403
    sig = hmac.new((config.env("VOICE_AGENT_WEBHOOK_SECRET") or config.APP_SECRET).encode(), body, hashlib.sha256).hexdigest()
    ok = await client.post("/webhooks/voice-agent", content=body, headers={"x-memo-signature": f"sha256={sig}"})
    assert ok.json() == {"ok": True, "applied": True}
    assert (await db.fetchval("SELECT status FROM call_sessions WHERE id=$1", cs)) == "declined"
