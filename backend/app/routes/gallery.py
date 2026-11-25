"""Photo import.
POST /api/gallery/scan     JSON/empty -> scan GALLERY_DIR; multipart (meta=JSON list, files=...) -> browser upload
POST /api/gallery/query    filter -> {count, total_bytes, preview_token, over_limit, limit, sample, ...}
POST /api/gallery/import   {preview_token, event_id} -> {job_id, count}
GET  /api/gallery/import/{job_id} -> job status/result
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from starlette.datastructures import UploadFile

from .. import db
from ..auth import Session, require_role
from ..core import common, gallery

router = APIRouter()
writer = require_role("owner", "editor")
MAX_FILES = 500


@router.post("/api/gallery/scan")
async def scan(request: Request, s: Session = Depends(writer)) -> dict:
    ctype = request.headers.get("content-type", "")
    with common.http_errors():
        if not ctype.startswith("multipart/form-data"):
            return await gallery.scan_folder(s.family_id)
        form = await request.form(max_files=MAX_FILES, max_fields=50)
        try:
            meta = json.loads(form.get("meta") or "[]")
        except json.JSONDecodeError as e:
            raise ValueError("meta must be a JSON list.") from e
        uploads = [f for f in form.getlist("files") if isinstance(f, UploadFile)]
        if not uploads:
            raise ValueError("No files were uploaded.")
        by_name = {m.get("name"): m for m in meta if isinstance(m, dict)}
        files = []
        for i, f in enumerate(uploads):
            m = meta[i] if i < len(meta) and isinstance(meta[i], dict) else by_name.get(f.filename, {})
            data = await f.read(gallery.MAX_UPLOAD_BYTES + 1)
            files.append((f.filename or f"upload-{i}", data, m))
        return await gallery.index_uploads(s.family_id, files)


@router.post("/api/gallery/query")
async def query(body: dict[str, Any], s: Session = Depends(writer)) -> dict:
    with common.http_errors():
        try:
            return await gallery.query(s.family_id, body)
        except (TypeError,) as e:
            raise ValueError(str(e)) from e


class ImportBody(BaseModel):
    preview_token: str
    event_id: str


@router.post("/api/gallery/import")
async def start_import(body: ImportBody, s: Session = Depends(writer)) -> dict:
    with common.http_errors():
        return await gallery.start_import(s.family_id, s.member_id, body.preview_token, body.event_id)


@router.get("/api/gallery/import/{job_id}")
async def import_status(job_id: int, s: Session = Depends(writer)) -> dict:
    r = await db.fetchrow("SELECT id, status, attempts, last_error, result, created_at, updated_at FROM jobs "
                          "WHERE id=$1 AND type='gallery_import' AND payload->>'family_id'=$2", job_id, s.family_id)
    if not r:
        raise HTTPException(404, "No such import.")
    return {"job_id": r["id"], "status": r["status"], "attempts": r["attempts"], "result": r["result"],
            "error": (r["last_error"] or "").split("\n")[0] or None}


@router.get("/api/gallery/items")
async def items(limit: int = 50, offset: int = 0, source: Optional[str] = None, s: Session = Depends(writer)) -> dict:
    rows = await db.fetch("SELECT * FROM gallery_items WHERE family_id=$1::uuid AND ($2::text IS NULL OR source=$2) "
                          "ORDER BY taken_at DESC NULLS LAST, id OFFSET $3 LIMIT $4", s.family_id, source,
                          max(0, offset), max(1, min(200, limit)))
    total = await db.fetchval("SELECT count(*) FROM gallery_items WHERE family_id=$1::uuid", s.family_id)
    return {"total": total, "items": [{**gallery._item_view(r), "imported": r["imported_memory_id"] is not None}
                                      for r in rows]}
