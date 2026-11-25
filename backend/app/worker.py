"""Worker process: `python -m app.worker` from backend/. Runs job handlers from app/tasks/*.py."""
from __future__ import annotations

import asyncio
import logging

from . import db, jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def main() -> None:
    """Runs forever: if Postgres goes away (Docker restart, network blip) the loop drops the pool, waits and
    reconnects instead of exiting, so no supervisor is needed for the worker to come back."""
    log = logging.getLogger("memo.worker")
    delay = 2.0
    while True:
        try:
            await db.init_schema()
            delay = 2.0
            await jobs.worker_loop()
        except (OSError, ConnectionError) as e:
            log.warning("database unavailable (%s); retrying in %.0f s", e, delay)
        except Exception as e:  # noqa: BLE001 - asyncpg raises its own types for lost connections
            if "connection" not in str(e).lower() and "asyncpg" not in type(e).__module__:
                raise
            log.warning("database connection lost (%s); retrying in %.0f s", e, delay)
        try:
            await db.close()
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(delay)
        delay = min(30.0, delay * 2)


if __name__ == "__main__":
    asyncio.run(main())
