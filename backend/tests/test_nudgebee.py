"""NudgeBee emitter: payload shape, dedupe, resolve, PII, no-op. No network, no database."""
import json
import re

import httpx
import pytest
from fastapi import FastAPI

from app import flags
from app.observability import nudgebee as nb

REQUIRED = {"id", "fingerprint", "status", "title", "rule_name"}
OPTIONAL = {"severity", "description", "starts_at", "ends_at", "subject", "source_tool", "url", "labels"}


@pytest.fixture
def sent(monkeypatch):
    nb.reset()
    calls: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append({"url": str(req.url), "auth": req.headers.get("authorization"), "body": json.loads(req.content)})
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(nb, "_transport", httpx.MockTransport(handler))
    monkeypatch.setenv("NUDGEBEE_WEBHOOK_URL", "https://nb.example/api/webhooks/event")
    monkeypatch.setenv("NUDGEBEE_TOKEN", "tok-123")
    monkeypatch.setenv("MEMO_ENV", "test")

    async def flag(key, family_id=None):
        return True
    monkeypatch.setattr(flags, "get", flag)
    yield calls
    nb.reset()


def events(calls):
    return [e for c in calls for e in c["body"]["events"]]


async def test_payload_matches_docs(sent):
    await nb.emit("job_failed", "Job x failed", severity="high", fingerprint_parts=("x",),
                  description="boom", labels={"kind": "x", "family_id": "11111111-1111-1111-1111-111111111111"})
    await nb.flush_now()
    assert sent[0]["url"] == "https://nb.example/api/webhooks/event"
    assert sent[0]["auth"] == "Bearer tok-123"
    (ev,) = events(sent)
    assert REQUIRED <= set(ev) <= REQUIRED | OPTIONAL
    assert ev["status"] == "firing" and ev["severity"] == "high"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", ev["starts_at"])
    assert all(isinstance(v, str) for v in ev["labels"].values())
    assert ev["labels"]["env"] == "test" and ev["labels"]["service"] == "api"
    assert not any(k.startswith("nb_") for k in ev["labels"])
    assert len(ev["id"]) <= 256 and len(ev["fingerprint"]) <= 256


async def test_dedupe_and_resolve_flow(sent):
    for _ in range(5):
        await nb.emit("job_failed", "t", fingerprint_parts=("k",), labels={"kind": "k"})
    await nb.flush_now()
    fired = events(sent)
    assert len(fired) == 1

    await nb.emit("job_failed", "t ok", fingerprint_parts=("k",), status="resolved")
    await nb.flush_now()
    res = events(sent)[-1]
    assert res["status"] == "resolved"
    assert (res["id"], res["fingerprint"], res["labels"]) == (fired[0]["id"], fired[0]["fingerprint"], fired[0]["labels"])
    assert res["ends_at"] >= res["starts_at"]

    n = len(events(sent))
    await nb.emit("job_failed", "t ok", fingerprint_parts=("k",), status="resolved")   # nothing open: silent
    await nb.flush_now()
    assert len(events(sent)) == n


async def test_refire_after_window_reuses_id(sent, monkeypatch):
    await nb.emit("r", "t", fingerprint_parts=("a",))
    await nb.flush_now()
    for st in nb._open.values():
        st["last_sent"] -= nb.DEDUPE_S + 1
    await nb.emit("r", "t", fingerprint_parts=("a",))
    await nb.flush_now()
    a, b = events(sent)
    assert a["id"] == b["id"] and a["status"] == b["status"] == "firing"


async def test_batching_background_flusher(sent, monkeypatch):
    monkeypatch.setattr(nb, "FLUSH_DELAY_S", 0.05)
    await nb.emit("r", "one", fingerprint_parts=(1,))
    await nb.emit("r", "two", fingerprint_parts=(2,))
    import asyncio
    await asyncio.sleep(0.3)
    assert len(sent) == 1 and len(sent[0]["body"]["events"]) == 2


async def test_job_hooks(sent):
    await nb.job_failed("render_reel", 1, 5, RuntimeError("x"))       # early retry: quiet
    await nb.job_failed("render_reel", 5, 5, RuntimeError("x"), {"family_id": "not-an-id", "name": "Asha"})
    await nb.flush_now()
    (ev,) = events(sent)
    assert ev["severity"] == "high" and ev["labels"]["kind"] == "render_reel"
    assert "family_id" not in ev["labels"]            # non-uuid is not forwarded
    await nb.job_ok("render_reel")
    await nb.flush_now()
    assert events(sent)[-1]["status"] == "resolved"


async def test_provider_threshold_and_recovery(sent):
    import asyncio
    for _ in range(nb.PROVIDER_THRESHOLD - 1):
        nb.record_provider_error("sarvam", "http_503")
    await asyncio.sleep(0)
    assert not nb._open
    nb.record_provider_error("sarvam", "http_503")
    await asyncio.sleep(0.01)
    await nb.flush_now()
    assert events(sent)[0]["labels"]["provider"] == "sarvam"
    for _ in range(nb.PROVIDER_OK_TO_RESOLVE):
        nb.record_http("sarvam", 200)
    await asyncio.sleep(0.01)
    await nb.flush_now()
    assert events(sent)[-1]["status"] == "resolved"
    nb.record_http("sarvam", 400)                      # client errors never count
    assert not nb._prov_errors.get("sarvam")


async def test_api_middleware_reports_5xx_without_raw_path(sent):
    from httpx import ASGITransport, AsyncClient
    app = FastAPI()

    @app.get("/boom/{who}")
    async def boom(who: str):
        raise ValueError("secret memory text")

    @app.get("/fine/{who}")
    async def fine(who: str):
        return {"ok": True}
    nb.install(app)
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t") as c:
        r = await c.get("/boom/asha-9876543210")
        assert r.status_code == 500
    await nb.flush_now()
    (ev,) = events(sent)
    blob = json.dumps(ev)
    assert "/boom/{who}" in blob and "asha" not in blob and "9876543210" not in blob and "secret memory" not in blob
    assert ev["labels"]["status_code"] == "500"


async def test_no_pii_in_payload(sent):
    await nb.emit("r", "Call to +919876543210 failed for priya@example.com", fingerprint_parts=("p",),
                  description="Grandma said: 'my wedding in 1975' number 919876543210",
                  labels={"kind": "x", "name": "Asha", "phone": "+919876543210", "transcript": "hello",
                          "family_id": "11111111-1111-1111-1111-111111111111"})
    await nb.flush_now()
    ev = events(sent)[0]
    assert set(ev["labels"]) <= nb.LABEL_KEYS
    blob = json.dumps(ev)
    assert "9876543210" not in blob and "priya@example.com" not in blob and "Asha" not in blob


async def test_noop_when_unconfigured(sent, monkeypatch):
    monkeypatch.delenv("NUDGEBEE_TOKEN")
    await nb.emit("r", "t", fingerprint_parts=("z",))
    await nb.flush_now()
    assert sent == [] and not nb._open


async def test_noop_when_flag_off(sent, monkeypatch):
    async def off(key, family_id=None):
        return False
    monkeypatch.setattr(flags, "get", off)
    await nb.emit("r", "t", fingerprint_parts=("z",))
    await nb.flush_now()
    assert sent == []


async def test_never_raises_on_network_error(monkeypatch):
    nb.reset()
    monkeypatch.setenv("NUDGEBEE_WEBHOOK_URL", "https://nb.example/e")
    monkeypatch.setenv("NUDGEBEE_TOKEN", "t")

    def boom(req):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(nb, "_transport", httpx.MockTransport(boom))

    async def flag(key, family_id=None):
        return True
    monkeypatch.setattr(flags, "get", flag)
    await nb.emit("r", "t", fingerprint_parts=("n",))
    await nb.flush_now()
    nb.reset()


def test_default_flag_is_on():
    assert flags.DEFAULTS["nudgebee_alerts"] is True
