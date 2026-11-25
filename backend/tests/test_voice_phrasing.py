"""voice-ai: any phrasing, by text (transcripts flow through the same code). Real LLM (Sarvam -> Groq), real Postgres.

Buckets (accuracy printed per bucket, target >= 90%):
  receptionist  intent + arguments: English, Hinglish, Kanglish, Roman / native Hindi and Kannada, indirect, typos
  dates_llm     the model's `when` words, pre-normalised and resolved by app.core.dates (never by the model)
  dates_code    the pre-normaliser alone (kal, parso, ninne, monne, month spellings in three scripts, typos)
  confirm       yes / no matched in code (haan, theek hai, haudu, sari, ok done, nahi, beda ...)
  detect        language / register detection (Hinglish, Kanglish, native scripts)
  keywords      the offline keyword router on the receptionist utterances (LLM down)
  grandma       talk answers against a throwaway family (created and deleted here): source + the fact asked for
  style         every Grandma answer and receptionist chat line: no markdown / lists, short sentences, no "As an AI"

Run: .venv/Scripts/python -m pytest tests/test_voice_phrasing.py -s --asyncio-mode=auto
"""
from __future__ import annotations

import re
from datetime import timedelta

import pytest
import pytest_asyncio

from _voice_fixtures import add_memory, drop_family, fresh_pool, make_family
from app.core import common, dates
from app.voice import grandma, reception, register as R
from app.voice import lang as L

pytestmark = pytest.mark.asyncio(loop_scope="module")

TODAY = common.tz_today()
Y1 = TODAY - timedelta(days=1)
Y2 = TODAY - timedelta(days=2)
LAST_MONTH = (TODAY.replace(day=1) - timedelta(days=1))


def _label_day(d) -> str:
    return f"{d.day} {L.MONTHS['en-IN'][d.month - 1]} {d.year}"


def _resolved(expr: str, route: bool = False) -> str | None:
    c = dates.resolve_when(R.to_english_dates(expr, route=route))
    return c[0]["label"] if c else None


def _place_ok(place: str, *want: str) -> bool:
    """The cleaned place mentions every wanted token (festival / month label / year), as the core will read it."""
    cleaned = R.clean_place(place or "").lower()
    lab = (_resolved(place or "", route=True) or "").lower()
    return all(w.lower() in cleaned or w.lower() in lab for w in want)


def _when_is(args: dict, label: str | None) -> bool:
    return _resolved(str(args.get("when") or "")) == label


# (language hint, utterance, tool, argument check or None)
RX = [
    # English, direct and indirect
    ("en-IN", "Take me to the Diwali 2026 room", "plan_route", lambda a: _place_ok(a.get("place"), "diwali", "2026")),
    ("en-IN", "I wanna see what we did last Holi", "plan_route", lambda a: _place_ok(a.get("place"), "holi")),
    ("en-IN", "show me Nov 26", "plan_route", lambda a: _place_ok(a.get("place"), "november 2026")),
    ("en-IN", "can we go to march 2025 pls", "plan_route", lambda a: _place_ok(a.get("place"), "march 2025")),
    ("en-IN", "Upload everything from yesterday", "query_gallery", lambda a: _when_is(a, _label_day(Y1))),
    ("en-IN", "grab the last 20 pics from my gallery", "query_gallery", lambda a: int(a.get("latest_n") or 0) == 20),
    ("en-IN", "Create an event for our Goa trip in December 2025", "create_event",
     lambda a: "goa" in str(a.get("name")).lower() and _when_is(a, "December 2025")),
    ("en-IN", "what happened in that room with the cake?", "decline", lambda a: a.get("reason") == "face_recognition"),
    ("en-IN", "add the ones with my dad in them", "decline", lambda a: a.get("reason") == "face_recognition"),
    ("en-IN", "turn the sarcasm off yaar", "change_setting", lambda a: a.get("key") == "sarcasm" and a.get("value") == "off"),
    # typos
    ("en-IN", "tak me to diwli 2026", "plan_route", lambda a: _place_ok(a.get("place"), "2026")),
    ("en-IN", "uplod all fotos from yesterdy", "query_gallery", lambda a: _when_is(a, _label_day(Y1))),
    ("en-IN", "creat a new evnt for holi in march 2025", "create_event",
     lambda a: "holi" in str(a.get("name")).lower() and _when_is(a, "March 2025")),
    # Hinglish (Roman)
    ("en-IN", "bhai mujhe Diwali wale room mein le chalo", "plan_route", lambda a: _place_ok(a.get("place"), "diwali")),
    ("en-IN", "kal ki saari photos daal do Diwali 2026 mein", "query_gallery",
     lambda a: _when_is(a, _label_day(Y1)) and "diwali" in str(a.get("event_name") or "").lower()),
    ("en-IN", "naya event banao Holi ke liye March 2025", "create_event",
     lambda a: "holi" in str(a.get("name")).lower() and _when_is(a, "March 2025")),
    ("en-IN", "parso wali pics upload karo", "query_gallery", lambda a: _when_is(a, _label_day(Y2))),
    ("en-IN", "pichle mahine ki saari photos dikhao aur add karo", "query_gallery", lambda a: _when_is(a, LAST_MONTH.strftime("%B %Y"))),
    ("en-IN", "sarcasm band karo please", "change_setting", lambda a: a.get("key") == "sarcasm" and a.get("value") == "off"),
    ("en-IN", "Priya ko is room mein bulao", "invite_contact", lambda a: "priya" in str(a.get("who")).lower()),
    ("en-IN", "last year wala Diwali event bana do", "create_event",
     lambda a: "diwali" in str(a.get("name")).lower() and _when_is(a, str(TODAY.year - 1))),
    # Kanglish (Roman)
    ("en-IN", "Diwali 2026 room ge karkondu hogu", "plan_route", lambda a: _place_ok(a.get("place"), "diwali", "2026")),
    ("en-IN", "ninne photos ella add maadu", "query_gallery", lambda a: _when_is(a, _label_day(Y1))),
    ("en-IN", "monne tegeda photos haaku", "query_gallery", lambda a: _when_is(a, _label_day(Y2))),
    ("en-IN", "hosa event maadi Ugadi March 2026", "create_event",
     lambda a: "ugadi" in str(a.get("name")).lower() and _when_is(a, "March 2026")),
    ("en-IN", "March 2025 room thorsu", "plan_route", lambda a: _place_ok(a.get("place"), "march 2025")),
    # native Hindi
    ("hi-IN", "मुझे होली 2025 वाले कमरे में ले चलो", "plan_route", lambda a: _place_ok(a.get("place"), "2025")),
    ("hi-IN", "कल की सारी फ़ोटो अपलोड करो", "query_gallery", lambda a: _when_is(a, _label_day(Y1))),
    ("hi-IN", "दिवाली नाम का नया त्योहार नवंबर 2026 में जोड़ो", "create_event",
     lambda a: _when_is(a, "November 2026")),
    ("hi-IN", "प्रिया को इस कमरे में बुलाओ", "invite_contact", lambda a: bool(a.get("who"))),
    # native Kannada
    ("kn-IN", "ನನ್ನನ್ನು ಮಾರ್ಚ್ 2025 ಕೊಠಡಿಗೆ ಕರೆದುಕೊಂಡು ಹೋಗಿ", "plan_route", lambda a: _place_ok(a.get("place"), "march 2025")),
    ("kn-IN", "ನಿನ್ನೆಯ ಎಲ್ಲಾ ಫೋಟೋಗಳನ್ನು ಸೇರಿಸಿ", "query_gallery", lambda a: _when_is(a, _label_day(Y1))),
    ("kn-IN", "ದೀಪಾವಳಿ ಎಂಬ ಹೊಸ ಹಬ್ಬವನ್ನು ನವೆಂಬರ್ 2026 ರಲ್ಲಿ ಸೇರಿಸಿ", "create_event", lambda a: _when_is(a, "November 2026")),
    ("kn-IN", "ಅಜ್ಜಿಯ ಹೆಸರನ್ನು ಅಮ್ಮಮ್ಮ ಎಂದು ಬದಲಿಸಿ", "change_setting", lambda a: a.get("key") == "grandma_name"),
]

# The model's `when` words for date-heavy requests, resolved in code.
DATES_LLM = [
    ("en-IN", "photos from day before yesterday", _label_day(Y2)),
    ("en-IN", "kal wali photos add karo", _label_day(Y1)),
    ("en-IN", "parso ki pics daalo", _label_day(Y2)),
    ("en-IN", "ninne tegeda photos add maadi", _label_day(Y1)),
    ("en-IN", "monne photos haaku", _label_day(Y2)),
    ("en-IN", "last month's pics please", LAST_MONTH.strftime("%B %Y")),
    ("en-IN", "pichle mahine ki photos", LAST_MONTH.strftime("%B %Y")),
    ("en-IN", "kalada tingalu photos ella", LAST_MONTH.strftime("%B %Y")),
    ("en-IN", "photos from navambar 2025", "November 2025"),
    ("en-IN", "photos from Novmber 2024", "November 2024"),
    ("hi-IN", "नवंबर 2025 की फ़ोटो जोड़ो", "November 2025"),
    ("hi-IN", "परसों की फ़ोटो डालो", _label_day(Y2)),
    ("kn-IN", "ಮೊನ್ನೆಯ ಫೋಟೋಗಳನ್ನು ಸೇರಿಸಿ", _label_day(Y2)),
    ("kn-IN", "ಡಿಸೆಂಬರ್ 2025 ರ ಫೋಟೋಗಳನ್ನು ಸೇರಿಸಿ", "December 2025"),
]

DATES_CODE = [
    ("kal", _label_day(Y1)), ("parso", _label_day(Y2)), ("pichle mahine", LAST_MONTH.strftime("%B %Y")),
    ("last year wala Diwali", str(TODAY.year - 1)), ("pichle saal", str(TODAY.year - 1)), ("ninne", _label_day(Y1)),
    ("monne", _label_day(Y2)), ("hoda varsha", str(TODAY.year - 1)), ("ee tingalu", TODAY.strftime("%B %Y")),
    ("navambar 2025", "November 2025"), ("disambar 2024", "December 2024"), ("Novmber 2024", "November 2024"),
    ("Febuary 2025", "February 2025"), ("नवंबर 2025", "November 2025"), ("ನವೆಂಬರ್ 2025", "November 2025"),
    ("कल", _label_day(Y1)), ("परसों", _label_day(Y2)), ("पिछले साल", str(TODAY.year - 1)), ("ನಿನ್ನೆ", _label_day(Y1)),
    ("ಮೊನ್ನೆ", _label_day(Y2)), ("ಕಳೆದ ತಿಂಗಳು", LAST_MONTH.strftime("%B %Y")), ("२०२५ मार्च", "March 2025"),
]
DATES_ROUTE = [("show me Nov 26", "November 2026"), ("Mar '25", "March 2025"), ("dec 25 room", "December 2025")]

CONFIRM = [  # (text, yes, no)
    ("haan", True, False), ("ha", True, False), ("haan ji", True, False), ("theek hai", True, False),
    ("chalo", True, False), ("haudu", True, False), ("sari", True, False), ("ok done", True, False),
    ("yes please", True, False), ("sure, go ahead", True, False), ("kar do", True, False), ("bilkul", True, False),
    ("aaytu", True, False), ("ಹೌದು", True, False), ("हाँ जी", True, False), ("ಸರಿ", True, False), ("okie", True, False),
    ("nahi", False, True), ("nahi yaar", False, True), ("beda", False, True), ("no", False, True),
    ("rehne do", False, True), ("haan nahi", False, True), ("sari beda", False, True), ("not now", False, True),
    ("ಬೇಡ", False, True), ("नहीं", False, True), ("hmm", False, False), ("which one?", False, False),
]

DETECT = [
    ("bhai mujhe Diwali wale room mein le chalo", "hinglish"), ("kal ki saari photos daal do", "hinglish"),
    ("Diwali 2026 room ge karkondu hogu", "kanglish"), ("ninne photos ella add maadu", "kanglish"),
    ("Take me to March 2025", "en"), ("what happened in that room with the cake?", "en"),
    ("मुझे होली वाले कमरे में ले चलो", "hi"), ("ನನ್ನನ್ನು ಮಾರ್ಚ್ ಕೊಠಡಿಗೆ ಕರೆದುಕೊಂಡು ಹೋಗಿ", "kn"),
    ("Dadi, Diwali pe kya kiya tha?", "hinglish"), ("Ajji, Deepavali alli enu maadidvi?", "kanglish"),
]

STYLE_BANNED = re.compile(r"as an ai|language model|how can i (help|assist) you|i hope this helps|great question|"
                          r"let me know if|^\s*[-*•]\s|^\s*\d+[.)]\s|\*\*|#{1,6}\s|`", re.I | re.M)
RESULTS: dict[str, list[bool]] = {}
STYLE_SAMPLES: list[str] = []


def _record(bucket: str, ok: bool, line: str) -> None:
    RESULTS.setdefault(bucket, []).append(ok)
    print(("OK " if ok else "XX ") + line)


def _report(bucket: str) -> float:
    r = RESULTS.get(bucket, [])
    acc = sum(r) / len(r) if r else 0.0
    print(f"\n== {bucket}: {sum(r)}/{len(r)} = {acc:.0%}")
    return acc


def style_problems(text: str) -> list[str]:
    probs = []
    if STYLE_BANNED.search(text):
        probs.append("banned phrase / markdown / list")
    for s in re.split(r"(?<=[.!?।])\s+", text.strip()):
        if len(s.split()) > 28:
            probs.append(f"long sentence ({len(s.split())} words)")
    return probs


# ---------------------------------------------------------------- code-only buckets

async def test_dates_code():
    for expr, want in DATES_CODE:
        got = _resolved(expr)
        _record("dates_code", got == want, f"{expr!r} -> {R.to_english_dates(expr)!r} -> {got} (want {want})")
    for expr, want in DATES_ROUTE:
        got = _resolved(expr, route=True)
        _record("dates_code", got == want, f"route {expr!r} -> {got} (want {want})")
    assert _report("dates_code") >= 0.9


async def test_confirmations():
    for text, y, n in CONFIRM:
        ok = L.is_yes(text) == y and L.is_no(text) == n
        _record("confirm", ok, f"{text!r} yes={L.is_yes(text)} no={L.is_no(text)} (want {y}/{n})")
    assert _report("confirm") >= 0.95


async def test_language_detection():
    for text, want in DETECT:
        got = R.detect(text)["register"]
        _record("detect", got == want, f"{text!r} -> {got} (want {want})")
    assert R.reply_lang("kal ki photos daal do", "en-IN") == "hi-IN"
    assert R.reply_lang("Take me to March 2025", "hi-IN") == "hi-IN"
    assert _report("detect") >= 0.9


async def test_keyword_router_offline():
    for lang, text, want, _check in RX:
        plan = reception.keyword_plan(text)
        got = plan[0][0] if plan else "none"
        _record("keywords", got == want, f"[{lang}] {text!r} -> {got} {plan[0][1] if plan else ''} (want {want})")
    assert _report("keywords") >= 0.8


# ---------------------------------------------------------------- real LLM buckets

async def test_receptionist_intent_and_args_real_llm():
    for lang, text, want, check in RX:
        got, args = await reception.route_intent(text, lang)
        ok = got == want and (check is None or bool(check(args)))
        _record("receptionist", ok, f"[{lang}] {text!r} -> {got} {args} (want {want})")
    assert _report("receptionist") >= 0.9


async def test_dates_via_llm():
    for lang, text, want in DATES_LLM:
        got, args = await reception.route_intent(text, lang)
        label = _resolved(str(args.get("when") or ""))
        _record("dates_llm", got == "query_gallery" and label == want,
                f"[{lang}] {text!r} -> {got} when={args.get('when')!r} -> {label} (want {want})")
    assert _report("dates_llm") >= 0.9


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def fam():
    await fresh_pool()
    f = await make_family(grandma="Ajji")
    fid, asha, ravi = f["id"], f["owner"], f["editor"]
    await add_memory(fid, asha, 2026, 11, 8, "text", "Lighting the lamps on the terrace",
                     "Asha and Meera lit forty diyas on the terrace while Ravi burst crackers.",
                     festival="Diwali", people=["Meera", "Ravi"])
    await add_memory(fid, ravi, 2026, 11, 9, "voice", "Kaju katli from Lakshmi Sweets",
                     "Ravi bought two boxes of kaju katli from Lakshmi Sweets in Jayanagar.",
                     festival="Diwali", people=["Ravi"])
    await add_memory(fid, asha, 2026, 11, 12, "text", "Missing Nani this Diwali",
                     "Our first Diwali without Nani. We kept her brass lamp lit all night.",
                     festival="Diwali", people=["Nani"], sensitivity="loss")
    await add_memory(fid, asha, 2026, 11, 20, "photo", "Meera's birthday cake",
                     "Meera turned eight. Ravi baked a chocolate cake shaped like a cat and it collapsed, everyone laughed.",
                     people=["Meera", "Ravi"])
    await add_memory(fid, ravi, 2026, 3, 14, "text", "Holi in the colony",
                     "We played Holi in the colony park. Meera's face was blue for two days.",
                     festival="Holi", people=["Meera"])
    yield f
    await drop_family(fid)


NOV = {"year": 2026, "month": 11}
# (question, scope, expected source, any-of keywords that must appear in the answer)
GRANDMA = [
    ("Who bought the sweets?", NOV, "family", ["ravi", "रवि", "ರವಿ"]),
    ("what happened in that room with the cake?", NOV, "family", ["cake", "meera", "collaps", "cat"]),
    ("how many diyas did they light?", NOV, "family", ["forty", "40"]),
    ("tell me about the lamps", NOV, "family", ["forty", "40", "terrace", "diya", "lamp"]),
    ("who brougt the swets?", NOV, "family", ["ravi"]),
    ("Diwali pe kya kiya tha humne?", NOV, "family", ["diye", "diya", "lamp", "terrace", "chhat", "40", "forty",
                                                       "kaju", "mithai", "sweets"]),
    ("mithai kaun laaya tha?", NOV, "family", ["ravi"]),
    ("Meera ka birthday kaisa tha?", NOV, "family", ["cake", "eight", "8", "aath"]),
    ("kitne diye jalaye the?", NOV, "family", ["40", "forty", "chaalis", "chalis"]),
    ("Deepavali alli enu maadidvi?", NOV, "family", ["deepa", "diya", "diye", "lamp", "40", "forty", "terrace",
                                                     "taarasi", "kaju", "sweets"]),
    ("sweets yaaru tandru?", NOV, "family", ["ravi"]),
    ("दिवाली पर मिठाई कौन लाया था?", NOV, "family", ["ravi", "रवि"]),
    ("ದೀಪಾವಳಿಗೆ ಸಿಹಿ ಯಾರು ತಂದರು?", NOV, "family", ["ravi", "ರವಿ"]),
    ("what did we do on Holi?", NOV, "family", ["blue", "colony", "park", "colour", "color"]),
    ("what car did grandpa drive?", NOV, "none", []),
    ("dadaji ki pehli naukri kya thi?", NOV, "none", []),
]


async def test_grandma_talk_real_llm(fam):
    for q, scope, want_src, words in GRANDMA:
        st: dict = {}
        lang, reg = reception.turn_register(q, "en-IN", st)
        res = await grandma.answer(fam["id"], q, dict(scope), lang, st, register=reg)
        text = " ".join(s["text"] for s in res["sentences"])
        ok = res["source"] == want_src and (not words or any(w.lower() in text.lower() for w in words))
        if want_src == "family":
            STYLE_SAMPLES.append(text)
        _record("grandma", ok, f"[{reg}] {q!r} -> {res['source']}: {text}")
    assert _report("grandma") >= 0.9


CHAT = [("hi!", "en-IN"), ("kaise ho?", "en-IN"), ("hegiddira?", "en-IN"), ("good morning robot", "en-IN")]


async def test_style_rules(fam):
    if not STYLE_SAMPLES:          # run alone: collect a few Grandma answers first
        for q, scope, _src, _w in GRANDMA[:5]:
            st: dict = {}
            lang, reg = reception.turn_register(q, "en-IN", st)
            res = await grandma.answer(fam["id"], q, dict(scope), lang, st, register=reg)
            STYLE_SAMPLES.append(" ".join(s["text"] for s in res["sentences"]))
    for text, lang in CHAT:      # receptionist small talk (no tool): the model's own words
        out = await reception.act_core(fam["id"], fam["owner"], text, lang, use_llm=True)
        STYLE_SAMPLES.append(out["reply"])
        print(f"chat {text!r} -> {out['reply']!r}")
    # the fixed lines and the Hinglish / Kanglish overlays obey the same rules
    for key, row in L.T.items():
        for v in row.values():
            STYLE_SAMPLES.append(v.format_map({k: "x" for k in re.findall(r"{(\w+)}", v)}))
    for text in STYLE_SAMPLES:
        probs = style_problems(text)
        _record("style", not probs, f"{text[:110]!r} {probs}")
    assert _report("style") >= 0.95
