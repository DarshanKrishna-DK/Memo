"""Object storage on local disk (S3-compatible swap later) + short-lived signed media URLs.

Keys look like "{family_id}/photos/{uuid}.jpg". Nothing under STORAGE_DIR is served without a valid
signature: GET /media/{key}?exp=..&sig=.. (route in app/routes/media.py).
"""
from __future__ import annotations

import hashlib
import hmac
import shutil
import time
import uuid
from pathlib import Path
from urllib.parse import quote

from . import config

SIGNED_URL_TTL_S = 15 * 60


def _abs(key: str) -> Path:
    p = (config.STORAGE_DIR / key).resolve()
    if config.STORAGE_DIR not in p.parents:
        raise ValueError("storage key escapes the storage dir")
    return p


def new_key(family_id: str, folder: str, ext: str) -> str:
    ext = ext if ext.startswith(".") else f".{ext}"
    return f"{family_id}/{folder}/{uuid.uuid4().hex}{ext.lower()}"


def put(key: str, data: bytes) -> str:
    p = _abs(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return key


def get(key: str) -> bytes:
    return _abs(key).read_bytes()


def path(key: str) -> Path:
    return _abs(key)


def exists(key: str) -> bool:
    try:
        return _abs(key).exists()
    except ValueError:
        return False


def delete(key: str | None) -> None:
    if not key:
        return
    try:
        _abs(key).unlink(missing_ok=True)
    except ValueError:
        pass


def delete_prefix(prefix: str) -> None:
    p = _abs(prefix)
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)


def _sig(key: str, exp: int) -> str:
    return hmac.new(config.APP_SECRET.encode(), f"{key}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def signed_url(key: str | None, ttl_s: int = SIGNED_URL_TTL_S, absolute: bool = False) -> str | None:
    """Relative URL by default (the web app proxies /media to the API). absolute=True for Telegram/Twilio."""
    if not key:
        return None
    exp = int(time.time()) + ttl_s
    url = f"/media/{quote(key)}?exp={exp}&sig={_sig(key, exp)}"
    return f"{config.PUBLIC_BASE_URL}{url}" if absolute else url


def verify(key: str, exp: int, sig: str) -> bool:
    return exp >= int(time.time()) and hmac.compare_digest(_sig(key, exp), sig)
