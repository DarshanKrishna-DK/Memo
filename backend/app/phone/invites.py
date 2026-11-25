"""Phone invites: contacts, single-use invite links, call safety rules and the Twilio call itself.

Rules live HERE (not in routes) so the same checks apply from the REST route, the receptionist tool and tests.
The call context is the host's name, the event title, month and year ONLY. No memory content ever.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from ..observability import nudgebee

from .. import auth, bus, config, db, flags

log = logging.getLogger("memo.phone")

TWILIO_CALLS_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json"
TWILIO_MSGS_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
E164 = re.compile(r"^\+[1-9]\d{6,14}$")
INVITE_HOURS = 24
QUIET_START, QUIET_END = 21, 8           # no calls from 21:00 to 08:00 contact-local
TERMINAL_STATUSES = ("accepted", "declined", "no_answer", "message_left", "failed")
LANG_LABELS = {"en-IN": "English", "hi-IN": "Hindi", "kn-IN": "Kannada"}
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]


class CallRefused(Exception):
    """A safety rule or setup problem stopped the call. `code` is stable for the UI; `message` is human."""

    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# ------------------------------------------------------------------ small helpers

def normalize_phone(raw: str) -> str:
    p = re.sub(r"[\s\-().]", "", raw or "")
    if not E164.match(p):
        raise ValueError("Phone must be in international format, like +919876543210.")
    return p


def last4(phone: str) -> str:
    return (phone or "")[-4:]


def mask(phone: str) -> str:
    return "•••• " + last4(phone) if phone else ""


def contact_public(r: Any, full: bool = False) -> dict:
    d = {"id": str(r["id"]), "name": r["name"], "relation": r["relation"], "language": r["language"],
         "phone_last4": last4(r["phone_e164"]), "phone_masked": mask(r["phone_e164"]),
         "consent_to_calls": r["consent_to_calls"], "consent_at": r["consent_at"],
         "do_not_call": r["do_not_call"], "timezone": r["timezone"],
         "has_telegram": r["telegram_user_id"] is not None}
    if full:
        d["phone_e164"] = r["phone_e164"]
    return d


def _is_public_url(url: str) -> bool:
    try:
        u = urlparse(url)
    except Exception:  # noqa: BLE001
        return False
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not host or host in ("localhost", "0.0.0.0") or host.endswith(".local"):
        return False
    if re.match(r"^(127\.|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.)", host) or host == "::1":
        return False
    return True


def public_url_ready() -> bool:
    return _is_public_url(config.PUBLIC_BASE_URL)


def _env(name: str) -> str:
    return config.env(name)


# ------------------------------------------------------------------ contacts

async def find_contacts(family_id: str, name_or_relation: str) -> list[dict]:
    q = (name_or_relation or "").strip()
    if not q:
        return []
    like = f"%{q}%"
    rows = await db.fetch(
        "SELECT * FROM contacts WHERE family_id=$1 AND (name ILIKE $2 OR relation ILIKE $2) ORDER BY name LIMIT 10",
        family_id, like)
    return [contact_public(r) | {"id": str(r["id"])} for r in rows]


# ------------------------------------------------------------------ invites

def _token_for(invite_id: str) -> str:
    """Deterministic per invite, so the link can be re-sent without storing the raw token (only its hash is stored)."""
    mac = hmac.new(config.APP_SECRET.encode(), f"invite:{invite_id}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def invite_link(invite_id: str) -> str:
    return f"{config.PUBLIC_BASE_URL}/i/{_token_for(invite_id)}"


async def _room_label(family_id: str, year: int, month: int, event_id: Optional[str]) -> str:
    if event_id:
        ev = await db.fetchrow("SELECT name FROM events WHERE id=$1 AND family_id=$2", event_id, family_id)
        if ev:
            return f"{ev['name']} {year}"
    return f"{MONTHS_EN[month - 1]} {year}"


async def create_invite(family_id: str, host_member_id: Optional[str], contact_id: str, year: int, month: int,
                        event_id: Optional[str] = None) -> dict:
    if not 1 <= month <= 12 or not 1900 <= year <= 2200:
        raise ValueError("That room's year or month is not valid.")
    c = await db.fetchrow("SELECT * FROM contacts WHERE id=$1 AND family_id=$2", contact_id, family_id)
    if not c:
        raise LookupError("No such contact in this family.")
    if event_id and not await db.fetchval("SELECT 1 FROM events WHERE id=$1 AND family_id=$2", event_id, family_id):
        raise LookupError("No such event in this family.")
    iid = str(uuid.uuid4())
    expires = datetime.now(timezone.utc) + timedelta(hours=INVITE_HOURS)
    await db.execute(
        "INSERT INTO invites(id, family_id, contact_id, event_id, year, month, role, token_hash, host_member_id, expires_at) "
        "VALUES ($1,$2,$3,$4,$5,$6,'viewer',$7,$8,$9)",
        iid, family_id, contact_id, event_id, year, month, auth.hash_token(_token_for(iid)), host_member_id, expires)
    label = await _room_label(family_id, year, month, event_id)
    refusal = None
    try:
        await preflight(family_id, c, expires, check_url=False)
    except CallRefused as e:
        refusal = {"code": e.code, "message": e.message}
    return {
        "invite": {"id": iid, "contact_id": str(c["id"]), "year": year, "month": month, "event_id": event_id,
                   "role": "viewer", "expires_at": expires, "status": "created"},
        "link": invite_link(iid),
        "confirm_text": f"Call {c['name']}, number ending {last4(c['phone_e164'])}, and invite them to {label}?",
        "call_refusal": refusal,
    }


# ------------------------------------------------------------------ safety rules

async def _family_settings(family_id: str) -> tuple[dict, str]:
    f = await db.fetchrow("SELECT settings, timezone FROM families WHERE id=$1", family_id)
    return (dict(f["settings"] or {}) if f else {}), (f["timezone"] if f else config.DEFAULT_TZ)


def in_quiet_hours(tz_name: str, now: Optional[datetime] = None) -> bool:
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo(config.DEFAULT_TZ)
    h = (now or datetime.now(timezone.utc)).astimezone(tz).hour
    return h >= QUIET_START or h < QUIET_END


async def preflight(family_id: str, contact: Any, invite_expires: Optional[datetime] = None, *,
                    check_url: bool = True, now: Optional[datetime] = None) -> None:
    """Raise CallRefused unless every rule passes. Order: switches, contact rules, rate limits, setup."""
    if not await flags.get("phone_calls_enabled", family_id):
        raise CallRefused("kill_switch", "Phone calls are switched off right now.")
    if not await flags.get("phone_allowlist", family_id):
        raise CallRefused("not_allowlisted", "Phone calls are not enabled for this family yet.")
    if contact["do_not_call"]:
        raise CallRefused("do_not_call", f"{contact['name']} asked not to be called. Share the link yourself instead.")
    if not contact["consent_to_calls"]:
        raise CallRefused("no_consent", f"Tick that {contact['name']} agreed to receive calls from Memo first.")
    settings, fam_tz = await _family_settings(family_id)
    if settings.get("call_quiet_hours", True) and in_quiet_hours(contact["timezone"], now):
        raise CallRefused("quiet_hours",
                          f"It is between 9 pm and 8 am for {contact['name']}. Memo does not call at night.")
    if settings.get("call_hourly_limit", True):
        n = await db.fetchval(
            "SELECT count(*) FROM call_sessions cs JOIN invites i ON i.id=cs.invite_id "
            "WHERE i.contact_id=$1 AND cs.started_at > now() - interval '1 hour' "
            "AND NOT (cs.status='failed' AND cs.provider_call_id IS NULL)", contact["id"])
        if n >= 1:
            raise CallRefused("hourly_limit", f"{contact['name']} was already called in the last hour.")
    cap = int(await flags.get("max_calls_per_day", family_id) or 0)
    try:
        tz = ZoneInfo(fam_tz)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo(config.DEFAULT_TZ)
    day_start = (now or datetime.now(timezone.utc)).astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    today = await db.fetchval(
        "SELECT count(*) FROM call_sessions cs JOIN invites i ON i.id=cs.invite_id "
        "WHERE i.family_id=$1 AND cs.started_at >= $2 AND NOT (cs.status='failed' AND cs.provider_call_id IS NULL)",
        family_id, day_start)
    if today >= cap:
        raise CallRefused("daily_cap", f"The daily limit of {cap} calls has been reached. Try tomorrow.")
    if invite_expires is not None and invite_expires < datetime.now(timezone.utc):
        raise CallRefused("invite_expired", "This invite has expired. Create a new one.")
    if check_url and not public_url_ready():
        raise CallRefused("no_public_url",
                          "Calls need a public https address for Twilio. Set PUBLIC_BASE_URL to your tunnel "
                          "or server URL (it is " + config.PUBLIC_BASE_URL + ").", 503)
    if check_url and not (_env("TWILIO_ACCOUNT_SID") and _env("TWILIO_AUTH_TOKEN") and _env("TWILIO_VOICE_FROM")):
        raise CallRefused("twilio_not_configured",
                          "Twilio is not configured (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_VOICE_FROM).", 503)


# ------------------------------------------------------------------ the call

async def _twilio_create_call(to: str, twiml_url: str, status_url: str) -> dict:
    """POST to Twilio's Calls API with a public Url (trial accounts reject inline Twiml)."""
    sid, tok = _env("TWILIO_ACCOUNT_SID"), _env("TWILIO_AUTH_TOKEN")
    form: dict[str, Any] = {
        "From": _env("TWILIO_VOICE_FROM").removeprefix("whatsapp:"), "To": to, "Url": twiml_url, "Method": "POST",
        "StatusCallback": status_url, "StatusCallbackMethod": "POST",
        "StatusCallbackEvent": ["initiated", "ringing", "answered", "completed"], "Timeout": "30",
    }
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(TWILIO_CALLS_URL.format(sid=sid), data=form, auth=(sid, tok))
        data = r.json() if r.content else {}
        if r.status_code == 400 and "trial" in str(data.get("message", "")).lower():
            r = await c.post(TWILIO_CALLS_URL.format(sid=sid), auth=(sid, tok),
                             data={k: form[k] for k in ("From", "To", "Url")})
            data = r.json() if r.content else {}
    nudgebee.record_http("twilio", r.status_code)
    if r.status_code >= 300:
        raise RuntimeError(f"Twilio error {r.status_code}: {str(data.get('message') or '')[:200]}")
    return data


async def place_call(family_id: str, invite_id: str) -> dict:
    """Place the call after the host said yes. Raises CallRefused with a clear reason. Never logs the number."""
    inv = await db.fetchrow("SELECT * FROM invites WHERE id=$1 AND family_id=$2", invite_id, family_id)
    if not inv or not inv["contact_id"]:
        raise CallRefused("not_found", "That invite does not exist.", 404)
    c = await db.fetchrow("SELECT * FROM contacts WHERE id=$1 AND family_id=$2", inv["contact_id"], family_id)
    if not c:
        raise CallRefused("not_found", "That contact no longer exists.", 404)
    await preflight(family_id, c, inv["expires_at"])
    cs_id = str(uuid.uuid4())
    await db.execute("INSERT INTO call_sessions(id, invite_id, status) VALUES ($1,$2,'queued')", cs_id, invite_id)
    await bus.publish(family_id, {"type": "call_progress", "invite_id": invite_id, "status": "queued",
                                  "contact_name": c["name"]})
    base = config.PUBLIC_BASE_URL
    try:
        data = await _twilio_create_call(c["phone_e164"], f"{base}/twilio/voice/{cs_id}/twiml",
                                         f"{base}/twilio/voice/{cs_id}/status")
    except Exception as e:  # noqa: BLE001
        await finish_call(cs_id, "failed", "The call could not be placed: " + str(e)[:200])
        raise CallRefused("twilio_error", str(e)[:220], 502) from e
    await db.execute("UPDATE call_sessions SET provider_call_id=$2 WHERE id=$1", cs_id, data.get("sid"))
    return {"call_session_id": cs_id, "status": "queued"}


async def set_progress(cs_id: str, status: str) -> None:
    """queued/ringing/talking only, never overwrites an outcome."""
    row = await db.fetchrow(
        "UPDATE call_sessions SET status=$2 WHERE id=$1 AND ended_at IS NULL AND status<>$2 RETURNING invite_id", cs_id, status)
    if row:
        fam = await db.fetchrow("SELECT family_id FROM invites WHERE id=$1", row["invite_id"])
        if fam:
            await bus.publish(str(fam["family_id"]), {"type": "call_progress", "invite_id": str(row["invite_id"]),
                                                      "status": status})


async def finish_call(cs_id: str, status: str, summary: str, message: Optional[str] = None) -> Optional[dict]:
    """Record the outcome once and tell the theater. Returns None if the call already had an outcome."""
    assert status in TERMINAL_STATUSES
    row = await db.fetchrow(
        "UPDATE call_sessions SET status=$2, outcome_summary=$3, message_text=coalesce($4, message_text), ended_at=now() "
        "WHERE id=$1 AND ended_at IS NULL RETURNING invite_id", cs_id, status, summary[:500], message)
    if not row:
        return None
    r = await db.fetchrow(
        "SELECT i.family_id, c.name, c.language, c.telegram_user_id, c.phone_e164, c.id AS cid, i.id AS iid, i.expires_at "
        "FROM invites i LEFT JOIN contacts c ON c.id=i.contact_id WHERE i.id=$1", row["invite_id"])
    ev: dict[str, Any] = {"type": "call_outcome", "invite_id": str(r["iid"]), "status": status,
                          "contact_name": r["name"], "summary": summary}
    if message:
        ev["message"] = message
    if status == "accepted":
        ev.update(await deliver_link(str(r["family_id"]), str(r["iid"]), r))
    await bus.publish(str(r["family_id"]), ev)
    return ev


async def deliver_link(family_id: str, invite_id: str, c: Any) -> dict:
    """Telegram if we know the contact there, else SMS if configured, else the host shares it from the UI."""
    link = invite_link(invite_id)
    text = f"Memo: you're invited to join the family's memory room. Open this link (valid 24 hours): {link}"
    if c["telegram_user_id"]:
        try:
            from ..telegram import send as tg
            await tg.send_message(int(c["telegram_user_id"]), text, [[{"text": "Open the room", "url": link}]])
            return {"delivery": "telegram"}
        except Exception as e:  # noqa: BLE001
            log.warning("telegram invite delivery failed: %s", type(e).__name__)
    sms_from = _env("TWILIO_SMS_FROM")
    if sms_from and c["phone_e164"]:
        sid, tok = _env("TWILIO_ACCOUNT_SID"), _env("TWILIO_AUTH_TOKEN")
        try:
            async with httpx.AsyncClient(timeout=15) as h:
                r = await h.post(TWILIO_MSGS_URL.format(sid=sid), auth=(sid, tok),
                                 data={"From": sms_from, "To": c["phone_e164"], "Body": text})
            if r.status_code < 300:
                return {"delivery": "sms"}
            log.warning("sms invite delivery failed: HTTP %s", r.status_code)
        except Exception as e:  # noqa: BLE001
            log.warning("sms invite delivery failed: %s", type(e).__name__)
    return {"delivery": "host_must_share", "link": link}


async def mark_do_not_call(contact_id: str) -> None:
    await db.execute("UPDATE contacts SET do_not_call=true WHERE id=$1", contact_id)
