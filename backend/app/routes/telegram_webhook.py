"""POST /webhooks/telegram (production). Telegram sends the secret set in setWebhook(secret_token=...)."""
from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, HTTPException, Request

from .. import config
from ..telegram.handlers import process_update

log = logging.getLogger("memo.tg.webhook")
router = APIRouter()


@router.post("/webhooks/telegram")
async def telegram_webhook(request: Request):
    secret = config.env("TELEGRAM_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(503, "TELEGRAM_WEBHOOK_SECRET is not configured")
    if not hmac.compare_digest(request.headers.get("x-telegram-bot-api-secret-token", ""), secret):
        raise HTTPException(403, "bad secret")
    update = await request.json()
    try:
        await process_update(update)
    except Exception:  # noqa: BLE001  answer 200 so Telegram does not retry-storm; updates are idempotent anyway
        log.exception("update %s failed", update.get("update_id"))
    return {"ok": True}
