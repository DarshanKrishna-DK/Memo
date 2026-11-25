"""Flagsmith provider: type mapping, graceful fallback, resolution order, and live segment/identity behaviour.

Live tests need the self-hosted instance (docker compose --profile flags up -d flagsmith) seeded by
scripts/flagsmith_seed.py; they skip when FLAGSMITH_ENVIRONMENT_KEY is unset or the server is unreachable.
No jobs are created here (a live worker may be running).
"""
from __future__ import annotations

import sys
import uuid
from collections import Counter
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import config, db, flags  # noqa: E402
from _core_fixtures import drop_family, fresh_pool, make_family  # noqa: E402

KEY = config.env("FLAGSMITH_ENVIRONMENT_KEY")
URL = config.env("FLAGSMITH_API_URL") or "http://localhost:8001/api/v1/"


def _server_up() -> bool:
    if not KEY:
        return False
    try:
        return httpx.get(URL.split("/api/v1")[0] + "/health/liveness/", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


live = pytest.mark.skipif(not _server_up(), reason="local Flagsmith not running / not seeded")


# ---------------------------------------------------------------- type mapping (pure)
def test_coerce_booleans_use_enabled_state():
    assert flags.coerce("museum_3d", True, None) is True
    assert flags.coerce("museum_3d", False, "anything") is False


def test_coerce_numbers_strings_json():
    assert flags.coerce("max_calls_per_day", True, 7) == 7
    assert flags.coerce("max_calls_per_day", True, "12") == 12
    assert flags.coerce("followup_variant", True, "b") == "b"
    assert flags.coerce("llm_model", True, "") == ""
    assert flags.coerce("cinematic_walk", True, '{"enabled": false, "seconds": 5}') == {"enabled": False, "seconds": 5}
    assert flags.coerce("tts_voice_by_language", True, {"hi-IN": "x"}) == {"hi-IN": "x"}


def test_coerce_disabled_or_bad_config_means_no_opinion():
    assert flags.coerce("max_calls_per_day", False, 9) is None          # disabled remote config -> code default
    assert flags.coerce("max_calls_per_day", True, "lots") is None
    assert flags.coerce("cinematic_walk", True, "not json") is None
    assert flags.coerce("cinematic_walk", True, "[1, 2]") is None        # JSON but not an object
    assert flags.coerce("followup_variant", True, None) is None


# ---------------------------------------------------------------- graceful fallback
async def test_unset_key_returns_none():
    p = flags.FlagsmithProvider(key="")
    assert await p.get("museum_3d", None) is None
    assert await p.wait_ready(1) is False
    st = p.status()
    assert st["provider"] == "defaults" and st["configured"] is False and st["api_host"] is None


async def test_unreachable_server_returns_none_without_blocking():
    p = flags.FlagsmithProvider(key="ser.pytest-not-a-real-key", api_url="http://127.0.0.1:9/api/v1/")
    try:
        assert await p.get("museum_3d", None) is None                     # returns at once; init runs in a thread
        assert await p.wait_ready(20) is False
        assert await p.get("museum_3d", None) is None
        st = p.status()
        assert st["provider"] == "defaults" and st["environment_loaded"] is False and st["last_error"]
        assert "pytest-not-a-real-key" not in repr(st)                     # never leaks the key
    finally:
        p.close()


async def test_client_side_key_is_rejected_for_local_evaluation():
    p = flags.FlagsmithProvider(key="not-a-server-key", api_url="http://127.0.0.1:9/api/v1/")
    assert await p.wait_ready(5) is False
    assert p.status()["last_error"].startswith("init failed")
    assert await p.get("museum_3d", None) is None


# ---------------------------------------------------------------- resolution order (real Postgres, test-only key)
class _FakeProvider:
    def __init__(self, value):
        self.value = value

    async def get(self, key, family_id):
        return self.value

    def status(self):
        return {"provider": "fake"}


async def test_resolution_order(monkeypatch):
    await fresh_pool()
    key = "pytest_flag_" + uuid.uuid4().hex[:8]                         # not a real flag: invisible to the app
    monkeypatch.setitem(flags.DEFAULTS, key, 1)
    monkeypatch.setattr(flags, "_provider", _FakeProvider(2))
    fam = await make_family("pytest-flags")
    try:
        flags._cache.clear()
        assert await flags.resolve(key, fam["id"]) == (2, "flagsmith")
        monkeypatch.setattr(flags, "_provider", _FakeProvider(None))
        flags._cache.clear()
        assert await flags.resolve(key, fam["id"]) == (1, "default")
        monkeypatch.setattr(flags, "_provider", _FakeProvider(2))
        await flags.set_override(key, 3, None)
        assert await flags.resolve(key, fam["id"]) == (3, "override:global")
        await flags.set_override(key, 4, fam["id"])
        assert await flags.resolve(key, fam["id"]) == (4, "override:family")
        assert await flags.get(key, fam["id"]) == 4
        assert (await flags.resolve(key, None)) == (3, "override:global")
    finally:
        await db.execute("DELETE FROM flag_overrides WHERE key=$1", key)
        await drop_family(fam["id"])
        flags._cache.clear()


# ---------------------------------------------------------------- live: identity, traits, segments, multivariate
@live
async def test_live_types_traits_and_segments():
    await fresh_pool()
    p = flags.FlagsmithProvider()
    hi = await make_family("pytest-flags-hi")
    en = await make_family("pytest-flags-en")
    try:
        await db.execute("UPDATE families SET language='hi-IN' WHERE id=$1::uuid", hi["id"])
        assert await p.wait_ready(15) is True
        assert p.status()["provider"] == "flagsmith" and p.status()["last_refresh_at"]

        t = await p.traits(hi["id"])
        assert t == {"family_id": hi["id"], "language": "hi-IN", "member_count": 2, "created_days_ago": 0,
                     "has_phone_invites": False, "has_call_consent": False}

        # types come back as the code expects
        assert isinstance(await p.get("museum_3d", en["id"]), bool)
        assert isinstance(await p.get("max_calls_per_day", en["id"]), int)
        assert isinstance(await p.get("cinematic_walk", en["id"]), dict)

        # segment hindi_or_kannada -> tts_voice_by_language override; English family gets the environment value
        hv = await p.get("tts_voice_by_language", hi["id"])
        assert hv and hv.get("hi-IN")
        assert await p.get("tts_voice_by_language", en["id"]) == {}
        names = {s.name for s in p._client.get_identity_segments(hi["id"], t)}
        assert "hindi_or_kannada" in names and "phone_pilot" not in names

        # phone_pilot: membership is by family_id trait
        pilot = p._client.get_identity_segments("x", {"family_id": "not-in-pilot"})
        assert "phone_pilot" not in {s.name for s in pilot}
    finally:
        p.close()
        await drop_family(hi["id"])
        await drop_family(en["id"])


@live
async def test_live_followup_variant_is_a_stable_50_50_split():
    p = flags.FlagsmithProvider()
    try:
        assert await p.wait_ready(15) is True
        ids = [str(uuid.uuid4()) for _ in range(400)]
        first = [p.evaluate("followup_variant", i, {"family_id": i}) for i in ids]
        assert first == [p.evaluate("followup_variant", i, {"family_id": i}) for i in ids]   # sticky per family
        c = Counter(first)
        assert set(c) == {"a", "b"} and 140 <= c["a"] <= 260
        assert p.evaluate("followup_variant", None) == "a"                  # no identity -> control value
    finally:
        p.close()
