"""Grandma in the theater: POST /api/grandma/tour, /api/grandma/greet, /api/grandma/talk."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import Session, current_session
from ..voice import grandma, lang as L, state as vstate

log = logging.getLogger("memo.routes.grandma")
router = APIRouter()


class TourIn(BaseModel):
    year: int
    month: int = Field(ge=1, le=12)
    event_id: Optional[str] = None
    resume_from: int = Field(default=0, ge=0)
    language: Optional[str] = None
    audio: bool = True


class GreetIn(BaseModel):
    year: int
    month: int = Field(ge=1, le=12)
    event_id: Optional[str] = None
    language: Optional[str] = None
    audio: bool = True


def guard_room(s: Session, year: Optional[int], month: Optional[int]) -> None:
    """Guests may only hear their invite room."""
    if s.is_guest and (s.invite_room is None or (year, month) != tuple(s.invite_room)):
        raise HTTPException(403, "Guests can only visit the room they were invited to.")


async def session_language(s: Session, requested: Optional[str], character: str) -> str:
    if requested:
        return L.norm(requested)
    st = await vstate.load(vstate.key_for(s.id, character))
    return L.norm(st.get("language") or await vstate.family_language(s.family_id, s.member_id))


@router.post("/api/grandma/tour")
async def tour(body: TourIn, s: Session = Depends(current_session)) -> dict:
    guard_room(s, body.year, body.month)
    lang = await session_language(s, body.language, "grandma")
    return await grandma.tour(s.family_id, body.year, body.month, body.event_id, lang, resume_from=body.resume_from,
                              audio=body.audio)


@router.post("/api/grandma/greet")
async def greet(body: GreetIn, s: Session = Depends(current_session)) -> dict:
    guard_room(s, body.year, body.month)
    lang = await session_language(s, body.language, "grandma")
    return await grandma.greet(s.family_id, body.year, body.month, body.event_id, lang, audio=body.audio)


def _scope(raw: Any) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            raise HTTPException(422, "scope must be JSON like {\"year\":2026,\"month\":11}")
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for k in ("year", "month"):
        if raw.get(k) not in (None, ""):
            out[k] = int(raw[k])
    if out.get("month") and not out.get("year"):
        raise HTTPException(422, "scope.month needs scope.year")
    return out


async def read_utterance(request: Request, language: Optional[str] = None) -> tuple[str, dict, Optional[str], Optional[str]]:
    """JSON {text, scope?, language?} or multipart (audio=<file>, scope=<json>|year/month, language?).
    Returns (text, fields, language, transcript_language)."""
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        fields = {k: v for k, v in form.items() if isinstance(v, str)}
        up = form.get("audio")
        lang = fields.get("language") or language
        if up is not None and not isinstance(up, str):
            data = await up.read()
            if not data:
                raise HTTPException(422, "The recording is empty.")
            if len(data) > 15 * 1024 * 1024:
                raise HTTPException(413, "Recording too long.")
            from ..ai import stt
            try:
                tr = await stt.transcribe(data, up.content_type or "audio/webm", None)
            except Exception as e:  # noqa: BLE001
                log.warning("transcription failed: %s", e)
                raise HTTPException(502, f"Couldn't transcribe the recording: {str(e)[:200]}")
            return (tr.get("text") or "").strip(), fields, lang, tr.get("language")
        return (fields.get("text") or "").strip(), fields, lang, None
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(422, "Send JSON {text, ...} or multipart with an audio file.")
    if not isinstance(body, dict):
        raise HTTPException(422, "Body must be a JSON object.")
    return str(body.get("text") or "").strip(), body, body.get("language") or language, None


@router.post("/api/grandma/talk")
async def talk(request: Request, s: Session = Depends(current_session)) -> dict:
    text, fields, lang_req, heard_lang = await read_utterance(request)
    scope = _scope(fields.get("scope") if "scope" in fields else {k: fields.get(k) for k in ("year", "month")})
    if s.is_guest:
        scope = {"year": s.invite_room[0], "month": s.invite_room[1]} if s.invite_room else {}
    if not text:
        lang = await session_language(s, lang_req, "grandma")
        return {"text": "", "audio_url": None, "subtitles": [], "highlights": [], "memory_ids": [], "sentences": [],
                "transcript": "", "source": "none", "heard": False, "language": lang,
                "action": {"type": "none", "data": {}}}
    lang = await session_language(s, lang_req, "grandma")
    out = await grandma.talk(s.family_id, text, scope, lang, state_key=vstate.key_for(s.id, "grandma"),
                             member_id=s.member_id, role=s.role, audio=str(fields.get("audio_reply", "true")).lower() != "false",
                             transcript=text)
    out["heard"] = True
    out["heard_language"] = heard_lang
    return out
