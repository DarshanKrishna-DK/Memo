"""The spoken side of the invite call (ported from MedSim's observer_call.py).

Twilio asks for instructions one turn at a time. The opener plays INSIDE <Gather input="speech"> so the guest
can talk over it. The agent may only use: host name, event title, month and year. Max 6 turns, <=22 words per
answer, <=5 guest messages kept. Calls are never recorded.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
from typing import Any, Optional
from urllib.parse import parse_qsl
from xml.sax.saxutils import escape as xml_escape

from .. import config, db
from ..ai import llm
from . import invites as inv

log = logging.getLogger("memo.phone.call")

MAX_TURNS = 6
MAX_REPLY_WORDS = 22
MAX_MESSAGES = 5
LLM_TIMEOUT_S = 5.0
TTS_TIMEOUT_S = 3.0
OPENER_TTS_TIMEOUT_S = 8.0

MONTHS = {
    "en-IN": inv.MONTHS_EN,
    "hi-IN": ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"],
    "kn-IN": ["ಜನವರಿ", "ಫೆಬ್ರವರಿ", "ಮಾರ್ಚ್", "ಏಪ್ರಿಲ್", "ಮೇ", "ಜೂನ್", "ಜುಲೈ", "ಆಗಸ್ಟ್", "ಸೆಪ್ಟೆಂಬರ್", "ಅಕ್ಟೋಬರ್",
              "ನವೆಂಬರ್", "ಡಿಸೆಂಬರ್"],
}
NO_EVENT = {"en-IN": "the family's memories", "hi-IN": "परिवार की यादें", "kn-IN": "ಕುಟುಂಬದ ನೆನಪುಗಳು"}

OPENER = {
    "en-IN": ("Hello {name}. This is an automated assistant calling for Memo. {host} has invited you to {what}, "
              "in the {month} {year} room of their family's memory museum. Would you like to join? "
              "You can ask me who, what, when or how. If you don't want calls, say stop calling me."),
    "hi-IN": ("नमस्ते {name}। मैं Memo की ओर से कॉल कर रहा एक स्वचालित असिस्टेंट हूँ। {host} ने आपको {month} {year} "
              "के कमरे में {what} के लिए आमंत्रित किया है। क्या आप जुड़ना चाहेंगे? आप पूछ सकते हैं कि कौन, क्या, कब या कैसे। "
              "अगर कॉल नहीं चाहिए, तो कहिए, कॉल करना बंद करो।"),
    "kn-IN": ("ನಮಸ್ಕಾರ {name}. ನಾನು Memo ಪರವಾಗಿ ಕರೆ ಮಾಡುತ್ತಿರುವ ಸ್ವಯಂಚಾಲಿತ ಸಹಾಯಕ. {host} ಅವರು ನಿಮ್ಮನ್ನು {month} {year} "
              "ಕೋಣೆಯಲ್ಲಿ {what} ಗೆ ಆಹ್ವಾನಿಸಿದ್ದಾರೆ. ನೀವು ಸೇರಲು ಬಯಸುತ್ತೀರಾ? ಯಾರು, ಏನು, ಯಾವಾಗ, ಹೇಗೆ ಎಂದು ಕೇಳಬಹುದು. "
              "ಕರೆ ಬೇಡವಾದರೆ, ಕರೆ ಮಾಡಬೇಡಿ ಎಂದು ಹೇಳಿ."),
}
LINES = {
    "goodbye": {"en-IN": "Thank you. Goodbye.", "hi-IN": "धन्यवाद। नमस्ते।", "kn-IN": "ಧನ್ಯವಾದ. ನಮಸ್ಕಾರ."},
    "reprompt": {"en-IN": "Hello, are you still there? Would you like to join?",
                 "hi-IN": "हेलो, क्या आप वहाँ हैं? क्या आप जुड़ना चाहेंगे?",
                 "kn-IN": "ಹಲೋ, ನೀವು ಇದ್ದೀರಾ? ನೀವು ಸೇರಲು ಬಯಸುತ್ತೀರಾ?"},
    "stop": {"en-IN": "Understood. I will not call you again. Sorry to have bothered you. Goodbye.",
             "hi-IN": "समझ गया। मैं आपको दोबारा कॉल नहीं करूँगा। परेशान करने के लिए क्षमा करें। नमस्ते।",
             "kn-IN": "ಅರ್ಥವಾಯಿತು. ಇನ್ನು ಕರೆ ಮಾಡುವುದಿಲ್ಲ. ತೊಂದರೆಗಾಗಿ ಕ್ಷಮಿಸಿ. ನಮಸ್ಕಾರ."},
    "accepted": {"en-IN": "Lovely. I am sending you the link now. It works for 24 hours. Goodbye.",
                 "hi-IN": "बहुत अच्छा। मैं अभी आपको लिंक भेज रहा हूँ। यह 24 घंटे चलेगा। नमस्ते।",
                 "kn-IN": "ತುಂಬಾ ಒಳ್ಳೆಯದು. ಈಗ ಲಿಂಕ್ ಕಳುಹಿಸುತ್ತಿದ್ದೇನೆ. ಇದು 24 ಗಂಟೆ ಕೆಲಸ ಮಾಡುತ್ತದೆ. ನಮಸ್ಕಾರ."},
    "declined": {"en-IN": "No problem. Thank you for your time. Goodbye.",
                 "hi-IN": "कोई बात नहीं। आपके समय के लिए धन्यवाद। नमस्ते।",
                 "kn-IN": "ಪರವಾಗಿಲ್ಲ. ನಿಮ್ಮ ಸಮಯಕ್ಕೆ ಧನ್ಯವಾದ. ನಮಸ್ಕಾರ."},
    "message": {"en-IN": "I will pass that on. Goodbye.", "hi-IN": "मैं यह संदेश पहुँचा दूँगा। नमस्ते।",
                "kn-IN": "ಈ ಸಂದೇಶವನ್ನು ತಲುಪಿಸುತ್ತೇನೆ. ನಮಸ್ಕಾರ."},
    "trouble": {"en-IN": "Sorry, I had a glitch. Would you like to join the room?",
                "hi-IN": "क्षमा करें, कुछ गड़बड़ हो गई। क्या आप कमरे में जुड़ना चाहेंगे?",
                "kn-IN": "ಕ್ಷಮಿಸಿ, ಏನೋ ತೊಂದರೆಯಾಯಿತು. ನೀವು ಕೋಣೆಗೆ ಸೇರಲು ಬಯಸುತ್ತೀರಾ?"},
}
HINTS = {
    "en-IN": "yes, no, sure, okay, who, what, when, how, Memo, stop calling me, leave a message",
    "hi-IN": "haan, nahi, theek hai, kaun, kya, kab, kaise, Memo, call mat karo",
    "kn-IN": "houdu, illa, sari, yaaru, enu, yaavaga, hege, Memo",
}

STOP_RE = re.compile(
    r"stop\s+(calling|call|phoning)|(do\s*n[o']?t|never|no\s+more)\s+(call|phone|ring)|remove\s+(me|my number)|"
    r"take\s+me\s+off|(call|phone)\s+(mat|na)\s+kar|mat\s+(call|phone)|call\s+band|कॉल\s*(मत|न)\s*कर|कॉल\s*(करना\s*)?बंद|"
    r"फ़?ोन\s*(मत|न)\s*कर|बंद\s*करो|ಕರೆ\s*ಮಾಡ(ಬೇಡ|ಬೇಡಿ)|ಕರೆ\s*ಬೇಡ|call\s+maadabedi", re.I)
YES_RE = re.compile(r"^\W*(yes|yeah|yep|sure|okay|ok|of course|please|join|haan|ha|ji haan|theek hai|ठीक है|हाँ|हां|जी|houdu|ಹೌದು|ಸರಿ)\b", re.I)
NO_RE = re.compile(r"^\W*(no|nope|not now|not interested|nahi|nahin|नहीं|नही|illa|ಇಲ್ಲ)\b", re.I)


def lang_of(c: Any) -> str:
    return c["language"] if c["language"] in config.LANGUAGES else "en-IN"


# ------------------------------------------------------------------ Twilio signature

def twilio_signature(auth_token: str, url: str, params: list[tuple[str, str]]) -> str:
    data = url + "".join(k + v for k, v in sorted(params))
    return base64.b64encode(hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()).decode()


async def read_params(request) -> list[tuple[str, str]]:
    if request.method != "POST":
        return []
    return parse_qsl((await request.body())[:20000].decode("utf-8", "replace"), keep_blank_values=True)


def webhook_token(cs_id: str) -> str:
    """Per-call secret for Twilio webhook URLs (HMAC of the call session id with APP_SECRET). Used when a proxy in
    front of us (e.g. a Cloudflare quick tunnel) strips the X-Twilio-Signature header; Twilio's docs allow
    authenticating webhooks with credentials in the URL."""
    return hmac.new(config.APP_SECRET.encode(), f"twilio:{cs_id}".encode(), hashlib.sha256).hexdigest()[:32]


def webhook_url(cs_id: str, kind: str) -> str:
    return f"{config.PUBLIC_BASE_URL}/twilio/voice/{cs_id}/{kind}?t={webhook_token(cs_id)}"


def signature_ok(request, params: list[tuple[str, str]]) -> bool:
    """Validate X-Twilio-Signature against PUBLIC_BASE_URL + path. No auth token configured -> reject (never open)."""
    token = config.env("TWILIO_AUTH_TOKEN")
    sent = request.headers.get("x-twilio-signature", "")
    if not sent:
        # Header stripped by the proxy: accept only with the per-call secret in the URL.
        cs_id = (request.path_params or {}).get("cs_id") or ""
        t = request.query_params.get("t", "")
        if cs_id and t and hmac.compare_digest(t, webhook_token(cs_id)):
            return True
    if not token or not sent:
        import logging
        logging.getLogger("memo.twilio").warning("twilio webhook without signature (token=%s, header=%s, headers=%s)",
                                                 bool(token), bool(sent), ",".join(request.headers.keys()))
        return False
    q = request.url.query
    url = config.PUBLIC_BASE_URL + request.url.path + (f"?{q}" if q else "")
    body = params if request.method == "POST" else []
    # Same variants Twilio's official RequestValidator accepts: the URL as configured and with the default port
    # (Twilio sometimes signs "https://host:443/path").
    variants = [url]
    scheme, _, rest = url.partition("://")
    host, slash, path = rest.partition("/")
    if ":" not in host:
        variants.append(f"{scheme}://{host}:{443 if scheme == 'https' else 80}{slash}{path}")
    ok = any(hmac.compare_digest(twilio_signature(token, u, body), sent) for u in variants)
    if not ok:
        import logging
        logging.getLogger("memo.twilio").warning("signature mismatch for %s (keys=%s, host=%s, fwd_host=%s)", url,
                                                 ",".join(k for k, _ in params), request.headers.get("host"),
                                                 request.headers.get("x-forwarded-host"))
    return ok


# ------------------------------------------------------------------ context + text

async def load_call(cs_id: str) -> Optional[dict]:
    r = await db.fetchrow(
        "SELECT cs.id AS cs_id, cs.invite_id, cs.status, cs.turns, cs.transcript, cs.ended_at, i.family_id, i.year, i.month, "
        "i.event_id, c.id AS contact_id, c.name AS contact_name, c.language, "
        "(SELECT nickname FROM members m WHERE m.id=i.host_member_id) AS host, "
        "(SELECT name FROM events e WHERE e.id=i.event_id) AS event_name "
        "FROM call_sessions cs JOIN invites i ON i.id=cs.invite_id LEFT JOIN contacts c ON c.id=i.contact_id WHERE cs.id=$1",
        cs_id)
    return dict(r) if r else None


def context(call: dict) -> dict:
    """The ONLY facts the agent may speak from."""
    lang = call["language"] if call["language"] in config.LANGUAGES else "en-IN"
    return {"lang": lang, "guest": (call["contact_name"] or "").split(" ")[0] or "there",
            "host": call["host"] or "a family member", "event": call["event_name"],
            "month_en": inv.MONTHS_EN[call["month"] - 1], "month": MONTHS[lang][call["month"] - 1], "year": call["year"]}


def opener_text(ctx: dict) -> str:
    return OPENER[ctx["lang"]].format(name=ctx["guest"], host=ctx["host"], what=ctx["event"] or NO_EVENT[ctx["lang"]],
                                      month=ctx["month"], year=ctx["year"])


def cap_reply(reply: str) -> str:
    t = re.sub(r"[*_#`]", "", (reply or "")).strip()
    if len(t.split()) <= MAX_REPLY_WORDS:
        return t
    out: list[str] = []
    for sent in re.split(r"(?<=[.!?।])\s+", t):
        if len(" ".join(out + [sent]).split()) > MAX_REPLY_WORDS:
            break
        out.append(sent)
    return " ".join(out) if out else " ".join(t.split()[:MAX_REPLY_WORDS]).rstrip(",;:") + "."


def build_system(ctx: dict) -> str:
    return (
        f"You are an automated phone assistant calling for Memo, a family memory museum. You called {ctx['guest']} "
        f"on behalf of {ctx['host']}, who invites them to {ctx['event'] or 'see the family memories'} in the "
        f"{ctx['month_en']} {ctx['year']} room, by opening a link we will send them.\n"
        "FACTS YOU MAY USE: the host's name, the event title, the month and year, and that a link will be sent to join "
        "(works in any browser for 24 hours). You know NOTHING else. Never describe photos or memories. If asked anything "
        "else say you only know the invitation details.\n"
        f"Reply in {inv.LANG_LABELS[ctx['lang']]}, at most {MAX_REPLY_WORDS} words, plain speech, no lists.\n"
        'Return ONLY JSON: {"reply": str, "intent": "accept"|"decline"|"message"|"question"|"end", "message": str}. '
        "intent=accept when they agree to join; decline when they refuse; message when they ask you to pass something to "
        f"{ctx['host']} (put their words in message); question for who/what/when/how; end when they want to hang up."
    )


def _parse(raw: str) -> dict:
    t = llm.strip_think(raw or "").strip()
    m = re.search(r"\{.*\}", t, re.S)
    data: dict = {}
    if m:
        try:
            data = json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            data = {}
    if not isinstance(data, dict) or not data.get("reply"):
        return {}
    intent = str(data.get("intent") or "question").lower()
    if intent not in ("accept", "decline", "message", "question", "end"):
        intent = "question"
    return {"reply": cap_reply(str(data["reply"])), "intent": intent, "message": str(data.get("message") or "")[:300]}


def heuristic_intent(speech: str) -> str:
    if YES_RE.search(speech):
        return "accept"
    if NO_RE.search(speech):
        return "decline"
    return "question"


async def answer(ctx: dict, transcript: list[dict], speech: str) -> dict:
    msgs: list[dict] = [{"role": "system", "content": build_system(ctx)}]
    for line in transcript[-8:]:
        msgs.append({"role": "assistant" if line["who"] == "agent" else "user", "content": line["text"]})
    msgs.append({"role": "user", "content": speech})
    try:
        msg, _ = await asyncio.wait_for(llm.chat(msgs, max_tokens=220, temperature=0.4, json_mode=True), LLM_TIMEOUT_S)
        out = _parse(msg.get("content") or "")
        if out:
            return out
    except Exception as e:  # noqa: BLE001
        log.warning("invite call LLM failed: %s", type(e).__name__)
    intent = heuristic_intent(speech)
    return {"reply": LINES["trouble"][ctx["lang"]] if intent == "question" else "", "intent": intent, "message": "",
            "fallback": True}


# ------------------------------------------------------------------ audio + TwiML

async def speech_url(text: str, lang: str, timeout: float = TTS_TIMEOUT_S) -> Optional[str]:
    """Murf/Sarvam audio from the voice-ai agent's TTS as a public signed URL, or None (then <Say>)."""
    if not inv.public_url_ready():
        return None
    try:
        from ..ai import tts
        from .. import storage
        res = await asyncio.wait_for(tts.synthesize(text, lang), timeout)
        return storage.signed_url(res["storage_key"], 3600, absolute=True)
    except Exception as e:  # noqa: BLE001
        log.warning("invite call TTS unavailable (%s): falling back to <Say>", type(e).__name__)
        return None


def speak(text: str, url: Optional[str], lang: str) -> str:
    if url:
        return f"<Play>{xml_escape(url)}</Play>"
    return f'<Say language="{lang}">{xml_escape(text)}</Say>'


def twiml_gather(cs_id: str, lang: str, say: str, say_url: Optional[str], bye: str, bye_url: Optional[str]) -> str:
    """The line is nested INSIDE <Gather> so the guest can talk over it."""
    action = webhook_url(cs_id, "turn")
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'<Gather input="speech" language="{lang}" speechTimeout="auto" actionOnEmptyResult="true" '
            f'hints="{xml_escape(HINTS[lang])}" action="{xml_escape(action)}" method="POST">'
            + speak(say, say_url, lang) + "</Gather>" + speak(bye, bye_url, lang) + "</Response>")


def twiml_hangup(text: str, url: Optional[str], lang: str) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response>' + speak(text, url, lang) + "<Hangup/></Response>"


# ------------------------------------------------------------------ turns

_PREPARED: dict[str, Optional[str]] = {}   # cs_id -> opener audio URL prepared before dialling (None = use <Say>)


async def prepare_opener(cs_id: str) -> None:
    """Synthesise the opener BEFORE the call is placed (Twilio gives the TwiML request ~15 s; TTS can take ~10 s)."""
    call = await load_call(cs_id)
    if not call:
        return
    ctx = context(call)
    _PREPARED[cs_id] = await speech_url(opener_text(ctx), ctx["lang"], OPENER_TTS_TIMEOUT_S)


async def start(cs_id: str) -> str:
    call = await load_call(cs_id)
    if not call or call["ended_at"]:
        return twiml_hangup("Goodbye.", None, "en-IN")
    ctx = context(call)
    await inv.set_progress(cs_id, "talking")
    text = opener_text(ctx)
    await _log(cs_id, "agent", text)
    url = _PREPARED.pop(cs_id, None)   # never synthesise while Twilio waits; fall back to <Say>
    bye = LINES["goodbye"][ctx["lang"]]
    return twiml_gather(cs_id, ctx["lang"], text, url, bye, None)


async def _log(cs_id: str, who: str, text: str, kind: str = "line") -> None:
    await db.execute(
        "UPDATE call_sessions SET transcript = transcript || $2::jsonb WHERE id=$1",
        cs_id, [{"who": who, "text": text[:400], "kind": kind}])


async def turn(cs_id: str, speech: str) -> str:
    call = await load_call(cs_id)
    if not call:
        return twiml_hangup("Goodbye.", None, "en-IN")
    ctx = context(call)
    lang = ctx["lang"]
    speech = (speech or "").strip()[:400]
    if call["ended_at"]:
        return twiml_hangup(LINES["goodbye"][lang], None, lang)

    turns = await db.fetchval("UPDATE call_sessions SET turns=turns+1 WHERE id=$1 RETURNING turns", cs_id)

    async def close(key: str, status: Optional[str], summary: str = "", message: Optional[str] = None) -> str:
        if status:
            await inv.finish_call(cs_id, status, summary, message)
        line = LINES[key][lang]
        await _log(cs_id, "agent", line)
        return twiml_hangup(line, await speech_url(line, lang), lang)

    if not speech:
        silent = sum(1 for t in (call["transcript"] or []) if t.get("kind") == "silence")
        await _log(cs_id, "guest", "", "silence")
        if silent >= 1 or turns >= MAX_TURNS:
            return await close("goodbye", "no_answer", "The phone was answered but nobody replied.")
        line = LINES["reprompt"][lang]
        await _log(cs_id, "agent", line)
        return twiml_gather(cs_id, lang, line, await speech_url(line, lang), LINES["goodbye"][lang], None)

    await _log(cs_id, "guest", speech)
    if STOP_RE.search(speech):
        await inv.mark_do_not_call(str(call["contact_id"]))
        return await close("stop", "declined", "Asked not to be called again. Marked do-not-call.")

    out = await answer(ctx, call["transcript"] or [], speech)
    intent, reply = out["intent"], out["reply"]
    if intent == "message":
        existing = sum(1 for t in (call["transcript"] or []) if t.get("kind") == "message")
        msg = out["message"] or speech
        if existing < MAX_MESSAGES:
            await _log(cs_id, "guest", msg, "message")
            await db.execute("UPDATE call_sessions SET message_text = coalesce(message_text || E'\\n', '') || $2 WHERE id=$1",
                             cs_id, msg)
            from .. import bus
            await bus.publish(str(call["family_id"]), {"type": "guest_message", "invite_id": str(call["invite_id"]),
                                                       "contact_name": call["contact_name"], "text": msg})
        row = await db.fetchrow("SELECT message_text FROM call_sessions WHERE id=$1", cs_id)
        return await close("message", "message_left", f"{call['contact_name']} left a message.", row["message_text"])
    if intent == "accept":
        return await close("accepted", "accepted", f"{call['contact_name']} accepted. The link was sent.")
    if intent in ("decline", "end"):
        return await close("declined", "declined", f"{call['contact_name']} declined the invitation.")
    if turns >= MAX_TURNS:
        return await close("goodbye", "no_answer", "The call ended without a decision.")
    reply = reply or LINES["trouble"][lang]
    await _log(cs_id, "agent", reply)
    return twiml_gather(cs_id, lang, reply, await speech_url(reply, lang), LINES["goodbye"][lang], None)
