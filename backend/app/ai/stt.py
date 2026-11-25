"""Speech-to-text via Sarvam REST (verified docs.sarvam.ai 2026-11: POST /speech-to-text, header
`api-subscription-key`, multipart `file`, `model` saaras:v4, `language_code` "unknown" = auto-detect).
The REST endpoint is meant for clips under ~30 s, so audio is converted with ffmpeg to 16 kHz mono wav and cut
into 25 s chunks (voice notes up to ~10 min are handled); chunk transcripts are joined in order.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
import wave
from collections import Counter
from pathlib import Path

import httpx

from ..observability import nudgebee

from .. import config

log = logging.getLogger("memo.stt")
URL = "https://api.sarvam.ai/speech-to-text"
CHUNK_S = 25
MAX_AUDIO_S = 600


class SttError(Exception):
    pass


async def _ffmpeg_chunks(audio: bytes, mime: str, workdir: Path) -> list[Path]:
    m = (mime or "audio/ogg").lower()
    ext = ".ogg" if ("ogg" in m or "opus" in m) else "." + m.split("/")[-1].split(";")[0]
    src = workdir / f"in{ext}"
    src.write_bytes(audio)
    out = workdir / "c_%03d.wav"
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-v", "error", "-i", str(src), "-t", str(MAX_AUDIO_S), "-vn", "-ac", "1", "-ar", "16000",
        "-f", "segment", "-segment_time", str(CHUNK_S), "-reset_timestamps", "1", str(out),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise SttError(f"ffmpeg failed: {err.decode(errors='ignore')[:300]}")
    chunks = sorted(workdir.glob("c_*.wav"))
    if not chunks:
        raise SttError("ffmpeg produced no audio")
    return chunks


def _wav_seconds(p: Path) -> float:
    with wave.open(str(p), "rb") as w:
        return w.getnframes() / float(w.getframerate())


async def _one(client: httpx.AsyncClient, key: str, wav: Path, language: str | None) -> dict:
    data = {"model": config.env("STT_MODEL", "saaras:v4"), "mode": "transcribe",
            "language_code": language or "unknown"}
    last = ""
    for attempt in range(3):
        files = {"file": (wav.name, wav.read_bytes(), "audio/wav")}
        try:
            r = await client.post(URL, headers={"api-subscription-key": key}, data=data, files=files)
        except httpx.HTTPError as e:
            last = type(e).__name__
            nudgebee.record_provider_error("sarvam", "network")
        else:
            nudgebee.record_http("sarvam", r.status_code)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code not in (429, 500, 502, 503):
                break
        await asyncio.sleep(1.5 * (attempt + 1))
    raise SttError(f"Sarvam speech-to-text failed ({last})")


async def transcribe(audio: bytes, mime: str, language: str | None = None) -> dict:
    """-> {"text", "language", "duration_s"}. language: BCP-47 hint (en-IN/hi-IN/kn-IN) or None for auto-detect."""
    key = config.env("SARVAM_API_KEY")
    if not key:
        raise SttError("SARVAM_API_KEY is not set")
    with tempfile.TemporaryDirectory(prefix="memo_stt_") as d:
        chunks = await _ffmpeg_chunks(audio, mime, Path(d))
        durations = [_wav_seconds(c) for c in chunks]
        sem = asyncio.Semaphore(3)
        async with httpx.AsyncClient(timeout=60.0) as client:
            async def go(c: Path, dur: float):
                if dur < 0.3:
                    return {"transcript": "", "language_code": None}
                async with sem:
                    return await _one(client, key, c, language)
            results = await asyncio.gather(*(go(c, du) for c, du in zip(chunks, durations)))
    text = " ".join((r.get("transcript") or "").strip() for r in results).strip()
    langs = Counter(r.get("language_code") for r in results
                    if r.get("language_code") and (r.get("transcript") or "").strip())
    return {"text": text, "language": langs.most_common(1)[0][0] if langs else language,
            "duration_s": round(sum(durations), 2)}
