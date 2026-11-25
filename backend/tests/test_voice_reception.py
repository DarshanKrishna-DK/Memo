"""voice-ai: the receptionist. Real LLM calls (Sarvam -> Groq) for intent accuracy; keyword router with the LLM off;
dates never guessed. Real Postgres, real core services."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import pytest_asyncio

from _voice_fixtures import drop_family, fresh_pool, make_family
from app import db
from app.core import common
from app.voice import reception, state as vstate

pytestmark = pytest.mark.asyncio(loop_scope="module")

PHRASINGS = [
    ("en-IN", "I want to add a new festival called Diwali", "create_event"),
    ("en-IN", "Create an event for our Goa trip in December 2025", "create_event"),
    ("en-IN", "Upload everything from yesterday", "query_gallery"),
    ("en-IN", "Add the last 20 photos from my gallery", "query_gallery"),
    ("en-IN", "Take me to the Diwali 2026 room", "plan_route"),
    ("en-IN", "Go to last year's Holi", "plan_route"),
    ("en-IN", "Open March 2025", "plan_route"),
    ("en-IN", "Turn off the sarcasm please", "change_setting"),
    ("en-IN", "Rename grandma to Ammamma", "change_setting"),
    ("en-IN", "Invite my sister Priya to this room", "invite_contact"),
    ("en-IN", "Add the ones with my dad in them", "decline"),
    ("hi-IN", "दिवाली नाम का नया त्योहार जोड़ो", "create_event"),
    ("hi-IN", "कल की सारी फ़ोटो अपलोड करो", "query_gallery"),
    ("hi-IN", "मुझे होली 2025 वाले कमरे में ले चलो", "plan_route"),
    ("hi-IN", "व्यंग्य बंद कर दो", "change_setting"),
    ("hi-IN", "प्रिया को इस कमरे में बुलाओ", "invite_contact"),
    ("kn-IN", "ದೀಪಾವಳಿ ಎಂಬ ಹೊಸ ಹಬ್ಬವನ್ನು ಸೇರಿಸಿ", "create_event"),
    ("kn-IN", "ನಿನ್ನೆಯ ಎಲ್ಲಾ ಫೋಟೋಗಳನ್ನು ಸೇರಿಸಿ", "query_gallery"),
    ("kn-IN", "ನನ್ನನ್ನು ಮಾರ್ಚ್ 2025 ಕೊಠಡಿಗೆ ಕರೆದುಕೊಂಡು ಹೋಗಿ", "plan_route"),
    ("kn-IN", "ಅಜ್ಜಿಯ ಹೆಸರನ್ನು ಅಮ್ಮಮ್ಮ ಎಂದು ಬದಲಿಸಿ", "change_setting"),
]


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def fam():
    await fresh_pool()
    f = await make_family()
    yield f
    await drop_family(f["id"])


async def test_intent_accuracy_real_llm():
    raw_hits, pipe_hits, rows = 0, 0, []
    for lang, text, want in PHRASINGS:
        got, args = await reception.choose_intent(text, lang)          # the model alone
        pgot, _ = await reception.route_intent(text, lang)             # code pre-checks + model (what act() does)
        raw_hits += got == want
        pipe_hits += pgot == want
        rows.append(f"{'OK ' if got == want else 'XX '}{'OK ' if pgot == want else 'XX '} [{lang}] {text!r} -> "
                    f"model={got} {args} pipeline={pgot} (want {want})")
    n = len(PHRASINGS)
    print("\nModel-only intent accuracy: %d/%d = %.0f%%" % (raw_hits, n, raw_hits / n * 100))
    print("Pipeline intent accuracy:   %d/%d = %.0f%%" % (pipe_hits, n, pipe_hits / n * 100))
    print("\n".join(rows))
    assert pipe_hits / n >= 0.9, f"pipeline intent accuracy {pipe_hits / n:.0%} below the 90% target (PRD V2)"


async def test_keyword_router_accuracy_offline():
    hits, rows = 0, []
    for lang, text, want in PHRASINGS:
        plan = reception.keyword_plan(text)
        got = plan[0][0] if plan else "none"
        ok = got == want
        hits += ok
        rows.append(f"{'OK ' if ok else 'XX '} [{lang}] {text!r} -> {got} {plan[0][1] if plan else ''}")
    acc = hits / len(PHRASINGS)
    print("\nKeyword router accuracy: %d/%d = %.0f%%" % (hits, len(PHRASINGS), acc * 100))
    print("\n".join(rows))
    assert acc >= 0.8


async def _events(fid: str, name: str) -> list:
    return await db.fetch("SELECT * FROM events WHERE family_id=$1 AND name ILIKE $2", fid, name)


async def test_date_never_guessed_real_llm(fam):
    key = f"pytest:{fam['id']}:rx1"
    out = await reception.act_core(fam["id"], fam["owner"], "I want to add a new festival called Diwali", "en-IN",
                                   state_key=key)
    print("\n1:", out["source"], out["reply"], out["steps"])
    assert not await _events(fam["id"], "Diwali"), "an event was created without a date"
    assert out["reply"] == "Sure! Which month and year was that?"
    out = await reception.act_core(fam["id"], fam["owner"], "November", "en-IN", state_key=key)
    print("2:", out["reply"])
    assert not await _events(fam["id"], "Diwali")
    assert out["reply"] == "Got it, November. Which year though?"
    out = await reception.act_core(fam["id"], fam["owner"], "2026", "en-IN", state_key=key)
    print("3:", out["reply"], out["action"]["type"])
    ev = await _events(fam["id"], "Diwali")
    assert len(ev) == 1 and (ev[0]["year"], ev[0]["month"]) == (2026, 11)
    assert out["action"]["type"] == "event_created"
    assert out["reply"].startswith("Done! Diwali 2026 is in. It lives on the ground floor, in the November room.")


async def test_keyword_router_with_llm_disabled(fam):
    fid = fam["id"]
    key = f"pytest:{fid}:rx2"
    # missing date: asked, not guessed
    out = await reception.act_core(fid, fam["owner"], "Add a new trip called Coorg", "en-IN", state_key=key, use_llm=False)
    print("\nK1:", out["source"], out["reply"])
    assert out["source"] == "keywords" and not await _events(fid, "Coorg")
    assert out["reply"] == "Sure! Which month and year was that?"
    out = await reception.act_core(fid, fam["owner"], "August 2025", "en-IN", state_key=key, use_llm=False)
    print("K2:", out["reply"])
    ev = await _events(fid, "Coorg")
    assert len(ev) == 1 and (ev[0]["year"], ev[0]["month"]) == (2025, 8) and out["action"]["type"] == "event_created"
    # route
    out = await reception.act_core(fid, fam["owner"], "Take me to August 2025", "en-IN", state_key=key, use_llm=False)
    print("K3:", out["reply"], out["action"]["type"])
    assert out["action"]["type"] == "route" and out["action"]["data"]["month"] == 8
    # faces declined
    out = await reception.act_core(fid, fam["owner"], "add the photos with my dad in them", "en-IN", state_key=key,
                                   use_llm=False)
    assert out["reply"].startswith("Ah, I can't recognise faces")
    # gallery: three photos from yesterday indexed (metadata rows), read out, then declined with "no"
    today = common.tz_today()
    y = today - timedelta(days=1)
    for i in range(3):
        await db.execute(
            "INSERT INTO gallery_items(family_id, source, path_or_handle, taken_at, taken_at_source, size_bytes, width, "
            "height, folder, mime, content_hash) VALUES ($1,'folder',$2,$3,'exif',$4,1200,800,'pytest','image/jpeg',$5)",
            fid, f"pytest/{i}.jpg", datetime(y.year, y.month, y.day, 10 + i, tzinfo=common.tz_now().tzinfo),
            3 * 1024 * 1024, f"pytest-hash-{fid}-{i}")
    out = await reception.act_core(fid, fam["owner"], "Upload everything from yesterday", "en-IN", state_key=key,
                                   use_llm=False)
    print("K4:", out["reply"], out["pending"])
    assert out["reply"].startswith(f"Okay, I found 3 photos from {y.day} ") and "9 MB" in out["reply"]
    assert out["reply"].endswith("Shall I add them to Coorg 2025?") and out["pending"] == "confirm_import"
    out = await reception.act_core(fid, fam["owner"], "no", "en-IN", state_key=key, use_llm=False)
    assert out["reply"] == "No problem, I'll leave it." and out["pending"] is None
    assert await db.fetchval("SELECT count(*) FROM jobs WHERE payload->>'family_id'=$1", fid) == 0


async def test_language_switch_changes_session_and_member(fam):
    key = f"pytest:{fam['id']}:rx3"
    out = await reception.act_core(fam["id"], fam["editor"], "please speak Kannada", "en-IN", state_key=key)
    print("\nL:", out["reply"])
    assert out["language"] == "kn-IN" and out["action"]["type"] == "setting_changed"
    assert await db.fetchval("SELECT language FROM members WHERE id=$1", fam["editor"]) == "kn-IN"
    assert (await vstate.load(key))["language"] == "kn-IN"
    out = await reception.act_core(fam["id"], fam["editor"], "ಹಲೋ", None, state_key=key, use_llm=False)
    assert out["language"] == "kn-IN"


async def test_hindi_create_event_real_llm(fam):
    key = f"pytest:{fam['id']}:rx4"
    out = await reception.act_core(fam["id"], fam["owner"], "होली नाम का त्योहार मार्च 2025 में जोड़ो", "hi-IN", state_key=key)
    print("\nHI:", out["source"], out["reply"], out["steps"])
    ev = await _events(fam["id"], "Holi")
    assert len(ev) == 1 and (ev[0]["year"], ev[0]["month"]) == (2025, 3)
