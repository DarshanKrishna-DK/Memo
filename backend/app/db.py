"""asyncpg pool + helpers. Use `await db.fetch(...)` etc. Rows come back as dict-like Records."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import asyncpg

from . import config

_pool: Optional[asyncpg.Pool] = None


async def _init_conn(conn: asyncpg.Connection) -> None:
    for t in ("json", "jsonb"):
        await conn.set_type_codec(t, encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(config.DATABASE_URL, min_size=1, max_size=10, init=_init_conn)
    return _pool


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def init_schema() -> None:
    sql = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    p = await pool()
    async with p.acquire() as c:
        await c.execute("SELECT pg_advisory_lock(424242)")
        try:
            await c.execute(sql)
        finally:
            await c.execute("SELECT pg_advisory_unlock(424242)")


async def fetch(q: str, *a: Any) -> list[asyncpg.Record]:
    return await (await pool()).fetch(q, *a)


async def fetchrow(q: str, *a: Any) -> Optional[asyncpg.Record]:
    return await (await pool()).fetchrow(q, *a)


async def fetchval(q: str, *a: Any) -> Any:
    return await (await pool()).fetchval(q, *a)


async def execute(q: str, *a: Any) -> str:
    return await (await pool()).execute(q, *a)


def acquire():
    """`async with db.acquire() as conn:` for transactions (`async with conn.transaction():`)."""
    class _Ctx:
        async def __aenter__(self):
            self.p = await pool()
            self.c = await self.p.acquire()
            return self.c

        async def __aexit__(self, *exc):
            await self.p.release(self.c)
    return _Ctx()


async def notify(channel: str, payload: dict) -> None:
    """Postgres NOTIFY so any process (api, worker, bot) can push live events. See app/events_bus.py."""
    await execute("SELECT pg_notify($1, $2)", channel, json.dumps(payload, default=str)[:7900])
