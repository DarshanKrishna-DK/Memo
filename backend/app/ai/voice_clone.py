"""Sarvam Instant Voice Cloning (beta), verified against docs.sarvam.ai/api-reference/voice-cloning 2026-11-25.

    POST /voices/create   multipart: file (wav/mp3/flac/opus/aac, <=50 MB, 10-15 s recommended), name (1-100),
                          language (BCP-47 of the recording), [style, gender, remove_background_noise=true]
                          -> 201 {"status":"success","data":{"voice_id":"svc-...","status":"saved","reference_text":...}}
                          (the API has no consent field; Memo records consent itself in `family_voices`)
    POST /voices/clone    multipart: text (<=1000 chars), voice_id | ref_audio, [language_code, pace, output_audio_codec,
                          speech_sample_rate, enable_text_normalization ...] -> {"audio_b64", "request_id", "audio_duration"}
    DELETE /voices/delete/{voice_id};  GET /voices.   Starter plan: 50 saved voices per organization.

Nothing here runs unless the owner uploads a consented recording; Memo never clones anyone on its own.
"""
from __future__ import annotations

import base64
import logging
import os
import re
from typing import Optional

import httpx

from .. import db

log = logging.getLogger("memo.voice_clone")
BASE = "https://api.sarvam.ai"
MAX_TEXT = 1000
MAX_FILE = 50 * 1024 * 1024


class CloneError(Exception):
    def __init__(self, msg: str, status: int = 502):
        super().__init__(msg)
        self.status = status


def _key() -> str:
    k = os.environ.get("SARVAM_API_KEY", "").strip()
    if not k:
        raise CloneError("SARVAM_API_KEY not set", 503)
    return k


def _fail(r: httpx.Response) -> CloneError:
    try:
        msg = r.json().get("error", {}).get("message") or r.text[:200]
    except Exception:  # noqa: BLE001
        msg = r.text[:200]
    hint = {403: " (the Sarvam plan's cloned-voice limit may be reached)",
            422: " (recording unclear, too noisy or too short)"}
    return CloneError(f"sarvam voice cloning HTTP {r.status_code}: {msg}{hint.get(r.status_code, '')}",
                      400 if r.status_code in (400, 422) else 502)


async def create_voice(audio: bytes, filename: str, name: str, language: str) -> dict:
    if not audio or len(audio) > MAX_FILE:
        raise CloneError("recording is empty or over 50 MB", 400)
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as c:
        try:
            r = await c.post(f"{BASE}/voices/create", headers={"api-subscription-key": _key()},
                             files={"file": (filename or "sample.wav", audio)},
                             data={"name": name[:100], "language": language, "remove_background_noise": "true"})
        except httpx.HTTPError as e:
            raise CloneError(f"sarvam request failed: {type(e).__name__}") from e
    if r.status_code not in (200, 201):
        raise _fail(r)
    d = r.json().get("data") or {}
    if not d.get("voice_id"):
        raise CloneError("sarvam returned no voice_id")
    return d


async def delete_voice(voice_id: str) -> None:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.delete(f"{BASE}/voices/delete/{voice_id}", headers={"api-subscription-key": _key()})
    if r.status_code not in (200, 204, 404):
        raise _fail(r)


async def speak(text: str, voice_id: str, language: str, fmt: str = "mp3", pace: Optional[float] = 0.92,
                sample_rate: int = 24000) -> bytes:
    """One cloned-voice clip (text <= 1000 chars; callers split longer text)."""
    data = {"text": text[:MAX_TEXT], "voice_id": voice_id, "language_code": language,
            "output_audio_codec": fmt, "speech_sample_rate": str(sample_rate), "enable_text_normalization": "true"}
    if pace:
        data["pace"] = str(pace)
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as c:
        try:
            # multipart/form-data without a file part: httpx emits multipart only for `files`, so send fields as (None, v)
            r = await c.post(f"{BASE}/voices/clone", headers={"api-subscription-key": _key()},
                             files={k: (None, v) for k, v in data.items()})
        except httpx.HTTPError as e:
            raise CloneError(f"sarvam request failed: {type(e).__name__}") from e
    if r.status_code != 200:
        raise _fail(r)
    body = r.json()
    b = body.get("audio_b64") or body.get("audio")
    if not b:
        raise CloneError("sarvam returned no audio")
    return base64.b64decode(b)


async def family_voice(family_id: Optional[str], role: str = "grandma") -> Optional[dict]:
    if not family_id:
        return None
    try:
        row = await db.fetchrow("SELECT voice_id, name, language FROM family_voices WHERE family_id=$1 AND role=$2",
                                family_id, role)
    except Exception as e:  # noqa: BLE001
        log.warning("family_voices lookup failed: %s", e)
        return None
    return dict(row) if row else None


CONSENT_TEXT = ("I confirm that the person whose voice is in this recording is an adult who was told that an AI "
                "voice will be made from it, for use inside this family's Memo only, and who agreed. "
                "I can delete the voice at any time.")
NAME_RE = re.compile(r"^[\w .'\-]{2,80}$", re.UNICODE)
