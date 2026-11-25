"""Twilio voice webhooks (signature-validated) and the signed voice-agent result endpoint."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response

from .. import config, db
from ..phone import call_flow as cf
from ..phone import invites as inv

log = logging.getLogger("memo.twilio")
router = APIRouter()


def _xml(body: str) -> Response:
    return Response(content=body, media_type="application/xml")


async def _guard(request: Request) -> dict[str, str]:
    params = await cf.read_params(request)
    if not cf.signature_ok(request, params):
        raise HTTPException(403, "Bad Twilio signature.")
    return dict(params)


@router.api_route("/twilio/voice/{cs_id}/twiml", methods=["GET", "POST"])
async def twiml(cs_id: str, request: Request) -> Response:
    await _guard(request)
    return _xml(await cf.start(cs_id))


@router.post("/twilio/voice/{cs_id}/turn")
async def turn(cs_id: str, request: Request) -> Response:
    form = await _guard(request)
    return _xml(await cf.turn(cs_id, form.get("SpeechResult", "")))


STATUS_MAP = {"queued": "queued", "initiated": "queued", "ringing": "ringing", "in-progress": "talking"}


@router.post("/twilio/voice/{cs_id}/status")
async def status(cs_id: str, request: Request) -> Response:
    form = await _guard(request)
    st = (form.get("CallStatus") or "").lower()
    if st in STATUS_MAP:
        await inv.set_progress(cs_id, STATUS_MAP[st])
    elif st in ("busy", "no-answer", "canceled"):
        await inv.finish_call(cs_id, "no_answer", "Nobody picked up." if st != "busy" else "The line was busy.")
    elif st == "failed":
        await inv.finish_call(cs_id, "failed", "The call could not be connected.")
    elif st == "completed":
        row = await db.fetchrow("SELECT turns, transcript FROM call_sessions WHERE id=$1", cs_id)
        if row and row["turns"] == 0:
            await inv.finish_call(cs_id, "no_answer", "The call ended before anyone replied.")
        elif row:
            has_msg = any(t.get("kind") == "message" for t in (row["transcript"] or []))
            if has_msg:
                await inv.finish_call(cs_id, "message_left", "A message was left.")
            else:
                await inv.finish_call(cs_id, "no_answer", "The call ended without a decision.")
    return Response(status_code=204)


def _voice_secret() -> str:
    return config.env("VOICE_AGENT_WEBHOOK_SECRET") or config.APP_SECRET


@router.post("/webhooks/voice-agent")
async def voice_agent(request: Request) -> dict:
    """Signed result from a calling platform. Header X-Memo-Signature: sha256=<hex HMAC-SHA256 of the raw body>.
    Body: {"call_session_id"|"provider_call_id", "outcome": accepted|declined|no_answer|message_left|failed,
    "summary": str, "message": str?}."""
    raw = await request.body()
    sent = request.headers.get("x-memo-signature", "").removeprefix("sha256=")
    good = hmac.new(_voice_secret().encode(), raw, hashlib.sha256).hexdigest()
    if not sent or not hmac.compare_digest(sent, good):
        raise HTTPException(403, "Bad signature.")
    try:
        b = json.loads(raw)
        outcome = b["outcome"]
    except Exception:  # noqa: BLE001
        raise HTTPException(422, "Body must be JSON with an outcome.")
    if outcome not in inv.TERMINAL_STATUSES:
        raise HTTPException(422, f"outcome must be one of {', '.join(inv.TERMINAL_STATUSES)}.")
    cs = b.get("call_session_id")
    if not cs and b.get("provider_call_id"):
        cs = await db.fetchval("SELECT id::text FROM call_sessions WHERE provider_call_id=$1", b["provider_call_id"])
    if not cs:
        raise HTTPException(404, "Unknown call.")
    ev = await inv.finish_call(str(cs), outcome, str(b.get("summary") or outcome)[:500],
                               (str(b["message"])[:1000] if b.get("message") else None))
    return {"ok": True, "applied": ev is not None}
