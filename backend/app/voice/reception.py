"""The receptionist: a bounded tool loop (<= 4 steps) over create_event, query_gallery, import_gallery, plan_route,
change_setting and invite_contact (+ decline). Ported from MedSim backend/reception.py.

    await act(family_id, member_id, text, language=None, state_key=..., role=...) ->
        {"reply", "speech": Speech, "action": {"type": route|event_created|import_started|setting_changed|
                                                        invite_called|none, "data"}, "source": llm|keywords|state,
         "steps": [...], "language", "pending": {...}|None}

Rules (PRD "The receptionist"):
  * The model picks a tool and fills arguments; the server validates every argument and runs the same core service
    the buttons call. The spoken result is written here from the facts the service returns (never by the model).
  * Dates are never worked out by the model: it returns the words ("yesterday", "November 2026") and
    app.core.dates.resolve_when resolves them. A `when` the user never said is ignored (no guessing); a missing
    year or month gets exactly one question.
  * Bulk imports and phone calls are confirmed aloud first: the count + size (gallery preview token) or the contact
    (name + last four digits) is read out and only a "yes" (matched in code, not by the model) acts.
  * Face / content based selection is declined honestly. When the LLM is down a keyword router runs the same tools.
Conversation state (pending confirmation, current event) lives in voice_state (app/voice/state.py).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any, Optional

from fastapi import HTTPException

from .. import config, db, flags
from ..ai import llm
from . import grounding, speech, state as vstate
from . import lang as L
from . import register as R

log = logging.getLogger("memo.reception")
MAX_STEPS = 4
WRITE_ROLES = ("owner", "editor")

# ---------------------------------------------------------------- tool specs (OpenAI format)

def _fn(name: str, desc: str, props: dict, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props, "required": required or []}}}


WHEN_DESC = ("The date words the USER said, translated to English but otherwise verbatim, e.g. 'November 2026', "
             "'yesterday', 'last year', '23 Nov'. Omit when the user gave no date. Never invent or complete a date.")
TOOLS = [
    _fn("create_event", "Add a new event (festival, trip, birthday or other) to the museum.", {
        "name": {"type": "string", "description": "Event name as the user said it, in English letters, e.g. 'Diwali'"},
        "kind": {"type": "string", "enum": ["festival", "trip", "birthday", "other"]},
        "when": {"type": "string", "description": WHEN_DESC}}, ["name"]),
    _fn("query_gallery", "Find photos in the family's gallery by metadata (date, size, camera, folder, all, latest N). "
        "Reads out the count; nothing is imported.", {
        "when": {"type": "string", "description": WHEN_DESC},
        "all": {"type": "boolean", "description": "The user asked for all / everything"},
        "latest_n": {"type": "integer", "description": "'the last 20' -> 20"},
        "camera": {"type": "string"}, "folder": {"type": "string"},
        "min_size_mb": {"type": "number"}, "max_size_mb": {"type": "number"},
        "type": {"type": "string", "enum": ["jpeg", "png", "webp"]},
        "event_name": {"type": "string", "description": "Event the user wants them added to, if named"}}),
    _fn("import_gallery", "Import the photos whose count was just read out. Only after the user said yes.", {
        "confirm": {"type": "boolean"}}, ["confirm"]),
    _fn("plan_route", "Take the user to a room: a month and year, or an event ('Diwali 2026', 'last year's Holi', "
        "'March 2025').", {"place": {"type": "string", "description": "The room or event words, in English, verbatim"}},
        ["place"]),
    _fn("change_setting", "Change a museum setting.", {
        "key": {"type": "string", "enum": ["language", "grandma_name", "sarcasm", "closed_with_care", "keep_location"]},
        "value": {"type": "string", "description": "language: en-IN|hi-IN|kn-IN; grandma_name: the name; sarcasm / "
                  "keep_location: on|off; closed_with_care: on|off"},
        "when": {"type": "string", "description": "closed_with_care only: the room's month and year words"}},
        ["key", "value"]),
    _fn("invite_contact", "Invite a saved contact into a room by phone. The call is confirmed aloud first.", {
        "who": {"type": "string", "description": "Name or relation, e.g. 'Priya', 'my sister'"},
        "place": {"type": "string", "description": "Room or event words if the user named one"}}, ["who"]),
    _fn("decline", "The request needs something the desk cannot do (recognising faces or what is inside photos, "
        "anything else outside these tools).", {
        "reason": {"type": "string", "enum": ["face_recognition", "out_of_scope"]}}, ["reason"]),
]
TOOL_NAMES = [t["function"]["name"] for t in TOOLS]


RX_EXAMPLES = """Examples (what the user says -> the one tool call):
- "Take me to the Diwali 2026 room" / "bhai mujhe Diwali wale room mein le chalo" / "Diwali 2026 room ge karkondu hogu" -> plan_route(place="Diwali 2026" or "Diwali")
- "I wanna see what we did last Holi" / "pichli Holi dikhao" -> plan_route(place="last Holi")
- "show me Nov 26" / "Nov 26 kholo" -> plan_route(place="Nov 26")
- "March 2025 wala kamra" / "ಮಾರ್ಚ್ 2025 ಕೊಠಡಿಗೆ ಹೋಗೋಣ" -> plan_route(place="March 2025")
- "kal ki saari photos daal do Diwali 2026 mein" -> query_gallery(when="yesterday", all=true, event_name="Diwali 2026")
- "ninne photos ella add maadu" -> query_gallery(when="yesterday", all=true)
- "parso wali pics upload karo" -> query_gallery(when="day before yesterday")
- "pichle mahine ki photos" / "last month's pics" -> query_gallery(when="last month")
- "last 20 photos daalo" -> query_gallery(latest_n=20)
- "naya event banao Holi ke liye March 2025" -> create_event(name="Holi", kind="festival", when="March 2025")
- "Coorg trip add karo" / "hosa trip seri Coorg" -> create_event(name="Coorg", kind="trip")
- "last year wala Diwali event banao" -> create_event(name="Diwali", kind="festival", when="last year")
- "sarcasm band karo" / "vyangya beda" -> change_setting(key="sarcasm", value="off")
- "Dadi ka naam Nani rakh do" -> change_setting(key="grandma_name", value="Nani")
- "Priya ko is room mein bulao" / "Priya na karesi" -> invite_contact(who="Priya")
- "what happened in that room with the cake?" / "cake wali photos" / "photos with my dad in them" -> decline(reason="face_recognition")
- "hi" / "kaise ho?" / "hegiddira?" -> no tool, one short friendly line"""


def system_prompt(lang: str, st: dict, room: Optional[dict], today: date, register: Optional[str] = None) -> str:
    ctx = {"today": today.isoformat(), "current_event": st.get("current_event"),
           "pending": (st.get("pending") or {}).get("kind"), "visitor_room": room or None}
    reg = register or L.norm(lang)
    style = {"hinglish": "The user talks Hinglish (Roman-script Hindi + English): any chat reply is natural Hinglish "
                         "in Roman letters.",
             "kanglish": "The user talks Kanglish (Roman-script Kannada + English): any chat reply is natural Kanglish "
                         "in Roman letters."}.get(reg, L.language_rule(lang))
    return (
        "You are the receptionist robot at the front desk of a family memory museum: friendly, crisp, upbeat, "
        "efficient but warm. You act only through your tools: create_event, query_gallery, import_gallery, "
        "plan_route, change_setting, invite_contact, decline. People talk any way they like: English, Hindi, Kannada, "
        "Hinglish, Kanglish, Roman or native script, slang, typos, half sentences, indirect wishes ('I wanna see...'). "
        "Work out what they want and make ONE tool call.\n"
        "DATES: never work them out. Copy the user's date words into `when`, translated to English but not resolved "
        "(kal -> 'yesterday', parso -> 'day before yesterday', ninne -> 'yesterday', monne -> 'day before yesterday', "
        "pichle mahine / kalada tingalu -> 'last month', last year wala / pichle saal / hoda varsha -> 'last year', "
        "'Nov 26' stays 'Nov 26'). If they gave no date, omit `when`. A year inside an event name ('Diwali 2026') "
        "belongs to the event, not to `when`.\n"
        "PLACES: `place` holds only the event and date words (drop bhai, mujhe, room, wala, le chalo, karkondu hogu, "
        "I wanna see, what we did).\n"
        "Photos are chosen by date, size, camera, folder, all or latest N only; choosing by who or what is in them "
        "-> decline(face_recognition). Phone numbers are never taken by voice. Inviting, calling or bringing a person "
        "into a room -> invite_contact. Anything no tool does -> decline(out_of_scope).\n"
        + RX_EXAMPLES + "\n"
        "If they are only greeting or chatting, make no tool call and reply with one short, warm, spoken sentence that "
        "reacts to what they said, in their style. Never 'How can I help you today', never 'As an AI', no lists, no "
        "markdown, no emojis. " + style + "\nContext: " + json.dumps(ctx, default=str)
    )


# ---------------------------------------------------------------- dates (code, never the model)

_DIGITS = str.maketrans("०१२३४५६७८९೦೧೨೩೪೫೬೭೮೯", "01234567890123456789")
RELATIVE_EN = re.compile(r"\b(today|yesterday|tomorrow|ago|last|this|next|previous|week|weekend)\b", re.I)
RELATIVE_ANY = re.compile(RELATIVE_EN.pattern + r"|परसों|कल|आज|पिछल|इस\s|ನಿನ್ನೆ|ಮೊನ್ನೆ|ಇವತ್ತು|ಇಂದು|ಕಳೆದ|ಹೋದ|ಈ\s|"
                          r"\bkal\b|\baaj\b|pichhle|pichle|pichla|parso|ninne|monne|kaleda|hoda", re.I)


def to_english_dates(text: str, route: bool = False) -> str:
    """Hindi / Kannada / Hinglish / Kanglish date words, month spellings, typos and digits -> English that
    resolve_when reads (app.voice.register.to_english_dates)."""
    return R.to_english_dates(text, route=route)


def when_grounded(when: str, user_text: str) -> bool:
    """True when every number and month in `when` was said by the user, and relative words have a counterpart."""
    u = (user_text or "").translate(_DIGITS)
    w = (when or "").translate(_DIGITS)
    for n in re.findall(r"\d+", w):
        if n not in re.findall(r"\d+", u):
            return False
    wm = L.month_numbers_in(w)
    if wm and not wm <= L.month_numbers_in(u):
        return False
    if RELATIVE_EN.search(w) and not RELATIVE_ANY.search(u):
        return False
    return bool(re.findall(r"\d+", w) or wm or RELATIVE_EN.search(w))


def has_year(expr: str) -> bool:
    e = to_english_dates(expr)
    return bool(re.search(r"\b(19|20|21)\d{2}\b", e) or RELATIVE_EN.search(e))


def _resolve(expr: str, tz: str) -> list[dict]:
    from ..core import dates
    return dates.resolve_when(to_english_dates(expr), tz)


# ---------------------------------------------------------------- keyword router (LLM down)

FACES_RE = re.compile(r"\b(face|faces|with (my |our )?\w+ in (them|it)|who is in|people in|recognis|recogniz|"
                      r"smiling|selfies? of)\b|चेहर|जिनमें .* (हैं|है)|ಮುಖ"
                      # choosing by what is inside a photo: "that room with the cake", "pics showing the dog"
                      r"|\b(room|photos?|pics?|pictures?|images?)\s+(with|having|showing)\s+(the|a|an|that)\s+\w+"
                      r"|\b(photos?|pics?|pictures?)\s+of\s+(the|a|an)\s+(cake|dog|cat|beach|tree|car|sea|food|"
                      r"lamps?|diyas?|rangoli|baby|kids?)\b", re.I)
KW = [
    ("invite_contact", re.compile(r"\binvite\b|\bcall (my|our|\w+) (to|into|and)|बुलाओ|बुला लो|इनवाइट|ಆಹ್ವಾನಿಸ|ಕರೆಸಿ|"
                                  r"\b\w+\s+(ko|ku)\s+(bulao|bula lo|bulalo|bula do|invite karo)\b|\bkaresi\b|"
                                  r"\bkarsi\b|\bbulao\b", re.I)),
    ("change_setting", re.compile(r"\b(language|speak|sarcasm|sarcastic|grandma'?s name|call grandma|rename grandma|"
                                  r"closed with care|close .* with care|keep (the )?location|location data|"
                                  r"dadi ka naam|ajji hesaru|vyangya|bhasha|bhaashe)\b|"
                                  r"भाषा|बोलो|व्यंग्य|दादी का नाम|ಭಾಷೆ|ಮಾತಾಡ|ಮಾತನಾಡ|ವ್ಯಂಗ್ಯ|ಅಜ್ಜಿಯ ಹೆಸರ", re.I)),
    ("import_gallery", re.compile(r"^\s*(yes|haan|हाँ|हां|ಹೌದು)\b.*\b(import|add them)\b", re.I)),
    ("query_gallery", re.compile(r"\b(photos?|pictures?|pics?|images?|upload|import|gallery|tasveer\w*|photu|"
                                 r"photogalu|fotos?|phots|potos?)\b|फ़ोटो|फोटो|तस्वीर|ಫೋಟೋ|ಚಿತ್ರ", re.I)),
    ("create_event", re.compile(r"\b(add|create|creat|craete|make|new|start)\b.{0,30}\b(event|evnt|evnet|festival|trip|birthday|holiday|"
                                r"vacation|celebration|called|named)\b|\bnew (event|festival|trip)\b|"
                                r"\b(naya|nayi|naye|hosa)\s+(event|tyohar|festival|trip|function|ivent)\b|"
                                r"\b(event|trip|festival)\s+(banao|banado|bana do|banaiye|add karo|jodo|maadi|maadu|"
                                r"seri|serisi|create maadi)\b|\bbanao\b|इवेंट|त्योहार|"
                                r"नया|जोड़|ಈವೆಂಟ್|ಹಬ್ಬ|ಹೊಸ|ಸೇರಿಸ", re.I)),
    ("plan_route", re.compile(r"\b(take me|tak me|teke me|go to|goto|bring me|open|show me|show|visit|walk me|let'?s go|where is|"
                              r"wanna see|want to see|what we did|what happened|le chalo|le chal|le jao|le chalo|"
                              r"dikhao|dikha do|dikhado|kholo|jaana hai|jana hai|chalo|karkondu|karkond|"
                              r"karedukondu|hogona|hogu|thorsu|torsu|torisu|nodona)\b|ले चलो|"
                              r"ले चलिए|ले जाओ|दिखाओ|खोलो|जाना है|ಕರೆದುಕೊಂಡು|ಕರ್ಕೊಂಡು|ಹೋಗೋಣ|ತೋರಿಸ|ತೆರೆ", re.I)),
]


def _event_name_from(text: str) -> Optional[str]:
    from ..ai import facts
    m = re.search(r"\b(?:called|named)\s+([\w'’ -]{2,60}?)(?:\s+(?:in|on|from|for|last|this|next)\b|[.,!?]|$)", text, re.I)
    if m:
        return m.group(1).strip()
    fest = facts.match_festival(text)
    if fest:
        return fest
    m = re.search(r"\b(?:add|create|make)\s+(?:a\s+|an\s+|the\s+)?(?:new\s+)?(?:event|trip|festival|birthday)?\s*"
                  r"(?:for\s+)?([A-Z][\w'’ -]{1,40}?)(?:\s+(?:in|on|from|last|this)\b|[.,!?]|$)", text)
    return m.group(1).strip() if m else None


def _event_mention(en: str) -> tuple[Optional[str], str]:
    """A festival named with an optional year ("Diwali 2026 mein") -> ("Diwali 2026", text without it), so the
    year goes to the event, not to the photo date."""
    from ..ai import facts
    fest = facts.match_festival(en)
    if not fest:
        return None, en
    aliases = [a for a in facts.FESTIVALS[fest][1] if a.isascii()] + [fest.lower()]
    for a in sorted(aliases, key=len, reverse=True):
        m = re.search(r"\b" + re.escape(a) + r"\b(\s+(?:19|20)\d{2})?", en, re.I)
        if m:
            label = fest + (m.group(1) or "")
            return label.strip(), (en[:m.start()] + " " + en[m.end():]).strip()
    return fest, en


def keyword_plan(text: str) -> list[tuple[str, dict]]:
    t = text or ""
    if FACES_RE.search(t):
        return [("decline", {"reason": "face_recognition"})]
    en = to_english_dates(t)
    event_name, rest = _event_mention(en)
    when_src = rest if event_name else en
    when = when_src if re.search(r"\d|" + RELATIVE_EN.pattern + "|" + "|".join(L.MONTHS["en-IN"]), when_src, re.I) else None
    for name, rx in KW:
        if not rx.search(t):
            continue
        if name == "invite_contact":
            m = re.search(r"\b(?:invite|call)\s+(?:my\s+|our\s+)?([\w'’]+(?:\s[\w'’]+)?)", t, re.I)
            if not m:
                m = re.search(r"\b([A-Za-z]\w+)\s+(?:ko|ku|na|nannu)\s+(?:is\s+room\s+mein\s+)?"
                              r"(?:bula|invite|karesi|karsi)", t, re.I)
            return [(name, {"who": m.group(1) if m else t})]
        if name == "change_setting":
            sw = L.language_switch(t)
            if sw:
                return [(name, {"key": "language", "value": sw})]
            if re.search(r"sarcas|vyang|व्यंग्य|ವ್ಯಂಗ್ಯ", t, re.I):
                off = re.search(r"\b(off|stop|no|disable|turn off|less|band|bandh|hatao|mat|beda|bedi|nillisi|"
                                r"nilsu|aaf)\b|बंद|ಬೇಡ|ನಿಲ್ಲಿಸ", t, re.I)
                return [(name, {"key": "sarcasm", "value": "off" if off else "on"})]
            m = (re.search(r"(?:call grandma|rename grandma(?: to)?|grandma'?s name (?:to|is))\s+(\w+)", t, re.I)
                 or re.search(r"(?:ಅಜ್ಜಿಯ ಹೆಸರನ್ನು|ಅಜ್ಜಿಯ ಹೆಸರು|दादी का नाम)\s+(\S+?)(?:\s|$|ಎಂದು)", t))
            if m:
                return [(name, {"key": "grandma_name", "value": m.group(1)})]
            if re.search(r"with care", t, re.I):
                return [(name, {"key": "closed_with_care", "value": "on", "when": when or ""})]
            if re.search(r"location", t, re.I):
                off = re.search(r"\b(off|don'?t|stop|remove|no)\b", t, re.I)
                return [(name, {"key": "keep_location", "value": "off" if off else "on"})]
            continue
        if name == "import_gallery":
            return [(name, {"confirm": True})]
        if name == "query_gallery":
            args: dict[str, Any] = {}
            if when:
                args["when"] = when
            m = re.search(r"\b(?:last|latest|newest|recent)\s+(\d+)\b", en, re.I)
            if m:
                args["latest_n"] = int(m.group(1))
            if re.search(r"\b(all|everything|every|saari|sari|saare|sare|sab|sabhi|ella|ellaa|yella)\b|सब|सारी|ಎಲ್ಲಾ|ಎಲ್ಲ",
                         t, re.I) and "latest_n" not in args and not when:
                args["all"] = True
            if event_name:
                args["event_name"] = event_name
            return [(name, args)]
        if name == "create_event":
            args = {"name": _event_name_from(en) or ""}
            if when:
                args["when"] = when
            return [(name, args)]
        if name == "plan_route":
            return [(name, {"place": R.clean_place(t)})]
    return []


LAST_RE = re.compile(r"\b(last|latest|previous|recent|pichli|pichhli|pichla|pichle|pichhle|kaleda|kalada|hoda)\b|पिछल|ಕಳೆದ|ಹೋದ",
                     re.I)

# ---------------------------------------------------------------- executor

class Desk:
    def __init__(self, family_id: str, member_id: Optional[str], role: str, lang: str, st: dict,
                 user_text: str, room: Optional[dict], reg: Optional[str] = None,
                 session_lang: Optional[str] = None) -> None:
        self.fid, self.mid, self.role, self.lang, self.st = family_id, member_id, role, lang, st
        self.reg = reg or lang                      # reply register: en-IN / hi-IN / kn-IN / hinglish / kanglish
        self.session_lang = session_lang or lang    # what the session keeps (a mirrored reply doesn't change it)
        self.user_text = user_text
        self.room = room
        self.tz = config.DEFAULT_TZ
        self.action: dict = {"type": "none", "data": {}}

    def say(self, key: str, **kw: Any) -> str:
        return L.t(key, self.reg, **kw)

    def _can_write(self) -> bool:
        return self.role in WRITE_ROLES

    def _month_label(self, y: int, m: int) -> str:
        return f"{L.month_name(m, self.reg)} {y}"

    def _ask_when(self, expr: Optional[str]) -> str:
        months = L.month_numbers_in(to_english_dates(expr or ""))
        if len(months) == 1:
            return self.say("rx_ask_year", month=L.month_name(next(iter(months)), self.reg))
        return self.say("rx_ask_when")

    def _ground_when(self, when: Optional[str]) -> Optional[str]:
        """Keep `when` only if the user actually said it (this turn or the turn that started the pending ask)."""
        if not when:
            return None
        said = self.user_text + " " + " ".join((self.st.get("pending") or {}).get("said", []))
        return when if when_grounded(to_english_dates(when), to_english_dates(said)) else None

    # -- create_event
    async def create_event(self, a: dict) -> dict:
        if not self._can_write():
            return {"ok": False, "spoken": self.say("rx_need_role"), "final": True}
        name = re.sub(r"\s+", " ", str(a.get("name") or "")).strip(" .")
        if name and not name.isascii():
            from ..ai import facts
            name = facts.match_festival(name) or name      # "दिवाली" / "ದೀಪಾವಳಿ" -> "Diwali" (recognition only)
        kind = a.get("kind") if a.get("kind") in ("festival", "trip", "birthday", "other") else None
        when = self._ground_when(a.get("when"))
        if not name:
            self.st["pending"] = {"kind": "need_name", "when": when, "said": [self.user_text]}
            return {"ok": False, "spoken": self.say("rx_ask_name"), "final": True, "question": True}
        if not when or not has_year(when):
            partial = [when] if when and L.month_numbers_in(to_english_dates(when)) else []
            self.st["pending"] = {"kind": "need_when", "name": name, "event_kind": kind, "said": [self.user_text],
                                  "partial": partial}
            return {"ok": False, "spoken": self._ask_when(when), "final": True, "question": True}
        cands = _resolve(when, self.tz)
        months = [c for c in cands if c.get("month")]
        if not months:
            self.st["pending"] = {"kind": "need_when", "name": name, "event_kind": kind, "said": [self.user_text]}
            return {"ok": False, "spoken": self._ask_when(when), "final": True, "question": True}
        c = months[0]
        if (c["start"].year, c["start"].month) != (c["end"].year, c["end"].month):
            self.st["pending"] = {"kind": "need_when", "name": name, "event_kind": kind, "said": [self.user_text]}
            return {"ok": False, "spoken": self.say("rx_ask_when"), "final": True, "question": True}
        from ..core import events
        try:
            res = await events.create_event(self.fid, self.mid, name, kind, c["year"], c["month"])
        except ValueError as e:
            return {"ok": False, "spoken": self.say("rx_error", reason=str(e)), "final": True}
        ev = res["event"]
        self.st["pending"] = None
        self.st["current_event"] = {"id": str(ev["id"]), "name": ev["name"], "year": ev["year"], "month": ev["month"]}
        label = f"{ev['name']} {ev['year']}" if str(ev["year"]) not in ev["name"] else ev["name"]
        floor = L.floor_label(int(res["level"]), self.reg)
        key = "rx_event_created" if res.get("created", True) else "rx_event_exists"
        spoken = self.say(key, event=label, floor=floor, month=L.month_name(ev["month"], self.reg))
        state = (res.get("room_state") or {}).get("state")
        has_mem = int((res.get("room_state") or {}).get("memory_count") or 0) > 0
        spoken += " " + (self.say("rx_add_photos") if has_mem or state == "open" else self.say("rx_door_shut"))
        self.action = {"type": "event_created", "data": {**res, "event": ev}}
        return {"ok": True, "spoken": spoken, "final": True, "result": {"event": ev, "level": res["level"]}}

    # -- query_gallery
    async def _target_event(self, name: Optional[str]) -> Optional[dict]:
        from ..core import events
        if name:
            m = re.search(r"\b((?:19|20)\d{2})\b", to_english_dates(name))
            year = int(m.group(1)) if m else None
            bare = re.sub(r"\b(?:19|20)\d{2}\b", " ", to_english_dates(name)).strip(" -") or name
            found = await events.find_events(self.fid, bare, year) or await events.find_events(self.fid, name)
            if found:
                e = found[0]
                return {"id": str(e["id"]), "name": e["name"], "year": e["year"], "month": e["month"]}
        return self.st.get("current_event")

    async def query_gallery(self, a: dict) -> dict:
        if not self._can_write():
            return {"ok": False, "spoken": self.say("rx_need_role"), "final": True}
        from ..core import gallery
        filt: dict[str, Any] = {}
        when = self._ground_when(a.get("when"))
        when_label = ""
        if a.get("when") and not when:
            self.st["pending"] = {"kind": "need_gallery_when", "args": {k: v for k, v in a.items() if k != "when"},
                                  "said": [self.user_text]}
            return {"ok": False, "spoken": self.say("rx_ask_when"), "final": True, "question": True}
        if when:
            cands = _resolve(when, self.tz)
            if not cands:
                self.st["pending"] = {"kind": "need_gallery_when", "args": {k: v for k, v in a.items() if k != "when"},
                                      "said": [self.user_text]}
                return {"ok": False, "spoken": self.say("rx_ask_when"), "final": True, "question": True}
            c = cands[0]
            filt["date_from"], filt["date_to"] = c["start"].isoformat(), c["end"].isoformat()
            when_label = c["label"]
        for k in ("camera", "folder", "type"):
            if a.get(k):
                filt[k] = str(a[k])[:80]
        if a.get("min_size_mb"):
            filt["min_size"] = int(float(a["min_size_mb"]) * 1024 * 1024)
        if a.get("max_size_mb"):
            filt["max_size"] = int(float(a["max_size_mb"]) * 1024 * 1024)
        if a.get("latest_n"):
            n = int(a["latest_n"])
            if n <= 0:
                return {"ok": False, "spoken": self.say("rx_found_none"), "final": True}
            filt["latest_n"] = n
        if a.get("all") or not filt:
            filt["all"] = True
        if filt.get("type") and str(filt["type"]).lower() not in ("jpeg", "jpg", "png", "webp"):
            filt.pop("type")          # "photo" is every item in the index
        try:
            res = await gallery.query(self.fid, filt)
        except ValueError as e:
            return {"ok": False, "spoken": self.say("rx_error", reason=str(e)), "final": True}
        count, total = int(res.get("count") or 0), int(res.get("total_bytes") or 0)
        if count == 0:
            self.st["pending"] = None
            return {"ok": True, "spoken": self.say("rx_found_none"), "final": True, "result": res}
        target = await self._target_event(a.get("event_name"))
        if res.get("over_limit"):
            # The preview already holds the newest that fit: read both numbers and the size, then ask once.
            limit = int(res.get("limit") or count)
            spoken = self.say("rx_over_limit", count=int(res.get("matched") or count), limit=limit,
                              size=L.size_label(total, self.lang))
        else:
            when_part = ""
            if when_label:
                when_part = {"en-IN": f" from {when_label}", "hi-IN": f"{when_label} की ",
                             "kn-IN": f"{when_label} ರ ", "hinglish": f"{when_label} ki ",
                             "kanglish": f"{when_label} ra "}.get(self.reg, f" from {when_label}")
            spoken = self.say("rx_found", count=count, photos=L.plural(count, "photo", "photos"), when=when_part,
                              size=L.size_label(total, self.lang))
        pend = {"kind": "confirm_import", "preview_token": res["preview_token"], "count": count, "total_bytes": total,
                "said": [self.user_text]}
        if target:
            pend["event"] = target
            spoken += " " + self.say("rx_add_to", event=self._event_label(target))
        else:
            pend["kind"] = "need_event"
            spoken += " " + self.say("rx_which_event")
        self.st["pending"] = pend
        return {"ok": True, "spoken": spoken, "final": True, "question": True,
                "result": {k: res.get(k) for k in ("count", "total_bytes", "over_limit", "limit")}}

    def _event_label(self, e: dict) -> str:
        return e["name"] if str(e.get("year")) in e["name"] else f"{e['name']} {e['year']}"

    # -- import_gallery (only from a confirmed preview)
    async def import_gallery(self, a: dict) -> dict:
        p = self.st.get("pending") or {}
        if p.get("kind") != "confirm_import" or not p.get("preview_token"):
            return {"ok": False, "spoken": self.say("rx_nothing_pending"), "final": True}
        if a.get("confirm") is False:
            self.st["pending"] = None
            return {"ok": True, "spoken": self.say("rx_cancelled"), "final": True}
        if not self._can_write():
            return {"ok": False, "spoken": self.say("rx_need_role"), "final": True}
        from ..core import gallery
        ev = p["event"]
        try:
            res = await gallery.start_import(self.fid, self.mid, p["preview_token"], ev["id"])
        except (ValueError, LookupError) as e:
            self.st["pending"] = None
            return {"ok": False, "spoken": self.say("rx_error", reason=str(e)), "final": True}
        self.st["pending"] = None
        n = int(res.get("count") or p["count"])
        self.action = {"type": "import_started", "data": {**res, "event": ev}}
        return {"ok": True, "spoken": self.say("rx_import_started", count=n, photos=L.plural(n, "photo", "photos"),
                                               event=self._event_label(ev)), "final": True, "result": res}

    # -- plan_route
    async def _resolve_place(self, place: str) -> dict:
        """Hinglish / Kanglish / chatty filler is stripped and date words normalised before the core reads the
        place ("bhai mujhe Diwali wale room mein le chalo" -> "Diwali", "Nov 26" -> "November 2026"). "last Holi" /
        "pichli Holi" with several Holi rooms means the most recent one that is not in the future."""
        from ..core import common, routing
        cleaned = R.clean_place(place)
        res = await routing.resolve_place(self.fid, cleaned)
        cands = res.get("candidates") or []
        if len(cands) > 1 and LAST_RE.search(place + " " + self.user_text):
            today = common.tz_today()
            past = [c for c in cands if (c["year"], c["month"]) <= (today.year, today.month)]
            if past:
                best = max(past, key=lambda c: (c["year"], c["month"]))
                res = {**res, "candidates": [best], "question": None}
        return res

    async def _go(self, c: dict) -> dict:
        from ..core import routing
        try:
            route = await routing.plan_route(self.fid, c["year"], c["month"], c.get("event_id"))
        except (ValueError, LookupError) as e:
            return {"ok": False, "spoken": self.say("rx_error", reason=str(e)), "final": True}
        self.st["pending"] = None
        self.st["room"] = {"year": route["year"], "month": route["month"], "event_id": route.get("event_id")}
        place = c.get("label") or self._month_label(route["year"], route["month"])
        if self.lang != "en-IN" and not c.get("event_id"):
            place = self._month_label(route["year"], route["month"])
        key = "rx_route" if route["room_state"] == "open" else "rx_route_locked"
        self.action = {"type": "route", "data": route}
        return {"ok": True, "spoken": self.say(key, place=place), "final": True, "result": route}

    async def plan_route(self, a: dict) -> dict:
        if self.role == "viewer" and self.room:
            return await self._go({"year": self.room["year"], "month": self.room["month"], "event_id": None})
        place = str(a.get("place") or "").strip()
        res = await self._resolve_place(place)
        cands = res.get("candidates") or []
        if len(cands) == 1:
            return await self._go(cands[0])
        if len(cands) > 1:
            self.st["pending"] = {"kind": "choose_place", "options": cands[:4], "said": [self.user_text]}
            opts = L.t("rx_or", self.reg).join(c["label"] for c in cands[:4])
            return {"ok": False, "spoken": self.say("rx_ask_which", options=opts), "final": True, "question": True}
        self.st["pending"] = {"kind": "need_place", "said": [self.user_text]}
        q = res.get("question") if self.lang == "en-IN" and res.get("question") else self.say("rx_where")
        return {"ok": False, "spoken": q, "final": True, "question": True}

    # -- change_setting
    async def change_setting(self, a: dict) -> dict:
        key = str(a.get("key") or "")
        val = a.get("value")
        if key == "language":
            code = L.norm(str(val)) if str(val).strip() else None
            sw = L.language_switch(self.user_text) or code
            if not sw:
                return {"ok": False, "spoken": self.say("rx_setting_bad"), "final": True}
            return await self.switch_language(sw, family_wide=self._can_write() and bool(
                re.search(r"\b(family|museum|default|everyone)\b|परिवार|ಕುಟುಂಬ", self.user_text, re.I)))
        if not self._can_write():
            return {"ok": False, "spoken": self.say("rx_need_role"), "final": True}
        from ..core import settings
        try:
            if key == "closed_with_care":
                when = self._ground_when(a.get("when")) or (f"{L.MONTHS['en-IN'][self.room['month'] - 1]} {self.room['year']}"
                                                            if self.room and self.room.get("month") else None)
                cands = _resolve(when, self.tz) if when and has_year(when) else []
                if not cands or not cands[0].get("month"):
                    self.st["pending"] = {"kind": "need_setting_when", "value": val, "said": [self.user_text]}
                    return {"ok": False, "spoken": self.say("rx_ask_when"), "final": True, "question": True}
                on = str(val).lower() not in ("off", "false", "no", "0")
                res = await settings.change_setting(self.fid, "closed_with_care",
                                                    {"year": cands[0]["year"], "month": cands[0]["month"], "closed": on})
            elif key in ("sarcasm", "keep_location"):
                res = await settings.change_setting(self.fid, key, str(val).lower())
            elif key == "grandma_name":
                res = await settings.change_setting(self.fid, key, str(val))
            else:
                return {"ok": False, "spoken": self.say("rx_setting_bad"), "final": True}
        except ValueError as e:
            return {"ok": False, "spoken": self.say("rx_error", reason=str(e)), "final": True}
        self.st["pending"] = None
        self.action = {"type": "setting_changed", "data": {"key": key, "value": res.get("value"), "family": res.get("family")}}
        return {"ok": True, "spoken": self.say("rx_setting", what=_setting_line(key, res.get("value"), self.reg)),
                "final": True, "result": {"key": key, "value": res.get("value")}}

    async def switch_language(self, code: str, family_wide: bool = False) -> dict:
        self.lang = code
        self.session_lang = code
        self.reg = code
        self.st["language"] = code
        await vstate.set_member_language(self.mid, code)
        data: dict[str, Any] = {"key": "language", "value": code, "scope": "session+member"}
        if family_wide:
            from ..core import settings
            res = await settings.change_setting(self.fid, "language", code)
            data.update({"scope": "family", "family": res.get("family")})
        self.action = {"type": "setting_changed", "data": data}
        return {"ok": True, "spoken": self.say("rx_setting", what=self.say("rx_lang_set")), "final": True, "result": data}

    # -- invite_contact (confirm aloud first, then phone-invites places the call)
    async def invite_contact(self, a: dict) -> dict:
        if not self._can_write():
            return {"ok": False, "spoken": self.say("rx_need_role"), "final": True}
        from ..phone import invites
        who = re.sub(r"^(my|our|the)\s+", "", str(a.get("who") or "").strip(), flags=re.I)
        found = await invites.find_contacts(self.fid, who) if who else []
        if not found:
            return {"ok": False, "spoken": self.say("rx_invite_none", who=who or "them"), "final": True}
        room = None
        if a.get("place"):
            res = await self._resolve_place(str(a["place"]))
            if len(res.get("candidates") or []) == 1:
                room = res["candidates"][0]
        if not room and self.room and self.room.get("month"):
            room = {"year": self.room["year"], "month": self.room["month"], "event_id": self.room.get("event_id")}
        if not room and self.st.get("room"):
            room = self.st["room"]
        if not room and self.st.get("current_event"):
            e = self.st["current_event"]
            room = {"year": e["year"], "month": e["month"], "event_id": e["id"]}
        if len(found) > 1:
            self.st["pending"] = {"kind": "choose_contact", "options": [{"id": c["id"], "name": c["name"]} for c in found[:4]],
                                  "room": room, "said": [self.user_text]}
            opts = L.t("rx_or", self.reg).join(c["name"] for c in found[:4])
            return {"ok": False, "spoken": self.say("rx_invite_which", options=opts), "final": True, "question": True}
        return await self._confirm_invite(found[0], room)

    async def _confirm_invite(self, c: dict, room: Optional[dict]) -> dict:
        if not room:
            self.st["pending"] = {"kind": "need_invite_room", "contact": {"id": c["id"], "name": c["name"]},
                                  "said": [self.user_text]}
            return {"ok": False, "spoken": self.say("rx_invite_where"), "final": True, "question": True}
        if c.get("consent_to_calls") is False or c.get("do_not_call"):
            self.st["pending"] = None
            return {"ok": False, "spoken": self.say("rx_invite_no_consent", name=c["name"]), "final": True}
        place = self._month_label(room["year"], room["month"])
        if room.get("event_id"):
            ev = await db.fetchrow("SELECT name, year FROM events WHERE id=$1 AND family_id=$2", room["event_id"], self.fid)
            if ev:
                place = self._event_label(dict(ev))
        last4 = c.get("phone_last4") or ""
        self.st["pending"] = {"kind": "confirm_invite", "contact": {"id": c["id"], "name": c["name"]}, "room": room,
                              "said": [self.user_text]}
        return {"ok": True, "spoken": self.say("rx_invite_confirm", name=c["name"], last4=" ".join(last4), place=place),
                "final": True, "question": True}

    async def place_invite(self) -> dict:
        p = self.st.get("pending") or {}
        from ..phone import invites
        room, c = p["room"], p["contact"]
        self.st["pending"] = None
        try:
            inv = await invites.create_invite(self.fid, self.mid, c["id"], int(room["year"]), int(room["month"]),
                                              room.get("event_id"))
        except (ValueError, LookupError) as e:
            return {"ok": False, "spoken": self.say("rx_error", reason=str(e)), "final": True}
        if inv.get("call_refusal"):
            return {"ok": False, "spoken": self.say("rx_error", reason=inv["call_refusal"]["message"]), "final": True,
                    "result": inv}
        try:
            call = await invites.place_call(self.fid, inv["invite"]["id"])
        except Exception as e:  # noqa: BLE001  (CallRefused carries a human message)
            return {"ok": False, "spoken": self.say("rx_error", reason=getattr(e, "message", str(e))[:200]),
                    "final": True, "result": inv}
        self.action = {"type": "invite_called", "data": {"invite": inv["invite"], "call": call, "contact": c}}
        return {"ok": True, "spoken": self.say("rx_invite_placed", name=c["name"]), "final": True}

    async def decline(self, a: dict) -> dict:
        key = "rx_no_faces" if a.get("reason") == "face_recognition" else "rx_cant"
        return {"ok": True, "spoken": self.say(key), "final": True}

    async def execute(self, name: str, args: dict) -> dict:
        fn = getattr(self, name, None) if name in TOOL_NAMES else None
        if not fn:
            return {"ok": False, "spoken": self.say("rx_cant"), "final": True}
        try:
            return await fn(args if isinstance(args, dict) else {})
        except HTTPException:
            raise
        except ImportError as e:
            log.error("core service missing for %s: %s", name, e)
            return {"ok": False, "spoken": self.say("rx_error", reason="that part of the museum isn't ready yet."),
                    "final": True}


SETTING_LINES = {
    "grandma_name": {"en-IN": "Grandma's name is now {v}", "hi-IN": "दादी का नाम अब {v} है", "kn-IN": "ಅಜ್ಜಿಯ ಹೆಸರು ಈಗ {v}"},
    "sarcasm:True": {"en-IN": "Sarcasm is on", "hi-IN": "व्यंग्य चालू है", "kn-IN": "ವ್ಯಂಗ್ಯ ಆನ್ ಆಗಿದೆ"},
    "sarcasm:False": {"en-IN": "Sarcasm is off", "hi-IN": "व्यंग्य बंद है", "kn-IN": "ವ್ಯಂಗ್ಯ ಆಫ್ ಆಗಿದೆ"},
    "keep_location:True": {"en-IN": "Photo locations will be kept", "hi-IN": "फ़ोटो की लोकेशन रखी जाएगी",
                           "kn-IN": "ಫೋಟೋ ಸ್ಥಳ ಉಳಿಸಲಾಗುತ್ತದೆ"},
    "keep_location:False": {"en-IN": "Photo locations will be removed", "hi-IN": "फ़ोटो की लोकेशन हटाई जाएगी",
                            "kn-IN": "ಫೋಟೋ ಸ್ಥಳ ತೆಗೆಯಲಾಗುತ್ತದೆ"},
    "closed_with_care": {"en-IN": "{v} is set", "hi-IN": "{v} सेट हो गया", "kn-IN": "{v} ಹೊಂದಿಸಲಾಗಿದೆ"},
}


def _setting_line(key: str, value: Any, lang: str) -> str:
    if key == "closed_with_care" and isinstance(value, dict):
        room = f"{L.month_name(value['month'], lang)} {value['year']}"
        word = {"en-IN": f"{room}: closed with care" if value.get("mode") == "closed_with_care" else f"{room}: open as usual",
                "hi-IN": f"{room}: सम्मान से बंद" if value.get("mode") == "closed_with_care" else f"{room}: सामान्य",
                "kn-IN": f"{room}: ಕಾಳಜಿಯಿಂದ ಮುಚ್ಚಲಾಗಿದೆ" if value.get("mode") == "closed_with_care" else f"{room}: ಸಾಮಾನ್ಯ"}
        return word[L.norm(lang)]
    row = SETTING_LINES.get(f"{key}:{value}") or SETTING_LINES.get(key)
    return (row or {}).get(L.norm(lang), "").format(v=value) if row else str(value)


# ---------------------------------------------------------------- pending answers (code, no model)

def _pick_option(text: str, options: list[dict], field: str) -> Optional[dict]:
    t = to_english_dates(text).lower()
    full = [o for o in options if str(o.get(field) or "").lower() and str(o.get(field)).lower() in t]
    if len(full) == 1:
        return full[0]
    years = re.findall(r"\b(?:19|20|21)\d{2}\b", t)
    if years:
        hit = [o for o in options if str(o.get("year")) in years]
        if len(hit) == 1:
            return hit[0]
    words = set(re.findall(r"[a-z]{4,}", t))
    hit = [o for o in options if words & set(re.findall(r"[a-z]{4,}", str(o.get(field) or "").lower()))]
    if len(hit) == 1:
        return hit[0]
    ords = {"first": 0, "second": 1, "third": 2, "last": -1}
    for w, i in ords.items():
        if re.search(rf"\b{w}\b", t) and options:
            return options[i]
    return None


async def _handle_pending(d: Desk, text: str) -> Optional[dict]:
    p = d.st.get("pending") or {}
    kind = p.get("kind")
    if not kind:
        return None
    if kind == "confirm_import":
        if L.is_yes(text):
            return await d.import_gallery({"confirm": True})
        if L.is_no(text):
            return await d.import_gallery({"confirm": False})
        return None
    if kind == "confirm_invite":
        if L.is_yes(text):
            return await d.place_invite()
        if L.is_no(text):
            d.st["pending"] = None
            return {"ok": True, "spoken": d.say("rx_cancelled"), "final": True}
        return None
    if L.is_no(text):
        d.st["pending"] = None
        return {"ok": True, "spoken": d.say("rx_cancelled"), "final": True}
    if kind == "need_when":
        expr = to_english_dates(text)
        d.user_text = text + " " + " ".join(p.get("said", []))
        if when_grounded(expr, text):
            return await d.create_event({"name": p["name"], "kind": p.get("event_kind"),
                                         "when": " ".join(p.get("partial", [])) + " " + expr if p.get("partial") else expr})
        return None
    if kind == "need_name":
        name = re.sub(r"^(it'?s|call it|name it|called)\s+", "", text.strip(), flags=re.I).strip(" .")
        if 0 < len(name) <= 60:
            return await d.create_event({"name": name, "when": p.get("when")})
        return None
    if kind == "need_gallery_when":
        expr = to_english_dates(text)
        if when_grounded(expr, text):
            return await d.query_gallery({**p.get("args", {}), "when": expr})
        return None
    if kind == "need_event":
        from ..core import events
        found = await events.find_events(d.fid, to_english_dates(text).strip(" .?") or None)
        if len(found) >= 1:
            e = found[0]
            target = {"id": str(e["id"]), "name": e["name"], "year": e["year"], "month": e["month"]}
            d.st["current_event"] = target
            d.st["pending"] = {**p, "kind": "confirm_import", "event": target}
            return {"ok": True, "spoken": d.say("rx_add_to", event=d._event_label(target)), "final": True, "question": True}
        return None
    if kind == "choose_place":
        o = _pick_option(text, p["options"], "label")
        return await d._go(o) if o else None
    if kind == "need_place":
        res = await d._resolve_place(text)
        if len(res.get("candidates") or []) == 1:
            return await d._go(res["candidates"][0])
        return None
    if kind == "choose_contact":
        o = _pick_option(text, p["options"], "name")
        if o:
            from ..phone import invites
            found = [c for c in await invites.find_contacts(d.fid, o["name"]) if c["id"] == o["id"]]
            if found:
                return await d._confirm_invite(found[0], p.get("room"))
        return None
    if kind == "need_invite_room":
        res = await d._resolve_place(text)
        if len(res.get("candidates") or []) == 1:
            from ..phone import invites
            found = [c for c in await invites.find_contacts(d.fid, p["contact"]["name"]) if c["id"] == p["contact"]["id"]]
            if found:
                return await d._confirm_invite(found[0], res["candidates"][0])
        return None
    if kind == "need_setting_when":
        expr = to_english_dates(text)
        if when_grounded(expr, text):
            return await d.change_setting({"key": "closed_with_care", "value": p.get("value", "on"), "when": expr})
        return None
    return None


# ---------------------------------------------------------------- the loop

def _parse_args(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


MULTI_RE = re.compile(r"\b(and then|and also|then)\b|\band\b.*\b(add|upload|take|go|import|photos?)\b|और फिर|ಮತ್ತು ನಂತರ", re.I)


async def _run_llm(d: Desk, messages: list[dict], steps: list[dict]) -> str:
    provider: Optional[str] = None
    multi = bool(MULTI_RE.search(d.user_text))
    for _ in range(MAX_STEPS):
        msg, provider = await llm.chat(messages, tools=TOOLS, max_tokens=300, temperature=0.1, stick_to=provider)
        calls = msg.get("tool_calls") or []
        if not calls:
            return llm.strip_think(msg.get("content") or "")
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        stop = False
        for call in calls[:2]:
            fn = call.get("function", {})
            name, args = fn.get("name", ""), _parse_args(fn.get("arguments"))
            res = await d.execute(name, args)
            steps.append({"tool": name, "args": args, "ok": bool(res.get("ok")), "spoken": res.get("spoken")})
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                             "content": json.dumps({"ok": res.get("ok"), "said_to_user": res.get("spoken")},
                                                   ensure_ascii=False)})
            if res.get("question") or not res.get("ok"):
                stop = True
        if stop or not multi:
            return ""
    return ""


async def route_intent(text: str, language: str = "en-IN") -> tuple[str, dict]:
    """The tool the full pipeline would pick, without executing: code pre-checks (language switch, faces), then the
    model. For the accuracy test."""
    sw = L.language_switch(text)
    if sw:
        return "change_setting", {"key": "language", "value": sw}
    if FACES_RE.search(text):
        return "decline", {"reason": "face_recognition"}
    return await choose_intent(text, language)


async def choose_intent(text: str, language: str = "en-IN") -> tuple[str, dict]:
    """One model call, no execution: which tool the model picks for an utterance (for the accuracy test)."""
    lang, reg = turn_register(text, L.norm(language), {})
    msgs = [{"role": "system", "content": system_prompt(lang, {}, None, date.today(), reg)}, {"role": "user", "content": text}]
    msg, _ = await llm.chat(msgs, tools=TOOLS, max_tokens=300, temperature=0.1)
    calls = msg.get("tool_calls") or []
    if not calls:
        return "none", {}
    fn = calls[0].get("function", {})
    return fn.get("name", "none"), _parse_args(fn.get("arguments"))


CLICHE_RE = re.compile(r"[,;]?\s*(how (can|may) i (help|assist) you( today)?|what can i do for you( today)?|"
                       r"is there anything (else )?i can help( you)? with|as an ai[^.!?]*|i hope this helps|"
                       r"let me know if[^.!?]*)\s*[.!?]?", re.I)


def humanize(text: str) -> str:
    """Drop assistant clichés the model sometimes adds to a chat line ("..., how can I help you?"); a person at a
    desk doesn't talk like that. Empty when nothing is left (the caller then uses a fixed line)."""
    out = CLICHE_RE.sub(".", text or "")
    out = re.sub(r"\.\s*\.", ".", re.sub(r"\s+", " ", out)).strip(" .")
    if not out:
        return ""
    return out if out[-1] in ".!?।" else out + "."


def turn_register(text: str, session_lang: str, st: dict) -> tuple[str, str]:
    """(voice language, reply register) for this turn. Hindi / Kannada in any script is mirrored; a neutral short
    answer ("2026", "ok", "yes") keeps the register of the conversation so far."""
    d = R.detect(text)
    short = len(text.split()) <= 3
    if (d["lang"] is None or (d["register"] == "en" and short)) and st.get("register"):
        prev = st["register"]
        return ("hi-IN" if prev == "hinglish" else "kn-IN" if prev == "kanglish" else L.norm(prev)), prev
    lang = R.reply_lang(text, session_lang)
    return lang, R.register_of(text, lang)


async def act_core(family_id: str, member_id: Optional[str], text: str, language: Optional[str] = None, *,
                   state_key: Optional[str] = None, room: Optional[dict] = None, role: str = "owner",
                   st: Optional[dict] = None, use_llm: bool = True) -> dict:
    """Text in, {"reply","action","source","steps","language","pending"} out. Saves conversation state."""
    family_id = str(family_id)
    text = " ".join((text or "").split())[:600]
    if not text:
        raise HTTPException(422, "Say or type a request.")
    if st is None:
        st = await vstate.load(state_key) if state_key else {}
    session_lang = L.norm(language or st.get("language") or await vstate.family_language(family_id, member_id))
    lang, reg = turn_register(text, session_lang, st)
    d = Desk(family_id, member_id, role, lang, st, text, room, reg=reg, session_lang=session_lang)
    steps: list[dict] = []
    source = "state"
    res: Optional[dict] = None
    sw = L.language_switch(text)
    if sw:
        res = await d.switch_language(sw, family_wide=False)
        steps.append({"tool": "change_setting", "args": {"key": "language", "value": sw}, "ok": True})
    if res is None:
        res = await _handle_pending(d, text)
        if res is not None:
            steps.append({"tool": "pending:" + str((st.get("pending") or {}).get("kind") or "done"), "ok": res.get("ok")})
    if res is None and FACES_RE.search(text):
        res = await d.decline({"reason": "face_recognition"})
        steps.append({"tool": "decline", "args": {"reason": "face_recognition"}, "ok": True})
    reply = res["spoken"] if res else ""
    if res is None:
        source = "llm"
        llm_text = ""
        try:
            if not use_llm:
                raise HTTPException(503, "LLM disabled")
            msgs = [{"role": "system", "content": system_prompt(lang, st, room, date.today(), reg)}]
            for h in (st.get("history") or [])[-6:]:
                msgs.append({"role": h["role"], "content": h["content"][:400]})
            msgs.append({"role": "user", "content": text})
            llm_text = await _run_llm(d, msgs, steps)
        except HTTPException as e:
            log.warning("receptionist LLM unavailable (%s); keyword router", str(e.detail)[:120])
            source = "keywords"
            if not steps:
                for name, args in keyword_plan(text):
                    r = await d.execute(name, args)
                    steps.append({"tool": name, "args": args, "ok": bool(r.get("ok")), "spoken": r.get("spoken")})
                    if r.get("question") or not r.get("ok"):
                        break
        spoken = [s["spoken"] for s in steps if s.get("spoken")]
        if spoken:
            reply = " ".join(spoken)
        else:
            clean = humanize(re.sub(r"[*_`#]+", "", llm_text or "").strip())
            reply = clean[:300] if clean else L.t("rx_hello" if source == "keywords" else "rx_cant", d.reg)
    hist = (st.get("history") or []) + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
    st["history"] = hist[-8:]
    st["language"] = d.session_lang
    st["register"] = d.reg
    if state_key:
        await vstate.save(state_key, family_id, member_id, "receptionist", st)
    return {"reply": reply, "action": d.action, "source": source, "steps": steps, "language": d.lang,
            "pending": (st.get("pending") or {}).get("kind")}


async def act(family_id: str, member_id: Optional[str], text: str, language: Optional[str] = None, *,
              state_key: Optional[str] = None, room: Optional[dict] = None, role: str = "owner",
              audio: bool = True, use_llm: bool = True) -> dict:
    out = await act_core(family_id, member_id, text, language, state_key=state_key, room=room, role=role,
                         use_llm=use_llm)
    sents = [{"text": s, "memory_ids": []} for s in grounding.split_sentences(out["reply"])]
    out["speech"] = await speech.build(sents, out["language"], "receptionist", family_id, audio=audio)
    return out
