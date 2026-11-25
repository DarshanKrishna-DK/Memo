"""POST /api/tts: speak a line (session required). Cached by hash; returns a short-lived signed URL."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..ai import tts
from ..auth import Session, current_session
from .grandma import session_language

router = APIRouter()


class TtsIn(BaseModel):
    text: str = Field(min_length=1, max_length=1500)
    language: Optional[str] = None
    voice: Optional[str] = None     # grandma | receptionist | guide | a Sarvam speaker | a Murf voice id


@router.post("/api/tts")
async def speak(body: TtsIn, s: Session = Depends(current_session)) -> dict:
    lang = await session_language(s, body.language, body.voice if body.voice in ("grandma", "receptionist") else "grandma")
    out = await tts.synthesize(body.text, lang, body.voice, family_id=s.family_id)
    return {"url": out["url"], "duration_s": out["duration_s"], "provider": out["provider"], "voice": out["voice"],
            "language": lang, "cached": out["cached"]}
