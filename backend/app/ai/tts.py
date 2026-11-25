"""Text-to-speech: Sarvam bulbul (primary, en-IN / hi-IN / kn-IN) with Murf Falcon as fallback (as in MedSim).

    await synthesize(text, language, voice=None, fmt="mp3", family_id=None)
        -> {"storage_key", "url", "duration_s", "provider", "voice", "cached"}

`voice` is a role ("grandma" | "receptionist" | "guide" | "phone"), a Sarvam speaker ("neha", or a bulbul:v4-flash
persona "roopa_hi_narration") or a Murf voice id ("en-IN-alia"). A role speaks with its chosen voice and prosody
(lang.VOICE_PROFILES: speaker + pace / pitch / temperature; see docs/VOICES.md for the measurements). The
`tts_voice_by_language` flag ({"hi-IN": "<speaker or murf id>"} or {"hi-IN": {"grandma": ...}}) overrides the role
default for that language. Audio is cached in storage by sha256(text + language + voice + fmt) and indexed in `tts_cache`,
so a line is synthesized once (guide robot lines, repeated tour sentences).

Verified 2026-11-24:
  Sarvam  POST https://api.sarvam.ai/text-to-speech, header api-subscription-key,
          body {text, language_code, speaker, model: bulbul:v3, output_audio_codec, speech_sample_rate}
          -> {"audios": [base64]}   (docs.sarvam.ai/api-reference-docs/text-to-speech/convert, live call 200)
  Murf    POST https://global.api.murf.ai/v1/speech/stream, header api-key,
          body {text, voiceId, model: FALCON, format: MP3, sampleRate, locale} -> audio/mpeg (live call 200)
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
from typing import Any, Optional

import httpx

from ..observability import nudgebee
import numpy as np
from fastapi import HTTPException

from .. import db, flags, storage
from ..voice import lang as L
from . import voice_clone

log = logging.getLogger("memo.tts")

SARVAM_URL = "https://api.sarvam.ai/text-to-speech"
MURF_URL = "https://global.api.murf.ai/v1/speech/stream"
SAMPLE_RATE = 24000
MAX_CHARS = 1500


class TTSError(Exception):
    pass


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))


SARVAM_PARAMS = ("pace", "pitch", "loudness", "temperature")
MURF_PARAMS = ("rate", "pitch", "style", "volumeOffset")


async def _sarvam(text: str, language: str, speaker: str, fmt: str, params: Optional[dict] = None) -> bytes:
    key = os.environ.get("SARVAM_API_KEY", "").strip()
    if not key:
        raise TTSError("SARVAM_API_KEY not set")
    params = params or {}
    body = {"text": text, "language_code": language, "speaker": speaker,
            "model": params.get("model") or L.sarvam_model_for(speaker),
            "output_audio_codec": fmt, "speech_sample_rate": SAMPLE_RATE}
    body.update({k: params[k] for k in SARVAM_PARAMS if params.get(k) is not None})
    async with _client() as c:
        try:
            r = await c.post(SARVAM_URL, json=body, headers={"api-subscription-key": key})
        except httpx.HTTPError as e:
            nudgebee.record_provider_error("sarvam", "network")
            raise TTSError(f"sarvam request failed: {type(e).__name__}") from e
    nudgebee.record_http("sarvam", r.status_code)
    if r.status_code != 200:
        raise TTSError(f"sarvam HTTP {r.status_code}: {r.text[:200]}")
    try:
        return b"".join(base64.b64decode(a) for a in r.json()["audios"])
    except Exception as e:  # noqa: BLE001
        raise TTSError("sarvam returned an unexpected body") from e


async def _clone(text: str, language: str, voice_id: str, fmt: str) -> bytes:
    """Cloned family voice (voice_clone.speak, <= 1000 chars per call): long text is split at sentence ends."""
    try:
        parts, cur = [], ""
        for sent in re.split(r"(?<=[.!?।])\s+", text):
            if cur and len(cur) + len(sent) + 1 > voice_clone.MAX_TEXT:
                parts.append(cur)
                cur = ""
            cur = f"{cur} {sent}".strip()
        parts.append(cur)
        clips = [await voice_clone.speak(t, voice_id, language, fmt) for t in parts if t]
    except voice_clone.CloneError as e:
        raise TTSError(str(e)) from e
    if len(clips) == 1 or fmt != "mp3":
        return clips[0]
    return b"".join(b"".join(_mp3_frames(c)[0]) for c in clips)


async def _murf(text: str, language: str, voice_id: str, fmt: str, params: Optional[dict] = None) -> bytes:
    key = os.environ.get("MURF_API_KEY", "").strip()
    if not key:
        raise TTSError("MURF_API_KEY not set")
    params = params or {}
    body = {"text": text, "voiceId": voice_id, "model": "FALCON", "format": fmt.upper(),
            "sampleRate": SAMPLE_RATE, "locale": language}
    body.update({k: params[k] for k in MURF_PARAMS if params.get(k) is not None})
    async with _client() as c:
        try:
            r = await c.post(MURF_URL, json=body, headers={"api-key": key})
        except httpx.HTTPError as e:
            nudgebee.record_provider_error("murf", "network")
            raise TTSError(f"murf request failed: {type(e).__name__}") from e
    nudgebee.record_http("murf", r.status_code)
    if r.status_code != 200 or not r.content:
        raise TTSError(f"murf HTTP {r.status_code}: {r.text[:200]}")
    return r.content


_MP3_BITRATES = {  # (version_is_1, layer3) kbps tables
    True: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0],
    False: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
}
_MP3_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def mp3_duration(data: bytes) -> Optional[float]:
    """Seconds of MPEG audio (Layer III) by walking frame headers; handles VBR. None if not parseable."""
    i = 0
    if data[:3] == b"ID3" and len(data) > 10:
        size = (data[6] & 0x7F) << 21 | (data[7] & 0x7F) << 14 | (data[8] & 0x7F) << 7 | (data[9] & 0x7F)
        i = 10 + size
    total, frames, n = 0.0, 0, len(data)
    while i + 4 <= n:
        b1, b2, b3 = data[i + 1], data[i + 2], data[i + 3]
        if data[i] != 0xFF or (b1 & 0xE0) != 0xE0:
            i += 1
            continue
        ver, layer = (b1 >> 3) & 3, (b1 >> 1) & 3
        br_i, sr_i, pad = (b2 >> 4) & 0xF, (b2 >> 2) & 3, (b2 >> 1) & 1
        if ver == 1 or layer != 1 or br_i in (0, 15) or sr_i == 3:
            i += 1
            continue
        v1 = ver == 3
        br = _MP3_BITRATES[v1][br_i] * 1000
        sr = _MP3_RATES[ver][sr_i]
        samples = 1152 if v1 else 576
        flen = (144 if v1 else 72) * br // sr + pad
        if flen < 4:
            i += 1
            continue
        total += samples / sr
        frames += 1
        i += flen
    return total if frames >= 2 else None


def wav_duration(data: bytes) -> Optional[float]:
    import struct
    try:
        ch, rate, byte_rate = struct.unpack("<HII", data[22:32])
        j = 12
        while j + 8 <= len(data):
            cid, size = data[j:j + 4], struct.unpack("<I", data[j + 4:j + 8])[0]
            if cid == b"data":
                return size / byte_rate if byte_rate else None
            j += 8 + size
    except struct.error:
        return None
    return None


def _duration(path: str, nbytes: int) -> float:
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        d = mp3_duration(data) if not data.startswith(b"RIFF") else wav_duration(data)
        if d:
            return round(d, 3)
    except OSError as e:
        log.warning("reading audio for duration failed: %s", e)
    exe = shutil.which("ffprobe")     # slow to start on Windows (~8 s); only when the header parse fails
    if exe:
        try:
            out = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
                                 capture_output=True, text=True, timeout=15)
            return round(float(json.loads(out.stdout)["format"]["duration"]), 3)
        except Exception as e:  # noqa: BLE001
            log.warning("ffprobe failed: %s", e)
    # No ffprobe: estimate from size at the ~128 kbps both vendors return for mp3.
    return round(nbytes * 8 / 128000, 3)


# ---------------------------------------------------------------- aged voice (Grandma only)
# No Sarvam or Murf voice is elderly (docs/VOICES.md), so Grandma's clips (and her fillers) are post-processed with
# ffmpeg: slightly lower, formant-preserving pitch; slower delivery with longer pauses; a slow pitch wobble
# (vibrato ~5 Hz) and a faint amplitude tremor; softer highs; a little breath noise; gentler loudness dynamics.
# GRANDMA_AGE_FX=off|subtle|strong (default strong); the tts_voice_by_language flag can override per language:
# {"hi-IN": {"grandma": {"voice": "neha", "age_fx": "subtle"}}} or {"hi-IN": {"age_fx": "off"}}.
# AGE_FX_VERSION is part of the cache key, so changing the chain re-makes every aged clip.
AGE_FX_VERSION = 2
AGE_FX_LEVELS = {
    "subtle": {"pitch": 0.98, "tempo": 0.96, "pause": 1.20, "vib_d": 0.09, "trem_d": 0.05, "lowpass": 7500,
               "shelf_db": -2.0, "breath_db": -54, "ratio": 1.4},
    "strong": {"pitch": 0.94, "tempo": 0.93, "pause": 1.45, "vib_d": 0.20, "trem_d": 0.10, "lowpass": 6000,
               "shelf_db": -5.0, "breath_db": -48, "ratio": 2.0},
}


def age_fx_level(override: Any = None) -> str:
    v = str(override if override not in (None, "") else os.environ.get("GRANDMA_AGE_FX", "strong")).strip().lower()
    if v in ("off", "none", "false", "0"):
        return "off"
    return v if v in AGE_FX_LEVELS else "strong"


def _stretch_pauses(x: np.ndarray, sr: int, factor: float) -> np.ndarray:
    """Lengthen every pause of >= 150 ms by `factor` (capped +0.5 s) by repeating its (near-silent) samples."""
    hop = int(0.01 * sr)
    n = len(x) // hop
    if n < 10 or factor <= 1.0:
        return x
    rms = np.sqrt(np.mean(x[:n * hop].astype(np.float64).reshape(n, hop) ** 2, axis=1))
    quiet = rms < max(0.02 * rms.max(), 1.0)
    out: list[np.ndarray] = []
    i = 0
    while i < n:
        j = i
        while j < n and quiet[j] == quiet[i]:
            j += 1
        seg = x[i * hop:j * hop]
        out.append(seg)
        if quiet[i] and 15 <= j - i and i > 0 and j < n:        # interior pause only
            extra = min(int(len(seg) * (factor - 1.0)), int(0.5 * sr))
            if extra > 0:
                out.append(np.resize(seg, extra))
        i = j
    out.append(x[n * hop:])
    return np.concatenate(out)


def _age_filter(c: dict) -> str:
    return (
        f"[0:a]rubberband=tempo={c['tempo']}:pitch={c['pitch']}:formant=preserved:transients=smooth,"
        f"vibrato=f=5.1:d={c['vib_d']},tremolo=f=4.4:d={c['trem_d']},"
        f"equalizer=f=220:t=q:w=1:g=1.5,lowpass=f={c['lowpass']},highshelf=f=4500:g={c['shelf_db']},"
        f"acompressor=threshold=0.09:ratio={c['ratio']}:attack=20:release=250:makeup=1.3,asplit[v1][v2];"
        f"anoisesrc=c=pink:r={SAMPLE_RATE}:a=1,highpass=f=1200,lowpass=f=6500,volume={c['breath_db']}dB[n0];"
        f"[n0][v2]sidechaingate=threshold=0.02:range=0.0:ratio=9:attack=5:release=120:level_sc=1[n];"
        f"[v1][n]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[o]")


def age_audio(audio: bytes, fmt: str, level: str) -> bytes:
    """Run Grandma's aged-voice chain over a synthesized clip. Raises on failure (callers keep the raw clip)."""
    c = AGE_FX_LEVELS[level]
    dec = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", "pipe:0", "-ac", "1", "-ar", str(SAMPLE_RATE),
                          "-f", "s16le", "pipe:1"], input=audio, capture_output=True, timeout=60, check=True).stdout
    x = _stretch_pauses(np.frombuffer(dec, dtype=np.int16), SAMPLE_RATE, c["pause"])
    codec = ["-c:a", "libmp3lame", "-b:a", "128k", "-f", "mp3"] if fmt == "mp3" else ["-c:a", "pcm_s16le", "-f", "wav"]
    enc = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1",
                          "-i", "pipe:0", "-filter_complex", _age_filter(c), "-map", "[o]", "-ar", str(SAMPLE_RATE),
                          "-ac", "1", *codec, "pipe:1"],
                         input=x.tobytes(), capture_output=True, timeout=90)
    if enc.returncode != 0:
        raise TTSError("ffmpeg aged voice: " + enc.stderr.decode(errors="ignore")[-300:])
    enc = enc.stdout
    if len(enc) < 1000:
        raise TTSError("aged voice produced no audio")
    return enc


# ---------------------------------------------------------------- loudness (every character)
# Sarvam clips came out around -23 LUFS after the aged chain (lowpass + high-shelf cut energy), noticeably quieter
# than the other characters. Every synthesized clip is now normalised to the same target, two-pass EBU R128
# (measure, then linear gain) so speech dynamics are kept. LOUDNORM_VERSION is part of the cache key.
LOUDNORM = {"I": -16.0, "TP": -1.5, "LRA": 11.0}
LOUDNORM_VERSION = 1


def normalize_loudness(audio: bytes, fmt: str) -> bytes:
    """Two-pass ffmpeg loudnorm to I=-16 LUFS, TP=-1.5 dBTP. Raises TTSError (callers keep the clip as is)."""
    base = f"loudnorm=I={LOUDNORM['I']}:TP={LOUDNORM['TP']}:LRA={LOUDNORM['LRA']}"
    m = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", "pipe:0", "-af", base + ":print_format=json",
                        "-f", "null", "-"], input=audio, capture_output=True, timeout=60)
    err = m.stderr.decode(errors="ignore")
    j = err[err.rfind("{"):err.rfind("}") + 1] if "{" in err else ""
    try:
        meas = json.loads(j)
        af = (f"{base}:measured_I={meas['input_i']}:measured_TP={meas['input_tp']}:measured_LRA={meas['input_lra']}"
              f":measured_thresh={meas['input_thresh']}:offset={meas['target_offset']}:linear=true")
        if float(meas["input_i"]) < -70:              # silence: nothing to normalise
            return audio
    except (ValueError, KeyError):
        af = base                                      # very short clip: single-pass (dynamic) is fine
    codec = ["-c:a", "libmp3lame", "-b:a", "128k", "-f", "mp3"] if fmt == "mp3" else ["-c:a", "pcm_s16le", "-f", "wav"]
    enc = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", "pipe:0", "-af", af, "-ar", str(SAMPLE_RATE),
                          "-ac", "1", *codec, "pipe:1"], input=audio, capture_output=True, timeout=90)
    if enc.returncode != 0 or len(enc.stdout) < 1000:
        raise TTSError("ffmpeg loudnorm: " + enc.stderr.decode(errors="ignore")[-300:])
    return enc.stdout


def _fx_override(by_lang: Any, language: str) -> Optional[str]:
    ov = by_lang.get(language) if isinstance(by_lang, dict) else None
    if isinstance(ov, dict):
        if ov.get("age_fx"):
            return ov["age_fx"]
        g = ov.get("grandma")
        if isinstance(g, dict) and g.get("age_fx"):
            return g["age_fx"]
    return None


def _attempt(v: Any, role: Optional[str]) -> Optional[tuple[str, str, dict]]:
    """A flag / caller voice value -> (provider, voice, params). A string is a Sarvam speaker or a Murf voice id
    (with the role's prosody when it is that role's chosen speaker); a dict is {"provider","voice","params"}."""
    if isinstance(v, dict) and v.get("voice"):
        prov = v.get("provider") or ("murf" if L.is_murf_voice(v["voice"]) else "sarvam")
        return prov, str(v["voice"]), dict(v.get("params") or {})
    if isinstance(v, str) and v.strip():
        v = v.strip()
        prov = "murf" if L.is_murf_voice(v) else "sarvam"
        params: dict = {}
        if role:
            if prov == "sarvam" and v in {p["voice"] for p in L.VOICE_PROFILES[role].values()}:
                params = dict(next(p["params"] for p in L.VOICE_PROFILES[role].values() if p["voice"] == v))
            elif prov == "murf":
                params = dict(L.MURF_PARAMS.get(role, {}))
        return prov, v, params
    return None


async def _plan(language: str, voice: Optional[str], family_id: Optional[str]) -> tuple[list[tuple[str, str, dict]], str]:
    """Ordered [(provider, voice, params)] attempts: explicit voice, flag override, the role's chosen voice
    (lang.VOICE_PROFILES, see docs/VOICES.md), then the role's Murf fallback."""
    role = voice if voice in L.ROLES else ("grandma" if not voice else None)
    override = None
    fx_override = None
    try:
        by_lang = await flags.get("tts_voice_by_language", family_id) or {}
        fx_override = _fx_override(by_lang, language)
        if isinstance(by_lang, dict):
            override = by_lang.get(language)
            if isinstance(override, dict) and role and role in override:   # {"hi-IN": {"grandma": "neha", ...}}
                override = override[role]
            elif isinstance(override, dict) and not override.get("voice"):
                override = None
    except Exception as e:  # noqa: BLE001
        log.warning("flag lookup failed: %s", e)
    plan: list[tuple[str, str, dict]] = []
    explicit = voice if voice and voice not in L.ROLES else None
    for v in (explicit, override if role else None):
        a = _attempt(v, role)
        if a:
            plan.append(a)
    r = role or "grandma"
    prof = L.VOICE_PROFILES[r][language]
    plan.append((prof["provider"], prof["voice"], dict(prof.get("params") or {})))
    plan.append(("murf", L.MURF_VOICES[r][language], dict(L.MURF_PARAMS.get(r, {}))))
    seen: set = set()
    out = []
    for p in plan:
        k = (p[0], p[1], json.dumps(p[2], sort_keys=True))
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out, (age_fx_level(fx_override) if role == "grandma" else "off")


async def synthesize(text: str, language: str, voice: str | None = None, fmt: str = "mp3",
                     family_id: str | None = None) -> dict:
    text = " ".join((text or "").split())[:MAX_CHARS]
    if not text:
        raise HTTPException(422, "Nothing to say: text is empty.")
    language = L.norm(language)
    fmt = (fmt or "mp3").lower()
    if fmt not in ("mp3", "wav"):
        raise HTTPException(422, "fmt must be mp3 or wav")
    plan, fx = await _plan(language, voice, family_id)
    role = voice if voice in L.ROLES else ("grandma" if not voice else None)
    cloned = await voice_clone.family_voice(family_id, "grandma") if role == "grandma" else None
    if cloned:                                   # the family's consented real voice: first choice, no aged-voice FX
        plan.insert(0, ("clone", cloned["voice_id"], {}))
        fx = "off"
    # Cache key uses the first choice so a later flag change re-synthesizes in the new voice.
    prosody = json.dumps(plan[0][2], sort_keys=True) if plan[0][2] else ""
    h = hashlib.sha256(f"{text}|{language}|{plan[0][0]}:{plan[0][1]}{prosody}|{fmt}{'|agefx:' + fx + ':v' + str(AGE_FX_VERSION) if fx != 'off' else ''}|ln:v{LOUDNORM_VERSION}".encode()).hexdigest()
    row = await db.fetchrow("SELECT storage_key, duration_s, provider, voice FROM tts_cache WHERE hash=$1", h)
    if row and storage.exists(row["storage_key"]):
        return {"storage_key": row["storage_key"], "url": storage.signed_url(row["storage_key"]),
                "duration_s": float(row["duration_s"]), "provider": row["provider"], "voice": row["voice"],
                "cached": True}
    errors: list[str] = []
    audio = b""
    used = plan[0]
    for provider, v, params in plan:
        try:
            if provider == "clone":
                audio = await _clone(text, language, v, fmt)
            else:
                audio = await (_sarvam if provider == "sarvam" else _murf)(text, language, v, fmt, params)
            used = (provider, v, params)
            break
        except TTSError as e:
            log.warning("tts %s/%s failed: %s", provider, v, e)
            errors.append(f"{provider}: {e}")
    if not audio:
        raise HTTPException(502, "Speech synthesis failed: " + "; ".join(errors)[:400])
    if fx != "off":
        try:
            audio = await asyncio.to_thread(age_audio, audio, fmt, fx)
        except Exception as e:  # noqa: BLE001 - keep the plain clip rather than fail the line
            log.warning("aged voice failed, using the plain clip: %s", str(e)[:200])
    try:
        audio = await asyncio.to_thread(normalize_loudness, audio, fmt)
    except Exception as e:  # noqa: BLE001 - a quieter clip is better than no clip
        log.warning("loudness normalisation failed, keeping the clip as is: %s", str(e)[:200])
    key = f"tts/{h[:2]}/{h}.{fmt}"
    storage.put(key, audio)
    dur = await asyncio.to_thread(_duration, str(storage.path(key)), len(audio))
    await db.execute(
        "INSERT INTO tts_cache(hash, storage_key, duration_s, provider, voice, language) VALUES ($1,$2,$3,$4,$5,$6) "
        "ON CONFLICT (hash) DO UPDATE SET storage_key=EXCLUDED.storage_key, duration_s=EXCLUDED.duration_s",
        h, key, dur, used[0], used[1], language)
    return {"storage_key": key, "url": storage.signed_url(key), "duration_s": dur, "provider": used[0],
            "voice": used[1], "cached": False}


def _mp3_frames(data: bytes) -> tuple[list[bytes], set]:
    """Audio frames of an mp3 (ID3 and Xing/Info/VBRI header frames dropped) and the set of sample rates seen."""
    i = 0
    if data[:3] == b"ID3" and len(data) > 10:
        i = 10 + ((data[6] & 0x7F) << 21 | (data[7] & 0x7F) << 14 | (data[8] & 0x7F) << 7 | (data[9] & 0x7F))
    frames: list[bytes] = []
    rates: set = set()
    n = len(data)
    while i + 4 <= n:
        b1, b2 = data[i + 1], data[i + 2]
        if data[i] != 0xFF or (b1 & 0xE0) != 0xE0:
            i += 1
            continue
        ver, layer = (b1 >> 3) & 3, (b1 >> 1) & 3
        br_i, sr_i, pad = (b2 >> 4) & 0xF, (b2 >> 2) & 3, (b2 >> 1) & 1
        if ver == 1 or layer != 1 or br_i in (0, 15) or sr_i == 3:
            i += 1
            continue
        v1 = ver == 3
        sr = _MP3_RATES[ver][sr_i]
        flen = (144 if v1 else 72) * _MP3_BITRATES[v1][br_i] * 1000 // sr + pad
        if flen < 4:
            i += 1
            continue
        fr = data[i:i + flen]
        if not any(tag in fr[:64] for tag in (b"Xing", b"Info", b"VBRI")):
            frames.append(fr)
            rates.add(sr)
        i += flen
    return frames, rates


async def concat(keys: list[str]) -> Optional[dict]:
    """One mp3 track from several cached clips, joined frame by frame in Python (spawning ffmpeg costs seconds on
    Windows). None when the clips differ in sample rate; the client then plays the per-sentence clips."""
    if not keys:
        return None
    if len(keys) == 1:
        return {"storage_key": keys[0], "url": storage.signed_url(keys[0])}
    h = hashlib.sha256("|".join(keys).encode()).hexdigest()
    key = f"tts/joined/{h}.mp3"
    if not storage.exists(key):
        def build() -> bool:
            out: list[bytes] = []
            rates: set = set()
            for k in keys:
                fr, r = _mp3_frames(storage.get(k))
                out += fr
                rates |= r
            if len(rates) != 1 or not out:
                return False
            storage.put(key, b"".join(out))
            return True
        if not await asyncio.to_thread(build):
            log.warning("concat skipped: clips have different sample rates")
            return None
    return {"storage_key": key, "url": storage.signed_url(key)}
