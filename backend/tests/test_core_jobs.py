"""core-api: the Postgres job queue survives a killed worker (O1). A real child process claims a job and is killed
mid-job; the restart path (requeue_orphans_of_dead_workers) and the stall sweep put it back; it then completes.
Jobs are scheduled an hour ahead so no live worker of another process can grab them during the test."""
from __future__ import annotations

import asyncio
import os
import secrets
import signal
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio

from _core_fixtures import fresh_pool
from app import db, jobs

pytestmark = pytest.mark.asyncio(loop_scope="module")
BACKEND = Path(__file__).resolve().parents[1]
TAG = f"pytest-jobs-{secrets.token_hex(4)}"
JOB_TYPE = f"pytest_core_{secrets.token_hex(3)}"
CHILD = r"""
import asyncio, os, sys
sys.path.insert(0, sys.argv[3])
from app import db
async def main():
    jid, host = int(sys.argv[1]), sys.argv[2]
    n = await db.execute("UPDATE jobs SET status='running', attempts=attempts+1, locked_at=now(), locked_by=$2 "
                         "WHERE id=$1 AND status='queued'", jid, f"{host}:{os.getpid()}")
    print(("claimed" if n.endswith("1") else "missed") + f" {os.getpid()}", flush=True)
    await asyncio.sleep(120)          # "processing" until killed
asyncio.run(main())
"""

ran: list[dict] = []


@jobs.handler(JOB_TYPE)
async def _handler(payload: dict) -> dict:
    ran.append(payload)
    return {"ok": True, "n": payload["n"]}


@pytest_asyncio.fixture(loop_scope="module", scope="module", autouse=True)
async def setup():
    await fresh_pool()
    yield
    await db.execute("DELETE FROM jobs WHERE payload->>'tag'=$1", TAG)
    await db.close()


async def _claim_and_run(jid: int) -> dict:
    row = await db.fetchrow(
        "UPDATE jobs SET status='running', attempts=attempts+1, locked_at=now(), locked_by=$2, updated_at=now() "
        "WHERE id=$1 AND status='queued' RETURNING id, type, payload, attempts, max_attempts", jid, jobs.WORKER_ID)
    assert row is not None
    await jobs.run_one(dict(row))
    return dict(await db.fetchrow("SELECT * FROM jobs WHERE id=$1", jid))


async def test_killed_worker_job_is_requeued_and_finishes(monkeypatch):
    jid = await jobs.enqueue(JOB_TYPE, {"tag": TAG, "n": 1}, delay_s=3600)
    fake_host = f"pytest-host-{secrets.token_hex(3)}"
    proc = subprocess.Popen([sys.executable, "-c", CHILD, str(jid), fake_host, str(BACKEND)],
                            stdout=subprocess.PIPE, text=True, cwd=str(BACKEND))
    line = (await asyncio.to_thread(proc.stdout.readline)).split()
    assert line[0] == "claimed"
    child_pid = int(line[1])          # (on Windows the venv python is a launcher with a child interpreter)
    r = await db.fetchrow("SELECT status, locked_by FROM jobs WHERE id=$1", jid)
    assert r["status"] == "running" and r["locked_by"] == f"{fake_host}:{child_pid}"
    os.kill(child_pid, signal.SIGTERM)                # the worker dies mid-job (TerminateProcess on Windows)
    proc.kill()
    proc.wait(timeout=10)
    assert (await db.fetchval("SELECT status FROM jobs WHERE id=$1", jid)) == "running"
    # a worker restarting on that host requeues what the dead process left running
    monkeypatch.setattr(jobs.socket, "gethostname", lambda: fake_host)
    await jobs.requeue_orphans_of_dead_workers()
    r = await db.fetchrow("SELECT status, locked_by, attempts FROM jobs WHERE id=$1", jid)
    assert r["status"] == "queued" and r["locked_by"] is None and r["attempts"] == 1
    done = await _claim_and_run(jid)
    assert done["status"] == "done" and done["result"] == {"ok": True, "n": 1}
    assert ran[-1]["n"] == 1


async def test_stalled_job_is_swept():
    jid = await jobs.enqueue(JOB_TYPE, {"tag": TAG, "n": 2}, delay_s=3600)
    await db.execute("UPDATE jobs SET status='running', locked_by='elsewhere:1', "
                     "locked_at=now() - interval '11 minutes' WHERE id=$1", jid)
    assert await jobs.sweep_stuck() >= 1
    r = await db.fetchrow("SELECT status, last_error FROM jobs WHERE id=$1", jid)
    assert r["status"] == "queued" and "requeued after stall" in r["last_error"]
    assert (await _claim_and_run(jid))["status"] == "done"


async def test_failure_retries_then_dead():
    jid = await jobs.enqueue("pytest_no_such_handler", {"tag": TAG}, delay_s=3600, max_attempts=2)
    for expected in ("queued", "dead"):
        await db.execute("UPDATE jobs SET run_at=now() + interval '1 hour' WHERE id=$1", jid)
        row = await db.fetchrow(
            "UPDATE jobs SET status='running', attempts=attempts+1, locked_at=now() WHERE id=$1 "
            "RETURNING id, type, payload, attempts, max_attempts", jid)
        await jobs.run_one(dict(row))
        r = await db.fetchrow("SELECT status, last_error FROM jobs WHERE id=$1", jid)
        assert r["status"] == expected and "no handler" in r["last_error"]
