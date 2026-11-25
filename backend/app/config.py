"""Settings from D:/Memo/.env.local (or the process environment). Never log secret values."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]          # D:/Memo
BACKEND = ROOT / "backend"
load_dotenv(ROOT / ".env.local")
load_dotenv(ROOT / ".env")


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _path(name: str, default: str) -> Path:
    p = Path(env(name, default))
    return p if p.is_absolute() else (BACKEND / p).resolve()


DATABASE_URL = env("DATABASE_URL", "postgresql://memo:memo@localhost:5433/memo")
APP_SECRET = env("APP_SECRET", "change-me-dev-secret")
PUBLIC_BASE_URL = (env("PUBLIC_BASE_URL") or env("RENDER_EXTERNAL_URL", "http://localhost:8000")).rstrip("/")   # what Twilio/Agora/Telegram reach
WEB_BASE_URL = (env("WEB_BASE_URL") or env("RENDER_EXTERNAL_URL", "http://localhost:5173")).rstrip("/")          # the React app
STORAGE_DIR = _path("STORAGE_DIR", "../data/storage")
GALLERY_DIR = _path("GALLERY_DIR", "../data/gallery")
DEFAULT_TZ = env("DEFAULT_TZ", "Asia/Kolkata")
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_WEBHOOK_SECRET = env("TELEGRAM_WEBHOOK_SECRET")
LANGUAGES = ("en-IN", "hi-IN", "kn-IN")
GRANDMA_NAMES = {"en-IN": "Grandma", "hi-IN": "Dadi", "kn-IN": "Ajji"}

STORAGE_DIR.mkdir(parents=True, exist_ok=True)
GALLERY_DIR.mkdir(parents=True, exist_ok=True)
