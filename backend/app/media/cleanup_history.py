"""History of photos taken out because they were blurry.

- 'deleted': a person removed it (POST /api/cleanup/blurry/delete or Telegram "Delete blurry"). A 384 px copy is
  made before the files go, so the history can still show it.
- 'auto_skipped': a gallery import left it out because flag auto_skip_blurry is on (copy made at skip time).
- 'flagged': still in the museum but marked blurry; computed live from media (not stored here).
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any, Optional, Union

from PIL import Image, ImageOps

from .. import db, storage

log = logging.getLogger("memo.cleanup")
THUMB = 384


def thumb_bytes(src: Union[bytes, Path, str]) -> Optional[bytes]:
    try:
        img = Image.open(io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src)
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((THUMB, THUMB))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80)
        return buf.getvalue()
    except Exception as e:  # noqa: BLE001 - unreadable source: history row without a picture
        log.warning("cleanup history thumb failed: %s", e)
        return None


def _keep_thumb(fid: str, name: str, src: Union[bytes, Path, str, None]) -> Optional[str]:
    if src is None:
        return None
    data = thumb_bytes(src)
    if not data:
        return None
    return storage.put(f"{fid}/cleanup_history/{name}.jpg", data)


async def prepare_deleted_media(fid: str, rows: list) -> list[dict]:
    """Before deleting media rows (+ files): copy a thumbnail and gather room info. rows need id, memory_id,
    thumb_key/large_key/storage_key, blur_score. Insert the result with insert(conn, entries)."""
    if not rows:
        return []
    mems = {r["id"]: r for r in await db.fetch(
        "SELECT id, event_id, event_year, event_month, status, title FROM memories WHERE id = ANY($1::uuid[])",
        list({r["memory_id"] for r in rows}))}
    out = []
    for r in rows:
        key = next((k for k in (r["thumb_key"], r["large_key"], r["storage_key"]) if k and storage.exists(k)), None)
        tk = _keep_thumb(fid, f"m_{r['id']}", storage.path(key) if key else None)
        m = mems.get(r["memory_id"])
        placed = m is not None and m["status"] == "saved"
        out.append({"family_id": fid, "media_id": r["id"], "gallery_item_id": None, "memory_id": r["memory_id"],
                    "event_id": m["event_id"] if placed else None,
                    "year": m["event_year"] if placed else None, "month": m["event_month"] if placed else None,
                    "reason": "deleted", "blur_score": r["blur_score"], "thumb_key": tk,
                    "name": m["title"] if m else None})
    return out


async def prepare_deleted_gallery(fid: str, rows: list) -> list[dict]:
    from .blur import gallery_file
    out = []
    for r in rows:
        p = gallery_file(r)
        cached = f"{fid}/cleanup_thumbs/{r['id']}.jpg"
        src = storage.path(cached) if storage.exists(cached) else (p if p and p.exists() else None)
        out.append({"family_id": fid, "media_id": None, "gallery_item_id": r["id"], "memory_id": None,
                    "event_id": None, "year": None, "month": None, "reason": "deleted",
                    "blur_score": r["blur_score"], "thumb_key": _keep_thumb(fid, f"g_{r['id']}", src),
                    "name": Path(r["path_or_handle"]).name})
    return out


async def insert(conn: Any, entries: list[dict]) -> None:
    """conn: an asyncpg connection (inside the delete transaction) or the db module."""
    for e in entries:
        await conn.execute(
            "INSERT INTO cleanup_history(family_id, media_id, gallery_item_id, memory_id, event_id, year, month, "
            "reason, blur_score, thumb_key, name) VALUES ($1::uuid,$2::uuid,$3::uuid,$4::uuid,$5::uuid,$6,$7,$8,$9,"
            "$10,$11) ON CONFLICT DO NOTHING",
            str(e["family_id"]), _s(e["media_id"]), _s(e["gallery_item_id"]), _s(e["memory_id"]), _s(e["event_id"]),
            e["year"], e["month"], e["reason"], e["blur_score"], e["thumb_key"], e["name"])


def _s(v) -> Optional[str]:
    return str(v) if v else None


async def record_auto_skipped(fid: str, item, ev, data: Optional[bytes] = None) -> None:
    """A gallery import left `item` (gallery_items row) out as blurry; ev = the target event row."""
    from .blur import gallery_file
    src: Union[bytes, Path, None] = data
    if src is None:
        p = gallery_file(item)
        src = p if p and p.exists() else None
    tk = _keep_thumb(fid, f"g_{item['id']}", src)
    await db.execute(
        "INSERT INTO cleanup_history(family_id, gallery_item_id, event_id, year, month, reason, blur_score, thumb_key, "
        "name) VALUES ($1::uuid,$2::uuid,$3::uuid,$4,$5,'auto_skipped',$6,$7,$8) "
        "ON CONFLICT (family_id, gallery_item_id, reason) WHERE gallery_item_id IS NOT NULL AND media_id IS NULL "
        "DO UPDATE SET event_id=EXCLUDED.event_id, year=EXCLUDED.year, month=EXCLUDED.month, "
        "blur_score=EXCLUDED.blur_score, thumb_key=coalesce(EXCLUDED.thumb_key, cleanup_history.thumb_key), "
        "created_at=now()",
        fid, str(item["id"]), str(ev["id"]), ev["year"], ev["month"], item["blur_score"], tk,
        Path(item["path_or_handle"]).name)


async def history(fid: str, year: Optional[int] = None, month: Optional[int] = None) -> dict:
    rows = await db.fetch(
        "SELECT * FROM cleanup_history WHERE family_id=$1::uuid AND ($2::int IS NULL OR year=$2) "
        "AND ($3::int IS NULL OR month=$3) ORDER BY created_at DESC LIMIT 500", fid, year, month)
    photos = [{"id": str(r["media_id"] or r["gallery_item_id"] or r["id"]), "history_id": str(r["id"]),
               "media_id": _s(r["media_id"]), "gallery_item_id": _s(r["gallery_item_id"]),
               "memory_id": _s(r["memory_id"]), "event_id": _s(r["event_id"]),
               "room": {"year": r["year"], "month": r["month"]} if r["year"] else None,
               "thumb_url": storage.signed_url(r["thumb_key"]), "blur_score": r["blur_score"],
               "reason": r["reason"], "name": r["name"], "when": r["created_at"].isoformat()} for r in rows]
    flagged = await db.fetch(
        "SELECT md.id, md.thumb_key, md.large_key, md.storage_key, md.blur_score, md.created_at, m.id memory_id, "
        "m.event_id, m.event_year, m.event_month, m.title FROM media md JOIN memories m ON m.id=md.memory_id "
        "WHERE m.family_id=$1::uuid AND md.type='photo' AND md.is_blurry AND NOT md.blur_kept "
        "AND m.status IN ('saved','attic') AND ($2::int IS NULL OR m.event_year=$2) "
        "AND ($3::int IS NULL OR m.event_month=$3) ORDER BY md.created_at DESC LIMIT 500", fid, year, month)
    photos += [{"id": str(r["id"]), "history_id": None, "media_id": str(r["id"]), "gallery_item_id": None,
                "memory_id": str(r["memory_id"]), "event_id": _s(r["event_id"]),
                "room": {"year": r["event_year"], "month": r["event_month"]} if r["event_year"] else None,
                "thumb_url": storage.signed_url(r["thumb_key"] or r["large_key"] or r["storage_key"]),
                "blur_score": r["blur_score"], "reason": "flagged", "name": r["title"],
                "when": r["created_at"].isoformat()} for r in flagged]
    photos.sort(key=lambda p: p["when"], reverse=True)
    counts = {k: sum(1 for p in photos if p["reason"] == k) for k in ("auto_skipped", "deleted", "flagged")}
    counts["total"] = len(photos)
    return {"year": year, "month": month, "counts": counts, "photos": photos}
