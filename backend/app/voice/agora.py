"""Agora Conversational AI sessions for the receptionist and Grandma. Ported from MedSim backend/voice.py.

One ConvoAI agent per character: Sarvam ASR (language "unknown" = auto-detect en/hi/kn), our own custom LLM
endpoint (POST {PUBLIC_BASE_URL}/api/voice/llm/{character}/{voice_session}/chat/completions, which runs the
receptionist tool loop or grounded Grandma), Murf Falcon TTS in the session language, VAD turn detection
(200 ms of speech interrupts, 560 ms of silence ends a turn). Action results go to the browser over the SSE bus
as {"type": "voice_action", ...}.

Agora's cloud must reach the custom LLM, so PUBLIC_BASE_URL has to be a public https URL. When it is not,
start() raises 503 with code "browser_voice_fallback" and the client uses the browser path
(record mic -> POST /api/grandma/talk or /api/reception/act).

Verified against docs.agora.io (as in MedSim, 2026-11): join POST /v2/projects/{appid}/join,
leave POST /v2/projects/{appid}/agents/{id}/leave, update POST /v2/projects/{appid}/agents/{id}/update.
"""
from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import hmac
import logging
import os
import secrets
import time
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from ..observability import nudgebee
from fastapi import HTTPException

from .. import config
from . import lang as L
from . import state as vstate
from .agora_token import RtcTokenBuilder, Role_Publisher

log = logging.getLogger("memo.agora")

AGORA_API = "https://api.agora.io/api/conversational-ai-agent/v2/projects"
AGENT_UID = 900001
TOKEN_TTL_S = 4 * 3600
AGENT_IDLE_TIMEOUT_S = 45
CHARACTERS = ("receptionist", "grandma")

TURN_DETECTION = {
    "mode": "default",
    "config": {
        "speech_threshold": 0.6,
        "start_of_speech": {"mode": "vad", "vad_config": {"interrupt_duration_ms": 200, "prefix_padding_ms": 800}},
        "end_of_speech": {"mode": "vad", "vad_config": {"silence_duration_ms": 560}},
    },
}


def _env(*names: str) -> dict[str, str]:
    missing = [n for n in names if not os.environ.get(n, "").strip()]
    if missing:
        raise HTTPException(503, f"Voice not configured: missing {', '.join(missing)}")
    return {n: os.environ[n].strip() for n in names}


def public_ready() -> bool:
    u = urlparse(config.PUBLIC_BASE_URL)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and host not in ("localhost", "127.0.0.1", "0.0.0.0") and not host.endswith(".local")


def fallback_error() -> HTTPException:
    return HTTPException(503, detail={
        "code": "browser_voice_fallback",
        "message": "Live voice needs a public https PUBLIC_BASE_URL so Agora can reach Memo's language model "
                   f"(it is {config.PUBLIC_BASE_URL}). Use the browser voice path: record the mic and POST it to "
                   "/api/grandma/talk or /api/reception/act.",
        "fallback": {"grandma": "/api/grandma/talk", "receptionist": "/api/reception/act"},
    })


def health() -> dict:
    has = lambda n: bool(os.environ.get(n, "").strip())  # noqa: E731
    return {"agora_configured": has("AGORA_APP_ID") and has("AGORA_APP_CERTIFICATE"),
            "convoai_configured": has("AGORA_CUSTOMER_ID") and has("AGORA_CUSTOMER_SECRET"),
            "murf_configured": has("MURF_API_KEY"), "public_url_ready": public_ready(),
            "public_base_url": config.PUBLIC_BASE_URL}


# ---------------------------------------------------------------- LLM bearer tokens (stateless, HMAC)

def mint_llm_token(vsid: str, ttl: int = TOKEN_TTL_S) -> str:
    exp = int(time.time()) + ttl
    sig = hmac.new(config.APP_SECRET.encode(), f"voice-llm:{vsid}:{exp}".encode(), hashlib.sha256).hexdigest()[:40]
    return f"{exp}.{sig}"


def verify_llm_token(vsid: str, token: str) -> bool:
    try:
        exp_s, sig = token.split(".", 1)
        exp = int(exp_s)
    except (ValueError, AttributeError):
        return False
    good = hmac.new(config.APP_SECRET.encode(), f"voice-llm:{vsid}:{exp}".encode(), hashlib.sha256).hexdigest()[:40]
    return exp >= time.time() and hmac.compare_digest(good, sig)


# ---------------------------------------------------------------- Agora REST

def _auth_header() -> dict[str, str]:
    e = _env("AGORA_CUSTOMER_ID", "AGORA_CUSTOMER_SECRET")
    raw = f"{e['AGORA_CUSTOMER_ID']}:{e['AGORA_CUSTOMER_SECRET']}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode(), "Content-Type": "application/json"}


async def _call(method: str, path: str, body: Optional[dict] = None) -> httpx.Response:
    app_id = _env("AGORA_APP_ID")["AGORA_APP_ID"]
    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.request(method, f"{AGORA_API}/{app_id}{path}", json=body, headers=_auth_header())
        nudgebee.record_http("agora", r.status_code)
        return r
    except httpx.HTTPError as e:
        nudgebee.record_provider_error("agora", "network")
        raise HTTPException(502, f"Agora request failed: {type(e).__name__}") from e


def _token(app_id: str, cert: str, channel: str, uid: int) -> str:
    return RtcTokenBuilder.build_token_with_rtm(app_id, cert, channel, str(uid), Role_Publisher, TOKEN_TTL_S, TOKEN_TTL_S)


def llm_url(character: str, vsid: str) -> str:
    return f"{config.PUBLIC_BASE_URL}/api/voice/llm/{character}/{vsid}/chat/completions"


def join_body(character: str, lang: str, channel: str, user_uid: int, agent_token: str, vsid: str,
              greeting: str, system_prompt: str) -> dict[str, Any]:
    sarvam = os.environ.get("SARVAM_API_KEY", "").strip()
    murf = _env("MURF_API_KEY")["MURF_API_KEY"]
    asr = ({"vendor": "sarvam", "params": {"api_key": sarvam, "language": "unknown"}} if sarvam
           else {"vendor": "ares", "language": lang})
    return {
        "name": f"memo-{character}-{secrets.token_hex(5)}",
        "properties": {
            "channel": channel,
            "token": agent_token,
            "agent_rtc_uid": str(AGENT_UID),
            "remote_rtc_uids": [str(user_uid)],
            "idle_timeout": AGENT_IDLE_TIMEOUT_S,
            "advanced_features": {"enable_rtm": True},
            "parameters": {"data_channel": "rtm", "enable_error_message": True, "enable_metrics": True},
            "asr": asr,
            "llm": {
                "vendor": "custom",
                "style": "openai",
                "url": llm_url(character, vsid),
                "api_key": mint_llm_token(vsid),
                "system_messages": [{"role": "system", "content": system_prompt}],
                "greeting_message": greeting,
                "failure_message": L.FAILURE[lang],
                "max_history": 16,
                "params": {"model": f"memo-{character}", "max_tokens": 300},
            },
            "turn_detection": copy.deepcopy(TURN_DETECTION),
            "filler_words": {
                "enable": True,
                "trigger": {"fixed_time_config": {"response_wait_ms": 1400}},
                "content": {"mode": "static", "static_config": {"phrases": L.FILLER_LINES[character][lang],
                                                                 "selection_rule": "shuffle"}},
            },
            "tts": tts_config(character, lang, sarvam, murf),
        },
    }


LIVE_GRANDMA_DELTA = {"pace": -0.05, "pitch": -0.08}      # added to Grandma's profile on Agora live sessions


def tts_config(character: str, lang: str, sarvam_key: str, murf_key: str) -> dict[str, Any]:
    """The character's chosen voice (lang.VOICE_PROFILES, docs/VOICES.md) for Agora's TTS: Sarvam bulbul through
    Agora's `sarvam` vendor (docs.agora.io/en/ai/models/tts/sarvam; params not in Agora's table, such as pitch and
    temperature for bulbul:v3, pass through to Sarvam), else the character's Murf voice with its rate / pitch."""
    prof = L.VOICE_PROFILES[character][lang]
    if prof["provider"] == "sarvam" and sarvam_key:
        p = prof.get("params") or {}
        params: dict[str, Any] = {"api_subscription_key": sarvam_key, "speaker": prof["voice"],
                                  "target_language_code": lang, "model": L.sarvam_model_for(prof["voice"]),
                                  "speech_sample_rate": 24000, "enable_preprocessing": True}
        params.update({k: p[k] for k in ("pace", "pitch", "loudness", "temperature") if p.get(k) is not None})
        if character == "grandma":
            # Agora streams the vendor's audio straight to the caller, so the ffmpeg aged-voice chain (tts.age_audio)
            # cannot run on live sessions; approximate its pitch / pace part with Sarvam's own controls.
            params["pace"] = round(params.get("pace", 1.0) + LIVE_GRANDMA_DELTA["pace"], 3)
            params["pitch"] = round(params.get("pitch", 0.0) + LIVE_GRANDMA_DELTA["pitch"], 3)
        return {"vendor": "sarvam", "params": params}
    mp = L.MURF_PARAMS.get(character, {})
    return {"vendor": "murf", "params": {
        "api_key": murf_key, "base_url": "wss://global.api.murf.ai/v1/speech/stream-input",
        "voiceId": L.MURF_VOICES[character][lang], "model": "FALCON", "locale": lang,
        "rate": mp.get("rate", 0), "pitch": mp.get("pitch", 0), "sample_rate": 24000}}


async def start(*, family_id: str, member_id: Optional[str], role: str, session_id: str, character: str,
                language: str, scope: dict, greeting: str, invite_room: Optional[tuple] = None) -> dict:
    if character not in CHARACTERS:
        raise HTTPException(422, "character must be receptionist or grandma")
    if not public_ready():
        raise fallback_error()
    env = _env("AGORA_APP_ID", "AGORA_APP_CERTIFICATE", "AGORA_CUSTOMER_ID", "AGORA_CUSTOMER_SECRET", "MURF_API_KEY")
    app_id, cert = env["AGORA_APP_ID"], env["AGORA_APP_CERTIFICATE"]
    vsid = secrets.token_urlsafe(12).replace("-", "x").replace("_", "y")
    channel = f"memo-{character}-{secrets.token_hex(4)}"
    user_uid = secrets.randbelow(900000) + 100000
    user_token = _token(app_id, cert, channel, user_uid)
    agent_token = _token(app_id, cert, channel, AGENT_UID)
    sys_prompt = ("Memo museum " + character + ". Replies are produced by Memo's server; this prompt is informational.")
    body = join_body(character, language, channel, user_uid, agent_token, vsid, greeting, sys_prompt)
    r = await _call("POST", "/join", body)
    if 400 <= r.status_code < 500 and "filler" in r.text.lower():
        body["properties"].pop("filler_words", None)
        r = await _call("POST", "/join", body)
    if r.status_code != 200:
        raise HTTPException(502, f"Agora join failed ({r.status_code}): {r.text[:500]}")
    agent_id = r.json().get("agent_id")
    if not agent_id:
        raise HTTPException(502, "Agora join returned no agent_id")
    st = {"language": language, "agent_id": agent_id, "channel": channel, "character": character, "scope": scope,
          "role": role, "web_session": session_id, "invite_room": list(invite_room) if invite_room else None}
    await vstate.save(f"agora:{vsid}", family_id, member_id, character, st)
    return {"appId": app_id, "channel": channel, "uid": user_uid, "rtcToken": user_token, "rtmToken": user_token,
            "token": user_token, "agentUid": AGENT_UID, "agentId": agent_id, "voiceSessionId": vsid,
            "character": character, "language": language}


# In-flight custom-LLM work (reception tool loop / grounded Grandma + TTS) per voice session, so an interrupt can
# cancel it. Process-local: the API runs as one process.
INFLIGHT: dict[str, "asyncio.Task"] = {}


async def interrupt(agent_id: str, vsid: Optional[str] = None) -> dict:
    """Cut the agent's current speech / thinking (Agora ConvoAI POST /v2/projects/{appid}/agents/{id}/interrupt,
    docs.agora.io/en/api-reference/api-ref/conversational-ai/interrupt) and cancel our in-flight LLM work for the
    session. Idempotent: an agent that is idle or already gone counts as interrupted."""
    cancelled = False
    task = INFLIGHT.pop(vsid, None) if vsid else None
    if task and not task.done():
        task.cancel()
        cancelled = True
    r = await _call("POST", f"/agents/{agent_id}/interrupt", {})
    if r.status_code == 200:
        return {"ok": True, "cancelled_llm": cancelled}
    t = r.text.lower()
    if r.status_code in (404, 409, 410) or any(k in t for k in ("not found", "not exist", "not speaking", "idle",
                                                                 "shutting down", "conflict", "invalidrequestbody")):
        return {"ok": True, "cancelled_llm": cancelled, "alreadyIdle": True}
    raise HTTPException(502, f"Agora interrupt failed ({r.status_code}): {r.text[:300]}")


async def stop(agent_id: str) -> dict:
    r = await _call("POST", f"/agents/{agent_id}/leave")
    if r.status_code == 200:
        return {"ok": True}
    t = r.text.lower()
    if r.status_code in (404, 410) or any(k in t for k in ("not found", "not exist", "invalidrequestbody", "shutting down",
                                                           "conflict")):
        return {"ok": True, "alreadyStopped": True}
    raise HTTPException(502, f"Agora leave failed ({r.status_code}): {r.text[:300]}")
