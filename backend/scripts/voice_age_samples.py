"""Make before/after Grandma samples + measure them + STT round trip.

    .venv/Scripts/python scripts/voice_age_samples.py            # writes data/voice-samples/, prints a table
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT.parent / ".env.local")
import difflib  # noqa: E402

import numpy as np  # noqa: E402

import voice_measure as vm  # noqa: E402
from app.ai import stt, tts  # noqa: E402
from app.voice import lang as L  # noqa: E402

OUT = ROOT.parent / "data" / "voice-samples"
SHORT = {"en-IN": "en", "hi-IN": "hi", "kn-IN": "kn"}


def centroid(audio: bytes) -> float:
    import numpy as np
    x = vm.decode(audio)
    sp = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / vm.SR)
    return float((f * sp).sum() / sp.sum()), float(sp[f > 4000].sum() / sp.sum())


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for lg in vm.SENT:
        p = L.VOICE_PROFILES["grandma"][lg]
        raw = await tts._sarvam(vm.SENT[lg], lg, p["voice"], "mp3", p["params"])
        variants = {"before": raw}
        for lvl in ("subtle", "strong"):
            variants["after-" + lvl] = await asyncio.to_thread(tts.age_audio, raw, "mp3", lvl)
        for name, audio in variants.items():
            fn = f"grandma-{SHORT[lg]}-{name}.mp3"
            (OUT / fn).write_bytes(audio)
            m = vm.measure(audio, vm.words_of(vm.SENT[lg]))
            c, hf = centroid(audio)
            m["centroid_hz"], m["hf4k_ratio"] = round(c), round(hf, 5)
            f0 = vm.yin(vm.decode(audio))
            st = 12 * np.log2(f0 / np.median(f0))
            m["jitter_st"] = round(float(np.median(np.abs(np.diff(st)))), 3)     # frame-to-frame pitch wobble
            try:
                r = await stt.transcribe(audio, "audio/mpeg", lg)
                text = r["text"] if isinstance(r, dict) else str(r)
                m["stt_sim"] = round(difflib.SequenceMatcher(None, "".join(vm.SENT[lg].split()).lower(), "".join(text.split()).lower()).ratio(), 3)
            except Exception as e:  # noqa: BLE001
                m["stt_error"] = str(e)[:120]
            m["dur_s"] = round(len(vm.decode(audio)) / vm.SR, 2)
            rows.append({"lang": lg, "variant": name, **m})
            print(lg, name, json.dumps(m))
    (OUT / "measurements.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


asyncio.run(main())
