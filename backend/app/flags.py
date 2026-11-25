"""Runtime switches. ONE interface for the whole app: `await flags.get(key, family_id)`.

Resolution order: flag_overrides row for the family -> global override row -> Flagsmith -> DEFAULTS.
Resolved values are cached for 30 s so a flip takes effect within about a minute without a deploy (PRD F1).
Flags hold switches and dials, never data.

Flagsmith (self-hosted, docs/FLAGSMITH.md) runs in LOCAL EVALUATION mode: the official SDK downloads the environment
document in a background thread (every REFRESH s) and evaluates segments in memory, so reading a flag never makes a
network call. Identity = family_id; traits come from the DB (language, member_count, created_days_ago,
has_phone_invites, has_call_consent, family_id). If FLAGSMITH_ENVIRONMENT_KEY is unset, the key is not a server key,
or the server is unreachable, the provider returns None and DB overrides / DEFAULTS apply (same as before).

Type mapping (Flagsmith -> Python), driven by the type of the key's DEFAULT:
  bool default  -> the feature's enabled state (a plain flag; its value is ignored). Disabled = False.
  int default   -> int(value)            str default -> str(value)        dict default -> json.loads(value)
  Remote-config features that are DISABLED (or whose value does not parse) return None, i.e. "use the code
  DEFAULT": switching a config feature off in the dashboard means "stop overriding", never "send an empty value".
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from . import config, db

log = logging.getLogger("memo.flags")

DEFAULTS: dict[str, Any] = {
    "museum_3d": True,
    "proactive_followups": True,
    "followup_variant": "a",
    "llm_model": "",                      # "" = provider default (sarvam-105b-conversations)
    "tts_voice_by_language": {},          # {"hi-IN": "anushka"} overrides
    "max_followups_per_week": 3,
    "voice_enabled": True,
    "barge_in": True,
    "cinematic_walk": {"enabled": True, "seconds": 8},
    "phone_calls_enabled": True,
    "max_calls_per_day": 5,
    "phone_allowlist": True,              # segment `phone_pilot` in Flagsmith; True = this family allowed
    "general_knowledge": True,
    "max_import_photos": 200,
    "sarcasm_enabled": True,
    "video_reels": True,
    "auto_skip_blurry": True,
    "nudgebee_alerts": True,              # app/observability/nudgebee.py sends incidents only when on
}

_cache: dict[tuple[str, str], tuple[float, Any, str]] = {}
TTL = 30.0


def coerce(key: str, enabled: bool, value: Any) -> Any:
    """A Flagsmith (enabled, value) pair -> the Python value for `key`, or None for "no opinion"."""
    default = DEFAULTS.get(key)
    if isinstance(default, bool):
        return bool(enabled)
    if not enabled or value is None:
        return None
    try:
        if isinstance(default, int):
            return int(value) if not isinstance(value, str) else int(float(value.strip()))
        if isinstance(default, dict):
            v = json.loads(value) if isinstance(value, str) else value
            return v if isinstance(v, dict) else None
        if isinstance(default, str):
            return str(value)
    except (TypeError, ValueError):
        log.warning("flagsmith value for %s does not parse as %s; using the default", key, type(default).__name__)
        return None
    return value


class FlagsmithProvider:
    """Official Flagsmith SDK in local-evaluation mode. get() returns None when Flagsmith has no opinion."""

    REFRESH = 20.0            # environment document poll interval (s)
    TRAITS_TTL = 30.0

    def __init__(self, key: Optional[str] = None, api_url: Optional[str] = None) -> None:
        self.key = config.env("FLAGSMITH_ENVIRONMENT_KEY") if key is None else key
        self.api_url = (api_url if api_url is not None else config.env("FLAGSMITH_API_URL")) \
            or "http://localhost:8001/api/v1/"
        self._client: Any = None
        self._started = False
        self._start_lock = threading.Lock()
        self._ready = threading.Event()
        self._init_failed: Optional[str] = None
        self._traits: dict[str, tuple[float, dict]] = {}
        self.last_refresh_at: Optional[float] = None      # last successful environment-document fetch
        self.last_attempt_at: Optional[float] = None
        self.last_error: Optional[str] = None

    @property
    def configured(self) -> bool:
        return bool(self.key)

    # ---- SDK lifecycle (the constructor does one blocking fetch, so start() runs it in a thread) ----
    def _build(self) -> Any:
        from flagsmith import Flagsmith
        from urllib3 import Retry

        provider = self

        class _Client(Flagsmith):
            def update_environment(self) -> None:          # record refresh time / failures for the ops view
                provider.last_attempt_at = time.time()
                before = self._local_evaluation
                super().update_environment()
                if self._local_evaluation is not None and self._local_evaluation is not before:
                    provider.last_refresh_at = time.time()
                    provider.last_error = None
                else:
                    provider.last_error = "environment document fetch failed"

        return _Client(environment_key=self.key, api_url=self.api_url, enable_local_evaluation=True,
                       environment_refresh_interval_seconds=self.REFRESH, request_timeout_seconds=3,
                       retries=Retry(total=1, backoff_factor=0.2), enable_analytics=False)

    def start(self) -> None:
        """Build the SDK client once, in a daemon thread (its constructor fetches the environment document, which
        can take seconds when the server is slow/unreachable). Reads return None until it is ready."""
        if not self.key or self._started:
            return
        with self._start_lock:
            if self._started:
                return
            self._started = True

        def run() -> None:
            try:
                self._client = self._build()
            except Exception as e:                            # bad key format, SDK error: stay on defaults
                self._init_failed = type(e).__name__
                self.last_error = f"init failed: {type(e).__name__}"
                log.warning("flagsmith disabled: %s", type(e).__name__)
            finally:
                self._ready.set()
        threading.Thread(target=run, name="flagsmith-init", daemon=True).start()

    async def client(self) -> Any:
        self.start()
        return self._client

    async def wait_ready(self, timeout: float = 10.0) -> bool:
        """For tests / startup: wait (off the event loop) until the client exists and has an environment."""
        self.start()
        if not self.key:
            return False
        await asyncio.to_thread(self._ready.wait, timeout)
        return self.loaded

    def close(self) -> None:
        c, self._client = self._client, None
        self._started = False
        self._ready.clear()
        if c is not None:
            try:
                c.close()
            except Exception:
                pass

    @property
    def loaded(self) -> bool:
        return self._client is not None and self._client._local_evaluation is not None

    # ---- identity traits from the DB ----
    async def traits(self, family_id: str) -> dict:
        hit = self._traits.get(family_id)
        if hit and time.time() - hit[0] < self.TRAITS_TTL:
            return hit[1]
        try:
            r = await db.fetchrow(
                "SELECT f.language, f.created_at, "
                "(SELECT count(*) FROM members m WHERE m.family_id=f.id) AS member_count, "
                "EXISTS(SELECT 1 FROM invites i JOIN contacts c ON c.id=i.contact_id WHERE i.family_id=f.id) "
                "  AS has_phone_invites, "
                "EXISTS(SELECT 1 FROM contacts c WHERE c.family_id=f.id AND c.consent_to_calls AND NOT c.do_not_call) "
                "  AS has_call_consent "
                "FROM families f WHERE f.id=$1::uuid", str(family_id))
        except Exception:                                     # not a uuid, DB hiccup: evaluate with no traits
            r = None
        t: dict = {"family_id": str(family_id)}
        if r:
            t.update(language=r["language"], member_count=int(r["member_count"]),
                     created_days_ago=max(0, (datetime.now(timezone.utc) - r["created_at"]).days),
                     has_phone_invites=bool(r["has_phone_invites"]), has_call_consent=bool(r["has_call_consent"]))
        self._traits[family_id] = (time.time(), t)
        return t

    def evaluate(self, key: str, family_id: Optional[str], traits: Optional[dict] = None) -> Any:
        """In-memory evaluation against the last environment document (no network). None = no opinion."""
        c = self._client
        if c is None or c._local_evaluation is None:
            return None
        try:
            fl = c.get_identity_flags(str(family_id), traits or {}) if family_id else c.get_environment_flags()
            f = fl.get_flag(key)
        except Exception:                                    # feature not defined in Flagsmith, etc.
            return None
        if getattr(f, "is_default", False):
            return None
        return coerce(key, bool(f.enabled), f.value)

    async def get(self, key: str, family_id: Optional[str]) -> Any:
        if await self.client() is None or not self.loaded:
            return None
        traits = await self.traits(str(family_id)) if family_id else None
        return self.evaluate(key, family_id, traits)

    def status(self) -> dict:
        def iso(t: Optional[float]) -> Optional[str]:
            return datetime.fromtimestamp(t, timezone.utc).isoformat() if t else None
        host = urlparse(self.api_url).netloc if self.configured else None
        return {"provider": "flagsmith" if self.loaded else "defaults", "configured": self.configured,
                "api_host": host, "local_evaluation": True, "environment_loaded": self.loaded,
                "refresh_interval_s": self.REFRESH, "cache_ttl_s": TTL,
                "last_refresh_at": iso(self.last_refresh_at), "last_attempt_at": iso(self.last_attempt_at),
                "last_error": self.last_error}


_provider = FlagsmithProvider()


async def resolve(key: str, family_id: Optional[str] = None) -> tuple[Any, str]:
    """(value, source) where source is override:family | override:global | flagsmith | default."""
    ck = (key, str(family_id or ""))
    hit = _cache.get(ck)
    if hit and time.time() - hit[0] < TTL:
        return hit[1], hit[2]
    val: Any
    src: str
    rows = await db.fetch(
        "SELECT family_id, value FROM flag_overrides WHERE key=$1 AND (family_id IS NULL OR family_id=$2::uuid)",
        key, str(family_id) if family_id else None,
    )
    fam = [r for r in rows if r["family_id"] is not None]
    glob = [r for r in rows if r["family_id"] is None]
    if fam:
        val, src = fam[0]["value"], "override:family"
    elif glob:
        val, src = glob[0]["value"], "override:global"
    else:
        val, src = await _provider.get(key, family_id), "flagsmith"
    if val is None:
        val, src = DEFAULTS.get(key), "default"
    _cache[ck] = (time.time(), val, src)
    return val, src


async def get(key: str, family_id: Optional[str] = None) -> Any:
    return (await resolve(key, family_id))[0]


async def all_for(family_id: Optional[str]) -> dict[str, Any]:
    return {k: await get(k, family_id) for k in DEFAULTS}


async def sources_for(family_id: Optional[str]) -> dict[str, str]:
    return {k: (await resolve(k, family_id))[1] for k in DEFAULTS}


def status() -> dict:
    return _provider.status()


async def set_override(key: str, value: Any, family_id: Optional[str] = None) -> None:
    await db.execute(
        "DELETE FROM flag_overrides WHERE key=$1 AND family_id IS NOT DISTINCT FROM $2::uuid", key, family_id)
    await db.execute("INSERT INTO flag_overrides(family_id, key, value) VALUES ($1::uuid, $2, $3::jsonb)",
                     family_id, key, value)
    _cache.clear()
