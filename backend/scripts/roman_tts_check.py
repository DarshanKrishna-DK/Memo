"""Does Sarvam read Roman-script Hinglish / Kanglish as well as native script? Synthesize both spellings of the same
line, transcribe each back with Sarvam STT (native script), and compare the transcripts to the native reference
(character similarity). Run: .venv/Scripts/python scripts/roman_tts_check.py [speaker]"""
from __future__ import annotations

import asyncio
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT.parent / ".env.local")
from app.ai import stt, tts  # noqa: E402

PAIRS = [
    ("hi-IN", "Arre, tumhe woh Diwali yaad hai? Tumhare papa ne chhat pe saare diye jalaaye the.",
     "अरे, तुम्हें वो दिवाली याद है? तुम्हारे पापा ने छत पे सारे दिये जलाए थे।"),
    ("hi-IN", "Achha, kaunsa mahina aur saal tha?", "अच्छा, कौन सा महीना और साल था?"),
    ("kn-IN", "Sari, yaava tingalu, yaava varsha?", "ಸರಿ, ಯಾವ ತಿಂಗಳು, ಯಾವ ವರ್ಷ?"),
    ("kn-IN", "Nodu, aa Deepavali nenapideya? Nimmappa ella deepa hachchidru.",
     "ನೋಡು, ಆ ದೀಪಾವಳಿ ನೆನಪಿದೆಯಾ? ನಿಮ್ಮಪ್ಪ ಎಲ್ಲಾ ದೀಪ ಹಚ್ಚಿದ್ರು."),
]


def sim(a: str, b: str) -> float:
    norm = lambda s: "".join(ch for ch in s if ch.isalnum())  # noqa: E731
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


async def main() -> None:
    speaker = sys.argv[1] if len(sys.argv) > 1 else "kavitha"
    for lang, roman, native in PAIRS:
        for label, text in (("roman", roman), ("native", native)):
            audio = await tts._sarvam(text, lang, speaker, "mp3", {})
            tr = await stt.transcribe(audio, "audio/mpeg", lang)
            print(f"{lang} {label:6} sim={sim(tr['text'], native):.2f}  heard: {tr['text']}")


asyncio.run(main())
