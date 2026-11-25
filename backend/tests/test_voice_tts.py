"""voice-ai: real text-to-speech per language (Sarvam bulbul:v3 primary, Murf Falcon fallback), cached by hash."""
from __future__ import annotations

import secrets

import pytest
import pytest_asyncio

from _voice_fixtures import fresh_pool
from app import storage
from app.ai import tts
from app.voice import lang as L

pytestmark = pytest.mark.asyncio(loop_scope="module")

LINES = {"en-IN": "Welcome back. November 2026 has eleven memories.",
         "hi-IN": "फिर से स्वागत है। नवंबर 2026 में ग्यारह यादें हैं।",
         "kn-IN": "ಮತ್ತೆ ಸ್ವಾಗತ. ನವೆಂಬರ್ 2026 ರಲ್ಲಿ ಹನ್ನೊಂದು ನೆನಪುಗಳಿವೆ."}


@pytest_asyncio.fixture(loop_scope="module", scope="module", autouse=True)
async def pool():
    await fresh_pool()


@pytest.mark.parametrize("lang", list(LINES))
async def test_real_tts_per_language(lang):
    nonce = secrets.token_hex(3)          # bypass the cache so this is a real call
    out = await tts.synthesize(f"{LINES[lang]} ({nonce})", lang, "grandma")
    print(f"\n{lang}: provider={out['provider']} voice={out['voice']} duration={out['duration_s']}s")
    data = storage.get(out["storage_key"])
    assert len(data) > 5000 and (data[:3] == b"ID3" or data[0] == 0xFF)     # an mp3
    assert out["duration_s"] > 1.0 and out["url"].startswith("/media/") and out["cached"] is False
    again = await tts.synthesize(f"{LINES[lang]} ({nonce})", lang, "grandma")
    assert again["cached"] is True and again["storage_key"] == out["storage_key"]


@pytest.mark.parametrize("lang", list(LINES))
async def test_murf_fallback_voice_per_language(lang):
    audio = await tts._murf(LINES[lang], lang, L.MURF_VOICES["grandma"][lang], "mp3")
    assert len(audio) > 5000


async def test_explicit_murf_voice_and_bad_speaker_falls_back():
    out = await tts.synthesize(f"Follow me. {secrets.token_hex(2)}", "en-IN", "en-IN-aarav")
    assert out["provider"] == "murf" and out["voice"] == "en-IN-aarav"
    out = await tts.synthesize(f"Here we are. {secrets.token_hex(2)}", "en-IN", "no_such_speaker")
    assert out["provider"] == "sarvam" and out["voice"] == L.SARVAM_VOICES["grandma"]["en-IN"]


def _tone_mp3() -> bytes:
    import subprocess
    return subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=170:d=1.2", "-f", "lavfi", "-t", "0.4",
                           "-i", "anullsrc=r=24000:cl=mono", "-f", "lavfi", "-i", "sine=f=190:d=1.2",
                           "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1", "-ar", "24000", "-ac", "1", "-f", "mp3",
                           "pipe:1"], capture_output=True, check=True).stdout


@pytest.mark.parametrize("level", ["subtle", "strong"])
async def test_age_audio_is_slower_mp3(level):
    raw = _tone_mp3()
    aged = tts.age_audio(raw, "mp3", level)
    assert aged[:3] == b"ID3" or aged[0] == 0xFF
    assert tts.mp3_duration(aged) > tts.mp3_duration(raw) * 1.05          # slower delivery + longer pause


def test_age_fx_level_env(monkeypatch):
    monkeypatch.delenv("GRANDMA_AGE_FX", raising=False)
    assert tts.age_fx_level() == "strong"
    monkeypatch.setenv("GRANDMA_AGE_FX", "off")
    assert tts.age_fx_level() == "off" and tts.age_fx_level("subtle") == "subtle"
    assert tts._fx_override({"hi-IN": {"grandma": {"voice": "neha", "age_fx": "subtle"}}}, "hi-IN") == "subtle"
