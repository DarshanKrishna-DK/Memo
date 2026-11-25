"""Reception desk: POST /api/reception/act (typed text, or a recorded clip as multipart `audio`)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import Session, current_session
from ..voice import reception, state as vstate
from .grandma import read_utterance, session_language

router = APIRouter()


@router.post("/api/reception/act")
async def act(request: Request, s: Session = Depends(current_session)) -> dict:
    """JSON {text, language?, room?: {year, month, event_id?}, audio_reply?: bool} or multipart (audio=<file>, ...).
    -> {reply, speech: Speech, action: {type, data}, source, steps, language, pending, transcript}"""
    text, fields, lang_req, heard_lang = await read_utterance(request)
    lang = await session_language(s, lang_req, "receptionist")
    if not text:
        return {"reply": "", "speech": None, "action": {"type": "none", "data": {}}, "source": "none", "steps": [],
                "language": lang, "pending": None, "transcript": "", "heard": False}
    room: Optional[dict] = fields.get("room") if isinstance(fields.get("room"), dict) else None
    if s.is_guest and s.invite_room:
        room = {"year": s.invite_room[0], "month": s.invite_room[1]}
    if room and (not isinstance(room.get("year"), int) or not isinstance(room.get("month"), int)):
        raise HTTPException(422, "room needs integer year and month")
    out = await reception.act(s.family_id, s.member_id, text, lang, state_key=vstate.key_for(s.id, "receptionist"),
                              room=room, role=s.role, audio=str(fields.get("audio_reply", "true")).lower() != "false")
    out["transcript"] = text
    out["heard"] = True
    out["heard_language"] = heard_lang
    return out
