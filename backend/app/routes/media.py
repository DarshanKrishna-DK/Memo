"""GET /media/{key}?exp=..&sig=.. serves a stored file only with a valid, unexpired signature."""
from __future__ import annotations

import mimetypes

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .. import storage

router = APIRouter()
mimetypes.add_type("audio/ogg", ".ogg")
mimetypes.add_type("audio/ogg", ".oga")
mimetypes.add_type("audio/mpeg", ".mp3")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("video/mp4", ".mp4")


@router.get("/media/{key:path}")
async def media(key: str, exp: int = 0, sig: str = ""):
    if not sig or not storage.verify(key, exp, sig):
        raise HTTPException(403, "This media link has expired or is invalid.")
    try:
        p = storage.path(key)
    except ValueError as e:
        raise HTTPException(403, "Invalid media key.") from e
    if not p.is_file():
        raise HTTPException(404, "Media not found.")
    mt = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    headers = {"Cache-Control": "private, max-age=600", "X-Content-Type-Options": "nosniff"}
    if p.suffix == ".zip":
        headers["Content-Disposition"] = f'attachment; filename="{p.name}"'
    return FileResponse(p, media_type=mt, headers=headers)
