"""Owner-only: give Grandma a cloned voice from a consented 30-60 s recording (Sarvam Instant Voice Cloning, beta).

POST   /api/voice/clone   multipart: file, language (en-IN|hi-IN|kn-IN), consent=true, consented_by="<her name>",
                          [name]  -> {voice_id, ...}; Grandma then speaks with it for this family (aged-voice FX off)
GET    /api/voice/clone   -> {active, name, language, consented_by, consent_at, consent_statement}
DELETE /api/voice/clone   -> removes the voice at Sarvam and in Memo; Grandma returns to the stock voice
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from .. import db
from ..ai import voice_clone as vc
from ..auth import Session, require_role
from ..voice import lang as L

router = APIRouter()


@router.get("/api/voice/clone")
async def status(s: Session = Depends(require_role("owner"))) -> dict:
    row = await db.fetchrow("SELECT name, language, consented_by, consent_at, voice_id FROM family_voices "
                            "WHERE family_id=$1 AND role='grandma'", s.family_id)
    if not row:
        return {"active": False, "consent_statement": vc.CONSENT_TEXT}
    return {"active": True, "name": row["name"], "language": row["language"], "consented_by": row["consented_by"],
            "consent_at": row["consent_at"].isoformat(), "voice_id": row["voice_id"],
            "consent_statement": vc.CONSENT_TEXT}


@router.post("/api/voice/clone")
async def create(file: UploadFile = File(...), language: str = Form("en-IN"), consent: bool = Form(False),
                 consented_by: str = Form(...), name: str = Form("Grandma"),
                 s: Session = Depends(require_role("owner"))) -> dict:
    if not consent:
        raise HTTPException(422, {"code": "consent_required", "message": vc.CONSENT_TEXT})
    consented_by = " ".join(consented_by.split())
    if not vc.NAME_RE.match(consented_by):
        raise HTTPException(422, "consented_by must be the name of the person who agreed.")
    language = L.norm(language)
    audio = await file.read()
    try:
        d = await vc.create_voice(audio, file.filename or "sample.wav", f"{name} ({s.family_id[:8]})", language)
    except vc.CloneError as e:
        raise HTTPException(e.status, str(e)) from e
    old = await db.fetchrow("SELECT voice_id FROM family_voices WHERE family_id=$1 AND role='grandma'", s.family_id)
    await db.execute(
        "INSERT INTO family_voices(family_id, role, voice_id, name, language, consented_by, consent_note, created_by) "
        "VALUES ($1,'grandma',$2,$3,$4,$5,$6,$7) ON CONFLICT (family_id, role) DO UPDATE SET "
        "voice_id=EXCLUDED.voice_id, name=EXCLUDED.name, language=EXCLUDED.language, "
        "consented_by=EXCLUDED.consented_by, consent_note=EXCLUDED.consent_note, consent_at=now(), "
        "created_by=EXCLUDED.created_by",
        s.family_id, d["voice_id"], name[:100], language, consented_by, vc.CONSENT_TEXT, s.member_id)
    if old and old["voice_id"] != d["voice_id"]:
        try:
            await vc.delete_voice(old["voice_id"])
        except vc.CloneError:
            pass
    return {"active": True, "voice_id": d["voice_id"], "reference_text": d.get("reference_text"),
            "background_noise_removed": d.get("background_noise_removed")}


@router.delete("/api/voice/clone")
async def remove(s: Session = Depends(require_role("owner"))) -> dict:
    row = await db.fetchrow("DELETE FROM family_voices WHERE family_id=$1 AND role='grandma' RETURNING voice_id",
                            s.family_id)
    if row:
        try:
            await vc.delete_voice(row["voice_id"])
        except vc.CloneError:
            pass
    return {"active": False}
