"""Operator surface (NudgeBee will call this later).

Auth: an owner session (sees its own family's jobs and flags), or header `x-ops-key: $OPS_API_KEY` when that env
var is set (sees all jobs and may set global flags).
GET  /api/ops/jobs?status=failed|dead|queued|running|done&type=&limit=
POST /api/ops/jobs/{id}/replay
GET  /api/ops/flags     -> {flags, defaults, sources, provider, overrides}
GET  /api/ops/flags/status  (Flagsmith provider status; never includes keys)
POST /api/ops/flags {key, value, scope: "family"|"global"}
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import config, db, flags
from ..auth import current_session

router = APIRouter()


@dataclass
class Operator:
    family_id: Optional[str]          # None = global operator (ops key)


async def operator(request: Request) -> Operator:
    key = config.env("OPS_API_KEY")
    given = request.headers.get("x-ops-key", "")
    if key and given and hmac.compare_digest(key, given):
        return Operator(family_id=None)
    s = await current_session(request)
    if s.role != "owner" or s.is_guest:
        raise HTTPException(403, "Only the family owner can use the operator tools.")
    return Operator(family_id=s.family_id)


def _job(r) -> dict:
    return {"id": r["id"], "type": r["type"], "status": r["status"], "attempts": r["attempts"],
            "max_attempts": r["max_attempts"], "run_at": r["run_at"].isoformat(), "last_error": r["last_error"],
            "payload": r["payload"], "result": r["result"], "locked_by": r["locked_by"],
            "created_at": r["created_at"].isoformat(), "updated_at": r["updated_at"].isoformat()}


@router.get("/api/ops/jobs")
async def list_jobs(status: str = "failed", type: Optional[str] = None, limit: int = 100,
                    op: Operator = Depends(operator)) -> dict:
    if status == "failed":   # the queue retries failures: 'failed' = has an error and is waiting to retry, or failed
        cond = "(status='failed' OR (status='queued' AND last_error IS NOT NULL AND attempts > 0))"
    elif status in ("dead", "queued", "running", "done"):
        cond = f"status='{status}'"
    else:
        raise HTTPException(400, "status must be failed, dead, queued, running or done.")
    rows = await db.fetch(
        f"SELECT * FROM jobs WHERE {cond} AND ($1::text IS NULL OR payload->>'family_id'=$1) "
        "AND ($2::text IS NULL OR type=$2) ORDER BY updated_at DESC LIMIT $3",
        op.family_id, type, max(1, min(500, limit)))
    stuck = await db.fetchval("SELECT count(*) FROM jobs WHERE status='running' AND locked_at < now() - "
                              "interval '10 minutes' AND ($1::text IS NULL OR payload->>'family_id'=$1)", op.family_id)
    return {"jobs": [_job(r) for r in rows], "stuck_running": stuck}


@router.post("/api/ops/jobs/{job_id}/replay")
async def replay(job_id: int, op: Operator = Depends(operator)) -> dict:
    r = await db.fetchrow(
        "UPDATE jobs SET status='queued', attempts=0, run_at=now(), locked_at=NULL, locked_by=NULL, updated_at=now() "
        "WHERE id=$1 AND status <> 'running' AND ($2::text IS NULL OR payload->>'family_id'=$2) RETURNING *",
        job_id, op.family_id)
    if not r:
        raise HTTPException(404, "No such job (or it is running right now).")
    await db.execute("SELECT pg_notify('memo_jobs', $1)", str(job_id))
    return {"job": _job(r)}


@router.get("/api/ops/flags")
async def get_flags(op: Operator = Depends(operator)) -> dict:
    rows = await db.fetch("SELECT family_id, key, value, updated_at FROM flag_overrides "
                          "WHERE family_id IS NULL OR family_id=$1::uuid ORDER BY key", op.family_id)
    return {"flags": await flags.all_for(op.family_id), "defaults": flags.DEFAULTS,
            "sources": await flags.sources_for(op.family_id), "provider": flags.status(),
            "overrides": [{"scope": "global" if r["family_id"] is None else "family", "key": r["key"],
                           "value": r["value"], "updated_at": r["updated_at"].isoformat()} for r in rows]}


class FlagBody(BaseModel):
    key: str
    value: Any
    scope: str = "family"


@router.post("/api/ops/flags")
async def set_flag(body: FlagBody, op: Operator = Depends(operator)) -> dict:
    if body.key not in flags.DEFAULTS:
        raise HTTPException(400, f"Unknown flag '{body.key}'.")
    if body.scope == "global":
        if op.family_id is not None:
            raise HTTPException(403, "Global flags need the operator key.")
        await flags.set_override(body.key, body.value, None)
    elif body.scope == "family":
        if op.family_id is None:
            raise HTTPException(400, "Use scope=global with the operator key.")
        await flags.set_override(body.key, body.value, op.family_id)
    else:
        raise HTTPException(400, "scope must be family or global.")
    return {"key": body.key, "value": await flags.get(body.key, op.family_id), "scope": body.scope}


@router.get("/api/ops/flags/status")
async def flags_status(op: Operator = Depends(operator)) -> dict:
    return flags.status()
