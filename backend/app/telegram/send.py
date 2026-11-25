"""Telegram Bot API over httpx (usable from the API, the worker and the dev bot). Token read at call time."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ..observability import nudgebee

from .. import config, db

log = logging.getLogger("memo.tg.send")
_username: str | None = None


class TelegramError(Exception):
    def __init__(self, msg: str, code: int = 0):
        super().__init__(msg)
        self.code = code


def token() -> str:
    t = config.env("TELEGRAM_BOT_TOKEN")
    if not t:
        raise TelegramError("TELEGRAM_BOT_TOKEN is not set")
    return t


async def api(method: str, data: dict | None = None, files: dict | None = None, timeout: float = 30.0) -> dict:
    url = f"https://api.telegram.org/bot{token()}/{method}"
    async with httpx.AsyncClient(timeout=timeout) as c:
        for attempt in range(6):
            try:
                r = await c.post(url, data=data if files else None, json=None if files else data, files=files)
            except httpx.HTTPError as e:
                nudgebee.record_provider_error("telegram", "network")
                if attempt == 5:
                    raise TelegramError(f"{method} failed: {type(e).__name__}") from e
                await asyncio.sleep(1 + attempt)
                continue
            nudgebee.record_http("telegram", r.status_code)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if r.status_code == 429 and attempt < 5:
                # Telegram flood control: honour retry_after (new bots get long waits at first).
                await asyncio.sleep(min(90, (body.get("parameters") or {}).get("retry_after", 2) + 1))
                continue
            if not body.get("ok"):
                raise TelegramError(f"{method}: {body.get('description') or r.status_code}", r.status_code)
            return body["result"]
    raise TelegramError(f"{method} failed")


def _markup(buttons: list[list[dict]] | None) -> dict | None:
    if not buttons:
        return None
    rows = []
    for row in buttons:
        out = []
        for b in row:
            if "url" in b:
                out.append({"text": b["text"], "url": b["url"]})
            else:
                out.append({"text": b["text"], "callback_data": b["data"][:64]})
        rows.append(out)
    return {"inline_keyboard": rows}


def _is_local(url: str) -> bool:
    return (urlparse(url).hostname or "") in ("localhost", "127.0.0.1", "0.0.0.0")


async def send_message(chat_id: int, text: str, buttons: list[list[dict]] | None = None) -> dict:
    """buttons: [{"text","data"}|{"text","url"}] rows. Telegram rejects localhost URL buttons, so in dev those
    become plain links in the message text."""
    if buttons:
        keep, extra = [], []
        for row in buttons:
            r2 = []
            for b in row:
                if "url" in b and _is_local(b["url"]):
                    extra.append(f"{b['text']}: {b['url']}")
                else:
                    r2.append(b)
            if r2:
                keep.append(r2)
        buttons = keep
        if extra:
            text = text + "\n\n" + "\n".join(extra)
    payload: dict = {"chat_id": chat_id, "text": text[:4096], "disable_web_page_preview": True}
    mk = _markup(buttons)
    if mk:
        payload["reply_markup"] = mk
    return await api("sendMessage", payload)


async def edit_message(chat_id: int, message_id: int, text: str, buttons: list[list[dict]] | None = None) -> None:
    payload: dict = {"chat_id": chat_id, "message_id": message_id, "text": text[:4096],
                     "reply_markup": _markup(buttons) or {"inline_keyboard": []}}
    try:
        await api("editMessageText", payload)
    except TelegramError as e:
        if "not modified" not in str(e):
            raise


async def answer_callback(callback_id: str, text: str = "") -> None:
    try:
        await api("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:190]})
    except TelegramError as e:
        log.debug("answerCallbackQuery: %s", e)


async def _send_file(method: str, field: str, chat_id: int, path: Path, caption: str) -> None:
    with open(path, "rb") as f:
        await api(method, {"chat_id": str(chat_id), "caption": caption[:1024]},
                  files={field: (Path(path).name, f.read())}, timeout=300.0)


async def send_document(chat_id: int, path: Path, caption: str = "") -> None:
    await _send_file("sendDocument", "document", chat_id, Path(path), caption)


async def send_video(chat_id: int, path: Path, caption: str = "") -> None:
    await _send_file("sendVideo", "video", chat_id, Path(path), caption)


MAX_DOWNLOAD = 20 * 1024 * 1024


async def download_file(file_id: str) -> tuple[bytes, str | None]:
    """Bot API getFile + download (limit 20 MB). Returns (bytes, file_path)."""
    info = await api("getFile", {"file_id": file_id})
    if int(info.get("file_size") or 0) > MAX_DOWNLOAD:
        raise TelegramError("file too large", 400)
    async with httpx.AsyncClient(timeout=120.0) as c:
        r = await c.get(f"https://api.telegram.org/file/bot{token()}/{info['file_path']}")
    if r.status_code != 200:
        raise TelegramError(f"download failed HTTP {r.status_code}", r.status_code)
    return r.content, info.get("file_path")


async def bot_username() -> str:
    global _username
    if not _username:
        from .. import config
        _username = config.env("TELEGRAM_BOT_USERNAME") or (await api("getMe"))["username"]
    return _username


async def invite_link(code: str) -> str:
    return f"https://t.me/{await bot_username()}?start={code}"


async def ask_family_followup(family_id, question: str, memory_id: str | None, source: str = "grandma_gap") -> None:
    """Ask every non-quiet member with a Telegram chat a question (used by Grandma when she lacks a fact).
    Replies come back through the normal follow-up answer path (reply_to or the open follow-up)."""
    members = await db.fetch(
        "SELECT id, telegram_chat_id FROM members WHERE family_id=$1 AND telegram_chat_id IS NOT NULL AND NOT quiet",
        str(family_id))
    for m in members:
        sent = await send_message(m["telegram_chat_id"], question)
        await db.execute(
            "INSERT INTO followups(family_id, memory_id, member_id, question, variant, source, asked_at, tg_message_id, tg_chat_id) "
            "VALUES ($1,$2,$3,$4,'a',$5,now(),$6,$7)",
            str(family_id), memory_id, m["id"], question, source, sent["message_id"], m["telegram_chat_id"])
