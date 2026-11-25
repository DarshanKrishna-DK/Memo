"""Languages for Memo's voices (en-IN, hi-IN, kn-IN): voices per character, fillers, scripted lines,
spoken templates, month names and number words. Ported and trimmed from MedSim backend/lang.py.

Every user-facing line the server writes from facts lives here, in all three languages, so the
receptionist, Grandma and the guide robot speak the session language (PRD V12).
"""
from __future__ import annotations

import re
from typing import Any, Optional

LANGS = ("en-IN", "hi-IN", "kn-IN")
SHORT = {"en-IN": "en", "hi-IN": "hi", "kn-IN": "kn"}
NAMES = {"en-IN": "English", "hi-IN": "Hindi", "kn-IN": "Kannada"}


def norm(value: Optional[str]) -> str:
    """'hi', 'hi-IN', 'HI', 'Hindi' -> 'hi-IN'. Unknown -> 'en-IN'."""
    v = (value or "").strip().lower()
    if v.startswith("hi") or v in ("हिंदी", "हिन्दी"):
        return "hi-IN"
    if v.startswith("kn") or v.startswith("kannada") or v.startswith("kanglish") or v == "ಕನ್ನಡ":
        return "kn-IN"
    return "en-IN"


# ---------------------------------------------------------------- voices
# Sarvam bulbul:v3 speakers (docs.sarvam.ai text-to-speech, verified 2026-11-24; v3 speakers are
# shared across all languages). Murf Falcon voices verified in MedSim (each lists the locale).
SARVAM_MODEL = "bulbul:v3"

# Chosen voice per character and language, with prosody (docs/VOICES.md has the brief and the measurements:
# median F0 by YIN, words per second, from scripts/voice_measure.py). One Sarvam bulbul:v3 speaker per character is
# shared by all three languages, so a character keeps the same voice when the session language (or a Hinglish
# reply) switches. Sarvam params: pace 0.5-2.0, pitch -0.5..0.5, loudness, temperature (expressiveness).
# The `tts_voice_by_language` flag still overrides any of these per language.
def _same(provider: str, voice: str, **params: Any) -> dict[str, dict]:
    return {lg: {"provider": provider, "voice": voice, "params": dict(params)} for lg in LANGS}


VOICE_PROFILES: dict[str, dict[str, dict]] = {
    # warm Indian grandmother in her 70s: lowest, slowest female bulbul:v3 voice, slowed and lowered a touch
    "grandma": _same("sarvam", "neha", pace=0.85, pitch=-0.15, temperature=0.5),
    # friendly, crisp, upbeat, mid-pitch
    "receptionist": _same("sarvam", "priya", pace=1.05, temperature=0.6),
    # cheerful, bright robot, short lines
    "guide": _same("sarvam", "rohan", pace=1.1, temperature=0.7),
    # polite, clear, measured phone agent
    "phone": _same("sarvam", "advait", pace=0.92, temperature=0.45),
}
SARVAM_VOICES = {r: {lg: p["voice"] for lg, p in v.items()} for r, v in VOICE_PROFILES.items()}
# Murf Falcon fallback per character (live voice list, 2026-11-24; each lists the locale). Grandma uses the two
# "Middle-Aged" / lowest-F0 female voices Murf has; Murf has no voice labelled older than middle-aged.
MURF_VOICES = {
    "grandma": {"en-IN": "en-IN-alia", "hi-IN": "bn-IN-ishani", "kn-IN": "hi-IN-namrita"},
    "receptionist": {"en-IN": "en-IN-priya", "hi-IN": "en-IN-priya", "kn-IN": "en-IN-pooja"},
    "guide": {"en-IN": "en-IN-aarav", "hi-IN": "en-IN-aarav", "kn-IN": "en-IN-nikhil"},
    "phone": {"en-IN": "en-IN-aarav", "hi-IN": "en-IN-aarav", "kn-IN": "en-IN-nikhil"},
}
MURF_PARAMS = {   # Murf rate / pitch are -50..50
    "grandma": {"rate": -20, "pitch": -8},
    "receptionist": {"rate": 0, "pitch": 0},
    "guide": {"rate": 5, "pitch": 5},
    "phone": {"rate": -5, "pitch": 0},
}
ROLES = tuple(VOICE_PROFILES)


def is_murf_voice(v: str) -> bool:
    return bool(re.match(r"^[a-z]{2}-[A-Z]{2}-[a-z]+$", v or ""))


def sarvam_model_for(speaker: str) -> str:
    """bulbul:v4-flash personas are named <name>_<lang>_<style>; plain names are bulbul:v3 speakers."""
    return "bulbul:v4-flash" if "_" in (speaker or "") else SARVAM_MODEL


# ---------------------------------------------------------------- fillers / failure (Agora)
FILLERS = {
    "en-IN": ["Hmm...", "Let me see...", "One moment...", "Achha...", "Umm..."],
    "hi-IN": ["हम्म...", "एक मिनट...", "अच्छा...", "देखती हूँ..."],
    "kn-IN": ["ಹ್ಮ್...", "ಒಂದು ನಿಮಿಷ...", "ಸರಿ...", "ನೋಡ್ತೀನಿ..."],
}
# Short "thinking" clips per character, pre-synthesized and cached (GET /api/voice/fillers): the client plays one
# when a reply takes longer than ~700 ms, so the character never goes silent. Keys: language or register.
FILLER_LINES = {
    "grandma": {
        "en-IN": ["Hmm, let me think...", "Achha... one second.", "Oh, wait, let me remember...", "Hmm...",
                  "You know... let me see."],
        "hi-IN": ["हम्म, सोचने दो...", "अच्छा... एक मिनट।", "अरे, याद करने दो...", "देखो... हम्म।"],
        "kn-IN": ["ಹ್ಮ್, ಒಂದ್ನಿಮಿಷ...", "ನೋಡು... ನೆನಪು ಮಾಡ್ಕೊಳ್ತೀನಿ.", "ಅಯ್ಯೋ, ತಾಳು...", "ಹ್ಮ್ ಸರಿ..."],
        "hinglish": ["Hmm, sochne do...", "Achha... ek minute.", "Arre, yaad karne do...", "Dekho... hmm."],
        "kanglish": ["Hmm, ondu nimisha...", "Nodu... nenapu maadkothini.", "Ayyo, taalu...", "Hmm sari..."],
    },
    "receptionist": {
        "en-IN": ["Sure, one sec!", "Let me check...", "Okay, checking...", "Hmm, one moment."],
        "hi-IN": ["एक सेकंड!", "देखती हूँ...", "अच्छा, चेक करती हूँ..."],
        "kn-IN": ["ಒಂದ್ ಸೆಕೆಂಡ್!", "ನೋಡ್ತೀನಿ...", "ಸರಿ, ಚೆಕ್ ಮಾಡ್ತೀನಿ..."],
        "hinglish": ["Ek second!", "Dekhti hoon...", "Achha, check karti hoon..."],
        "kanglish": ["Ondu second!", "Nodtini...", "Sari, check maadtini..."],
    },
}


def filler_lines(character: str, lang_or_register: str) -> tuple[list[str], str, str]:
    """-> (lines, voice language, register) for a character; register 'hinglish' / 'kanglish' or a language."""
    rows = FILLER_LINES["grandma" if character not in FILLER_LINES else character]
    key = lang_or_register if lang_or_register in ("hinglish", "kanglish") else norm(lang_or_register)
    voice_lang = "hi-IN" if key == "hinglish" else "kn-IN" if key == "kanglish" else key
    return rows[key], voice_lang, key


FAILURE = {
    "en-IN": "Hmm, sorry, say that once more?",
    "hi-IN": "हम्म, माफ़ कीजिए, एक बार फिर से कहेंगे?",
    "kn-IN": "ಹ್ಮ್, ಕ್ಷಮಿಸಿ, ಇನ್ನೊಮ್ಮೆ ಹೇಳ್ತೀರಾ?",
}

# ---------------------------------------------------------------- guide robot (scripted, no model)
# The word for Grandma inside the locked-door line; replaced with the family's chosen Grandma name.
GRANDMA_DEFAULTS = {"en-IN": "Grandma", "hi-IN": "दादी", "kn-IN": "ಅಜ್ಜಿ"}
GUIDE_LINES = {
    "follow_me": {"en-IN": "Follow me.", "hi-IN": "मेरे पीछे आइए।", "kn-IN": "ನನ್ನ ಹಿಂದೆ ಬನ್ನಿ."},
    "to_lift": {"en-IN": "This way to the lift.", "hi-IN": "लिफ़्ट इस तरफ़ है।", "kn-IN": "ಲಿಫ್ಟ್ ಈ ಕಡೆ ಇದೆ."},
    "here_we_are": {"en-IN": "Here we are.", "hi-IN": "लीजिए, हम पहुँच गए।", "kn-IN": "ಇಲ್ಲಿದ್ದೇವೆ, ಬಂದೆವು."},
    "locked_door": {
        "en-IN": "This door is shut. Read the board, and tell Grandma on Telegram to open it.",
        "hi-IN": "यह दरवाज़ा बंद है। बोर्ड पढ़िए, और टेलीग्राम पर दादी को बताइए ताकि यह खुल सके।",
        "kn-IN": "ಈ ಬಾಗಿಲು ಮುಚ್ಚಿದೆ. ಬೋರ್ಡ್ ಓದಿ, ಮತ್ತು ತೆರೆಯಲು ಟೆಲಿಗ್ರಾಮ್‌ನಲ್ಲಿ ಅಜ್ಜಿಗೆ ಹೇಳಿ.",
    },
    "enjoy": {"en-IN": "Enjoy the room. I'll wait by the door.", "hi-IN": "कमरे का आनंद लीजिए। मैं दरवाज़े पर रुकता हूँ।",
              "kn-IN": "ಕೊಠಡಿಯನ್ನು ಆನಂದಿಸಿ. ನಾನು ಬಾಗಿಲ ಬಳಿ ಕಾಯುತ್ತೇನೆ."},
}

# ---------------------------------------------------------------- months / numbers
MONTHS = {
    "en-IN": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
              "October", "November", "December"],
    "hi-IN": ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर",
              "नवंबर", "दिसंबर"],
    "kn-IN": ["ಜನವರಿ", "ಫೆಬ್ರವರಿ", "ಮಾರ್ಚ್", "ಏಪ್ರಿಲ್", "ಮೇ", "ಜೂನ್", "ಜುಲೈ", "ಆಗಸ್ಟ್", "ಸೆಪ್ಟೆಂಬರ್",
              "ಅಕ್ಟೋಬರ್", "ನವೆಂಬರ್", "ಡಿಸೆಂಬರ್"],
}
# Extra spellings seen in transcripts, mapped to month numbers.
MONTH_ALIASES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10,
    "nov": 11, "dec": 12, "फरवरी": 2, "सितम्बर": 9, "नवम्बर": 11, "दिसम्बर": 12, "अक्तूबर": 10,
}


def month_name(m: int, lang: str) -> str:
    if lang in ("hinglish", "kanglish"):      # Roman-script replies say the month the English way
        return MONTHS["en-IN"][m - 1]
    return MONTHS[norm(lang)][m - 1]


_INDIC = "ऀ-෿"


def indic_word_in(name: str, text: str) -> bool:
    """A Devanagari/Kannada month name as a word: nothing Indic right before it; case suffixes may follow
    (ನವೆಂಬರ್‌ನಲ್ಲಿ), except for very short names (ಮೇ, मई) which must stand alone (ಮೇಲೆ is not May)."""
    after = rf"(?![{_INDIC}])" if len(name) <= 2 else ""
    return re.search(rf"(?<![{_INDIC}]){re.escape(name)}{after}", text) is not None


def month_numbers_in(text: str) -> set[int]:
    """Every month mentioned in text, in any of the three languages."""
    t = (text or "").lower()
    found: set[int] = set()
    for names in MONTHS.values():
        for i, n in enumerate(names):
            if indic_word_in(n, t) if not n.isascii() else re.search(rf"\b{n.lower()}\b", t):
                found.add(i + 1)
    for a, m in MONTH_ALIASES.items():
        if (re.search(rf"\b{a}\b", t) if a.isascii() else indic_word_in(a, t)):
            found.add(m)
    return found


_EN_NUM = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
           "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_EN_TENS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty", 60: "sixty", 70: "seventy", 80: "eighty",
            90: "ninety"}
EN_NUMBER_WORDS: dict[str, int] = {w: i for i, w in enumerate(_EN_NUM)}
EN_NUMBER_WORDS.update({w: n for n, w in _EN_TENS.items()})
EN_NUMBER_WORDS.update({"hundred": 100, "thousand": 1000, "dozen": 12})


def number_words(n: int, lang: str) -> str:
    """Counts read naturally: English words up to 99, digits otherwise (TTS reads hi/kn digits well)."""
    if norm(lang) != "en-IN" or n < 0 or n >= 100:
        return str(n)
    if n < 20:
        return _EN_NUM[n]
    tens, ones = divmod(n, 10)
    return _EN_TENS[tens * 10] + (f"-{_EN_NUM[ones]}" if ones else "")


def plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


# ---------------------------------------------------------------- spoken templates
# {placeholders} are filled from facts in code. Keep each line short: it is spoken aloud.
T: dict[str, dict[str, str]] = {
    # Grandma greeting / gaps / labels
    "greet": {
        "en-IN": "Oh, welcome back! {room} has {count} {memories}{voice_part}.",
        "hi-IN": "अरे, आ गए! {room} में {count} यादें हैं{voice_part}।",
        "kn-IN": "ಓ, ಬಂದ್ಯಾ! {room} ನಲ್ಲಿ {count} ನೆನಪುಗಳಿವೆ{voice_part}.",
    },
    "greet_voice": {
        "en-IN": ", {n} of them {voice_notes}",
        "hi-IN": ", जिनमें {n} वॉइस नोट हैं",
        "kn-IN": ", ಅವುಗಳಲ್ಲಿ {n} ವಾಯ್ಸ್ ನೋಟ್‌ಗಳು",
    },
    "greet_empty": {
        "en-IN": "Come, sit. {room} has no memories yet, you know. Tell me something on Telegram and I'll open it up.",
        "hi-IN": "स्वागत है। {room} में अभी कोई याद नहीं है। टेलीग्राम पर कुछ बताइए, तो यह खुल जाएगा।",
        "kn-IN": "ಸ್ವಾಗತ. {room} ನಲ್ಲಿ ಇನ್ನೂ ಯಾವ ನೆನಪೂ ಇಲ್ಲ. ಟೆಲಿಗ್ರಾಮ್‌ನಲ್ಲಿ ಏನಾದರೂ ಹೇಳಿ, ಆಗ ತೆರೆಯುತ್ತದೆ.",
    },
    "greet_offer": {
        "en-IN": "So, shall I tell you the story, or just play your memories?",
        "hi-IN": "कहानी सुनाऊँ, या आपकी यादें चलाना शुरू करूँ?",
        "kn-IN": "ಕಥೆ ಹೇಳಲಾ, ಅಥವಾ ನಿಮ್ಮ ನೆನಪುಗಳನ್ನು ಪ್ಲೇ ಮಾಡಲಾ?",
    },
    "dont_have": {
        "en-IN": "Hmm, that one isn't in your family's memories, dear.",
        "hi-IN": "हम्म, ये बात तो परिवार की यादों में नहीं है।",
        "kn-IN": "ಹ್ಮ್, ಅದು ನಮ್ಮ ಮನೆಯ ನೆನಪುಗಳಲ್ಲಿ ಇಲ್ಲ ಕಣೋ.",
    },
    "offer_ask": {
        "en-IN": "Shall I ask the family on Telegram?",
        "hi-IN": "क्या मैं टेलीग्राम पर परिवार से पूछ लूँ?",
        "kn-IN": "ಟೆಲಿಗ್ರಾಮ್‌ನಲ್ಲಿ ಕುಟುಂಬವನ್ನು ಕೇಳಲಾ?",
    },
    "asked_family": {
        "en-IN": "There, I've asked the family on Telegram. When they answer, it'll join the museum.",
        "hi-IN": "हो गया। मैंने टेलीग्राम पर परिवार से पूछ लिया है। उनका जवाब संग्रहालय में जुड़ जाएगा।",
        "kn-IN": "ಆಯ್ತು. ಟೆಲಿಗ್ರಾಮ್‌ನಲ್ಲಿ ಕುಟುಂಬವನ್ನು ಕೇಳಿದ್ದೇನೆ. ಅವರ ಉತ್ತರ ಮ್ಯೂಸಿಯಂಗೆ ಸೇರುತ್ತದೆ.",
    },
    "ask_failed": {
        "en-IN": "Oh, Telegram isn't answering just now. Try me again in a bit?",
        "hi-IN": "अभी टेलीग्राम तक नहीं पहुँच पाई। थोड़ी देर में फिर कोशिश कीजिए।",
        "kn-IN": "ಈಗ ಟೆಲಿಗ್ರಾಮ್ ತಲುಪಲಾಗಲಿಲ್ಲ. ಸ್ವಲ್ಪ ಸಮಯದ ನಂತರ ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.",
    },
    "okay_no_ask": {"en-IN": "All right, I won't bother them.", "hi-IN": "ठीक है, नहीं पूछूँगी।", "kn-IN": "ಸರಿ, ಕೇಳುವುದಿಲ್ಲ."},
    "general_label": {
        "en-IN": "Now, this isn't from your family's memories, but here's what's generally known.",
        "hi-IN": "यह आपके परिवार की यादों से नहीं है, लेकिन आम तौर पर यह माना जाता है।",
        "kn-IN": "ಇದು ನಿಮ್ಮ ಕುಟುಂಬದ ನೆನಪುಗಳಿಂದ ಅಲ್ಲ, ಆದರೆ ಸಾಮಾನ್ಯವಾಗಿ ತಿಳಿದಿರುವುದು ಇದು.",
    },
    "general_off": {
        "en-IN": "Here I only talk about your family's memories, dear.",
        "hi-IN": "यहाँ मैं सिर्फ़ आपके परिवार की यादों के बारे में बात कर सकती हूँ।",
        "kn-IN": "ಇಲ್ಲಿ ನಾನು ನಿಮ್ಮ ಕುಟುಂಬದ ನೆನಪುಗಳ ಬಗ್ಗೆ ಮಾತ್ರ ಮಾತನಾಡಬಲ್ಲೆ.",
    },
    "no_advice": {
        "en-IN": "Ah, medical, legal or money advice I can't give. Please ask someone who knows, okay?",
        "hi-IN": "मैं डॉक्टरी, कानूनी या पैसों की सलाह नहीं दे सकती। कृपया किसी जानकार से पूछिए।",
        "kn-IN": "ನಾನು ವೈದ್ಯಕೀಯ, ಕಾನೂನು ಅಥವಾ ಹಣಕಾಸಿನ ಸಲಹೆ ಕೊಡಲಾರೆ. ದಯವಿಟ್ಟು ತಜ್ಞರನ್ನು ಕೇಳಿ.",
    },
    "carry_on": {
        "en-IN": "Shall I carry on with the story?",
        "hi-IN": "कहानी आगे सुनाऊँ?",
        "kn-IN": "ಕಥೆಯನ್ನು ಮುಂದುವರಿಸಲಾ?",
    },
    "tour_empty": {
        "en-IN": "There's nothing I can tell from this room yet.",
        "hi-IN": "इस कमरे से अभी सुनाने को कुछ नहीं है।",
        "kn-IN": "ಈ ಕೊಠಡಿಯಿಂದ ಇನ್ನೂ ಹೇಳಲು ಏನೂ ಇಲ್ಲ.",
    },
    # Plain template tour lines (used when the model fails the checks twice)
    "tpl_intro": {
        "en-IN": "{room} holds {count} {memories}{who}.",
        "hi-IN": "{room} में {count} यादें हैं{who}।",
        "kn-IN": "{room} ನಲ್ಲಿ {count} ನೆನಪುಗಳಿವೆ{who}.",
    },
    "tpl_who": {"en-IN": ", shared by {names}", "hi-IN": ", जिन्हें {names} ने भेजा", "kn-IN": ", {names} ಕಳುಹಿಸಿದವು"},
    "tpl_festival": {"en-IN": "This was the month of {festival}.", "hi-IN": "यह {festival} का महीना था।",
                     "kn-IN": "ಇದು {festival} ತಿಂಗಳು."},
    "tpl_item": {"en-IN": "{when}{by}: {title}.", "hi-IN": "{when}{by}: {title}।", "kn-IN": "{when}{by}: {title}."},
    "tpl_item_on": {"en-IN": "On {day} {month}", "hi-IN": "{day} {month} को", "kn-IN": "{month} {day} ರಂದು"},
    "tpl_item_then": {"en-IN": "Then", "hi-IN": "फिर", "kn-IN": "ನಂತರ"},
    "tpl_by": {"en-IN": ", {name} shared", "hi-IN": ", {name} ने बताया", "kn-IN": ", {name} ಹಂಚಿಕೊಂಡರು"},
    "tpl_gentle": {"en-IN": "This one is tender, so I'll tell it softly.", "hi-IN": "यह याद नाज़ुक है, धीरे से सुनाती हूँ।",
                   "kn-IN": "ಇದು ಸೂಕ್ಷ್ಮ ನೆನಪು, ಮೆಲ್ಲಗೆ ಹೇಳುತ್ತೇನೆ."},
    "tpl_end": {"en-IN": "That's this room for now.", "hi-IN": "अभी के लिए इस कमरे में इतना ही।",
                "kn-IN": "ಸದ್ಯಕ್ಕೆ ಈ ಕೊಠಡಿಯಲ್ಲಿ ಇಷ್ಟೇ."},
    # Receptionist
    "rx_hello": {
        "en-IN": "Hi there! I can add an event, bring in your photos, walk you to any room, or change a setting. What'll it be?",
        "hi-IN": "नमस्ते! मैं इवेंट जोड़ सकती हूँ, फ़ोटो ला सकती हूँ, किसी कमरे तक ले जा सकती हूँ, या कोई सेटिंग बदल सकती हूँ।",
        "kn-IN": "ನಮಸ್ಕಾರ! ನಾನು ಈವೆಂಟ್ ಸೇರಿಸಬಹುದು, ಫೋಟೋ ತರಬಹುದು, ಕೊಠಡಿಗೆ ಕರೆದೊಯ್ಯಬಹುದು, ಅಥವಾ ಸೆಟ್ಟಿಂಗ್ ಬದಲಿಸಬಹುದು.",
    },
    "rx_cant": {
        "en-IN": "Ah, that one I can't do from the desk.",
        "hi-IN": "यह मैं यहाँ नहीं कर सकती।",
        "kn-IN": "ಅದನ್ನು ನಾನು ಇಲ್ಲಿ ಮಾಡಲಾರೆ.",
    },
    "rx_ask_when": {
        "en-IN": "Sure! Which month and year was that?",
        "hi-IN": "अच्छा, वो कौन सा महीना और साल था?",
        "kn-IN": "ಸರಿ, ಅದು ಯಾವ ತಿಂಗಳು, ಯಾವ ವರ್ಷ?",
    },
    "rx_ask_year": {
        "en-IN": "Got it, {month}. Which year though?",
        "hi-IN": "वह किस साल का {month} था?",
        "kn-IN": "ಅದು ಯಾವ ವರ್ಷದ {month}?",
    },
    "rx_ask_which": {
        "en-IN": "Hmm, did you mean {options}?",
        "hi-IN": "आपका मतलब {options} था?",
        "kn-IN": "ನೀವು ಹೇಳಿದ್ದು {options}?",
    },
    "rx_or": {"en-IN": " or ", "hi-IN": " या ", "kn-IN": " ಅಥವಾ "},
    "rx_ask_name": {
        "en-IN": "Lovely. What should we call it?",
        "hi-IN": "इवेंट का नाम क्या रखूँ?",
        "kn-IN": "ಈವೆಂಟ್‌ಗೆ ಏನು ಹೆಸರು ಇಡಲಿ?",
    },
    "rx_event_created": {
        "en-IN": "Done! {event} is in. It lives on {floor}, in the {month} room.",
        "hi-IN": "{event} जुड़ गया। यह {floor} पर, {month} वाले कमरे में है।",
        "kn-IN": "{event} ಸೇರಿಸಲಾಗಿದೆ. ಇದು {floor}, {month} ಕೊಠಡಿಯಲ್ಲಿದೆ.",
    },
    "rx_door_shut": {
        "en-IN": "Its door stays shut till it has memories, so want to add some photos?",
        "hi-IN": "जब तक इसमें यादें नहीं होंगी, दरवाज़ा बंद रहेगा। फ़ोटो जोड़ें?",
        "kn-IN": "ನೆನಪುಗಳು ಸೇರುವವರೆಗೆ ಬಾಗಿಲು ಮುಚ್ಚಿರುತ್ತದೆ. ಫೋಟೋ ಸೇರಿಸೋಣವೇ?",
    },
    "rx_add_photos": {"en-IN": "Want to add photos to it?", "hi-IN": "फ़ोटो जोड़ें?", "kn-IN": "ಫೋಟೋ ಸೇರಿಸೋಣವೇ?"},
    "rx_event_exists": {
        "en-IN": "Oh, {event} is already here, on {floor}, in the {month} room.",
        "hi-IN": "{event} पहले से है, {floor} पर, {month} वाले कमरे में।",
        "kn-IN": "{event} ಈಗಾಗಲೇ ಇದೆ, {floor}, {month} ಕೊಠಡಿಯಲ್ಲಿ.",
    },
    "floor_ground": {"en-IN": "the ground floor", "hi-IN": "भूतल", "kn-IN": "ನೆಲ ಮಹಡಿಯಲ್ಲಿ"},
    "floor_n": {"en-IN": "floor {n}", "hi-IN": "मंज़िल {n}", "kn-IN": "{n}ನೇ ಮಹಡಿಯಲ್ಲಿ"},
    "rx_found": {
        "en-IN": "Okay, I found {count} {photos}{when}, about {size}.",
        "hi-IN": "मुझे {when}{count} फ़ोटो मिलीं, {size}।",
        "kn-IN": "{when}{count} ಫೋಟೋಗಳು ಸಿಕ್ಕವು, {size}.",
    },
    "rx_found_none": {
        "en-IN": "Hmm, I couldn't find any new photos for that.",
        "hi-IN": "उसके लिए कोई नई फ़ोटो नहीं मिली।",
        "kn-IN": "ಅದಕ್ಕೆ ಯಾವ ಹೊಸ ಫೋಟೋವೂ ಸಿಗಲಿಲ್ಲ.",
    },
    "rx_add_to": {"en-IN": "Shall I add them to {event}?", "hi-IN": "इन्हें {event} में जोड़ दूँ?", "kn-IN": "ಇವನ್ನು {event} ಗೆ ಸೇರಿಸಲಾ?"},
    "rx_which_event": {
        "en-IN": "Which event should they go into?",
        "hi-IN": "इन्हें किस इवेंट में जोड़ूँ?",
        "kn-IN": "ಇವನ್ನು ಯಾವ ಈವೆಂಟ್‌ಗೆ ಸೇರಿಸಲಿ?",
    },
    "rx_over_limit": {
        "en-IN": "That's {count} photos, a bit more than the {limit} I can add in one go. The newest {limit} come to {size}.",
        "hi-IN": "ये {count} फ़ोटो हैं, एक बार में {limit} से ज़्यादा नहीं जोड़ सकती। सबसे नई {limit} फ़ोटो {size} की हैं।",
        "kn-IN": "ಇವು {count} ಫೋಟೋಗಳು, ಒಮ್ಮೆಗೆ {limit} ಕ್ಕಿಂತ ಹೆಚ್ಚು ಸೇರಿಸಲಾರೆ. ಹೊಸ {limit} ಫೋಟೋಗಳು {size}.",
    },
    "rx_import_started": {
        "en-IN": "On it! Adding {count} {photos} to {event}. I'll tell you once they're in.",
        "hi-IN": "{count} फ़ोटो {event} में जोड़ रही हूँ। हो जाने पर बताऊँगी।",
        "kn-IN": "{count} ಫೋಟೋಗಳನ್ನು {event} ಗೆ ಸೇರಿಸುತ್ತಿದ್ದೇನೆ. ಮುಗಿದಾಗ ಹೇಳುತ್ತೇನೆ.",
    },
    "rx_nothing_pending": {
        "en-IN": "Nothing's waiting for a yes right now. Which photos would you like first?",
        "hi-IN": "अभी कुछ भी पुष्टि के लिए नहीं है। पहले बताइए कौन-सी फ़ोटो चाहिए।",
        "kn-IN": "ಈಗ ಯಾವುದೂ ದೃಢೀಕರಣಕ್ಕೆ ಕಾಯುತ್ತಿಲ್ಲ. ಮೊದಲು ಯಾವ ಫೋಟೋಗಳು ಬೇಕು ಹೇಳಿ.",
    },
    "rx_cancelled": {"en-IN": "No problem, I'll leave it.", "hi-IN": "कोई बात नहीं, रहने देती हूँ।", "kn-IN": "ಪರವಾಗಿಲ್ಲ, ಬಿಟ್ಟುಬಿಡ್ತೀನಿ."},
    "rx_no_faces": {
        "en-IN": "Ah, I can't recognise faces or what's inside photos. I can pick them by date, size, camera or folder though.",
        "hi-IN": "मैं चेहरे नहीं पहचान सकती। तारीख़, साइज़, कैमरा या फ़ोल्डर से चुन सकती हूँ।",
        "kn-IN": "ನಾನು ಮುಖಗಳನ್ನು ಗುರುತಿಸಲಾರೆ. ದಿನಾಂಕ, ಗಾತ್ರ, ಕ್ಯಾಮೆರಾ ಅಥವಾ ಫೋಲ್ಡರ್ ಮೂಲಕ ಆರಿಸಬಲ್ಲೆ.",
    },
    "rx_route": {
        "en-IN": "{place}, coming right up. Follow the guide!",
        "hi-IN": "{place}। गाइड के पीछे चलिए।",
        "kn-IN": "{place}. ಮಾರ್ಗದರ್ಶಿಯನ್ನು ಹಿಂಬಾಲಿಸಿ.",
    },
    "rx_route_locked": {
        "en-IN": "{place} is shut for now, but the guide will show you the door.",
        "hi-IN": "{place} अभी बंद है। गाइड आपको दरवाज़ा दिखाएगा।",
        "kn-IN": "{place} ಸದ್ಯಕ್ಕೆ ಮುಚ್ಚಿದೆ. ಮಾರ್ಗದರ್ಶಿ ಬಾಗಿಲು ತೋರಿಸುತ್ತಾನೆ.",
    },
    "rx_where": {
        "en-IN": "Which room would you like? Just say a month and year, or an event.",
        "hi-IN": "कौन-सा कमरा? कोई महीना और साल, या इवेंट बताइए।",
        "kn-IN": "ಯಾವ ಕೊಠಡಿ? ತಿಂಗಳು ಮತ್ತು ವರ್ಷ, ಅಥವಾ ಈವೆಂಟ್ ಹೇಳಿ.",
    },
    "rx_setting": {
        "en-IN": "Done! {what}.",
        "hi-IN": "हो गया! {what}।",
        "kn-IN": "ಆಯ್ತು! {what}.",
    },
    "rx_lang_set": {
        "en-IN": "I'll speak English from now on",
        "hi-IN": "अब से मैं हिंदी में बात करूँगी",
        "kn-IN": "ಇನ್ನು ಮುಂದೆ ನಾನು ಕನ್ನಡದಲ್ಲಿ ಮಾತನಾಡುತ್ತೇನೆ",
    },
    "rx_setting_bad": {
        "en-IN": "I can change the language, Grandma's name, sarcasm, closing a room with care, or keeping photo locations.",
        "hi-IN": "मैं भाषा, दादी का नाम, व्यंग्य, किसी कमरे को सम्मान से बंद करना, या फ़ोटो की लोकेशन रखना बदल सकती हूँ।",
        "kn-IN": "ನಾನು ಭಾಷೆ, ಅಜ್ಜಿಯ ಹೆಸರು, ವ್ಯಂಗ್ಯ, ಕೊಠಡಿಯನ್ನು ಕಾಳಜಿಯಿಂದ ಮುಚ್ಚುವುದು, ಅಥವಾ ಫೋಟೋ ಸ್ಥಳ ಇಡುವುದನ್ನು ಬದಲಿಸಬಲ್ಲೆ.",
    },
    "rx_invite_confirm": {
        "en-IN": "Call {name}, number ending {last4}, and invite them to {place}?",
        "hi-IN": "{name} को, जिनका नंबर {last4} पर ख़त्म होता है, फ़ोन करके {place} में बुलाऊँ?",
        "kn-IN": "{last4} ರಲ್ಲಿ ಕೊನೆಯಾಗುವ ನಂಬರ್‌ನ {name} ಅವರಿಗೆ ಕರೆ ಮಾಡಿ {place} ಗೆ ಆಹ್ವಾನಿಸಲಾ?",
    },
    "rx_invite_none": {
        "en-IN": "I couldn't find {who} in your contacts. Contacts are added at the reception desk, typed, never spoken.",
        "hi-IN": "आपके कॉन्टैक्ट्स में {who} नहीं मिले। कॉन्टैक्ट रिसेप्शन डेस्क पर टाइप करके जोड़े जाते हैं।",
        "kn-IN": "ನಿಮ್ಮ ಸಂಪರ್ಕಗಳಲ್ಲಿ {who} ಸಿಗಲಿಲ್ಲ. ಸಂಪರ್ಕಗಳನ್ನು ರಿಸೆಪ್ಷನ್ ಡೆಸ್ಕ್‌ನಲ್ಲಿ ಟೈಪ್ ಮಾಡಿ ಸೇರಿಸಲಾಗುತ್ತದೆ.",
    },
    "rx_invite_which": {
        "en-IN": "I found {options}. Which one?",
        "hi-IN": "मुझे {options} मिले। कौन-से?",
        "kn-IN": "{options} ಸಿಕ್ಕರು. ಯಾರು?",
    },
    "rx_invite_no_consent": {
        "en-IN": "{name} hasn't agreed to calls from Memo yet, so I can't call. The owner can tick consent at the desk.",
        "hi-IN": "{name} ने अभी Memo से कॉल के लिए सहमति नहीं दी है, इसलिए मैं कॉल नहीं कर सकती।",
        "kn-IN": "{name} ಇನ್ನೂ Memo ಕರೆಗಳಿಗೆ ಒಪ್ಪಿಗೆ ನೀಡಿಲ್ಲ, ಹಾಗಾಗಿ ಕರೆ ಮಾಡಲಾರೆ.",
    },
    "rx_invite_placed": {
        "en-IN": "Calling {name} now. I'll show you what they say!",
        "hi-IN": "{name} को अभी फ़ोन कर रही हूँ। उनका जवाब दिखाऊँगी।",
        "kn-IN": "{name} ಅವರಿಗೆ ಈಗ ಕರೆ ಮಾಡುತ್ತಿದ್ದೇನೆ. ಅವರ ಉತ್ತರ ತೋರಿಸುತ್ತೇನೆ.",
    },
    "rx_invite_where": {
        "en-IN": "Which room should I invite them to?",
        "hi-IN": "उन्हें किस कमरे में बुलाऊँ?",
        "kn-IN": "ಅವರನ್ನು ಯಾವ ಕೊಠಡಿಗೆ ಆಹ್ವಾನಿಸಲಿ?",
    },
    "rx_error": {
        "en-IN": "Oops, sorry, that didn't work: {reason}",
        "hi-IN": "माफ़ कीजिए, यह नहीं हो पाया: {reason}",
        "kn-IN": "ಕ್ಷಮಿಸಿ, ಅದು ಆಗಲಿಲ್ಲ: {reason}",
    },
    # list events: {count} = number, {list} = "Tech talks, May 2026; Diwali, November 2025", {more} = rx_events_more or ""
    "rx_events": {
        "en-IN": "You have {count} {events}: {list}{more}. Which one shall we visit?",
        "hi-IN": "आपके {count} इवेंट हैं: {list}{more}। किसमें चलें?",
        "kn-IN": "ನಿಮ್ಮ ಬಳಿ {count} ಈವೆಂಟ್‌ಗಳಿವೆ: {list}{more}. ಯಾವುದಕ್ಕೆ ಹೋಗೋಣ?",
    },
    "rx_events_more": {"en-IN": ", and {n} more", "hi-IN": ", और {n} और", "kn-IN": ", ಮತ್ತು ಇನ್ನೂ {n}"},
    "rx_events_rooms": {
        "en-IN": " Rooms with memories but no event: {list}.",
        "hi-IN": " बिना इवेंट वाले, यादों से भरे कमरे: {list}।",
        "kn-IN": " ಈವೆಂಟ್ ಇಲ್ಲದ, ನೆನಪುಗಳಿರುವ ಕೊಠಡಿಗಳು: {list}.",
    },
    "rx_events_none": {
        "en-IN": "There are no events yet.{rooms} Want to add one?",
        "hi-IN": "अभी कोई इवेंट नहीं है।{rooms} एक जोड़ें?",
        "kn-IN": "ಇನ್ನೂ ಯಾವ ಈವೆಂಟ್ ಇಲ್ಲ.{rooms} ಒಂದನ್ನು ಸೇರಿಸೋಣವೇ?",
    },
    "rx_need_role": {
        "en-IN": "Only the family's owner or an editor can do that.",
        "hi-IN": "यह सिर्फ़ परिवार के मालिक या एडिटर कर सकते हैं।",
        "kn-IN": "ಇದನ್ನು ಕುಟುಂಬದ ಮಾಲೀಕರು ಅಥವಾ ಎಡಿಟರ್ ಮಾತ್ರ ಮಾಡಬಹುದು.",
    },
}


# Roman-script replies for users who type or speak Hinglish / Kanglish (PRD: reply in the user's style).
# Voiced with the hi-IN / kn-IN voice. Same placeholders as the native lines.
MIXED: dict[str, dict[str, str]] = {
    "greet": {"hinglish": "Arre, aa gaye! {room} mein {count} yaadein hain{voice_part}.",
              "kanglish": "Oh, bandya! {room} alli {count} nenapugalu ive{voice_part}."},
    "greet_voice": {"hinglish": ", unmein {n} voice notes hain", "kanglish": ", adralli {n} voice notes"},
    "greet_offer": {"hinglish": "Toh, kahaani sunaaun, ya seedha yaadein chala doon?",
                    "kanglish": "Hmm, kathe hella, illa nenapugalanna play maadla?"},
    "dont_have": {"hinglish": "Hmm, ye baat toh family ki yaadon mein nahi hai.",
                  "kanglish": "Hmm, adu namma maneya nenapugalalli illa kano."},
    "offer_ask": {"hinglish": "Telegram pe family se pooch loon?", "kanglish": "Telegram alli family na kelibidla?"},
    "asked_family": {"hinglish": "Lo, Telegram pe family se pooch liya. Jawab aayega toh museum mein jud jaayega.",
                     "kanglish": "Nodu, Telegram alli family na kelidini. Uttara bandre museum ge serutte."},
    "ask_failed": {"hinglish": "Arre, abhi Telegram nahi lag raha. Thodi der mein phir try karna?",
                   "kanglish": "Ayyo, eega Telegram sigta illa. Swalpa hottu bittu matte try maadi?"},
    "okay_no_ask": {"hinglish": "Theek hai, nahi poochti.", "kanglish": "Sari, kelalla."},
    "general_label": {"hinglish": "Ye family ki yaadon se nahi hai, par aam taur pe ye maana jaata hai.",
                      "kanglish": "Idu namma nenapugalinda alla, aadre saamanyavaagi heegante."},
    "general_off": {"hinglish": "Yahan main sirf family ki yaadon ki baat karti hoon.",
                    "kanglish": "Illi naanu namma maneya nenapugala bagge maatra maatadtini."},
    "no_advice": {"hinglish": "Arre, doctor, kanoon ya paison ki salah main nahi de sakti. Kisi jaankar se poochna, haan?",
                  "kanglish": "Ayyo, doctor, kaanoonu, duddina salahe naanu kodakkagalla. Gottiruvavranna keli, aaytha?"},
    "carry_on": {"hinglish": "Kahaani aage sunaaun?", "kanglish": "Kathe munduvarisla?"},
    "tour_empty": {"hinglish": "Is room se abhi sunaane ko kuch nahi hai.", "kanglish": "Ee room inda innu helakke enu illa."},
    "rx_hello": {"hinglish": "Namaste! Main event bana sakti hoon, photos la sakti hoon, kisi bhi room tak le ja sakti hoon, "
                             "ya setting badal sakti hoon. Bolo, kya karein?",
                 "kanglish": "Namaskara! Event add maadbahudu, photos tarbahudu, yaava room ge bekadru karkondu hogbahudu, "
                             "illa setting badlaayisbahudu. Heli, enu maadona?"},
    "rx_cant": {"hinglish": "Arre, ye desk se nahi ho paayega.", "kanglish": "Ayyo, adu desk inda aagalla."},
    "rx_ask_when": {"hinglish": "Achha, kaunsa mahina aur saal tha?", "kanglish": "Sari, yaava tingalu, yaava varsha?"},
    "rx_ask_year": {"hinglish": "{month}, theek hai. Par kaunse saal ka?", "kanglish": "{month}, sari. Aadre yaava varsha?"},
    "rx_ask_which": {"hinglish": "Hmm, {options}, kaunsa?", "kanglish": "Hmm, {options}, yaavdu?"},
    "rx_or": {"hinglish": " ya ", "kanglish": " illa "},
    "rx_ask_name": {"hinglish": "Badhiya! Iska naam kya rakhein?", "kanglish": "Super! Idakke enu hesaru idona?"},
    "rx_event_created": {"hinglish": "Ho gaya! {event} add ho gaya, {floor} pe, {month} wale room mein.",
                         "kanglish": "Aaytu! {event} add aaytu, {floor}, {month} room alli ide."},
    "rx_door_shut": {"hinglish": "Jab tak yaadein nahi aati, darwaza band rahega. Photos daal dein?",
                     "kanglish": "Nenapugalu baro tanaka baagilu muchkondirutte. Photos add maadona?"},
    "rx_add_photos": {"hinglish": "Photos bhi daal dein?", "kanglish": "Photos add maadona?"},
    "rx_event_exists": {"hinglish": "Arre, {event} toh pehle se hai, {floor} pe, {month} wale room mein.",
                        "kanglish": "Oh, {event} already ide, {floor}, {month} room alli."},
    "floor_ground": {"hinglish": "ground floor", "kanglish": "ground floor alli"},
    "floor_n": {"hinglish": "floor {n}", "kanglish": "floor {n} alli"},
    "rx_found": {"hinglish": "Achha, {when}{count} photos mili, lagbhag {size}.",
                 "kanglish": "Sari, {when}{count} photos sikkidvu, sumaaru {size}."},
    "rx_found_none": {"hinglish": "Hmm, iske liye koi nayi photo nahi mili.", "kanglish": "Hmm, adakke yaava hosa photo sikkilla."},
    "rx_add_to": {"hinglish": "{event} mein daal doon?", "kanglish": "{event} ge add maadla?"},
    "rx_which_event": {"hinglish": "Kis event mein daalun?", "kanglish": "Yaava event ge add maadli?"},
    "rx_over_limit": {"hinglish": "Ye {count} photos hain, ek baar mein {limit} se zyada nahi daal sakti. Sabse nayi {limit} "
                                  "photos {size} ki hain.",
                      "kanglish": "Ivu {count} photos, ondu sala {limit} ginta jaasti add maadakke aagalla. Hosa {limit} "
                                  "photos {size} aagutte."},
    "rx_import_started": {"hinglish": "Chalo, {count} photos {event} mein daal rahi hoon. Ho jaane pe bataungi.",
                          "kanglish": "Sari, {count} photos {event} ge add maadtidini. Mugid mele heltini."},
    "rx_nothing_pending": {"hinglish": "Abhi kuch bhi haan ka wait nahi kar raha. Pehle batao, kaunsi photos chahiye?",
                           "kanglish": "Eega yaavdu haudu ge kaaytilla. Modlu heli, yaava photos beku?"},
    "rx_cancelled": {"hinglish": "Koi baat nahi, rehne deti hoon.", "kanglish": "Paravagilla, bittbidtini."},
    "rx_no_faces": {"hinglish": "Photo ke andar kaun hai ya kya hai, wo main nahi pehchaan sakti. Date, size, camera ya "
                                "folder se chun sakti hoon.",
                    "kanglish": "Photo olage yaaru, enu ide anta nange gottagalla. Date, size, camera illa folder inda "
                                "aarisbahudu."},
    "rx_route": {"hinglish": "{place}, chalo! Guide ke peeche aao.", "kanglish": "{place}, banni! Guide hinde hogi."},
    "rx_route_locked": {"hinglish": "{place} abhi band hai, par guide darwaza dikha dega.",
                        "kanglish": "{place} eega muchide, aadre guide baagilu thorsthare."},
    "rx_where": {"hinglish": "Kaunsa room? Mahina aur saal bolo, ya koi event.",
                 "kanglish": "Yaava room? Tingalu mattu varsha heli, illa yaavdaadru event."},
    "rx_setting": {"hinglish": "Ho gaya! {what}.", "kanglish": "Aaytu! {what}."},
    "rx_need_role": {"hinglish": "Ye sirf family ke owner ya editor kar sakte hain.",
                     "kanglish": "Idanna family owner illa editor maatra maadbahudu."},
    "rx_error": {"hinglish": "Sorry, ye nahi ho paaya: {reason}", "kanglish": "Sorry, adu aagilla: {reason}"},
    "rx_invite_confirm": {"hinglish": "{name} ko call karoon, jinka number {last4} pe khatam hota hai, aur {place} mein bulaoon?",
                          "kanglish": "{last4} alli mugiyo number na {name} ge call maadi, {place} ge karili?"},
    "rx_invite_none": {"hinglish": "Contacts mein {who} nahi mile. Contacts desk pe type karke add hote hain, bol ke nahi.",
                       "kanglish": "Contacts alli {who} sikkilla. Contacts na desk alli type maadi add maadbeku, heli alla."},
    "rx_invite_which": {"hinglish": "{options} mile. Kaunse wale?", "kanglish": "{options} sikkidru. Yaaru?"},
    "rx_invite_no_consent": {"hinglish": "{name} ne abhi Memo ke calls ke liye haan nahi bola, toh call nahi kar sakti.",
                             "kanglish": "{name} innu Memo calls ge oppilla, haagaagi call maadakkagalla."},
    "rx_invite_placed": {"hinglish": "{name} ko abhi call kar rahi hoon. Jo bolenge, dikha doongi.",
                         "kanglish": "{name} ge eega call maadtidini. Avru enu heltaare anta thorstini."},
    "rx_invite_where": {"hinglish": "Unhe kaunse room mein bulaoon?", "kanglish": "Avranna yaava room ge karili?"},
    "rx_lang_set": {"hinglish": "Ab se main Hindi mein baat karungi", "kanglish": "Inmunde naanu Kannada dalli maatadtini"},
    "rx_events": {"hinglish": "Aapke {count} events hain: {list}{more}. Kaunse mein chalein?",
                  "kanglish": "Nimma hatra {count} events ive: {list}{more}. Yaavdakke hogona?"},
    "rx_events_more": {"hinglish": ", aur {n} aur", "kanglish": ", innu {n}"},
    "rx_events_rooms": {"hinglish": " Bina event wale yaadon ke rooms: {list}.",
                        "kanglish": " Event illada nenapugala rooms: {list}."},
    "rx_events_none": {"hinglish": "Abhi koi event nahi hai.{rooms} Ek bana dein?",
                       "kanglish": "Innu yaava event illa.{rooms} Ondu add maadona?"},
}
for _k, _row in MIXED.items():
    T.setdefault(_k, {}).update(_row)


def t(key: str, lang: str, **kw: Any) -> str:
    """`lang` is a language (en-IN / hi-IN / kn-IN) or a register ("hinglish" / "kanglish": Roman-script replies
    for users who type that way); a register without its own line falls back to the language's line."""
    row = T[key]
    s = row.get(lang) or row.get(norm(lang)) or row["en-IN"]
    return s.format(**kw) if kw else s


def floor_label(level: int, lang: str) -> str:
    return t("floor_ground", lang) if level <= 0 else t("floor_n", lang, n=level)


def size_label(n_bytes: int, lang: str) -> str:
    mb = n_bytes / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{max(1, round(mb))} MB"


# ---------------------------------------------------------------- language switch ("speak Kannada")
_SWITCH = [
    ("kn-IN", re.compile(r"\b(speak|talk|switch to|change (the )?language to|in)\s+kannada\b|ಕನ್ನಡದಲ್ಲಿ|ಕನ್ನಡ\s*(ಮಾತಾಡ|ಮಾತನಾಡ)|कन्नड़\s*(में|बोल)", re.I)),
    ("hi-IN", re.compile(r"\b(speak|talk|switch to|change (the )?language to|in)\s+hindi\b|हिंदी\s*में|हिन्दी\s*में|ಹಿಂದಿ(ಯಲ್ಲಿ)?\s*(ಮಾತಾಡ|ಮಾತನಾಡ)|hindi\s+(mein|me)\s+bol", re.I)),
    ("en-IN", re.compile(r"\b(speak|talk|switch to|change (the )?language to|in)\s+english\b|इंग्लिश\s*में|अंग्रेज़ी\s*में|अंग्रेजी\s*में|ಇಂಗ್ಲಿಷ್‌?ನಲ್ಲಿ", re.I)),
]


def language_switch(text: str) -> Optional[str]:
    for code, rx in _SWITCH:
        if rx.search(text or ""):
            return code
    return None


def language_switch_rest(text: str) -> tuple[Optional[str], str]:
    """(language, what is left once the switch request is removed), so "talk in Hindi, when was this?" can switch
    AND answer. The rest is "" when the message was only the switch (or the leftover is not a question)."""
    for code, rx in _SWITCH:
        if rx.search(text or ""):
            rest = rx.sub(" ", text or "")
            rest = re.sub(r"^\W*(?:(?:and|aur|mattu|now|ab|please|pls|ok|okay|ajji|dadi|grandma|amma|nani)\b\W*)*",
                          "", rest, flags=re.I)
            rest = re.sub(r"^\w{1,2}\b\W*", "", rest.strip())   # tail of a cut word ("bol-o, ...")
            rest = " ".join(rest.split()).strip(" ,.;:!-")
            asks = re.search(r"\?|\b(?:who|what|when|where|which|why|how|tell|show|explain|kab|kaun|kya|kahan|kaise|"
                             r"kyun|batao|bataiye|dikhao|yaaru|yavaga|yelli|enu|yake|heli|helu|thorisu)\b|"
                             r"कब|कौन|क्या|कहाँ|कैसे|बताओ|ಯಾರು|ಯಾವಾಗ|ಎಲ್ಲಿ|ಏನು|ಹೇಳಿ", rest, re.I)
            return code, (rest if asks else "")
    return None, ""


def language_rule(lang: str) -> str:
    lg = norm(lang)
    if lg == "hi-IN":
        return ("LANGUAGE: write natural spoken Hindi in Devanagari script. Keep people's names, place names and "
                "event titles exactly as they are spelled in the facts (do not translate or transliterate them).")
    if lg == "kn-IN":
        return ("LANGUAGE: write natural spoken Kannada in Kannada script. Keep people's names, place names and "
                "event titles exactly as they are spelled in the facts (do not translate or transliterate them).")
    return "LANGUAGE: write simple, warm Indian English."


# yes / no in three languages, Hinglish and Kanglish (confirmations are matched in code, never by the model)
_YES = (r"yes|yeah|yea|yep|yup|ya|yess+|sure|ok(ay)?|okie|okk*|k|kk|alright|all right|go ahead|go for it|do it|"
        r"please do|yes please|confirm|correct|right|exactly|absolutely|of course|definitely|sounds good|perfect|"
        r"done|ok done|why not|let'?s do it|let'?s go|"
        r"haa+n?|haan? ji|han|hanji|ha|hn|ji|ji haan|theek hai|thik hai|theek h|thik h|thik|theek|chalo|chal|"
        r"kar do|kardo|karo|kar dijiye|daal do|daldo|dal do|ho jaye|bilkul|zaroor|zarur|pakka|sahi hai|haan bhai|"
        r"haudu|houdu|howdu|hu+|hoon|sari|sari sari|aytu|aaytu|aitu|maadi|madi|maadu|madu|haaku|hakbidi|"
        r"हाँ|हां|हा|जी|जी हाँ|ठीक है|हाँ जी|कर दो|चलो|बिल्कुल|ज़रूर|जरूर|पक्का|"
        r"ಹೌದು|ಸರಿ|ಆಯ್ತು|ಮಾಡಿ|ಹಾಂ|ಹೂಂ|ಹೂ|ಓಕೆ|ಹಾಕಿ")
_NO = (r"no|nope|nah|naa|nahh|don'?t|do not|cancel|stop|never ?mind|leave it|not now|no thanks|later|wait|hold on|"
       r"nahi|nahin|nai|nhi|na|mat|mat karo|rehne do|rehne de|rahne do|ruko|ruk|chhodo|chodo|"
       r"beda|bedaa|bedi|illa|beda bidi|bidi|nillisu|"
       r"नहीं|नही|मत|रहने दो|रुको|छोड़ो|ಬೇಡ|ಇಲ್ಲ|ಬೇಡಾ|ನಿಲ್ಲಿಸಿ|ಬಿಡಿ")
YES_RE = re.compile(r"^\s*(" + _YES + r")(?=$|[\s,.!?।])", re.I)
NO_RE = re.compile(r"^\s*(" + _NO + r")(?=$|[\s,.!?।])", re.I)
# "haan nahi", "ok wait", "sari beda", "yes, no wait": a no anywhere after a yes word cancels the yes.
_NO_ANYWHERE = re.compile(r"(?<![\w])(no|nahi|nahin|nai|beda|illa|cancel|wait|nope|mat|नहीं|ಬೇಡ|ಇಲ್ಲ)(?![\w])", re.I)


def is_yes(text: str) -> bool:
    s = (text or "").strip()
    return bool(YES_RE.match(s)) and not NO_RE.match(s) and not _NO_ANYWHERE.search(s)


def is_no(text: str) -> bool:
    s = (text or "").strip()
    if NO_RE.match(s):
        return True
    return bool(YES_RE.match(s) and _NO_ANYWHERE.search(s))
