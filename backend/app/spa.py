"""Production serving of the built React app (web/dist). Mounted by main.py only when the dist folder exists, so dev
(Vite on :5173 proxying to the API) is unaffected. Backend paths are never shadowed: the SPA fallback is a GET catch-all
registered after every router, and it refuses the backend prefixes below with a plain 404."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from . import config

log = logging.getLogger("memo.spa")
DIST = Path(os.environ.get("WEB_DIST_DIR") or (config.ROOT / "web" / "dist"))
BACKEND_PREFIXES = ("api", "media", "m", "i", "webhooks", "twilio")   # same list as web/vite.config.ts


def mount(app: FastAPI) -> bool:
    index = DIST / "index.html"
    if not index.is_file():
        return False
    root = DIST.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.split("/", 1)[0] in BACKEND_PREFIXES:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        target = (root / full_path).resolve()
        if full_path and target.is_file() and root in target.parents:
            immutable = full_path.startswith("assets/")
            return FileResponse(target, headers={"Cache-Control": "public, max-age=31536000, immutable" if immutable else "public, max-age=300"})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})   # client-side route

    log.info("serving web app from %s", root)
    return True
