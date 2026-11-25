"""Live voice (Agora Conversational AI) for the receptionist and Grandma, plus the custom LLM endpoint Agora calls.

POST /api/voice/start    {character, language?, year?, month?, event_id?} -> session (appId, channel, uid, tokens)
                         503 {code:"browser_voice_fallback"} when PUBLIC_BASE_URL is not public https
POST /api/voice/stop     {agentId} (also accepts navigator.sendBeacon text/plain JSON)
POST /api/voice/context  {voiceSessionId, year?, month?, event_id?, language?} -> refresh Grandma's room
POST /api/voice/llm/{character}/{vsid}[/chat/completions]   OpenAI-compatible streaming endpoint (Agora only)
GET  /api/voice/health
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .. import bus, db, flags
from ..ai import tts
from ..auth import Session, current_session
from ..voice import agora, grandma, grounding, lang as L, reception, state as vstate
from .grandma import guard_room, session_language

log = logging.getLogger("memo.routes.voice")
router = APIRouter()


class StartIn(BaseModel):
    character: str = Field(pattern="^(receptionist|grandma)$")
    language: Optional[str] = None
    year: Optional[int] = None
    month: Optional[int] = Field(default=None, ge=1, le=12)
    event_id: Optional[str] = None


class ContextIn(BaseModel):
    voiceSessionId: str
    year: Optional[int] = None
    month: Optional[int] = Field(default=None, ge=1, le=12)
    event_id: Optional[str] = None
    language: Optional[str] = None


@router.get("/api/voice/health")
async def health(s: Session = Depends(current_session)) -> dict:
    return {**agora.health(), "voice_enabled": bool(await flags.get("voice_enabled", s.family_id)),
            "browser_path": {"grandma": "/api/grandma/talk", "receptionist": "/api/reception/act"}}


@router.post("/api/voice/start")
async def start(body: StartIn, s: Session = Depends(current_session)) -> dict:
    if not await flags.get("voice_enabled", s.family_id):
        raise HTTPException(403, {"code": "voice_disabled", "message": "Voice is switched off for this family."})
    scope: dict = {}
    if body.character == "grandma":
        if s.is_guest and s.invite_room:
            scope = {"year": s.invite_room[0], "month": s.invite_room[1]}
        elif body.year and body.month:
            scope = {"year": body.year, "month": body.month, "event_id": body.event_id}
    lang = await session_language(s, body.language, body.character)
    if not agora.public_ready():
        raise agora.fallback_error()   # decided before any paid work: the client uses the browser voice path
    if body.character == "grandma" and scope.get("month"):
        g = await grandma.greet(s.family_id, scope["year"], scope["month"], scope.get("event_id"), lang, audio=False)
        greeting = g["text"]
    elif body.character == "grandma":
        greeting = L.t("greet_offer", lang)
    else:
        greeting = L.t("rx_hello", lang)
    out = await agora.start(family_id=s.family_id, member_id=s.member_id, role=s.role, session_id=s.id,
                            character=body.character, language=lang, scope=scope, greeting=greeting,
                            invite_room=s.invite_room)
    out["greeting"] = greeting
    return out


@router.post("/api/voice/stop")
async def stop(request: Request, s: Session = Depends(current_session)) -> dict:
    try:
        data = json.loads((await request.body()) or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(422, "body must be JSON {agentId}")
    agent_id = str(data.get("agentId") or "")
    if not agent_id:
        raise HTTPException(422, "agentId is required")
    return await agora.stop(agent_id)


@router.post("/api/voice/interrupt")
async def interrupt(request: Request, s: Session = Depends(current_session)) -> dict:
    """{agentId} (sendBeacon text/plain OK) -> cut a live Agora agent mid-speech and cancel our in-flight LLM/TTS
    work for that voice session. Only the family that started the agent may interrupt it. Idempotent."""
    try:
        data = json.loads((await request.body()) or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(422, "body must be JSON {agentId}")
    agent_id = str(data.get("agentId") or "")
    if not agent_id:
        raise HTTPException(422, "agentId is required")
    row = await db.fetchrow("SELECT key, family_id FROM voice_state WHERE key LIKE 'agora:%' AND state->>'agent_id'=$1",
                            agent_id)
    if row and str(row["family_id"]) != s.family_id:
        raise HTTPException(404, "No such voice session.")
    vsid = row["key"].split(":", 1)[1] if row else None
    out = await agora.interrupt(agent_id, vsid)
    if vsid:
        st = await vstate.raw(f"agora:{vsid}")
        if st:
            state = dict(st["state"] or {})
            state["interrupted_at"] = time.time()
            await vstate.save(f"agora:{vsid}", s.family_id, s.member_id, st["character"], state)
    return out


@router.get("/api/voice/fillers")
async def fillers(character: str = "grandma", lang: Optional[str] = None,
                  s: Session = Depends(current_session)) -> dict:
    """Short pre-synthesized thinking clips for a character ("Hmm, let me think..."), cached in tts_cache, for the
    client to play when a reply takes longer than ~700 ms. `lang`: en-IN | hi-IN | kn-IN | hinglish | kanglish
    (default: the session language). -> {character, language, register, fillers:[{text, audio_url, duration_s}]}"""
    if character not in ("grandma", "receptionist"):
        raise HTTPException(422, "character must be grandma or receptionist")
    key = lang if lang in ("hinglish", "kanglish") else await session_language(s, lang, character)
    lines, voice_lang, reg = L.filler_lines(character, key)

    async def one(text: str) -> dict:
        out = await tts.synthesize(text, voice_lang, character, family_id=s.family_id)
        return {"text": text, "audio_url": out["url"], "duration_s": out["duration_s"]}

    clips = await asyncio.gather(*(one(t) for t in lines))
    return {"character": character, "language": voice_lang, "register": reg, "fillers": list(clips)}


@router.post("/api/voice/context")
async def context(body: ContextIn, s: Session = Depends(current_session)) -> dict:
    key = f"agora:{body.voiceSessionId}"
    row = await vstate.raw(key)
    if not row or str(row["family_id"]) != s.family_id:
        raise HTTPException(404, "No such voice session.")
    st = dict(row["state"] or {})
    if body.year and body.month:
        guard_room(s, body.year, body.month)
        st["scope"] = {"year": body.year, "month": body.month, "event_id": body.event_id}
    if body.language:
        st["language"] = L.norm(body.language)
    await vstate.save(key, s.family_id, s.member_id, row["character"], st)
    return {"ok": True, "scope": st.get("scope"), "language": st.get("language"),
            "note": "Agora's TTS voice is fixed per session; restart the session after a language change."}


# ---------------------------------------------------------------- custom LLM endpoint (called by Agora)

PLACEHOLDER_RE = ("", "(inaudible, background noise)")


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") in (None, "text"))
    return ""


def _last_user(messages: Any) -> str:
    if not isinstance(messages, list) or not messages:
        return ""
    last = messages[-1]
    if not isinstance(last, dict) or last.get("role") != "user":
        return ""
    return " ".join(_text_of(last.get("content")).split())


def _sse(cid: str, model: str, delta: dict, finish: Optional[str] = None) -> str:
    c = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()), "model": model,
         "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    return f"data: {json.dumps(c, ensure_ascii=False)}\n\n"


def _reply(stream: bool, model: str, sentences: list[str]) -> Response:
    cid = "chatcmpl-memo-" + secrets.token_hex(6)
    if not stream:
        return JSONResponse({"id": cid, "object": "chat.completion", "created": int(time.time()), "model": model,
                             "choices": [{"index": 0, "message": {"role": "assistant", "content": " ".join(sentences)},
                                          "finish_reason": "stop"}]})
    body = _sse(cid, model, {"role": "assistant", "content": ""})
    for i, s in enumerate(sentences):
        body += _sse(cid, model, {"content": (" " if i else "") + s})
    body += _sse(cid, model, {}, "stop") + "data: [DONE]\n\n"
    return Response(content=body, media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


async def _llm(character: str, vsid: str, request: Request) -> Response:
    h = request.headers.get("authorization", "")
    token = h[7:].strip() if h.lower().startswith("bearer ") else ""
    if character not in agora.CHARACTERS or not agora.verify_llm_token(vsid, token):
        return JSONResponse({"error": {"message": "invalid or missing bearer token", "type": "invalid_request_error"}},
                            status_code=401)
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": {"message": "body must be JSON"}}, status_code=400)
    stream = payload.get("stream", True) is not False
    model = f"memo-{character}"
    key = f"agora:{vsid}"
    row = await vstate.raw(key)
    if not row:
        return JSONResponse({"error": {"message": "voice session expired"}}, status_code=404)
    fid = str(row["family_id"])
    mid = str(row["member_id"]) if row["member_id"] else None
    st = dict(row["state"] or {})
    text = _last_user(payload.get("messages"))
    if text.strip() in PLACEHOLDER_RE:
        return _reply(stream, model, [])        # background noise: say nothing (MedSim's blank-turn rule)
    lang = L.norm(st.get("language"))

    async def work() -> tuple[list[str], dict, str]:
        if character == "receptionist":
            room = None
            if st.get("invite_room"):
                room = {"year": st["invite_room"][0], "month": st["invite_room"][1]}
            out = await reception.act_core(fid, mid, text, lang, state_key=key, room=room, role=st.get("role") or "viewer")
            return grounding.split_sentences(out["reply"]), out["action"], out["source"]
        scope = {k: v for k, v in (st.get("scope") or {}).items() if k in ("year", "month") and v}
        out = await grandma.talk(fid, text, scope, lang, state_key=key, member_id=mid,
                                 role=st.get("role") or "viewer", audio=False)
        for s in out["sentences"]:
            if s["memory_ids"]:
                await bus.publish(fid, {"type": "voice_highlight", "voice_session": vsid,
                                        "memory_ids": s["memory_ids"], "text": s["text"]})
        return [s["text"] for s in out["sentences"]], out.get("action") or {"type": "none", "data": {}}, out["source"]

    # Tracked so POST /api/voice/interrupt can cancel it (a newer turn also supersedes an older one).
    old = agora.INFLIGHT.get(vsid)
    if old and not old.done():
        old.cancel()
    task = asyncio.create_task(work())
    agora.INFLIGHT[vsid] = task
    try:
        sentences, action, source = await task
    except asyncio.CancelledError:
        if not task.cancelled():
            raise
        return _reply(stream, model, [])        # interrupted: say nothing
    except HTTPException as e:
        log.warning("voice llm %s failed: %s", character, e.detail)
        return _reply(stream, model, [L.FAILURE[lang]])
    finally:
        if agora.INFLIGHT.get(vsid) is task:
            agora.INFLIGHT.pop(vsid, None)
    await bus.publish(fid, {"type": "voice_action", "character": character, "voice_session": vsid,
                            "transcript": text, "reply": " ".join(sentences), "source": source,
                            "action": json.loads(json.dumps(action, default=str))})
    return _reply(stream, model, sentences)


@router.post("/api/voice/llm/{character}/{vsid}/chat/completions")
async def llm_chat(character: str, vsid: str, request: Request) -> Response:
    return await _llm(character, vsid, request)


@router.post("/api/voice/llm/{character}/{vsid}")
async def llm_root(character: str, vsid: str, request: Request) -> Response:
    return await _llm(character, vsid, request)
