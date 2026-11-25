"""Call housekeeping: stuck-call sweep (no outcome 15 min after start -> failed) and the 30-day purge."""
from __future__ import annotations

import logging

from .. import db, jobs
from ..phone import invites as inv

log = logging.getLogger("memo.tasks.calls")
SWEEP_EVERY_S = 300
PURGE_EVERY_S = 6 * 3600


async def sweep_stuck_calls() -> int:
    rows = await db.fetch(
        "SELECT id FROM call_sessions WHERE ended_at IS NULL AND started_at < now() - interval '15 minutes'")
    for r in rows:
        await inv.finish_call(str(r["id"]), "failed", "No status arrived from the phone network, so the call was marked failed.")
    return len(rows)


async def purge_old_calls() -> int:
    """Outcomes and messages are kept 30 days, then deleted."""
    r = await db.execute("DELETE FROM call_sessions WHERE started_at < now() - interval '30 days'")
    return int(r.split()[-1])


@jobs.handler("calls_sweep")
async def _sweep(_p: dict) -> dict:
    try:
        return {"failed": await sweep_stuck_calls()}
    finally:
        await jobs.enqueue("calls_sweep", {}, delay_s=SWEEP_EVERY_S)


@jobs.handler("calls_purge")
async def _purge(_p: dict) -> dict:
    try:
        return {"deleted": await purge_old_calls()}
    finally:
        await jobs.enqueue("calls_purge", {}, delay_s=PURGE_EVERY_S)
