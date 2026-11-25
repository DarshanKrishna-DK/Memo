"""Scan every Sarvam bulbul:v4-flash persona of a language (+ all bulbul:v3 speakers) with the voice_measure
metrics plus jitter and spectral centroid. Clips go to a scratch dir; shortlist is copied to data/voice-samples/personas.

    .venv/Scripts/python scripts/voice_persona_scan.py <outdir>
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT.parent / ".env.local")
import numpy as np  # noqa: E402
import voice_measure as vm  # noqa: E402
from app.ai import tts  # noqa: E402

V3 = "shubh aditya ritu priya neha rahul pooja rohan simran kavya amit dev ishita shreya ratan varun manan sumit roopa kabir aayan ashutosh advait anand tanya tarun sunny mani gokul vijay shruti suhani mohit kavitha rehan soham rupali".split()
PERS = json.loads((Path(__file__).parent / "sarvam_personas.json").read_text(encoding="utf-8"))
SUFFIX = {"en-IN": ["en"], "hi-IN": ["hi", "enhi"], "kn-IN": ["kn"]}


def measure_file(path: str, lg: str) -> dict:
    audio = Path(path).read_bytes()
    x = vm.decode(audio)
    f0 = vm.yin(x)
    med = float(np.median(f0)) if len(f0) else 0
    st = 12 * np.log2(f0 / med) if med else np.array([0.0])
    sp = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    fr = np.fft.rfftfreq(len(x), 1 / vm.SR)
    m = vm.measure(audio, vm.words_of(vm.SENT[lg]))
    m.update(centroid=round(float((fr * sp).sum() / sp.sum())), jitter=round(float(np.median(np.abs(np.diff(st)))), 3))
    return m


async def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(4)
    jobs = []

    async def one(lg, model, spk):
        f = out / f"{lg}__{model.split(':')[1]}__{spk}.mp3"
        if f.exists():
            return (lg, model, spk, str(f), None)
        async with sem:
            for _ in range(3):
                try:
                    f.write_bytes(await tts._sarvam(vm.SENT[lg], lg, spk, "mp3", {"model": model, "pace": 0.85, "temperature": 0.5}))
                    return (lg, model, spk, str(f), None)
                except Exception as e:  # noqa: BLE001
                    err = str(e)[:100]
                    await asyncio.sleep(2)
            return (lg, model, spk, str(f), err)

    for lg in vm.SENT:
        jobs += [one(lg, "bulbul:v3", v) for v in V3]
        jobs += [one(lg, "bulbul:v4-flash", p) for p in PERS if p.split("_")[1] in SUFFIX[lg]]
    res = await asyncio.gather(*jobs)
    print("synth done", sum(r[4] is not None for r in res), "errors", flush=True)
    from concurrent.futures import ProcessPoolExecutor
    ok = [r for r in res if r[4] is None]
    with ProcessPoolExecutor(max_workers=6) as ex:
        ms = list(ex.map(measure_file, [r[3] for r in ok], [r[0] for r in ok]))
    rows = [{"lang": r[0], "model": r[1], "voice": r[2], **m} for r, m in zip(ok, ms)]
    rows += [{"lang": r[0], "model": r[1], "voice": r[2], "error": r[4]} for r in res if r[4]]
    (out / "scan.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(rows), "rows", flush=True)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
