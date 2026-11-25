"""Production-only wiring, all opt-in by environment (nothing happens in dev unless the variables are set):
  - serves web/dist via app.spa when it exists;
  - RUN_WORKER_IN_PROCESS=1 runs the job worker inside the API process (one Render service instead of two);
  - FLAGSMITH_DB_NAME=flagsmith creates that extra database on the same Postgres server if it is missing (best effort);
  - TELEGRAM_MODE=webhook + TELEGRAM_REGISTER_WEBHOOK=1 registers PUBLIC_BASE_URL/webhooks/telegram with Telegram.
Telegram allows ONE consumer per bot token: once a webhook is set, local long polling (python -m app.telegram.bot,
which calls deleteWebhook on start) and the webhook fight each other. Hence the separate opt-in flag."""
from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI

from . import config, jobs, spa

log = logging.getLogger("memo.deploy")
_tasks: list[asyncio.Task] = []


def _on(name: str) -> bool:
    return config.env(name).lower() in ("1", "true", "yes", "on")


async def _worker_forever() -> None:
    """Same reconnect behaviour as app.worker.main, but never closes the pool the API shares."""
    delay = 2.0
    while True:
        try:
            await jobs.worker_loop()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - lost DB connection / listener: wait and start the loop again
            log.warning("in-process worker stopped (%s); restarting in %.0f s", e, delay)
        await asyncio.sleep(delay)
        delay = min(30.0, delay * 2)


async def _start_worker() -> None:
    if _on("RUN_WORKER_IN_PROCESS"):
        _tasks.append(asyncio.create_task(_worker_forever(), name="memo-worker"))
        log.info("job worker running inside the API process")


async def _register_webhook() -> None:
    if config.env("TELEGRAM_MODE").lower() != "webhook" or not _on("TELEGRAM_REGISTER_WEBHOOK"):
        return
    from .telegram import send
    url = f"{config.PUBLIC_BASE_URL}/webhooks/telegram"
    if not config.TELEGRAM_WEBHOOK_SECRET or not config.TELEGRAM_BOT_TOKEN or not url.startswith("https://"):
        log.warning("not registering the Telegram webhook: needs TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET and an https PUBLIC_BASE_URL")
        return
    await send.api("setWebhook", {"url": url, "secret_token": config.TELEGRAM_WEBHOOK_SECRET,
                                  "allowed_updates": ["message", "callback_query"], "drop_pending_updates": False})
    log.info("Telegram webhook set to %s", url)


async def _ensure_flagsmith_db() -> None:
    """Render gives a Postgres instance one database; self-hosted Flagsmith wants its own on the same server."""
    name = config.env("FLAGSMITH_DB_NAME")
    if not name:
        return
    if not name.replace("_", "").isalnum():
        log.warning("FLAGSMITH_DB_NAME %r is not a plain identifier; skipped", name)
        return
    from . import db
    async with (await db.pool()).acquire() as c:
        if await c.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", name):
            return
        await c.execute(f'CREATE DATABASE "{name}"')
        log.info("created database %s for Flagsmith", name)


def install(app: FastAPI, startup_hooks: list) -> None:
    startup_hooks.extend([_ensure_flagsmith_db, _start_worker, _register_webhook])
    spa.mount(app)     # no-op unless web/dist exists; must run after every router is included
