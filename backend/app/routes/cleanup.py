"""Blurry photo cleanup. Owner may delete anything; editors only photos in memories they authored."""
from __future__ import annotations

import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from .. import config, db, jobs, storage
from ..auth import Session, require_role
from ..media import blur

router = APIRouter()
RW = ("owner", "editor")


class Selection(BaseModel):
    media_ids: list[str] = Field(default_factory=list, max_length=500)
    gallery_item_ids: list[str] = Field(default_factory=list, max_length=500)


def _gallery_thumb(fid: str, row) -> str | None:
    """Gallery folder files live outside object storage; cache a small thumb there so it can be signed."""
    key = f"{fid}/cleanup_thumbs/{row['id']}.jpg"
    if not storage.exists(key):
        p = blur.gallery_file(row)
        if not p or not p.exists():
            return None
        try:
            img = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
            img.thumbnail((384, 384))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=80)
            storage.put(key, buf.getvalue())
        except Exception:  # noqa: BLE001
            return None
    return storage.signed_url(key)


def _uuids(ids: list[str]) -> list[str]:
    try:
        return [str(uuid.UUID(i)) for i in ids]
    except ValueError:
        raise HTTPException(422, "ids must be UUIDs") from None


@router.get("/api/cleanup/blurry")
async def list_blurry(s: Session = Depends(require_role(*RW))):
    own_only = s.role != "owner"
    rows = await db.fetch(
        "SELECT m.id, m.thumb_key, m.large_key, m.blur_score, m.taken_at, mem.id AS memory_id, mem.title, "
        "mem.kind, mem.event_year, mem.event_month, mem.author_id, mem.status FROM media m "
        "JOIN memories mem ON mem.id=m.memory_id "
        "WHERE mem.family_id=$1::uuid AND m.type='photo' AND m.is_blurry AND mem.status <> 'deleted' "
        "AND ($2::boolean = false OR mem.author_id = $3::uuid) ORDER BY m.blur_score NULLS FIRST",
        s.family_id, own_only, s.member_id)
    photos = [{"media_id": str(r["id"]), "memory_id": str(r["memory_id"]), "memory_title": r["title"],
               "room": {"year": r["event_year"], "month": r["event_month"]} if r["event_year"] else None,
               "attic": r["status"] == "attic", "score": r["blur_score"], "taken_at": r["taken_at"],
               "thumb_url": storage.signed_url(r["thumb_key"] or r["large_key"])} for r in rows]
    gallery = []
    if not own_only:
        grows = await db.fetch(
            "SELECT * FROM gallery_items WHERE family_id=$1::uuid AND is_blurry AND imported_memory_id IS NULL "
            "ORDER BY blur_score NULLS FIRST LIMIT 500", s.family_id)
        gallery = [{"gallery_item_id": str(r["id"]), "name": Path(r["path_or_handle"]).name, "folder": r["folder"],
                    "score": r["blur_score"], "taken_at": r["taken_at"], "thumb_url": _gallery_thumb(s.family_id, r)}
                   for r in grows]
    return {"threshold": blur.threshold(), "photos": photos, "gallery": gallery,
            "count": len(photos) + len(gallery)}


async def _allowed_media(s: Session, ids: list[str]) -> tuple[list, list[str]]:
    if not ids:
        return [], []
    rows = await db.fetch(
        "SELECT m.id, m.storage_key, m.large_key, m.thumb_key, m.memory_id, mem.author_id FROM media m "
        "JOIN memories mem ON mem.id=m.memory_id WHERE m.id = ANY($1::uuid[]) AND mem.family_id=$2::uuid "
        "AND m.type='photo'", ids, s.family_id)
    ok = [r for r in rows if s.role == "owner" or (r["author_id"] and str(r["author_id"]) == s.member_id)]
    found = {str(r["id"]) for r in ok}
    return ok, [i for i in ids if i not in found]


@router.post("/api/cleanup/blurry/delete")
async def delete_blurry(body: Selection, s: Session = Depends(require_role(*RW))):
    mids, gids = _uuids(body.media_ids), _uuids(body.gallery_item_ids)
    ok, denied = await _allowed_media(s, mids)
    memories_deleted: list[str] = []
    grows: list = []
    async with db.acquire() as conn:
        async with conn.transaction():
            if ok:
                await conn.execute("DELETE FROM media WHERE id = ANY($1::uuid[])", [r["id"] for r in ok])
            for mem_id in {r["memory_id"] for r in ok}:
                left = await conn.fetchval("SELECT count(*) FROM media WHERE memory_id=$1 AND type='photo'", mem_id)
                kind = await conn.fetchval("SELECT kind FROM memories WHERE id=$1", mem_id)
                if not left and kind in ("photo", "album"):
                    await conn.execute("UPDATE memories SET status='deleted', updated_at=now() WHERE id=$1", mem_id)
                    memories_deleted.append(str(mem_id))
            if gids and s.role == "owner":
                grows = await conn.fetch(
                    "DELETE FROM gallery_items WHERE id = ANY($1::uuid[]) AND family_id=$2::uuid RETURNING *",
                    gids, s.family_id)
    for r in ok:
        for k in {r["storage_key"], r["large_key"], r["thumb_key"]}:
            storage.delete(k)
    files_removed = 0
    for r in grows:
        storage.delete(r["upload_key"])
        storage.delete(f"{s.family_id}/cleanup_thumbs/{r['id']}.jpg")
        p = blur.gallery_file(r)
        # only ever remove files inside Memo's own gallery folder, never arbitrary paths
        if r["source"] == "folder" and p and p.exists() and config.GALLERY_DIR in p.resolve().parents:
            p.unlink(missing_ok=True)
            files_removed += 1
    return {"deleted_media": len(ok), "deleted_gallery": len(grows), "gallery_files_removed": files_removed,
            "memories_deleted": memories_deleted,
            "not_allowed_or_missing": denied + ([] if s.role == "owner" else gids)}


@router.post("/api/cleanup/blurry/keep")
async def keep_blurry(body: Selection, s: Session = Depends(require_role(*RW))):
    mids, gids = _uuids(body.media_ids), _uuids(body.gallery_item_ids)
    ok, denied = await _allowed_media(s, mids)
    if ok:
        await db.execute("UPDATE media SET is_blurry=false, blur_kept=true WHERE id = ANY($1::uuid[])",
                         [r["id"] for r in ok])
    kept_g = 0
    if gids and s.role == "owner":
        r = await db.execute("UPDATE gallery_items SET is_blurry=false, blur_kept=true "
                             "WHERE id = ANY($1::uuid[]) AND family_id=$2::uuid", gids, s.family_id)
        kept_g = int(r.split()[-1])
    return {"kept_media": len(ok), "kept_gallery": kept_g,
            "not_allowed_or_missing": denied + ([] if s.role == "owner" else gids)}


@router.post("/api/cleanup/rescan", status_code=202)
async def rescan(s: Session = Depends(require_role(*RW))):
    jid = await jobs.enqueue("cleanup_rescan", {"family_id": s.family_id}, max_attempts=2)
    return {"job_id": jid}
