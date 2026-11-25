"""voice-ai: HTTP endpoints through the real app (session cookie, real DB, real Sarvam/Groq/Murf/Wikipedia).
Covers both voice paths: the browser path (recorded audio -> /api/grandma/talk) and the Agora path's custom LLM
endpoint (/api/voice/llm/...), plus the 503 fallback from /api/voice/start while PUBLIC_BASE_URL is local."""
from __future__ import annotations

import json

import httpx
import pytest
import pytest_asyncio

from _voice_fixtures import drop_family, fresh_pool, make_family, seed_november_room
from app import auth, config, storage
from app.ai import tts
from app.main import app
from app.voice import agora, lang as L, state as vstate

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def env():
    await fresh_pool()
    f = await make_family()
    f["mem"] = await seed_november_room(f)
    sid = await auth.new_session(f["id"], f["owner"], "owner")
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                               cookies={auth.COOKIE: sid}, timeout=120)
    f["client"] = client
    yield f
    await client.aclose()
    await drop_family(f["id"])


async def test_requires_session():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.post("/api/tts", json={"text": "hi"})).status_code == 401
        assert (await c.post("/api/grandma/greet", json={"year": 2026, "month": 11})).status_code == 401


async def test_tts_and_guide_lines(env):
    c = env["client"]
    r = await c.post("/api/tts", json={"text": "This way to the lift.", "language": "en-IN", "voice": "guide"})
    assert r.status_code == 200, r.text
    assert r.json()["url"].startswith("/media/") and r.json()["duration_s"] > 0.5
    r = await c.get("/api/guide/lines", params={"lang": "hi-IN"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["language"] == "hi-IN" and set(body["lines"]) >= {"follow_me", "to_lift", "here_we_are", "locked_door"}
    assert "Ajji" in body["lines"]["locked_door"]["text"]
    assert all(v["audio_url"] for v in body["lines"].values())


async def test_voice_start_falls_back_when_not_public(env):
    if agora.public_ready():
        pytest.skip("PUBLIC_BASE_URL is public: the Agora path is live")
    r = await env["client"].post("/api/voice/start", json={"character": "grandma", "year": 2026, "month": 11})
    assert r.status_code == 503
    d = r.json()["detail"]
    assert d["code"] == "browser_voice_fallback" and d["fallback"]["grandma"] == "/api/grandma/talk"


async def test_greet_tour_and_text_talk(env):
    c = env["client"]
    g = (await c.post("/api/grandma/greet", json={"year": 2026, "month": 11})).json()
    assert g["text"].startswith("Oh, welcome back! November 2026 has four memories, one of them a voice note.")
    assert g["audio_url"] and g["subtitles"][0]["start_s"] == 0
    t = await c.post("/api/grandma/tour", json={"year": 2026, "month": 11})
    assert t.status_code == 200, t.text
    tour = t.json()
    assert tour["sentences"] and all(s["audio_url"] for s in tour["sentences"])
    assert tour["highlights"] and all(h["memory_id"] in env["mem"].values() for h in tour["highlights"])
    ends = [s["end_s"] for s in tour["subtitles"]]
    assert ends == sorted(ends)
    print(f"\ntour: {len(tour['sentences'])} sentences, {tour['subtitles'][-1]['end_s']:.1f}s of audio, source={tour['source']}")
    r = (await c.post("/api/grandma/talk", json={"text": "What is the essence of Diwali?",
                                                 "scope": {"year": 2026, "month": 11}})).json()
    assert r["source"] == "general" and r["text"].startswith("Now, this isn't from your family's memories, but")


async def test_recorded_audio_talk_browser_path(env):
    # A real spoken question (synthesized by our TTS), sent as a recording the way the browser path does.
    q = await tts.synthesize("Who bought the sweets?", "en-IN", "receptionist")
    audio = storage.get(q["storage_key"])
    r = await env["client"].post("/api/grandma/talk", files={"audio": ("q.mp3", audio, "audio/mpeg")},
                                 data={"scope": json.dumps({"year": 2026, "month": 11})})
    assert r.status_code == 200, r.text
    body = r.json()
    print("\nheard:", body["transcript"], "->", body["source"], body["text"])
    assert "sweet" in body["transcript"].lower()
    assert body["source"] == "family" and "Ravi" in body["text"] and body["audio_url"]


async def test_reception_act_json(env):
    r = await env["client"].post("/api/reception/act", json={"text": "Take me to November 2026"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["action"]["type"] == "route" and b["action"]["data"]["month"] == 11
    assert b["speech"]["audio_url"] and b["reply"]


async def test_agora_custom_llm_endpoint(env):
    """What Agora's engine calls: OpenAI-style streaming chat completions with our bearer token."""
    vsid = "pytestvs" + env["id"][:8]
    await vstate.save(f"agora:{vsid}", env["id"], env["owner"], "grandma",
                      {"language": "en-IN", "character": "grandma", "scope": {"year": 2026, "month": 11}, "role": "owner"})
    c = env["client"]
    bad = await c.post(f"/api/voice/llm/grandma/{vsid}/chat/completions", json={"messages": []},
                       headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401
    tok = agora.mint_llm_token(vsid)
    r = await c.post(f"/api/voice/llm/grandma/{vsid}/chat/completions", headers={"Authorization": f"Bearer {tok}"},
                     json={"stream": True, "messages": [{"role": "system", "content": "x"},
                                                        {"role": "user", "content": "Who bought the sweets?"}]})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    chunks = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: {")]
    text = "".join(ch["choices"][0]["delta"].get("content", "") for ch in chunks)
    print("\nagora llm said:", text)
    assert "Ravi" in text and r.text.rstrip().endswith("data: [DONE]")
    # a blank noise turn is answered with silence
    r = await c.post(f"/api/voice/llm/grandma/{vsid}/chat/completions", headers={"Authorization": f"Bearer {tok}"},
                     json={"stream": False, "messages": [{"role": "user", "content": "  "}]})
    assert r.json()["choices"][0]["message"]["content"] == ""
    assert config.PUBLIC_BASE_URL  # sanity


async def test_fillers_cached_per_character_and_register(env):
    c = env["client"]
    for character, lang, want_lang in (("grandma", "en-IN", "en-IN"), ("receptionist", "hinglish", "hi-IN"),
                                       ("grandma", "kanglish", "kn-IN")):
        r = await c.get("/api/voice/fillers", params={"character": character, "lang": lang})
        assert r.status_code == 200, r.text
        b = r.json()
        print(f"\n{character}/{lang}:", [f["text"] for f in b["fillers"]])
        assert b["language"] == want_lang and len(b["fillers"]) >= 3
        assert all(f["audio_url"].startswith("/media/") and 0.2 < f["duration_s"] < 6 for f in b["fillers"])
    again = (await c.get("/api/voice/fillers", params={"character": "grandma", "lang": "en-IN"})).json()
    assert again["fillers"][0]["text"] == L.FILLER_LINES["grandma"]["en-IN"][0]
    assert (await c.get("/api/voice/fillers", params={"character": "nobody"})).status_code == 422


async def test_interrupt_requires_agent_and_is_idempotent(env):
    c = env["client"]
    assert (await c.post("/api/voice/interrupt", json={})).status_code == 422
    # A voice session of this family with an in-flight LLM task: interrupt cancels it (Agora answers for the id).
    import asyncio
    vsid = "pytestvs" + env["id"][:6]
    await vstate.save(f"agora:{vsid}", env["id"], env["owner"], "grandma", {"agent_id": "pytest-agent-x", "language": "en-IN"})
    task = asyncio.create_task(asyncio.sleep(30))
    agora.INFLIGHT[vsid] = task
    r = await c.post("/api/voice/interrupt", content=json.dumps({"agentId": "pytest-agent-x"}),
                     headers={"content-type": "text/plain"})
    print("\ninterrupt:", r.status_code, r.text[:200])
    if r.status_code == 503:
        pytest.skip("Agora REST credentials not configured")
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["cancelled_llm"] is True
    await asyncio.sleep(0)
    assert task.cancelled()
    r2 = await c.post("/api/voice/interrupt", json={"agentId": "pytest-agent-x"})
    assert r2.status_code == 200 and r2.json()["ok"] is True and r2.json()["cancelled_llm"] is False
