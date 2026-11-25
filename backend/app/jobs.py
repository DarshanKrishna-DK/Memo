"""Postgres job queue. Producers: `await jobs.enqueue("transcribe", {...})`.
Handlers register with `@jobs.handler("transcribe")` in app/tasks/*.py (auto-imported by the worker).
Workers claim with SELECT ... FOR UPDATE SKIP LOCKED; a job stuck in 'running' for > 10 min is
re-queued by the sweep (a killed worker never loses a job). After max_attempts -> 'dead' (operator list).
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import os
import pkgutil
import socket
import traceback
from datetime import timedelta
from typing import Awaitable, Callable, Optional

from . import db
from .observability import nudgebee

log = logging.getLogger("memo.jobs")
Handler = Callable[[dict], Awaitable[Optional[dict]]]
HANDLERS: dict[str, Handler] = {}
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def handler(job_type: str):
    def deco(fn: Handler) -> Handler:
        HANDLERS[job_type] = fn
        return fn
    return deco


async def enqueue(job_type: str, payload: dict, delay_s: float = 0, max_attempts: int = 5, conn=None) -> int:
    q = ("INSERT INTO jobs(type, payload, run_at, max_attempts) VALUES ($1, $2::jsonb, now() + $3::interval, $4) "
         "RETURNING id")
    args = (job_type, payload, timedelta(seconds=delay_s), max_attempts)
    jid = await (conn.fetchval(q, *args) if conn else db.fetchval(q, *args))
    await db.execute("SELECT pg_notify('memo_jobs', $1)", str(jid))
    return jid


async def _claim() -> Optional[dict]:
    row = await db.fetchrow(
        """UPDATE jobs SET status='running', attempts=attempts+1, locked_at=now(), locked_by=$1, updated_at=now()
           WHERE id = (SELECT id FROM jobs WHERE status='queued' AND run_at <= now()
                       ORDER BY run_at LIMIT 1 FOR UPDATE SKIP LOCKED)
           RETURNING id, type, payload, attempts, max_attempts""", WORKER_ID)
    return dict(row) if row else None


async def sweep_stuck() -> int:
    r = await db.execute(
        "UPDATE jobs SET status='queued', locked_at=NULL, locked_by=NULL, updated_at=now(), "
        "last_error=coalesce(last_error,'') || ' [requeued after stall]' "
        "WHERE status='running' AND locked_at < now() - interval '10 minutes'")
    return int(r.split()[-1])


async def requeue_orphans_of_dead_workers() -> None:
    """On worker start: jobs this host left 'running' (process was killed) go straight back to the queue."""
    host = socket.gethostname()
    await db.execute(
        "UPDATE jobs SET status='queued', locked_at=NULL, locked_by=NULL, updated_at=now() "
        "WHERE status='running' AND locked_by LIKE $1 AND locked_by <> $2", f"{host}:%", WORKER_ID)


def import_task_modules() -> None:
    from . import tasks
    for m in pkgutil.iter_modules(tasks.__path__):
        importlib.import_module(f"{tasks.__name__}.{m.name}")


async def run_one(job: dict) -> None:
    fn = HANDLERS.get(job["type"])
    try:
        if fn is None:
            raise RuntimeError(f"no handler for job type {job['type']}")
        result = await fn(job["payload"])
        await db.execute("UPDATE jobs SET status='done', result=$2::jsonb, updated_at=now() WHERE id=$1",
                         job["id"], result or {})
        await nudgebee.job_ok(job["type"])
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1500:]}"
        log.warning("job %s %s failed (attempt %s): %s", job["id"], job["type"], job["attempts"], e)
        dead = job["attempts"] >= job["max_attempts"]
        backoff = timedelta(seconds=min(600, 5 * 2 ** job["attempts"]))
        await db.execute(
            "UPDATE jobs SET status=$2, last_error=$3, run_at=now()+$4::interval, locked_at=NULL, updated_at=now() "
            "WHERE id=$1", job["id"], "dead" if dead else "queued", err, backoff)
        await nudgebee.job_failed(job["type"], job["attempts"], job["max_attempts"], e, job.get("payload"))
        if dead:
            await db.notify("memo_ops", {"type": "job_dead", "job_id": job["id"], "job_type": job["type"]})


async def worker_loop(concurrency: int = 4) -> None:
    import_task_modules()
    await requeue_orphans_of_dead_workers()
    log.info("worker %s handling %s", WORKER_ID, sorted(HANDLERS))
    nudgebee.start_watchdog()
    wake = asyncio.Event()
    conn = await (await db.pool()).acquire()
    await conn.add_listener("memo_jobs", lambda *_: wake.set())
    sem = asyncio.Semaphore(concurrency)
    loop = asyncio.get_running_loop()
    last_sweep = 0.0
    while True:
        if loop.time() - last_sweep > 60:
            await sweep_stuck()
            last_sweep = loop.time()
        await sem.acquire()
        job = await _claim()
        if not job:
            sem.release()
            wake.clear()
            try:
                await asyncio.wait_for(wake.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
            continue

        async def _go(j=job):
            try:
                await run_one(j)
            finally:
                sem.release()
        asyncio.create_task(_go())
