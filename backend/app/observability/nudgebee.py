"""NudgeBee Generic Event Webhook sender (https://docs.nudgebee.com/docs/integrations/Webhooks/event_webhook/).

Memo's AI-SRE signal feed: job failures, API 5xx, provider degradation, worker health watchdog.
Design rules:
  * never raises, never blocks a request: callers await `emit` (cheap, in-memory) or call `emit_nowait`;
    the HTTP POST runs in a background flusher with a 3 s timeout.
  * batched + debounced: one event per fingerprint per DEDUPE_S while it stays open; recovery sends `resolved`
    with the same id + labels (state is in memory, per process).
  * no-op unless NUDGEBEE_WEBHOOK_URL and NUDGEBEE_TOKEN are set and flag `nudgebee_alerts` is on.
  * NO personal data: labels are allow-listed, descriptions are scrubbed. family_id goes only as an opaque id.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from .. import config

log = logging.getLogger("memo.nudgebee")

DEDUPE_S = 300.0        # one firing event per fingerprint per window
FLUSH_DELAY_S = 2.0     # batch window
TIMEOUT_S = 3.0
PROVIDER_WINDOW_S = 300.0
PROVIDER_THRESHOLD = 5  # errors in the window before a provider is called degraded
PROVIDER_OK_TO_RESOLVE = 3
SEVERITIES = ("critical", "high", "medium", "low", "info")
LABEL_KEYS = {"service", "env", "family_id", "kind", "provider", "route", "method", "error_type", "status_code",
              "check", "test"}

_service = "api"
_open: dict[str, dict] = {}            # fingerprint -> {id, labels, last_sent, count, starts_at}
_pending: dict[str, dict] = {}         # fingerprint -> event awaiting flush
_flusher: Optional[asyncio.Task] = None
_tasks: set[asyncio.Task] = set()
_transport: Optional[httpx.AsyncBaseTransport] = None   # tests inject a MockTransport
_prov_errors: dict[str, deque] = {}
_prov_ok: dict[str, int] = {}


def set_service(name: str) -> None:
    global _service
    _service = name


def configured() -> bool:
    return bool(config.env("NUDGEBEE_WEBHOOK_URL") and config.env("NUDGEBEE_TOKEN"))


def reset() -> None:
    """Test helper: forget all in-memory state."""
    global _flusher
    _open.clear(); _pending.clear(); _prov_errors.clear(); _prov_ok.clear()
    _flusher = None


# ---------------------------------------------------------------- payload

_DIGITS = re.compile(r"\d{6,}")
_EMAIL = re.compile(r"\S+@\S+")


def scrub(text: str, limit: int = 300) -> str:
    text = _EMAIL.sub("[email]", text or "")
    text = _DIGITS.sub("[num]", text)
    return text.replace("\n", " ")[:limit]


def _clean_ctl(s: str, limit: int = 256) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", "", s)[:limit]


def _labels(extra: Optional[dict]) -> dict[str, str]:
    out = {"service": _service, "env": config.env("MEMO_ENV", "local") or "local"}
    for k, v in (extra or {}).items():
        if k in LABEL_KEYS and v is not None and v != "":
            out[k] = scrub(str(v), 128)
    return out


def fingerprint(rule: str, parts: tuple | list) -> str:
    raw = "|".join([rule, *[str(p) for p in parts]])
    return f"memo:{rule}:" + hashlib.sha1(raw.encode()).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_event(*, id: str, fingerprint: str, status: str, title: str, rule_name: str, severity: str,
                description: str, labels: dict[str, str], starts_at: str, ends_at: Optional[str] = None) -> dict:
    ev: dict[str, Any] = {
        "id": _clean_ctl(id), "fingerprint": _clean_ctl(fingerprint), "status": status,
        "title": scrub(title, 200), "rule_name": _clean_ctl(rule_name),
        "severity": severity if severity in SEVERITIES else "medium",
        "description": scrub(description), "starts_at": starts_at,
        "subject": {"name": f"memo-{labels.get('service', 'api')}", "type": "service"},
        "source_tool": "memo", "labels": labels,
    }
    if ends_at:
        ev["ends_at"] = ends_at
    return ev


async def _post(events: list[dict]) -> tuple[int, str]:
    """POST events (<=100 per request). Returns (status, body snippet). May raise; callers wrap."""
    url, tok = config.env("NUDGEBEE_WEBHOOK_URL"), config.env("NUDGEBEE_TOKEN")
    last = (0, "")
    for i in range(0, len(events), 100):
        async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=_transport) as c:
            r = await c.post(url, json={"events": events[i:i + 100]},
                             headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
        last = (r.status_code, r.text[:300])
    return last


# ---------------------------------------------------------------- queue / flush

async def _flush_loop() -> None:
    global _flusher
    try:
        await asyncio.sleep(FLUSH_DELAY_S)
        while _pending:
            batch = list(_pending.values())
            _pending.clear()
            try:
                status, body = await asyncio.wait_for(_post(batch), TIMEOUT_S + 1)
                if status >= 300:
                    log.warning("nudgebee rejected events: HTTP %s %s", status, body[:120])
            except Exception as e:  # noqa: BLE001
                log.debug("nudgebee send failed: %s", type(e).__name__)
    finally:
        _flusher = None


def _enqueue(fp: str, ev: dict) -> None:
    global _flusher
    _pending[fp] = ev
    if _flusher is None or _flusher.done():
        _flusher = asyncio.get_running_loop().create_task(_flush_loop())


async def _enabled() -> bool:
    if not configured():
        return False
    try:
        from .. import flags
        return bool(await asyncio.wait_for(flags.get("nudgebee_alerts"), 2.0))
    except Exception:  # noqa: BLE001 - DB may be the very thing that is down: default on
        return True


async def emit(rule: str, title: str, *, severity: str = "medium", fingerprint_parts: tuple | list = (),
               description: str = "", labels: Optional[dict] = None, status: str = "firing") -> None:
    """Report a problem (`firing`) or its recovery (`resolved`). Cheap, never raises."""
    try:
        if not await _enabled():
            return
        fp = fingerprint(rule, fingerprint_parts)
        now = time.time()
        cur = _open.get(fp)
        if status == "resolved":
            if not cur:
                return
            del _open[fp]
            if fp in _pending and _pending[fp]["status"] == "firing":
                del _pending[fp]          # never reached NudgeBee; nothing to close
                return
            _enqueue(fp, build_event(id=cur["id"], fingerprint=fp, status="resolved", title=title, rule_name=rule,
                                     severity=severity, description=description, labels=cur["labels"],
                                     starts_at=cur["starts_at"], ends_at=_now()))
            return
        if cur and now - cur["last_sent"] < DEDUPE_S:
            cur["count"] += 1
            return
        lab = _labels(labels)
        eid = cur["id"] if cur else f"{fp[-12:]}-{uuid.uuid4().hex[:8]}"
        starts = cur["starts_at"] if cur else _now()
        _open[fp] = {"id": eid, "labels": lab, "last_sent": now, "count": 1, "starts_at": starts}
        _enqueue(fp, build_event(id=eid, fingerprint=fp, status="firing", title=title, rule_name=rule,
                                 severity=severity, description=description, labels=lab, starts_at=starts))
    except Exception as e:  # noqa: BLE001
        log.debug("nudgebee emit failed: %s", type(e).__name__)


def emit_nowait(*a, **kw) -> None:
    """For sync code running inside an event loop: schedules `emit`. Silently does nothing without a loop."""
    try:
        t = asyncio.get_running_loop().create_task(emit(*a, **kw))
    except RuntimeError:
        return
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


async def flush_now() -> None:
    """Send whatever is pending immediately (tests, shutdown)."""
    if _pending:
        batch = list(_pending.values()); _pending.clear()
        try:
            await _post(batch)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- signal (a): jobs

def _opaque_family(payload: Optional[dict]) -> Optional[str]:
    fid = (payload or {}).get("family_id")
    return str(fid) if fid and re.fullmatch(r"[0-9a-fA-F-]{36}", str(fid)) else None


async def job_failed(kind: str, attempts: int, max_attempts: int, exc: BaseException,
                     payload: Optional[dict] = None) -> None:
    dead = attempts >= max_attempts
    if not dead and attempts < 3:
        return
    await emit("job_failed", f"Memo job '{kind}' {'exhausted retries' if dead else 'keeps failing'}",
               severity="high" if dead else "low", fingerprint_parts=(kind,),
               description=f"Job kind {kind} failed on attempt {attempts}/{max_attempts}: {type(exc).__name__}",
               labels={"kind": kind, "error_type": type(exc).__name__, "family_id": _opaque_family(payload)})


async def job_ok(kind: str) -> None:
    if fingerprint("job_failed", (kind,)) in _open:
        await emit("job_failed", f"Memo job '{kind}' recovered", fingerprint_parts=(kind,), status="resolved",
                   description=f"Job kind {kind} succeeded again")


# ---------------------------------------------------------------- signal (b): API 5xx

class ApiErrorMiddleware:
    """Pure ASGI middleware: reports unhandled exceptions and 5xx responses; re-raises untouched."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        status = {"code": 0}

        async def _send(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
            await send(msg)

        exc: Optional[BaseException] = None
        try:
            await self.app(scope, receive, _send)
        except BaseException as e:  # noqa: BLE001
            exc = e
            status["code"] = status["code"] or 500
            raise
        finally:
            try:
                route = getattr(scope.get("route"), "path", None) or "unmatched"   # template, never the raw path
                method = scope.get("method", "GET")
                if status["code"] >= 500 or exc is not None:
                    await emit("api_5xx", f"Memo API 5xx on {method} {route}", severity="high",
                               fingerprint_parts=(method, route),
                               description=f"{method} {route} returned {status['code']}"
                                           + (f" ({type(exc).__name__})" if exc else ""),
                               labels={"route": route, "method": method, "status_code": status["code"],
                                       "error_type": type(exc).__name__ if exc else None})
                elif status["code"] and _open:
                    if fingerprint("api_5xx", (method, route)) in _open:
                        await emit("api_5xx", f"Memo API recovered on {method} {route}",
                                   fingerprint_parts=(method, route), status="resolved")
            except Exception:  # noqa: BLE001
                pass


def install(app) -> None:
    """The one line main.py needs: `nudgebee.install(app)`."""
    set_service("api")
    app.add_middleware(ApiErrorMiddleware)


# ---------------------------------------------------------------- signal (c): providers

def record_provider_error(provider: str, kind: str = "error") -> None:
    """Sync + cheap; call from the failure path of an external call. Fires once errors in the window pass the threshold."""
    try:
        now = time.time()
        dq = _prov_errors.setdefault(provider, deque())
        dq.append(now)
        while dq and now - dq[0] > PROVIDER_WINDOW_S:
            dq.popleft()
        _prov_ok[provider] = 0
        if len(dq) >= PROVIDER_THRESHOLD:
            emit_nowait("provider_degraded", f"{provider} calls are failing", severity="high",
                        fingerprint_parts=(provider,),
                        description=f"{len(dq)} {provider} errors in the last {int(PROVIDER_WINDOW_S // 60)} min "
                                    f"(latest: {kind})",
                        labels={"provider": provider, "kind": kind})
    except Exception:  # noqa: BLE001
        pass


def record_http(provider: str, status: int) -> None:
    """Classify an HTTP result: 5xx/429 = provider trouble, 2xx = healthy, other 4xx = our request, ignored."""
    if status >= 500 or status == 429:
        record_provider_error(provider, f"http_{status}")
    elif status < 400:
        record_provider_ok(provider)


def record_provider_ok(provider: str) -> None:
    try:
        if fingerprint("provider_degraded", (provider,)) not in _open:
            _prov_errors.pop(provider, None)
            return
        _prov_ok[provider] = _prov_ok.get(provider, 0) + 1
        if _prov_ok[provider] >= PROVIDER_OK_TO_RESOLVE:
            _prov_errors.pop(provider, None)
            emit_nowait("provider_degraded", f"{provider} calls recovered", fingerprint_parts=(provider,),
                        status="resolved")
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- signal (d): watchdog (runs in the worker)

async def check_health(backlog_min: float = 10.0) -> None:
    from .. import db
    try:
        await asyncio.wait_for(db.fetchval("SELECT 1"), 5.0)
    except Exception as e:  # noqa: BLE001
        await emit("db_unreachable", "Memo cannot reach Postgres", severity="critical",
                   description=f"Health check failed: {type(e).__name__}", labels={"check": "db"})
        return
    await emit("db_unreachable", "Memo database reachable again", status="resolved")
    try:
        age = await asyncio.wait_for(db.fetchval(
            "SELECT extract(epoch FROM now() - min(run_at)) FROM jobs WHERE status='queued' AND run_at <= now()"), 5.0)
    except Exception:  # noqa: BLE001
        return
    if age is not None and age > backlog_min * 60:
        await emit("queue_backlog", "Memo job queue is backed up", severity="high",
                   description=f"Oldest runnable job has waited {int(age // 60)} min (limit {int(backlog_min)})",
                   labels={"check": "queue"})
    else:
        await emit("queue_backlog", "Memo job queue drained", status="resolved")


_watchdog_task: Optional[asyncio.Task] = None


def start_watchdog() -> None:
    """Idempotent: one health loop per process (called from jobs.worker_loop, so in-process workers get it too)."""
    global _watchdog_task
    if _watchdog_task is None or _watchdog_task.done():
        _watchdog_task = asyncio.get_running_loop().create_task(watchdog())


async def watchdog(interval_s: float = 60.0) -> None:
    """Background loop for the worker process. Never exits, never raises."""
    backlog = float(config.env("NUDGEBEE_BACKLOG_MIN", "10") or 10)
    while True:
        try:
            if configured():
                await check_health(backlog)
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(interval_s)
