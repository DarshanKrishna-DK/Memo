"""Measure candidate TTS voices objectively: median F0 (YIN), pitch spread and speaking rate.

    .venv/Scripts/python scripts/voice_measure.py candidates [lang ...]   # every female candidate, default params
    .venv/Scripts/python scripts/voice_measure.py final                   # the chosen character voices (lang.VOICE_PROFILES)

Each clip is synthesized live (Sarvam bulbul / Murf Falcon), decoded with ffmpeg to 16 kHz mono PCM, and measured:
  f0_med   median fundamental frequency over voiced frames (YIN, 70-400 Hz, threshold 0.15)
  f0_sd_st spread of F0 in semitones (how much the voice moves; flat = robotic, wide = lively)
  wps      words per second over the speech span (leading/trailing silence trimmed)
Results are printed as a table and saved as JSON next to this script (voice_measure_<mode>.json).
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT.parent / ".env.local")

from app.ai import tts  # noqa: E402
from app.voice import lang as L  # noqa: E402

SR = 16000
SENT = {
    "en-IN": "Arre, you remember that Diwali? Your father lit every single lamp on the terrace, and then he burnt "
             "his finger, poor thing. We laughed so much that night.",
    "hi-IN": "अरे, तुम्हें वो दिवाली याद है? तुम्हारे पापा ने छत पर हर एक दीया जलाया था, और फिर अपनी उँगली जला ली, "
             "बेचारे। उस रात हम सब बहुत हँसे थे।",
    "kn-IN": "ಅಯ್ಯೋ, ಆ ದೀಪಾವಳಿ ನೆನಪಿದೆಯಾ? ನಿಮ್ಮಪ್ಪ ತಾರಸಿ ಮೇಲೆ ಎಲ್ಲಾ ದೀಪ ಹಚ್ಚಿದ್ರು, ಆಮೇಲೆ ಬೆರಳು ಸುಟ್ಕೊಂಡ್ರು, ಪಾಪ. "
             "ಆ ರಾತ್ರಿ ನಾವೆಲ್ಲ ತುಂಬಾ ನಕ್ಕಿದ್ವಿ.",
}

V3_FEMALE = ["ritu", "priya", "neha", "pooja", "simran", "kavya", "ishita", "shreya", "roopa", "tanya", "shruti",
             "suhani", "kavitha", "rupali"]
V4_FEMALE = {
    "en-IN": ["aditi_en_stories", "chandrika_en_stories", "roopa_en_conversational", "zarina_en_conversation",
              "shabana_en_edtech", "aparna_en_companion", "shalini_en_companion", "sanchita_en_companion",
              "ishita_en_stories", "neha_en_latenight", "ritu_en_latenight", "simran_en_narration"],
    "hi-IN": ["roopa_hi_narration", "roopa_hi_companion", "roopa_hi_conversational", "shilpa_hi_narration",
              "tanya_hi_narration", "sarika_hi_conversation", "suman_hi_companion", "vandana_hi_ecomm",
              "shalini_hi_companion", "simran_hi_narration", "ishita_hi_devotional", "aarti_hi_customer",
              "ritu_hi_conversation", "ritu_hi_customer_warm"],
    "kn-IN": ["chaitra_kn_conversation", "chaitra_kn_narration", "suchitra_kn_narration"],
}
MURF_FEMALE = {
    "en-IN": ["hi-IN-poonam", "hi-IN-neeta", "en-IN-anisha", "hi-IN-jaya", "hi-IN-rachna", "en-IN-pooja",
              "en-IN-anusha", "en-IN-priya", "ml-IN-nimisha"],
    "hi-IN": ["hi-IN-khyati", "hi-IN-poonam", "hi-IN-neeta", "hi-IN-jaya", "hi-IN-shweta", "hi-IN-rachna",
              "hi-IN-namrita", "en-IN-alia", "bn-IN-ishani", "hi-IN-ayushi", "en-IN-anisha", "en-IN-pooja"],
    "kn-IN": ["kn-IN-harshitha", "hi-IN-poonam", "hi-IN-neeta", "hi-IN-jaya", "hi-IN-rachna", "hi-IN-namrita",
              "en-IN-pooja"],
}


def decode(data: bytes) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-ac", "1", "-ar", str(SR), "-f", "s16le", "pipe:1"],
                         input=data, capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.int16).astype(np.float32) / 32768.0


def yin(x: np.ndarray, fmin: float = 70, fmax: float = 400, frame: int = 1024, hop: int = 160,
        thresh: float = 0.15) -> np.ndarray:
    tmin, tmax = int(SR / fmax), int(SR / fmin)
    f0, aper = [], []
    rms_all = np.sqrt(np.mean(x ** 2)) + 1e-9
    starts = [s for s in range(0, len(x) - frame - tmax, hop)
              if np.sqrt(np.mean(x[s:s + frame] ** 2)) >= 0.15 * rms_all]
    if not starts:
        return np.array([])
    W = np.stack([x[s:s + frame + tmax] for s in starts])            # frames x (frame + tmax)
    A = W[:, :frame]
    nfft = 1 << int(np.ceil(np.log2(frame + tmax + frame)))
    cross = np.fft.irfft(np.fft.rfft(W, nfft) * np.conj(np.fft.rfft(A, nfft)), nfft)[:, :tmax + 1]
    sq = np.concatenate([np.zeros((len(W), 1)), np.cumsum(W ** 2, axis=1)], axis=1)
    taus = np.arange(tmax + 1)
    e_shift = sq[:, taus + frame] - sq[:, taus]
    D = (A ** 2).sum(1, keepdims=True) + e_shift - 2 * cross        # YIN difference function, all frames at once
    for d in D:
        cmnd = np.ones_like(d)
        cs = np.cumsum(d[1:])
        cmnd[1:] = d[1:] * np.arange(1, tmax + 1) / np.maximum(cs, 1e-12)
        tau = None
        for t in range(tmin, tmax):
            if cmnd[t] < thresh:
                while t + 1 < tmax and cmnd[t + 1] < cmnd[t]:
                    t += 1
                tau = t
                break
        if tau is None:
            continue
        # parabolic interpolation
        if 1 <= tau < tmax:
            s0, s1, s2 = cmnd[tau - 1], cmnd[tau], cmnd[tau + 1]
            den = s0 + s2 - 2 * s1
            aper.append(float(s1))
            tau = tau + (0.5 * (s0 - s2) / den if den else 0)
        f0.append(SR / tau)
    yin.aper = np.array(aper)       # aperiodicity per voiced frame (higher = breathier / noisier voicing)
    return np.array(f0)


def speech_span(x: np.ndarray) -> float:
    win = int(0.02 * SR)
    n = len(x) // win
    if n == 0:
        return 0.0
    e = np.sqrt(np.mean(x[:n * win].reshape(n, win) ** 2, axis=1))
    on = np.where(e > 0.05 * e.max())[0]
    return (on[-1] - on[0] + 1) * win / SR if len(on) else 0.0


def measure(audio: bytes, words: int) -> dict:
    x = decode(audio)
    f0 = yin(x)
    span = speech_span(x)
    med = float(np.median(f0)) if len(f0) else 0.0
    sd = float(np.std(12 * np.log2(f0 / med))) if len(f0) and med else 0.0
    p10, p90 = (np.percentile(f0, [10, 90]) if len(f0) else (0, 0))
    ap = float(np.median(yin.aper)) if len(getattr(yin, "aper", [])) else 0.0
    return {"f0_med": round(med, 1), "f0_p10": round(float(p10), 1), "f0_p90": round(float(p90), 1),
            "aper": round(ap, 3), "f0_sd_st": round(sd, 2), "wps": round(words / span, 2) if span else 0.0,
            "span_s": round(span, 2), "voiced_frames": int(len(f0))}


async def synth(provider: str, voice: str, lang: str, text: str, params: dict) -> bytes:
    if provider == "sarvam":
        return await tts._sarvam(text, lang, voice, "mp3", params)
    return await tts._murf(text, lang, voice, "mp3", params)


def words_of(text: str) -> int:
    return len(text.split())


async def run(cands: list[tuple[str, str, str, dict]], tag: str) -> list[dict]:
    sem = asyncio.Semaphore(2)
    rows: list[dict] = []

    async def one(lang: str, provider: str, voice: str, params: dict) -> None:
        async with sem:
            try:
                audio = await synth(provider, voice, lang, SENT[lang], params)
                m = await asyncio.to_thread(measure, audio, words_of(SENT[lang]))
                rows.append({"lang": lang, "provider": provider, "voice": voice, "params": params, **m})
            except Exception as e:  # noqa: BLE001
                rows.append({"lang": lang, "provider": provider, "voice": voice, "params": params,
                             "error": str(e)[:160]})

    await asyncio.gather(*(one(*c) for c in cands))
    rows.sort(key=lambda r: (r["lang"], r.get("f0_med", 999)))
    for r in rows:
        if "error" in r:
            print(f"{r['lang']} {r['provider']:6} {r['voice']:26} ERROR {r['error']}")
        else:
            print(f"{r['lang']} {r['provider']:6} {r['voice']:26} {json.dumps(r['params']):38} F0 {r['f0_med']:6.1f} Hz  "
                  f"[{r['f0_p10']:.0f}-{r['f0_p90']:.0f}]  sd {r['f0_sd_st']:4.2f} st  aper {r['aper']:.3f}  {r['wps']:4.2f} w/s")
    (Path(__file__).parent / f"voice_measure_{tag}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                                                                    encoding="utf-8")
    return rows


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "candidates"
    langs = (sys.argv[2:] if mode in ("candidates", "final") else []) or list(SENT)
    cands: list[tuple[str, str, str, dict]] = []
    if mode == "candidates":
        for lg in langs:
            cands += [(lg, "sarvam", v, {"model": "bulbul:v3"}) for v in V3_FEMALE]
            cands += [(lg, "sarvam", v, {"model": "bulbul:v4-flash"}) for v in V4_FEMALE[lg]]
            cands += [(lg, "murf", v, {}) for v in MURF_FEMALE[lg]]
    elif mode == "final":
        for role in L.VOICE_PROFILES:
            for lg in langs:
                p = L.VOICE_PROFILES[role][lg]
                for _ in range(2):          # two takes: bulbul samples (temperature), so one clip can mislead
                    cands.append((lg, p["provider"], p["voice"], p.get("params", {})))
        for lg in langs:                    # Grandma's Murf fallback, for comparison
            cands.append((lg, "murf", L.MURF_VOICES["grandma"][lg], L.MURF_PARAMS["grandma"]))
    else:   # ad hoc specs: provider:voice:lang[:k=v,k=v] ...
        for spec in sys.argv[2:]:
            provider, voice, lg, *rest = spec.split(":")
            params = {}
            for kv in (rest[0].split(",") if rest and rest[0] else []):
                k, v = kv.split("=")
                try:
                    params[k] = int(v) if provider == "murf" and k in ("rate", "pitch") else float(v)
                except ValueError:
                    params[k] = v
            cands.append((lg, provider, voice, params))
        mode = "adhoc"
    asyncio.run(run(cands, mode))


if __name__ == "__main__":
    main()
