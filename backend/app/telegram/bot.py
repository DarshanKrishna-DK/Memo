"""Dev entry: long polling.  `python -m app.telegram.bot`   (production uses POST /webhooks/telegram).
`process_update` (re-exported) is the same function the webhook route calls."""
from __future__ import annotations

import asyncio
import logging

from .. import db
from . import send
from .handlers import process_update

log = logging.getLogger("memo.tg.bot")
COMMANDS = [("start", "Create or join a family"), ("museum", "Sign-in link to the museum"),
            ("invite", "Invite family"), ("members", "Who is here"), ("nickname", "Change your name"),
            ("quiet", "Pause follow-up questions"), ("export", "Download everything"), ("help", "Help")]


async def run() -> None:
    await db.init_schema()
    me = await send.api("getMe")
    log.info("polling as @%s", me["username"])
    await send.api("deleteWebhook", {"drop_pending_updates": False})
    await send.api("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in COMMANDS]})
    try:  # display name + description (BotFather set the username as the name)
        if me.get("first_name") != "Memo Family Museum":
            await send.api("setMyName", {"name": "Memo Family Museum"})
            await send.api("setMyDescription", {"description": "Send me a memory (a text, a voice note or photos) and I'll put it in your family's 3D museum. Grandma will tell the story."})
    except send.TelegramError as e:
        log.warning("could not set bot name: %s", e)
    offset = None
    while True:
        try:
            ups = await send.api("getUpdates", {"timeout": 30, "offset": offset,
                                                "allowed_updates": ["message", "callback_query"]}, timeout=45.0)
        except send.TelegramError as e:
            log.warning("getUpdates: %s", e)
            await asyncio.sleep(3)
            continue
        for u in ups:
            offset = u["update_id"] + 1
            try:
                await process_update(u)
            except Exception:  # noqa: BLE001  one bad update must not stop the bot
                log.exception("update %s failed", u.get("update_id"))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)   # request URLs contain the bot token
    asyncio.run(run())


if __name__ == "__main__":
    main()
