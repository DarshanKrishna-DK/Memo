"""voice-ai: Grandma's accuracy checks, and real tours / answers against a seeded room (real LLM, real Postgres)."""
from __future__ import annotations

import pytest
import pytest_asyncio

from _voice_fixtures import drop_family, fresh_pool, make_family, seed_november_room
from app import db
from app.voice import grandma, grounding

pytestmark = pytest.mark.asyncio(loop_scope="module")

MEMS = [
    {"id": "11111111-1111-1111-1111-111111111111", "kind": "text", "title": "Lighting the lamps",
     "text": "Asha and Meera lit forty diyas on the terrace.", "author": "Asha", "teller": "Asha",
     "event_date": {"year": 2026, "month": 11, "day": 8}, "festival": "Diwali", "people": ["Meera"]},
    {"id": "22222222-2222-2222-2222-222222222222", "kind": "voice", "title": "Kaju katli",
     "text": "Ravi bought two boxes of kaju katli.", "author": "Ravi", "teller": "Ravi",
     "event_date": {"year": 2026, "month": 11, "day": 9}, "festival": "Diwali", "people": []},
]
FACTS = grandma.compute_facts(MEMS, {"year": 2026, "month": 11}, "en-IN")
ALIAS = {"m1": MEMS[0]["id"], "m2": MEMS[1]["id"]}


def corpus():
    return grounding.build_corpus(MEMS, FACTS, ["Ajji", "November 2026"])


def test_grounded_text_passes():
    out = {"sentences": [
        {"text": "On 8 November, Asha and Meera lit forty diyas on the terrace.", "memory_ids": ["m1"], "names": ["Asha", "Meera"]},
        {"text": "The next day Ravi brought two boxes of kaju katli. Lovely, isn't it?", "memory_ids": ["m2"]},
        {"text": "November 2026 has two memories.", "memory_ids": []},
    ]}
    sents, problems = grounding.check(out, ALIAS, corpus())
    assert problems == [], problems
    assert sents[0]["memory_ids"] == [MEMS[0]["id"]]


def test_rejects_invented_name():
    out = {"sentences": [{"text": "Uncle Suresh lit the lamps with Asha.", "memory_ids": ["m1"]}]}
    _, problems = grounding.check(out, ALIAS, corpus())
    assert any("Suresh" in p for p in problems), problems


def test_rejects_invented_date_and_month():
    out = {"sentences": [{"text": "On 23 October, Asha lit the lamps.", "memory_ids": ["m1"]}]}
    _, problems = grounding.check(out, ALIAS, corpus())
    assert any("23" in p for p in problems), problems
    assert any("October" in p for p in problems), problems


def test_rejects_invented_number_word_and_year():
    out = {"sentences": [{"text": "Ravi bought seven boxes back in 2019.", "memory_ids": ["m2"]}]}
    _, problems = grounding.check(out, ALIAS, corpus())
    assert any("7" in p for p in problems) and any("2019" in p for p in problems), problems


def test_rejects_unknown_memory_id_and_declared_name():
    out = {"sentences": [{"text": "Asha smiled.", "memory_ids": ["m9"], "names": ["Priyanka"]}]}
    _, problems = grounding.check(out, ALIAS, corpus())
    assert any("unknown memory id" in p for p in problems)
    assert any("Priyanka" in p for p in problems)


def test_hindi_text_numbers_and_months_checked():
    ok = {"sentences": [{"text": "8 नवंबर को Asha और Meera ने दीये जलाए।", "memory_ids": ["m1"]}]}
    assert grounding.check(ok, ALIAS, corpus())[1] == []
    bad = {"sentences": [{"text": "15 अक्टूबर को Asha ने दीये जलाए।", "memory_ids": ["m1"]}]}
    probs = grounding.check(bad, ALIAS, corpus())[1]
    assert any("15" in p for p in probs) and any("October" in p for p in probs), probs


def test_kannada_words_are_not_mistaken_for_months():
    ok = {"sentences": [{"text": "ನವೆಂಬರ್ 8 ರಂದು Asha ಮತ್ತು Meera ಮನೆಯ ಮೇಲೆ ದೀಪ ಹಚ್ಚಿದರು.", "memory_ids": ["m1"]}]}
    assert grounding.check(ok, ALIAS, corpus())[1] == []          # ಮೇಲೆ ("on top") is not ಮೇ (May)
    bad = {"sentences": [{"text": "ಮೇ 3 ರಂದು Asha ದೀಪ ಹಚ್ಚಿದರು.", "memory_ids": ["m1"]}]}
    probs = grounding.check(bad, ALIAS, corpus())[1]
    assert any("May" in p for p in probs) and any("3" in p for p in probs), probs


# ---------------------------------------------------------------- real model on a seeded room

@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def fam():
    await fresh_pool()
    f = await make_family()
    f["mem"] = await seed_november_room(f)
    yield f
    await drop_family(f["id"])


async def test_tour_is_grounded_and_skips_dont_narrate(fam):
    sp = await grandma.tour(fam["id"], 2026, 11, language="en-IN", audio=False)
    print("\nTOUR source:", sp["source"])
    for s in sp["sentences"]:
        print("  ", s["text"], s["memory_ids"])
    text = sp["text"]
    assert "Kumar" not in text and fam["mem"]["secret"] not in sp["memory_ids"]
    valid = set(fam["mem"].values())
    assert set(sp["memory_ids"]) <= valid
    # every sentence passes the entity check against the room's narratable memories
    mems = [m for m in await grandma._memories(fam["id"], {"year": 2026, "month": 11}) if m["narrate_ok"]]
    facts = grandma.compute_facts(mems, {"year": 2026, "month": 11}, "en-IN")
    c = grounding.build_corpus(mems, facts, ["Ajji", facts["scope"], (await db.fetchval(
        "SELECT name FROM families WHERE id=$1", fam["id"]))])
    for s in sp["sentences"]:
        assert grounding.entity_problems(s["text"], c) == [], s["text"]
    words = len(text.split())
    print("TOUR words:", words, "estimated seconds at 2.5 w/s:", round(words / 2.5))
    # resume: the same tour from sentence 2 starts with sentence 2
    sp2 = await grandma.tour(fam["id"], 2026, 11, language="en-IN", resume_from=2, audio=False)
    assert sp2["sentences"][0]["index"] == 2 and sp2["sentences"][0]["text"] == sp["sentences"][2]["text"]


async def test_greeting_from_facts(fam):
    sp = await grandma.greet(fam["id"], 2026, 11, language="en-IN", audio=False)
    assert sp["sentences"][0]["text"] == "Oh, welcome back! November 2026 has four memories, one of them a voice note."


async def test_talk_family_none_general_and_advice(fam):
    st: dict = {}
    fa = await grandma.answer(fam["id"], "Who bought the sweets?", {"year": 2026, "month": 11}, "en-IN", st)
    print("\nFAMILY:", fa["source"], [s["text"] for s in fa["sentences"]])
    assert fa["source"] == "family" and "Ravi" in " ".join(s["text"] for s in fa["sentences"])
    none = await grandma.answer(fam["id"], "What was the name of grandpa's first school?", {"year": 2026, "month": 11},
                                "en-IN", st)
    print("NONE:", none["source"], [s["text"] for s in none["sentences"]])
    assert none["source"] == "none" and "isn't in your family's memories" in none["sentences"][0]["text"]
    assert st["pending"]["kind"] == "ask_family"
    st["pending"] = None
    gen = await grandma.answer(fam["id"], "What is the essence of Diwali?", {"year": 2026, "month": 11}, "en-IN", st)
    print("GENERAL:", gen["source"], [s["text"] for s in gen["sentences"]][:2])
    assert gen["source"] == "general"
    assert gen["sentences"][0]["text"].startswith("Now, this isn't from your family's memories, but")
    adv = await grandma.answer(fam["id"], "Should I take my blood pressure tablet twice?", {"year": 2026, "month": 11},
                               "en-IN", st)
    assert "advice I can't give" in adv["sentences"][0]["text"]


def test_fillers_hinglish_and_festival_aliases_are_not_entities():
    c = corpus()
    for text in ["Arre, Asha and Meera lit forty diyas!", "Achha, you know, Ravi bought kaju katli.",
                 "Nodu, Deepavali alli Asha mattu Meera deepa hachchidru.", "Dekho, Tumhe yaad hai? Ravi laaya tha.",
                 "Hmm, Ayyo, that Diwali... Ravi bought two boxes.", "Oho! Haan, Meera was there."]:
        assert grounding.entity_problems(text, c) == [], text
    # invented facts are still caught inside code-mixed text
    assert any("Suresh" in p for p in grounding.entity_problems("Arre, Suresh laaya tha mithai.", c))
    assert any("2019" in p for p in grounding.entity_problems("Nodu, 2019 alli Ravi bandru.", c))
