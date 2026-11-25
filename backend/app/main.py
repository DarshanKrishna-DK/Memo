"""FastAPI app. Every module in app/routes/ that exposes `router` is included automatically, so feature
owners add files without editing this one. Run: `uvicorn app.main:app --port 8000` from backend/.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config, db, routes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("memo")

STARTUP_HOOKS: list = []   # modules may append async callables (e.g. telegram webhook setup)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await db.init_schema()
    for hook in STARTUP_HOOKS:
        try:
            await hook()
        except Exception as e:  # noqa: BLE001
            log.warning("startup hook %s failed: %s", getattr(hook, "__name__", hook), e)
    yield
    await db.close()


app = FastAPI(title="Memo", lifespan=lifespan)
from .observability import nudgebee; nudgebee.install(app)  # noqa: E702  5xx reporting to NudgeBee (no-op unless configured)
app.add_middleware(
    CORSMiddleware, allow_origins=list({config.WEB_BASE_URL, "http://localhost:5173", "http://127.0.0.1:5173"}), allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

for m in pkgutil.iter_modules(routes.__path__):
    mod = importlib.import_module(f"{routes.__name__}.{m.name}")
    if hasattr(mod, "router"):
        app.include_router(mod.router)


@app.get("/api/health")
async def health() -> dict:
    ok = await db.fetchval("SELECT 1") == 1
    return {"ok": ok}


from . import deploy  # noqa: E402  production wiring (SPA, in-process worker, webhook); keep last so the SPA catch-all is registered after every route
deploy.install(app, STARTUP_HOOKS)
