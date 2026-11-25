"""GET /api/export -> a zip of memo.json + all stored media (owner or editor)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from .. import db
from ..auth import Session, require_role
from ..core import common, export

router = APIRouter()


@router.get("/api/export")
async def get_export(s: Session = Depends(require_role("owner", "editor"))):
    with common.http_errors():
        path = await export.build_export_zip(s.family_id)
    await db.execute("INSERT INTO audit_events(family_id, member_id, type, data) VALUES ($1::uuid,$2::uuid,"
                     "'export',$3::jsonb)", s.family_id, s.member_id, {"bytes": path.stat().st_size})
    return FileResponse(path, media_type="application/zip", filename=path.name)
