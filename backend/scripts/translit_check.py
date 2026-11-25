"""Does transliterating Roman Hinglish/Kanglish to native script (Sarvam /transliterate) before TTS help?
Measure by STT round trip: similarity of the STT transcript to the transliterated native-script text, and F0/pace."""
from __future__ import annotations
import asyncio, difflib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv
load_dotenv(ROOT.parent / ".env.local")
import httpx, os
from app.ai import stt, tts
from app.voice import lang as L

CASES = [
 ("hi-IN", "Arre beta, tumhe woh Diwali yaad hai? Papa ne chhat par saare diye jalaye the aur phir apni ungli jala li."),
 ("hi-IN", "Achha, ek minute ruko, main yaad karti hoon. Haan, woh Mysore wali trip, jab sab log bus mein gaane gaa rahe the."),
 ("hi-IN", "Kal shaam ko tumhari Nani ka phone aaya tha, bol rahi thi ki is Sunday ghar aao."),
 ("kn-IN", "Ayyo, ninage aa Deepavali nenapide? Appa terrace mele ella deepa hachchidru, aamele bere sutkondru, paapa."),
 ("kn-IN", "Nodu, ond nimisha, nenapu maadkothini. Aa Mysore trip alli ellaru haadu haadtha iddaru."),
]

async def translit(text, lg):
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("https://api.sarvam.ai/transliterate", headers={"api-subscription-key": os.environ["SARVAM_API_KEY"]},
                         json={"input": text, "source_language_code": "en-IN", "target_language_code": lg, "spoken_form": True})
    r.raise_for_status()
    return r.json()["transliterated_text"]

def sim(a, b):
    n = lambda t: "".join(ch for ch in t.lower() if ch.isalnum())
    return round(difflib.SequenceMatcher(None, n(a), n(b)).ratio(), 3)

async def main():
    p = L.VOICE_PROFILES["grandma"]["hi-IN"]
    out = []
    for lg, roman in CASES:
        native = await translit(roman, lg)
        row = {"lang": lg, "roman": roman, "native": native}
        for tag, txt in (("roman", roman), ("native", native)):
            a = await tts._sarvam(txt, lg, p["voice"], "mp3", p["params"])
            t = (await stt.transcribe(a, "audio/mpeg", lg))["text"]
            row[tag + "_stt"] = t
            row[tag + "_sim_to_native"] = sim(t, native)
        print(json.dumps(row, ensure_ascii=False)); out.append(row)
    for lg in ("hi-IN", "kn-IN"):
        rs = [r for r in out if r["lang"] == lg]
        print(lg, "mean sim roman->native", round(sum(r["roman_sim_to_native"] for r in rs)/len(rs), 3),
              "native", round(sum(r["native_sim_to_native"] for r in rs)/len(rs), 3))
asyncio.run(main())
