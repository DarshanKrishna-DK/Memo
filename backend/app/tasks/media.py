"""Job: media_regen {media_id} | {memory_id} | {family_id} [, force: bool]
Re-creates missing 1600px / 512px photo derivatives from the stored original (e.g. after a storage restore or a
size change). With force=True it rebuilds them even when they exist."""
from __future__ import annotations

import asyncio

from .. import db, jobs, storage
from ..media import images


async def regenerate(where: str, arg: str, force: bool = False) -> dict:
    rows = await db.fetch(
        "SELECT md.id, md.storage_key, md.large_key, md.thumb_key, m.family_id FROM media md "
        f"JOIN memories m ON m.id=md.memory_id WHERE {where} AND md.type='photo' AND md.storage_key IS NOT NULL", arg)
    done = missing = 0
    for r in rows:
        need = force or not (r["large_key"] and storage.exists(r["large_key"])) \
            or not (r["thumb_key"] and storage.exists(r["thumb_key"]))
        if not need:
            continue
        if not storage.exists(r["storage_key"]):
            missing += 1
            continue
        data = await asyncio.to_thread(storage.get, r["storage_key"])
        d = await asyncio.to_thread(images.derivatives, data)
        fid = str(r["family_id"])
        lkey = r["large_key"] or storage.new_key(fid, "photos", ".jpg")
        tkey = r["thumb_key"] or storage.new_key(fid, "photos", ".jpg")
        storage.put(lkey, d["large"])
        storage.put(tkey, d["thumb"])
        await db.execute("UPDATE media SET large_key=$2, thumb_key=$3, width=$4, height=$5 WHERE id=$1",
                         r["id"], lkey, tkey, d["width"], d["height"])
        done += 1
    return {"checked": len(rows), "regenerated": done, "original_missing": missing}


@jobs.handler("media_regen")
async def media_regen(payload: dict) -> dict:
    force = bool(payload.get("force"))
    if payload.get("media_id"):
        return await regenerate("md.id=$1::uuid", payload["media_id"], force)
    if payload.get("memory_id"):
        return await regenerate("md.memory_id=$1::uuid", payload["memory_id"], force)
    if payload.get("family_id"):
        return await regenerate("m.family_id=$1::uuid", payload["family_id"], force)
    raise ValueError("media_regen needs media_id, memory_id or family_id")
