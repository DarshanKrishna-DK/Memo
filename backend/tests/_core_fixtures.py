"""Shared helpers for core-api tests: a throwaway family in the real Postgres, real JPEGs with EXIF."""
from __future__ import annotations

import asyncio
import io
import secrets
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db, jobs, storage  # noqa: E402


async def fresh_pool() -> None:
    """Each test module runs on its own event loop; drop any pool bound to another loop."""
    db._pool = None
    await db.init_schema()


async def make_family(name: str = "pytest-core-api", grandma: str = "Ajji") -> dict:
    fid = await db.fetchval(
        "INSERT INTO families(name, grandma_name, invite_code) VALUES ($1,$2,$3) RETURNING id",
        f"{name}-{secrets.token_hex(4)}", grandma, "pytest-" + secrets.token_urlsafe(16))
    owner = await db.fetchval("INSERT INTO members(family_id, nickname, role) VALUES ($1,'Asha','owner') RETURNING id",
                              fid)
    editor = await db.fetchval("INSERT INTO members(family_id, nickname, role) VALUES ($1,'Ravi','editor') "
                               "RETURNING id", fid)
    return {"id": str(fid), "owner": str(owner), "editor": str(editor)}


async def drop_family(fid: str) -> None:
    await db.execute("DELETE FROM jobs WHERE payload->>'family_id'=$1", fid)
    await db.execute("DELETE FROM families WHERE id=$1::uuid", fid)
    storage.delete_prefix(fid)


async def add_memory(fid: str, year: int, month: int, *, author: str | None = None, kind: str = "text",
                     title: str = "A memory", festival: str | None = None, status: str = "saved",
                     sensitivity: str = "none", day: int | None = None) -> str:
    return str(await db.fetchval(
        "INSERT INTO memories(family_id, author_id, kind, title, text_original, event_year, event_month, event_day, "
        "festival, status, sensitivity, date_confidence) VALUES ($1::uuid,$2::uuid,$3,$4,$5,$6,$7,$8,$9,$10,$11,1) "
        "RETURNING id", fid, author, kind, title, f"{title} story text", year, month, day, festival, status,
        sensitivity))


def sharp_image(seed: int, size=(900, 600)) -> Image.Image:
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 255, (size[1] // 10, size[0] // 10, 3), dtype=np.uint8)
    return Image.fromarray(arr).resize(size, Image.NEAREST)


def blurry_image(size=(900, 600)) -> Image.Image:
    x = np.linspace(0, 255, size[0], dtype=np.float32)
    arr = np.tile(x, (size[1], 1))
    return Image.fromarray(np.stack([arr, arr * 0.8, arr * 0.5], axis=-1).astype(np.uint8))


def jpeg_bytes(img: Image.Image, taken: datetime | None, camera: tuple[str, str] | None = ("Canon", "Canon EOS 200D"),
               gps: bool = True) -> bytes:
    ex = Image.Exif()
    if camera:
        ex[271], ex[272] = camera
    if taken:
        ex.get_ifd(0x8769)[36867] = taken.strftime("%Y:%m:%d %H:%M:%S")
    if gps:
        g = ex.get_ifd(0x8825)
        g[1], g[2], g[3], g[4] = "N", (12.0, 58.0, 20.0), "E", (77.0, 35.0, 40.0)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90, exif=ex.tobytes())
    return buf.getvalue()


async def run_job_now(job_id: int, timeout: float = 90) -> dict:
    """Run one specific job here (a worker from another process may have grabbed it first: then wait for it)."""
    import app.tasks.gallery  # noqa: F401  registers the handler
    row = await db.fetchrow(
        "UPDATE jobs SET status='running', attempts=attempts+1, locked_at=now(), locked_by='pytest', "
        "updated_at=now() WHERE id=$1 AND status='queued' "
        "RETURNING id, type, payload, attempts, max_attempts", job_id)
    if row:
        await jobs.run_one(dict(row))
        return dict(await db.fetchrow("SELECT status, result, last_error FROM jobs WHERE id=$1", job_id))
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        r = await db.fetchrow("SELECT status, result, last_error FROM jobs WHERE id=$1", job_id)
        if r["status"] in ("done", "dead"):
            return dict(r)
        await asyncio.sleep(0.5)
    raise TimeoutError(f"job {job_id} did not finish")
