"""Contacts: the owner types numbers at the reception desk (never from voice) and ticks consent."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import config, db
from ..auth import Session, current_session, require_role
from ..phone import invites as inv

router = APIRouter()


def _tz(v: str) -> str:
    try:
        ZoneInfo(v)
    except Exception:  # noqa: BLE001
        raise HTTPException(422, f"Unknown timezone {v}.")
    return v


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    phone: str
    relation: Optional[str] = Field(None, max_length=40)
    language: str = "en-IN"
    consent_to_calls: bool = False
    timezone: str = config.DEFAULT_TZ
    telegram_user_id: Optional[int] = None


class ContactPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    phone: Optional[str] = None
    relation: Optional[str] = None
    language: Optional[str] = None
    consent_to_calls: Optional[bool] = None
    do_not_call: Optional[bool] = None
    timezone: Optional[str] = None
    telegram_user_id: Optional[int] = None


def _check_lang(v: str) -> str:
    if v not in config.LANGUAGES:
        raise HTTPException(422, f"Language must be one of {', '.join(config.LANGUAGES)}.")
    return v


def _phone(v: str) -> str:
    try:
        return inv.normalize_phone(v)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/api/contacts")
async def list_contacts(s: Session = Depends(require_role("owner", "editor"))) -> dict:
    rows = await db.fetch("SELECT * FROM contacts WHERE family_id=$1 ORDER BY name", s.family_id)
    return {"contacts": [inv.contact_public(r, full=s.role == "owner") for r in rows]}


@router.post("/api/contacts", status_code=201)
async def add_contact(b: ContactIn, s: Session = Depends(require_role("owner"))) -> dict:
    phone = _phone(b.phone)
    consent_by = s.member_id if b.consent_to_calls else None
    consent_at = datetime.now(timezone.utc) if b.consent_to_calls else None
    r = await db.fetchrow(
        "INSERT INTO contacts(family_id,name,relation,phone_e164,language,consent_to_calls,consent_by,consent_at,timezone,telegram_user_id) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING *",
        s.family_id, b.name.strip(), b.relation, phone, _check_lang(b.language), b.consent_to_calls, consent_by,
        consent_at, _tz(b.timezone), b.telegram_user_id)
    return {"contact": inv.contact_public(r, full=True)}


@router.patch("/api/contacts/{contact_id}")
async def patch_contact(contact_id: str, b: ContactPatch, s: Session = Depends(require_role("owner"))) -> dict:
    cur = await db.fetchrow("SELECT * FROM contacts WHERE id=$1 AND family_id=$2", contact_id, s.family_id)
    if not cur:
        raise HTTPException(404, "No such contact.")
    d = b.model_dump(exclude_unset=True)
    sets: dict = {}
    if "name" in d:
        sets["name"] = d["name"].strip()
    if "phone" in d:
        sets["phone_e164"] = _phone(d["phone"])
    for k in ("relation", "telegram_user_id"):
        if k in d:
            sets[k] = d[k]
    if "language" in d:
        sets["language"] = _check_lang(d["language"])
    if "timezone" in d:
        sets["timezone"] = _tz(d["timezone"])
    if d.get("consent_to_calls") is True:
        sets.update(consent_to_calls=True, consent_by=s.member_id, consent_at=datetime.now(timezone.utc))
    elif d.get("consent_to_calls") is False:
        sets.update(consent_to_calls=False, consent_by=None, consent_at=None)
    if "do_not_call" in d:
        if d["do_not_call"] is False and d.get("consent_to_calls") is not True:
            raise HTTPException(422, "To allow calls again, tick that the person has agreed to receive them.")
        sets["do_not_call"] = d["do_not_call"]
    if not sets:
        return {"contact": inv.contact_public(cur, full=True)}
    cols = list(sets)
    r = await db.fetchrow(
        f"UPDATE contacts SET {', '.join(f'{c}=${i + 3}' for i, c in enumerate(cols))} WHERE id=$1 AND family_id=$2 RETURNING *",
        contact_id, s.family_id, *[sets[c] for c in cols])
    return {"contact": inv.contact_public(r, full=True)}


@router.delete("/api/contacts/{contact_id}", status_code=204)
async def delete_contact(contact_id: str, s: Session = Depends(require_role("owner"))) -> None:
    r = await db.execute("DELETE FROM contacts WHERE id=$1 AND family_id=$2", contact_id, s.family_id)
    if r.endswith(" 0"):
        raise HTTPException(404, "No such contact.")
