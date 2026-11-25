"""Public (no session) bot info so the sign-in screen can show the Telegram QR/link."""
from fastapi import APIRouter

from ..core import common

router = APIRouter()


@router.get("/api/bot")
async def bot_info() -> dict:
    username = await common.bot_username()
    return {"username": username, "bot_username": username, "url": f"https://t.me/{username}" if username else None}
