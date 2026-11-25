"""Job video_transcode {media_id}: original (already stored by the capture job) -> web MP4 (large_key) + poster
(thumb_key) + duration. Idempotent: a row that already has its web copy is skipped."""
from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path

from .. import bus, db, jobs, storage
from ..media import video

log = logging.getLogger("memo.video")


@jobs.handler("video_transcode")
async def video_transcode(payload: dict) -> dict:
    row = await db.fetchrow(
        "SELECT md.*, m.family_id, m.status mstatus, m.event_year, m.event_month, m.title "
        "FROM media md JOIN memories m ON m.id=md.memory_id WHERE md.id=$1::uuid AND md.type='video'",
        payload["media_id"])
    if row is None or row["mstatus"] == "deleted":
        return {"skipped": "gone"}
    if row["large_key"] and storage.exists(row["large_key"]):
        return {"skipped": "done"}
    if not row["storage_key"] or not storage.exists(row["storage_key"]):
        return {"skipped": "no original"}
    fid = str(row["family_id"])
    work = Path(tempfile.mkdtemp(prefix="memo_vid_"))
    try:
        out, jpg = work / "web.mp4", work / "poster.jpg"
        async with video.LOCK:                               # one ffmpeg transcode at a time per process
            try:
                info = await asyncio.to_thread(video.transcode, storage.path(row["storage_key"]), out)
                await asyncio.to_thread(video.poster, out, jpg, info["duration_s"])
            except video.VideoError as e:
                await db.execute("UPDATE media SET video_error=$2 WHERE id=$1", row["id"], str(e)[:500])
                raise
        lk = storage.new_key(fid, "videos", ".mp4")
        tk = storage.new_key(fid, "videos", ".jpg")
        storage.path(lk).parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, out, storage.path(lk))
        storage.put(tk, jpg.read_bytes())
        await db.execute(
            "UPDATE media SET large_key=$2, thumb_key=$3, duration_s=$4, width=coalesce($5,width), "
            "height=coalesce($6,height), video_error=NULL WHERE id=$1",
            row["id"], lk, tk, info["duration_s"], info["width"], info["height"])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if row["mstatus"] == "saved" and row["event_year"]:
        await bus.publish(fid, {"type": "memory_saved", "memory_id": str(row["memory_id"]), "year": row["event_year"],
                                "month": row["event_month"], "title": row["title"]})
    return {"media_id": str(row["id"]), "duration_s": info["duration_s"], "large_key": lk, "thumb_key": tk}
