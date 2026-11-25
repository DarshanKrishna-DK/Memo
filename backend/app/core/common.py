"""Small helpers shared by the core services and core-api routes."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Iterator, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from .. import config, db, flags


def sid(v: Any) -> Optional[str]:
    return str(v) if v is not None else None


def tz_now(tz: str | None = None) -> datetime:
    return datetime.now(ZoneInfo(tz or config.DEFAULT_TZ))


def tz_today(tz: str | None = None) -> date:
    return tz_now(tz).date()


async def family(family_id: str) -> dict:
    row = await db.fetchrow(
        "SELECT id, name, language, grandma_name, timezone, invite_code, settings, created_at "
        "FROM families WHERE id=$1::uuid", str(family_id))
    if not row:
        raise LookupError("Family not found.")
    d = dict(row)
    d["id"] = str(d["id"])
    d["settings"] = d.get("settings") or {}
    return d


def family_public(fam: dict) -> dict:
    return {"id": fam["id"], "name": fam["name"], "language": fam["language"],
            "grandma_name": fam["grandma_name"]}


async def sarcasm_on(family_id: str, fam: dict | None = None) -> bool:
    fam = fam or await family(family_id)
    if fam["settings"].get("sarcasm_on") is False:
        return False
    return bool(await flags.get("sarcasm_enabled", family_id))


@contextmanager
def http_errors() -> Iterator[None]:
    """Map service exceptions to HTTP: LookupError 404, PermissionError 403, ValueError 400."""
    try:
        yield
    except HTTPException:
        raise
    except LookupError as e:
        raise HTTPException(404, str(e) or "Not found.") from e
    except PermissionError as e:
        raise HTTPException(403, str(e) or "Not allowed.") from e
    except ValueError as e:
        raise HTTPException(400, str(e) or "Bad request.") from e


def human_bytes(n: int) -> str:
    f = float(n or 0)
    for unit in ("bytes", "KB", "MB", "GB"):
        if f < 1024 or unit == "GB":
            return f"{int(f)} bytes" if unit == "bytes" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{f:.1f} GB"


def guard_room(s, year: int, month: int | None = None) -> None:
    """Guests (phone invites) may read only their invite room."""
    if getattr(s, "is_guest", False):
        iy, im = s.invite_room or (None, None)
        if int(year) != iy or (month is not None and int(month) != im):
            raise HTTPException(403, "This invite opens one room only.")


_bot: dict = {"name": None, "at": 0.0}


async def bot_username() -> str | None:
    """Telegram getMe, called once and cached (retried after 10 minutes if it failed)."""
    import time

    import httpx
    if config.env("TELEGRAM_BOT_USERNAME"):
        return config.env("TELEGRAM_BOT_USERNAME")
    if not config.TELEGRAM_BOT_TOKEN:
        return None
    if _bot["name"] or time.time() - _bot["at"] < 600:
        return _bot["name"]
    _bot["at"] = time.time()
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getMe")
            if r.status_code == 200 and r.json().get("ok"):
                _bot["name"] = r.json()["result"].get("username")
    except httpx.HTTPError:
        pass
    return _bot["name"]
