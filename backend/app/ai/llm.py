"""OpenAI-compatible LLM provider selection (Sarvam primary, Groq fallback). Ported from MedSim.

Memo usage: `msg, provider = await llm.chat(messages, json_mode=True)`; `llm.strip_think(msg["content"])`.
The `llm_model` flag can pin a model: pass model=... (handled below).

Used by /voice/start (the model Agora's ConvoAI engine calls), the nurse
agent tool loop, and the simple debrief. Keys are read from the environment
at call time and are never logged or returned.

Verified against docs.sarvam.ai: POST https://api.sarvam.ai/v1/chat/completions,
auth via `Authorization: Bearer <key>` (or `api-subscription-key`), models
`sarvam-105b` (reasoning on) and `sarvam-105b-conversations` (reasoning off,
voice-friendly), tool calling + response_format supported.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

import httpx

from ..observability import nudgebee
from fastapi import HTTPException

log = logging.getLogger("memo.llm")

PROVIDERS: dict[str, dict[str, str]] = {
    "sarvam": {
        "url": "https://api.sarvam.ai/v1/chat/completions",
        "key_env": "SARVAM_API_KEY",
        "model_env": "SARVAM_MODEL",
        "default_model": "sarvam-105b-conversations",
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key_env": "GROQ_API_KEY",
        "model_env": "GROQ_MODEL",
        "default_model": "openai/gpt-oss-20b",  # only Groq model enabled on this key (verified 2026-11-20)
    },
}


class ProviderError(Exception):
    """Upstream LLM call failed (status/body kept for diagnostics, no keys)."""


def provider_config(name: str) -> Optional[dict[str, str]]:
    spec = PROVIDERS.get(name)
    if not spec:
        return None
    key = os.environ.get(spec["key_env"], "").strip()
    if not key:
        return None
    return {
        "name": name,
        "url": spec["url"],
        "api_key": key,
        "model": os.environ.get(spec["model_env"], "").strip() or spec["default_model"],
    }


def provider_order(preferred: Optional[str] = None) -> list[str]:
    """Preferred provider first (PATIENT_LLM_PROVIDER, default sarvam), then the other."""
    first = (preferred or os.environ.get("LLM_PROVIDER") or "sarvam").strip().lower()
    if first not in PROVIDERS:
        first = "sarvam"
    return [first] + [n for n in PROVIDERS if n != first]


def configured_providers(preferred: Optional[str] = None) -> list[dict[str, str]]:
    return [c for n in provider_order(preferred) if (c := provider_config(n))]


def require_provider(preferred: Optional[str] = None) -> dict[str, str]:
    cfgs = configured_providers(preferred)
    if not cfgs:
        raise HTTPException(
            status_code=503,
            detail="No LLM provider configured: set SARVAM_API_KEY (or GROQ_API_KEY).",
        )
    return cfgs[0]


def llm_health() -> dict[str, Any]:
    cfgs = configured_providers()
    return {
        "preferred": provider_order()[0],
        "sarvam_configured": provider_config("sarvam") is not None,
        "groq_configured": provider_config("groq") is not None,
        "active": cfgs[0]["name"] if cfgs else None,
        "model": cfgs[0]["model"] if cfgs else None,
        "anthropic_configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_think(text: str) -> str:
    """Drop reasoning-model <think> blocks from visible output."""
    text = _THINK_RE.sub("", text or "")
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    return text.strip()


async def _chat_one(
    cfg: dict[str, str],
    payload: dict[str, Any],
    client: Optional[httpx.AsyncClient],
) -> dict[str, Any]:
    body = {**payload, "model": cfg["model"]}
    headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}
    owns = client is None
    c = client or httpx.AsyncClient(timeout=45.0)
    try:
        r = await c.post(cfg["url"], json=body, headers=headers)
    except httpx.HTTPError as e:
        nudgebee.record_provider_error(cfg["name"], "network")
        raise ProviderError(f"{cfg['name']} request failed: {type(e).__name__}") from e
    finally:
        if owns:
            await c.aclose()
    nudgebee.record_http(cfg["name"], r.status_code)
    if r.status_code >= 400:
        raise ProviderError(f"{cfg['name']} HTTP {r.status_code}: {r.text[:300]}")
    try:
        return r.json()["choices"][0]["message"]
    except Exception as e:  # noqa: BLE001
        raise ProviderError(f"{cfg['name']} returned an unexpected body") from e


async def chat(
    messages: list[dict[str, Any]],
    *,
    tools: Optional[list[dict[str, Any]]] = None,
    json_mode: bool = False,
    max_tokens: int = 600,
    temperature: float = 0.2,
    client: Optional[httpx.AsyncClient] = None,
    stick_to: Optional[str] = None,
) -> tuple[dict[str, Any], str]:
    """Chat completion with provider fallback. Returns (assistant_message, provider_name).

    ``stick_to`` pins one provider (needed mid tool-loop so tool_call ids stay valid).
    Raises HTTPException(503) if nothing is configured, 502 if every provider fails.
    """
    cfgs = configured_providers()
    if stick_to:
        cfgs = [c for c in cfgs if c["name"] == stick_to]
    if not cfgs:
        raise HTTPException(
            status_code=503,
            detail="No LLM provider configured: set SARVAM_API_KEY (or GROQ_API_KEY).",
        )
    payload: dict[str, Any] = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    errors: list[str] = []
    for cfg in cfgs:
        try:
            msg = await _chat_one(cfg, payload, client)
            return msg, cfg["name"]
        except ProviderError as e:
            log.warning("%s", e)
            errors.append(str(e))
    raise HTTPException(status_code=502, detail="; ".join(errors)[:600])
