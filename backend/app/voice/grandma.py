"""Grandma, the guide: tour (narrate a room) and talk (answer a question). PRD "Grandma, the guide".

    await tour(family_id, year, month, event_id=None, language=None, resume_from=0)   -> Speech (+ source)
    await talk(family_id, question, scope, language=None, ...)                         -> Speech + {transcript, source}
    await greet(family_id, year, month, event_id=None, language=None)                  -> Speech

Facts (counts, dates, contributors, festival, events) are computed here in Python from app.core.memories; the model
only writes connecting words, as JSON {"sentences": [{"text", "memory_ids", "names"}]}. grounding.check() rejects
unknown memory ids and names / dates / numbers not in the memories or facts; one regeneration, then a plain template.
Memories with narrate_ok=false are never narrated; sensitive ones are marked gentle (told softly, no jokes).
Talk: room scope first, widened to the floor (year) then the museum only when the room has no answer. Three sources
never blended: family (grounded) / general (Wikipedia festival summary, labelled) / none ("I don't have that" +
offer to ask the family on Telegram via app.telegram.send.ask_family_followup).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Optional

from fastapi import HTTPException

from .. import db
from ..ai import facts as festival_facts
from ..ai import llm
from . import grounding, speech, state as vstate
from . import lang as L

log = logging.getLogger("memo.grandma")

TOUR_MIN_WORDS, TOUR_MAX_WORDS = 140, 230      # ~60-90 s of speech at ~2.5 words/s
MAX_MEMORIES_IN_PROMPT = 40

ADVICE_RE = re.compile(
    r"\b(medicine|medication|dose|dosage|tablet|pill|diagnos\w*|symptom\w*|treat(ment)?|cure|disease|cancer|diabetes|"
    r"blood pressure|lawyer|legal|lawsuit|court|sue|property dispute|will and testament|invest\w*|stock\w*|"
    r"shares|mutual fund|loan|tax(es)?|insurance|crypto|bitcoin)\b"
    r"|दवा|दवाई|इलाज|बीमारी|वकील|कानून|निवेश|लोन|टैक्स|ಔಷಧ|ಚಿಕಿತ್ಸೆ|ಕಾಯಿಲೆ|ವಕೀಲ|ಕಾನೂನು|ಹೂಡಿಕೆ|ಸಾಲ|ತೆರಿಗೆ", re.I)
ADVICE_ASK_RE = re.compile(r"\b(should i|should we|what should|is it safe|can i take|how much should|advice|advise|recommend)\b"
                           r"|क्या मुझे|सलाह|ಸಲಹೆ|ನಾನು .*ಬೇಕಾ", re.I)
GENERAL_Q_RE = re.compile(r"\b(what is|what's|meaning|essence|why do (we|people)|history|significance|tell me about)\b"
                          r"|क्या है|क्यों मनाते|महत्व|ಏನು|ಯಾಕೆ ಆಚರಿಸ|ಮಹತ್ವ", re.I)
FAMILY_Q_RE = re.compile(r"\b(we|our|us|my|me|family|did|who|when did|last year|this year)\b|हमने|हमारे|मेरे|परिवार|"
                         r"ನಾವು|ನಮ್ಮ|ನನ್ನ|ಕುಟುಂಬ", re.I)
INVITE_STRICT_RE = re.compile(r"\binvite\b|\bcall (my|our|her|him|them|\w+) (to|into|and invite)|बुलाओ|बुला लो|इनवाइट|ಆಹ್ವಾನಿಸ|ಕರೆಸಿ|bulao|bula lo|karesi", re.I)


# ---------------------------------------------------------------- data + facts

async def _family(family_id: str) -> dict:
    row = await db.fetchrow("SELECT name, language, grandma_name FROM families WHERE id=$1", family_id)
    if not row:
        raise HTTPException(404, "Family not found.")
    return dict(row)


async def _memories(family_id: str, scope: dict, event_id: Optional[str] = None) -> list[dict]:
    from ..core import memories as core_memories   # owned by core-api; imported lazily (built in parallel)
    if scope.get("year") and scope.get("month"):
        mems = await core_memories.room_memories(family_id, int(scope["year"]), int(scope["month"]), event_id)
    else:
        mems = await core_memories.scope_memories(family_id, {k: v for k, v in scope.items() if k in ("year", "month") and v})
    mems = [dict(m) for m in mems]
    ids = [m["id"] for m in mems]
    if ids:
        rows = await db.fetch(
            "SELECT m.id::text AS id, m.people, e.name AS event_name FROM memories m LEFT JOIN events e ON e.id=m.event_id "
            "WHERE m.id = ANY($1::uuid[]) AND m.family_id=$2", ids, family_id)
        extra = {r["id"]: r for r in rows}
        for m in mems:
            x = extra.get(m["id"])
            m["people"] = list(x["people"] or []) if x else []
            m["event_name"] = x["event_name"] if x else None
    return mems


def _date_label(m: dict, lang: str, with_year: bool = True) -> str:
    d = m.get("event_date") or {}
    if not d.get("month"):
        return ""
    mon = L.month_name(int(d["month"]), lang)
    day = d.get("day")
    yr = f" {d['year']}" if with_year and d.get("year") else ""
    return f"{day} {mon}{yr}" if day else f"{mon}{yr}"


def _scope_label(scope: dict, lang: str) -> str:
    if scope.get("year") and scope.get("month"):
        return f"{L.month_name(int(scope['month']), lang)} {scope['year']}"
    if scope.get("year"):
        return str(scope["year"])
    return {"en-IN": "the museum", "hi-IN": "संग्रहालय", "kn-IN": "ಮ್ಯೂಸಿಯಂ"}[L.norm(lang)]


def compute_facts(mems: list[dict], scope: dict, lang: str) -> dict:
    kinds = [m.get("kind") for m in mems]
    contributors: list[str] = []
    for m in mems:
        for who in (m.get("teller"), m.get("author")):
            if who and who not in contributors:
                contributors.append(who)
    festivals = sorted({m["festival"] for m in mems if m.get("festival")})
    events = sorted({m["event_name"] for m in mems if m.get("event_name")})
    days = sorted({int(m["event_date"]["day"]) for m in mems if (m.get("event_date") or {}).get("day")})
    people = sorted({p for m in mems for p in (m.get("people") or [])})
    photos = sum(len(m.get("photos") or []) for m in mems)
    months = sorted({int(m["event_date"]["month"]) for m in mems if (m.get("event_date") or {}).get("month")})
    years = sorted({int(m["event_date"]["year"]) for m in mems if (m.get("event_date") or {}).get("year")})
    return {
        "scope": _scope_label(scope, lang),
        "year": scope.get("year"), "month": scope.get("month"),
        "memory_count": len(mems),
        "voice_notes": kinds.count("voice"),
        "photo_memories": kinds.count("photo") + kinds.count("album"),
        "photos": photos,
        "written": kinds.count("text") + kinds.count("forward"),
        "days": days, "years": years, "month_numbers": months + ([int(scope["month"])] if scope.get("month") else []),
        "contributors": contributors, "festivals": festivals, "events": events, "people": people,
    }


def _prompt_memories(mems: list[dict], lang: str) -> tuple[list[dict], dict[str, str]]:
    out, alias = [], {}
    for i, m in enumerate(mems[:MAX_MEMORIES_IN_PROMPT], 1):
        a = f"m{i}"
        alias[a] = m["id"]
        text = (m.get("text") or m.get("transcript") or "")[:500]
        out.append({k: v for k, v in {
            "id": a, "kind": m.get("kind"), "date": _date_label(m, "en-IN"), "title": m.get("title"),
            "summary": m.get("summary"), "text": text or None, "told_by": m.get("teller") or m.get("author"),
            "people": m.get("people") or None, "festival": m.get("festival"), "event": m.get("event_name"),
            "photos": len(m.get("photos") or []) or None,
            "gentle": True if (m.get("sensitivity") or "none") != "none" else None,
        }.items() if v not in (None, "", [])})
    return out, alias


def _persona(fam: dict, lang: str) -> str:
    return (f"You are {fam['grandma_name']}, the grandmother who guides the {fam['name']} family's memory museum: a warm "
            "Indian grandmother in her seventies, unhurried, smiling, a little teasing. You are a character, not any "
            "real person, and not an assistant. " + STYLE)


# Spoken style (PRD "Grandma, the guide" / "The voice experience"): a person on a voice call, not a chatbot.
STYLE = (
    "HOW YOU TALK: every word is spoken aloud, so talk like a real grandmother, never like a written answer. Short "
    "spoken sentences, mostly under 15 words, with contractions. First react to what they just said (\"Oh, the "
    "lamps!\", \"Arre, you remember that?\"), then tell it like a family story, not a report. At most one small "
    "filler per reply, and not in every reply: hmm, achha, oh!, let me think..., you know; in Hindi arre, dekho, "
    "achha; in Kannada nodu, ayyo, hmm sari. Vary how you begin; never open two replies the same way. Put '...' just "
    "before a tender detail, to pause. Gentle teasing and a little humour are welcome, never about gentle memories. "
    "Never say 'As an AI', never sound like an assistant ('How can I help you today?', 'Let me know if...', 'Great "
    "question'), never repeat the question back. No lists, no headings, no markdown, no emojis. "
)

RULES = (
    "STRICT RULES: Use only the facts and memories given. Never add a name, place, date, number, relationship or event "
    "that is not written there. Fillers and reactions are fine; invented facts are not. You may say 'someone' when "
    "unsure who. Write numbers exactly as given. Memories marked gentle are about loss, illness or conflict: tell them "
    "softly and never joke about them. No medical, legal or financial advice. "
)


def style_rule(lang: str, register: Optional[str] = None) -> str:
    """Language + register line: mirror how the visitor talks (Hinglish in -> Hinglish out)."""
    reg = register or L.norm(lang)
    if reg == "hinglish":
        return ("LANGUAGE: the visitor talks in Hinglish (Hindi in Roman letters mixed with English). Reply the same "
                "way: natural spoken Hinglish in Roman letters, the way a grandmother texts her grandchild "
                "(\"Arre, woh Diwali yaad hai? Sab ne milke diye jalaaye the.\"). Keep names, places and event titles "
                "exactly as spelled in the facts.")
    if reg == "kanglish":
        return ("LANGUAGE: the visitor talks in Kanglish (Kannada in Roman letters mixed with English). Reply the same "
                "way: natural spoken Kannada in Roman letters mixed with English, like a Bengaluru grandmother "
                "(\"Nodu, aa Deepavali nenapideya? Ellaru seri deepa hachchidru.\"). Keep names, places and event "
                "titles exactly as spelled in the facts.")
    extra = {"hi-IN": " Mix in everyday English words the way families really speak (photo, room, party).",
             "kn-IN": " Mix in everyday English words the way families really speak (photo, room, party).",
             "en-IN": " Warm Indian English, the way an Indian grandmother speaks it."}[L.norm(lang)]
    return L.language_rule(lang) + extra


async def _generate(messages: list[dict], alias: dict, corpus: dict, max_tokens: int) -> tuple[Optional[list[dict]], list[str], dict]:
    """One model call + checks. Returns (sentences|None, problems, raw json)."""
    msg, _prov = await llm.chat(messages, json_mode=True, max_tokens=max_tokens, temperature=0.5)
    raw = llm.strip_think(msg.get("content") or "")
    try:
        data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1]) if "{" in raw else {}
    except json.JSONDecodeError:
        return None, ["output was not valid JSON"], {}
    sents, problems = grounding.check(data, alias, corpus)
    return (sents if not problems else None), problems, data


async def generate_checked(messages: list[dict], alias: dict, corpus: dict, max_tokens: int = 900,
                           min_words: int = 0) -> tuple[Optional[list[dict]], dict]:
    """Generate, check, regenerate once with the problems named. None when both attempts fail (or the LLM is down).
    A grounded but too-short first draft is asked to be longer once; if the retry fails the checks, the short
    grounded draft is used (never an unchecked one)."""
    info: dict[str, Any] = {"attempts": 0, "problems": []}
    best: Optional[list[dict]] = None
    for attempt in range(2):
        info["attempts"] = attempt + 1
        try:
            sents, problems, data = await _generate(messages, alias, corpus, max_tokens)
        except HTTPException as e:
            info["problems"].append(f"llm unavailable: {str(e.detail)[:120]}")
            return best, info
        if sents:
            words = sum(len(s["text"].split()) for s in sents)
            if attempt == 0 and min_words and words < min_words * 0.7:
                best = sents
                problems = [f"too short ({words} words); write about {min_words} words, still only from the facts"]
            else:
                info["data"] = data
                return sents, info
        if attempt == 1 and best:
            return best, info
        info["problems"].append(problems)
        log.info("grandma output rejected (attempt %s): %s", attempt + 1, problems[:6])
        messages = messages + [
            {"role": "assistant", "content": json.dumps(data, ensure_ascii=False)[:3000] if data else "(invalid)"},
            {"role": "user", "content": "That was rejected: " + "; ".join(problems[:8]) +
             ". Rewrite it using ONLY names, dates and numbers that appear in the facts and memories. Same JSON shape."},
        ]
    return None, info


# ---------------------------------------------------------------- tour

def _fingerprint(mems: list[dict], lang: str, fam: dict) -> str:
    raw = json.dumps([[m["id"], m.get("title"), m.get("summary"), m.get("text"), m.get("narrate_ok"), m.get("sensitivity"),
                       m.get("event_date")] for m in mems], sort_keys=True, default=str)
    return hashlib.sha256(f"{raw}|{lang}|{fam['grandma_name']}".encode()).hexdigest()[:32]


def template_tour(mems: list[dict], facts: dict, lang: str) -> list[dict]:
    """Plain lines straight from the data (no model)."""
    if not mems:
        return [{"text": L.t("tour_empty", lang), "memory_ids": []}]
    n = facts["memory_count"]
    who = ""
    if facts["contributors"]:
        names = ", ".join(facts["contributors"][:4])
        who = L.t("tpl_who", lang, names=names)
    out = [{"text": L.t("tpl_intro", lang, room=facts["scope"], count=L.number_words(n, lang),
                        memories=L.plural(n, "memory", "memories"), who=who), "memory_ids": []}]
    if facts["festivals"]:
        out.append({"text": L.t("tpl_festival", lang, festival=facts["festivals"][0]), "memory_ids": []})
    for i, m in enumerate(mems[:10]):
        d = m.get("event_date") or {}
        when = (L.t("tpl_item_on", lang, day=d["day"], month=L.month_name(int(d["month"]), lang))
                if d.get("day") and d.get("month") else L.t("tpl_item_then", lang))
        by_name = m.get("teller") or m.get("author")
        by = L.t("tpl_by", lang, name=by_name) if by_name else ""
        title = (m.get("title") or m.get("summary") or (m.get("text") or "")[:120] or m.get("kind") or "").strip().rstrip(".")
        if (m.get("sensitivity") or "none") != "none":
            out.append({"text": L.t("tpl_gentle", lang), "memory_ids": [m["id"]]})
        out.append({"text": L.t("tpl_item", lang, when=when, by=by, title=title), "memory_ids": [m["id"]]})
    out.append({"text": L.t("tpl_end", lang), "memory_ids": []})
    return out


async def _tour_sentences(family_id: str, year: int, month: int, event_id: Optional[str], lang: str) -> tuple[list[dict], str, list[dict]]:
    fam = await _family(family_id)
    scope = {"year": year, "month": month}
    all_mems = await _memories(family_id, scope, event_id)
    mems = [m for m in all_mems if m.get("narrate_ok", True)]
    scope_key = f"{year}-{month:02d}" + (f":{event_id}" if event_id else "")
    fp = _fingerprint(mems, lang, fam)
    row = await db.fetchrow("SELECT sentences, source, fingerprint FROM grandma_tours WHERE family_id=$1 AND scope_key=$2 "
                            "AND language=$3", family_id, scope_key, lang)
    if row and row["fingerprint"] == fp:
        return list(row["sentences"]), row["source"], mems
    facts = compute_facts(mems, scope, lang)
    if not mems:
        sents, source = template_tour(mems, facts, lang), "template"
    else:
        pm, alias = _prompt_memories(mems, lang)
        corpus = grounding.build_corpus(mems, facts, [fam["grandma_name"], fam["name"], facts["scope"]])
        n = len(mems)
        lo, hi = min(TOUR_MIN_WORDS, 30 + 30 * n), min(TOUR_MAX_WORDS, 60 + 45 * n)
        system = (
            _persona(fam, lang) + f"The visitor just sat down in the theater of the {facts['scope']} room. Tell the room's story in "
            f"{lo} to {hi} words (about {round(lo / 2.5)} to {round(hi / 2.5)} seconds aloud), as a story the family told. "
            "Open with a warm line built from the facts (the room, how many memories, who shared them). Then go through "
            "the memories in date order, retelling what each one says in your own warm words, the way you'd tell it "
            "to a grandchild sitting beside you: feelings, small reactions and warmth are welcome, new facts are not. "
            "End with a short, warm closing line. Sentences of at most 20 words. "
            "Each sentence lists, in memory_ids, the ids of the memories it talks about (so the screen can show them), "
            "and in names the people's names it uses. Never write the ids (m1, m2) inside the text. "
            + RULES + style_rule(lang) +
            ' Reply with JSON only: {"sentences":[{"text":"...","memory_ids":["m1"],"names":["..."]}]}'
        )
        user = json.dumps({"facts": {k: v for k, v in facts.items() if k not in ("month_numbers",)}, "memories": pm},
                          ensure_ascii=False, default=str)
        sents, info = await generate_checked([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                             alias, corpus, max_tokens=1400, min_words=lo)
        source = "llm"
        if not sents:
            log.warning("tour fell back to the template: %s", str(info.get("problems"))[:300])
            sents, source = template_tour(mems, facts, lang), "template"
    await db.execute(
        "INSERT INTO grandma_tours(family_id, scope_key, language, fingerprint, sentences, source) VALUES ($1,$2,$3,$4,$5::jsonb,$6) "
        "ON CONFLICT (family_id, scope_key, language) DO UPDATE SET fingerprint=EXCLUDED.fingerprint, "
        "sentences=EXCLUDED.sentences, source=EXCLUDED.source, created_at=now()",
        family_id, scope_key, lang, fp, sents, source)
    return sents, source, mems


async def tour(family_id, year, month, event_id=None, language=None, resume_from: int = 0, audio: bool = True) -> dict:
    lang = L.norm(language or await vstate.family_language(family_id))
    sents, source, _ = await _tour_sentences(str(family_id), int(year), int(month), event_id, lang)
    start = max(0, min(int(resume_from or 0), len(sents)))
    sp = await speech.build(sents, lang, "grandma", str(family_id), start_index=start, audio=audio)
    sp["source"] = source
    return sp


# ---------------------------------------------------------------- greeting

async def greet(family_id, year, month, event_id=None, language=None, audio: bool = True) -> dict:
    lang = L.norm(language or await vstate.family_language(family_id))
    mems = await _memories(str(family_id), {"year": int(year), "month": int(month)}, event_id)
    room = f"{L.month_name(int(month), lang)} {year}"
    n = len(mems)
    if n == 0:
        lines = [L.t("greet_empty", lang, room=room)]
    else:
        v = sum(1 for m in mems if m.get("kind") == "voice")
        vp = L.t("greet_voice", lang, n=L.number_words(v, lang), voice_notes=L.plural(v, "a voice note", "voice notes")) if v else ""
        if L.norm(lang) == "en-IN" and v == 1:
            vp = ", one of them a voice note"
        lines = [L.t("greet", lang, room=room, count=L.number_words(n, lang), memories=L.plural(n, "memory", "memories"),
                     voice_part=vp), L.t("greet_offer", lang)]
    sp = await speech.build([{"text": s, "memory_ids": []} for s in lines], lang, "grandma", str(family_id), audio=audio)
    sp["source"] = "facts"
    sp["memory_count"] = n
    return sp


# ---------------------------------------------------------------- talk

async def _family_answer(fam: dict, question: str, mems: list[dict], scope: dict, lang: str, history: list[dict],
                         register: Optional[str] = None) -> dict:
    """{"source": family|general|none, "festival", "sentences"|None, "needs_wider"}"""
    mems = [m for m in mems if m.get("narrate_ok", True)]
    facts = compute_facts(mems, scope, lang)
    pm, alias = _prompt_memories(mems, lang)
    corpus = grounding.build_corpus(mems, facts, [fam["grandma_name"], fam["name"], facts["scope"]])
    system = (
        _persona(fam, lang) + f"The visitor is in the theater ({facts['scope']}) and asked a question. Decide the source:\n"
        '- "family": the memories below answer it. Answer in 1 to 3 short spoken sentences: a quick reaction to what '
        "they said, then the answer told like a little family story with the concrete details the memory gives "
        "(who, what, where, how many), citing memory ids. A reaction never replaces the answer. Questions may be indirect, "
        "Hinglish or Kanglish, or have typos (\"what happened in that room with the cake?\", \"Diwali pe kya kiya "
        "tha?\", \"Deepavali alli enu maadidvi?\"): answer what they mean.\n"
        '- "general": it asks about a festival or custom in general (its meaning, history, how it is celebrated), not '
        'about this family. Put the festival\'s English name in "festival" and leave sentences empty.\n'
        '- "none": the memories do not contain the answer. Leave sentences empty. Set "needs_wider" true if memories '
        "from other months or years might answer it.\n" + RULES + style_rule(lang, register) +
        ' Reply with JSON only: {"source":"family|general|none","festival":null,"needs_wider":false,'
        '"sentences":[{"text":"...","memory_ids":["m1"],"names":["..."]}]}'
    )
    msgs: list[dict] = [{"role": "system", "content": system},
                        {"role": "user", "content": "FACTS AND MEMORIES:\n" + json.dumps(
                            {"facts": {k: v for k, v in facts.items() if k != "month_numbers"}, "memories": pm},
                            ensure_ascii=False, default=str)}]
    for h in history[-4:]:
        msgs.append({"role": h["role"], "content": h["content"][:400]})
    # Code-side hints (no extra model call): the festival's canonical name for aliases and spellings ("Deepavali",
    # "ದೀಪಾವಳಿ" -> Diwali) and the visitor's register, so Roman Kannada / Hindi questions are read as such.
    hints = []
    fest = festival_facts.match_festival(question)
    if fest and fest.lower() not in question.lower():
        hints.append(f"'{fest}' is the festival they mean")
    if register in ("hinglish", "kanglish"):
        hints.append("written in " + ("Hinglish (Roman-script Hindi)" if register == "hinglish"
                                      else "Kanglish (Roman-script Kannada)"))
    msgs.append({"role": "user", "content": "QUESTION: " + question + (f"  [{'; '.join(hints)}]" if hints else "")})
    try:
        msg, _ = await llm.chat(msgs, json_mode=True, max_tokens=500, temperature=0.3)
    except HTTPException as e:
        return {"source": "error", "error": str(e.detail)[:200]}
    raw = llm.strip_think(msg.get("content") or "")
    try:
        data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError):
        data = {}
    log.debug("talk classification raw: %s", raw[:400])
    src = str(data.get("source") or "none").lower()
    if src == "general":
        return {"source": "general", "festival": data.get("festival")}
    if src != "family" or not data.get("sentences"):
        return {"source": "none", "needs_wider": bool(data.get("needs_wider"))}
    sents, problems = grounding.check(data, alias, corpus)
    if problems:
        msgs2 = msgs + [{"role": "assistant", "content": raw[:3000]},
                        {"role": "user", "content": "That was rejected: " + "; ".join(problems[:8]) +
                         ". Answer again using ONLY names, dates and numbers written in the memories. Same JSON shape."}]
        try:
            sents2, problems2, _ = await _generate(msgs2, alias, corpus, 500)
        except HTTPException:
            sents2 = None
        if not sents2:
            return {"source": "none", "needs_wider": False, "rejected": problems}
        sents = sents2
    return {"source": "family", "sentences": sents}


def _speakable(summary: str) -> str:
    """Encyclopedia text -> something a voice can read: drop (parentheticals) and [notes]."""
    s = re.sub(r"\s*\[[^\]]*\]", "", summary or "")
    for _ in range(3):
        s = re.sub(r"\s*\([^()]*\)", "", s)
    s = re.sub(r"\s*\([^)]*?,", ",", s)          # an unbalanced "(Sanskrit: ...," fragment
    return " ".join(s.replace(" ,", ",").split())


def _wider(scope: dict) -> list[dict]:
    if scope.get("year") and scope.get("month"):
        return [{"year": int(scope["year"])}, {}]
    if scope.get("year"):
        return [{}]
    return []


async def answer(family_id: str, question: str, scope: dict, lang: str, st: dict,
                 register: Optional[str] = None) -> dict:
    """Text-only answer: {"sentences", "source", "scope_used", "action"?, "state"}. Used by talk() and the Agora LLM."""
    q = " ".join((question or "").split())
    reg = register or lang          # fixed lines follow the visitor's register (Hinglish in -> Hinglish out)
    fam = await _family(family_id)
    pending = st.get("pending") or {}

    # 1) pending "shall I ask the family?" -> yes / no in code
    if pending.get("kind") == "ask_family":
        if L.is_yes(q):
            st["pending"] = None
            try:
                from ..telegram import send as tg_send
                await tg_send.ask_family_followup(family_id, pending["question"], pending.get("memory_id"), source="grandma_gap")
                return {"sentences": [{"text": L.t("asked_family", reg), "memory_ids": []}], "source": "none",
                        "action": {"type": "followup_asked", "data": {"question": pending["question"]}}}
            except Exception as e:  # noqa: BLE001
                log.warning("ask_family_followup failed: %s", e)
                return {"sentences": [{"text": L.t("ask_failed", reg), "memory_ids": []}], "source": "none"}
        if L.is_no(q):
            st["pending"] = None
            return {"sentences": [{"text": L.t("okay_no_ask", reg), "memory_ids": []}], "source": "none"}
        st["pending"] = None   # anything else is a new question

    # 2) advice is refused in code
    if ADVICE_RE.search(q) and ADVICE_ASK_RE.search(q):
        return {"sentences": [{"text": L.t("no_advice", reg), "memory_ids": []}], "source": "none"}

    # 3) a plain general question about a festival ("what is the essence of Diwali?") goes to the general source in code
    tried = [dict(scope)]
    mems = await _memories(family_id, scope)
    fest_q = festival_facts.match_festival(q)
    if fest_q and GENERAL_Q_RE.search(q) and not FAMILY_Q_RE.search(q):
        res: dict = {"source": "general", "festival": fest_q}
    else:
        # 4) model: family / general / none, widening scope only when needed
        res = await _family_answer(fam, q, mems, scope, lang, st.get("history") or [], register=reg)
    used = scope
    if res["source"] == "none" and not res.get("needs_wider"):
        # The question names a festival this room has no memory of ("what did we do on Holi?" in November):
        # other months may hold it, so widen in code rather than trusting the model's flag.
        room_fests = {festival_facts.match_festival(m.get("festival") or "") for m in mems}
        if fest_q and fest_q not in room_fests:
            res["needs_wider"] = True
    if res["source"] == "none" and res.get("needs_wider"):
        for wider in _wider(scope):
            wm = await _memories(family_id, wider)
            if len(wm) <= len(mems):
                continue
            tried.append(wider)
            r2 = await _family_answer(fam, q, wm, wider, lang, st.get("history") or [], register=reg)
            if r2["source"] != "none" or not r2.get("needs_wider"):
                res, used, mems = r2, wider, wm
                if r2["source"] != "none":
                    break
    if res["source"] == "error" and festival_facts.match_festival(q) and GENERAL_Q_RE.search(q):
        res = {"source": "general", "festival": festival_facts.match_festival(q)}   # LLM down: festival facts still work
    if res["source"] == "error":
        # LLM down: say so plainly in character, nothing invented.
        return {"sentences": [{"text": L.FAILURE[lang], "memory_ids": []}], "source": "none", "scope_used": used,
                "error": res.get("error")}
    if res["source"] == "family":
        return {"sentences": res["sentences"], "source": "family", "scope_used": used}
    if res["source"] == "general":
        fest = festival_facts.match_festival(str(res.get("festival") or "")) or festival_facts.match_festival(q)
        if not fest:
            fests = {m.get("festival") for m in mems if m.get("festival")}
            fest = next((festival_facts.match_festival(f) for f in fests if festival_facts.match_festival(f)), None)
        from .. import flags
        if not await flags.get("general_knowledge", family_id):
            return {"sentences": [{"text": L.t("general_off", reg), "memory_ids": []}], "source": "none", "scope_used": used}
        info = await festival_facts.festival_summary(fest, lang, family_id) if fest else None
        if info:
            body = grounding.split_sentences(_speakable(info["summary"]))[:3]
            sents = [{"text": L.t("general_label", reg), "memory_ids": []}] + [{"text": s, "memory_ids": []} for s in body]
            return {"sentences": sents, "source": "general", "scope_used": used,
                    "general": {"festival": info["festival"], "source_url": info["source_url"]}}
    # none
    first_id = mems[0]["id"] if mems else None
    st["pending"] = {"kind": "ask_family", "question": q, "memory_id": first_id}
    return {"sentences": [{"text": L.t("dont_have", reg), "memory_ids": []},
                          {"text": L.t("offer_ask", reg), "memory_ids": []}], "source": "none", "scope_used": used}


async def talk(family_id, question: str, scope: dict, language=None, *, state_key: Optional[str] = None,
               member_id: Optional[str] = None, role: str = "viewer", audio: bool = True,
               transcript: Optional[str] = None) -> dict:
    family_id = str(family_id)
    st = await vstate.load(state_key) if state_key else {}
    lang = L.norm(language or st.get("language") or await vstate.family_language(family_id, member_id))
    q = " ".join((question or "").split())
    if not q:
        raise HTTPException(422, "I didn't catch a question.")
    action = None
    switched = L.language_switch(q)
    if switched:
        lang = switched
        st["language"] = lang
        await vstate.set_member_language(member_id, lang)
        res = {"sentences": [{"text": L.t("rx_setting", lang, what=L.t("rx_lang_set", lang)), "memory_ids": []}],
               "source": "none", "action": {"type": "setting_changed", "data": {"key": "language", "value": lang,
                                                                                  "scope": "session"}}}
    elif INVITE_STRICT_RE.search(q) or (st.get("pending") or {}).get("kind") in (
            "choose_contact", "confirm_invite", "need_invite_room"):
        # Inviting from the theater uses the receptionist's invite flow (find contact, confirm aloud, then call).
        from . import reception
        rx = await reception.act_core(family_id, member_id, q, lang, state_key=state_key, room=scope,
                                      role=role, st=None)
        res = {"sentences": [{"text": s, "memory_ids": []} for s in grounding.split_sentences(rx["reply"])],
               "source": "none", "action": rx["action"]}
        st = await vstate.load(state_key) if state_key else st   # reception saved its own state
    else:
        # Mirror the visitor: Hindi / Kannada in any script, Hinglish / Kanglish -> reply voiced and written that way
        # for this turn (the session language itself is unchanged).
        from .reception import turn_register
        lang, reg = turn_register(q, lang, st)
        st["register"] = reg
        res = await answer(family_id, q, scope, lang, st, register=reg)
    action = res.get("action")
    hist = (st.get("history") or []) + [{"role": "user", "content": q},
                                        {"role": "assistant", "content": " ".join(s["text"] for s in res["sentences"])}]
    st["history"] = hist[-8:]
    if state_key:
        await vstate.save(state_key, family_id, member_id, "grandma", st)
    sp = await speech.build(res["sentences"], lang, "grandma", family_id, audio=audio, join=True)
    sp.update({"transcript": transcript if transcript is not None else q, "source": res["source"],
               "scope_used": res.get("scope_used", scope), "action": action or {"type": "none", "data": {}}})
    if res.get("general"):
        sp["general"] = res["general"]
    return sp
