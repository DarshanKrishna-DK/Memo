"""GET /api/guide/lines?lang=: the guide robot's scripted lines (no model), synthesized once per language and cached."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends

from .. import db
from ..ai import tts
from ..auth import Session, current_session
from ..voice import lang as L
from .grandma import session_language

router = APIRouter()


@router.get("/api/guide/lines")
async def lines(lang: Optional[str] = None, s: Session = Depends(current_session)) -> dict:
    language = await session_language(s, lang, "receptionist")
    gname = await db.fetchval("SELECT grandma_name FROM families WHERE id=$1", s.family_id) or "Grandma"

    async def one(key: str, row: dict) -> tuple[str, dict]:
        text = row[language]
        if key == "locked_door":
            text = text.replace(L.GRANDMA_DEFAULTS[language], gname)
        out = await tts.synthesize(text, language, "guide", family_id=s.family_id)
        return key, {"text": text, "audio_url": out["url"], "duration_s": out["duration_s"]}

    pairs = await asyncio.gather(*(one(k, v) for k, v in L.GUIDE_LINES.items()))
    return {"language": language, "lines": dict(pairs)}
