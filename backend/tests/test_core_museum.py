"""core-api: room states, deterministic boards, floors/levels, routes and place resolution (real Postgres)."""
from __future__ import annotations

import pytest
import pytest_asyncio

from _core_fixtures import add_memory, drop_family, fresh_pool, make_family
from app import db, flags
from app.core import common, events, museum, routing, settings

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def fam():
    await fresh_pool()
    f = await make_family()
    today = common.tz_today()
    f["today"] = today
    y = today.year
    f["first"] = y - 3
    # open rooms: Jan of first year, Mar of last year (Holi), the current month is left empty
    await add_memory(f["id"], y - 3, 1, author=f["owner"], title="First steps")
    await add_memory(f["id"], y - 1, 3, author=f["owner"], title="Colours everywhere", festival="Holi")
    await add_memory(f["id"], y - 1, 11, author=f["owner"], title="Lamps", festival="Diwali")
    await add_memory(f["id"], y - 1, 6, author=f["owner"], title="An attic one", status="attic")
    yield f
    await drop_family(f["id"])
    await db.close()


async def test_floor_levels(fam):
    assert museum.floor_level(2023, 2023) == 0
    assert museum.floor_level(2023, 2026) == 3
    fl = await museum.floors(fam["id"])
    y = fam["today"].year
    assert [x["year"] for x in fl] == [y, y - 1, y - 2, y - 3]          # newest first, includes current year
    assert [x["level"] for x in fl] == [3, 2, 1, 0]
    assert fl[1]["open"] == 2 and fl[2]["open"] == 0 and fl[3]["open"] == 1


async def test_room_states(fam):
    t = fam["today"]
    y = t.year
    rooms = (await museum.year_rooms(fam["id"], y - 1))["rooms"]
    assert rooms[2]["state"] == "open" and rooms[2]["memory_count"] == 1 and rooms[2]["festival"] == "Holi"
    assert rooms[2]["board_text"] is None
    assert rooms[5]["state"] == "locked"                     # attic memory does not open a room
    st = await museum.room_state(fam["id"], y, t.month)
    assert st["state"] == "current_empty"
    assert "Ajji" in st["board_text"]
    if t.month < 12:
        assert (await museum.room_state(fam["id"], y, t.month + 1))["state"] == "not_yet"
    # whole floor empty in a past year -> whole-floor line
    empty = await museum.year_rooms(fam["id"], y - 2)
    assert empty["floor_board"] == museum.FLOOR_EMPTY
    assert all(museum.FLOOR_EMPTY in r["board_text"] for r in empty["rooms"])


async def test_board_is_deterministic_and_prompts(fam):
    y = fam["today"].year
    a = museum.board_text(fam["id"], y - 1, 5, "locked", "Ajji", True)
    b = museum.board_text(fam["id"], y - 1, 5, "locked", "Ajji", True)
    assert a == b
    assert a.endswith("Tell Ajji on Telegram to open this door.")
    assert a.split(" Tell ")[0] in museum.LOCKED
    texts = {museum.board_text(fam["id"], y - 1, m, "locked", "Ajji", True) for m in range(1, 13)}
    assert len(texts) > 1                                          # varies across rooms
    first = (await museum.year_rooms(fam["id"], y - 1))["rooms"][4]["board_text"]
    again = (await museum.year_rooms(fam["id"], y - 1))["rooms"][4]["board_text"]
    assert first == again
    assert museum.board_text(fam["id"], y + 1, 1, "not_yet", "Ajji", True) in museum.NOT_YET
    assert museum.board_text(fam["id"], y, 1, "closed", "Ajji", True) == "Closed with care."
    off = museum.board_text(fam["id"], y - 1, 5, "locked", "Dadi", False)
    assert off == "No memories here yet. Tell Dadi on Telegram to open this door."


async def test_sarcasm_switch_and_closed_with_care(fam):
    y = fam["today"].year
    await settings.change_setting(fam["id"], "sarcasm", False)
    try:
        rooms = (await museum.year_rooms(fam["id"], y - 1))["rooms"]
        assert rooms[4]["board_text"].startswith("No memories here yet.")
    finally:
        await settings.change_setting(fam["id"], "sarcasm", True)
    await settings.change_setting(fam["id"], "closed_with_care", {"year": y - 1, "month": 3, "closed": True})
    st = await museum.room_state(fam["id"], y - 1, 3)
    assert st == {"state": "closed", "memory_count": 0, "board_text": "Closed with care."}
    await settings.change_setting(fam["id"], "closed_with_care", {"year": y - 1, "month": 3, "closed": False})
    assert (await museum.room_state(fam["id"], y - 1, 3))["state"] == "open"


async def test_routes_by_level(fam):
    y = fam["today"].year
    ground = await routing.plan_route(fam["id"], y - 3, 1)
    assert ground["level"] == 0 and ground["needs_lift"] is False
    assert [w["kind"] for w in ground["waypoints"]] == ["desk", "corridor", "door", "seat"]
    assert ground["waypoints"][2]["door_index"] == 0
    assert ground["walk_seconds"] == 5
    up = await routing.plan_route(fam["id"], y - 1, 3)
    assert up["level"] == 2 and up["needs_lift"] is True
    assert [w["kind"] for w in up["waypoints"]] == ["desk", "lift", "ride", "corridor", "door", "seat"]
    assert up["waypoints"][2]["level"] == 2 and up["waypoints"][4]["door_index"] == 2
    assert 5 <= up["walk_seconds"] <= 10
    locked = await routing.plan_route(fam["id"], y - 1, 5)
    assert locked["room_state"] == "locked" and locked["waypoints"][-1]["kind"] == "door"   # nobody sits
    assert locked["board_text"]
    # the cinematic_walk flag scales the walk
    await flags.set_override("cinematic_walk", {"enabled": True, "seconds": 10}, fam["id"])
    assert (await routing.plan_route(fam["id"], y - 1, 3))["walk_seconds"] == 10
    await flags.set_override("cinematic_walk", {"enabled": False, "seconds": 8}, fam["id"])
    assert (await routing.plan_route(fam["id"], y - 1, 3))["walk_seconds"] == 0
    await db.execute("DELETE FROM flag_overrides WHERE family_id=$1::uuid", fam["id"])
    flags._cache.clear()
    with pytest.raises(LookupError):
        await routing.plan_route(fam["id"], y - 10, 1)


async def test_events_and_place_resolution(fam):
    y = fam["today"].year
    out = await events.create_event(fam["id"], fam["owner"], "Diwali", "", y, 11)
    assert out["event"]["kind"] == "festival"
    assert out["level"] == 3 and out["room"] == {"year": y, "month": 11}
    again = await events.create_event(fam["id"], fam["owner"], "diwali", "festival", y, 11)
    assert again["event"]["id"] == out["event"]["id"] and again["created"] is False
    eid = out["event"]["id"]

    r = await routing.resolve_place(fam["id"], f"take me to the Diwali {y} room")
    assert r["question"] is None and r["candidates"] == [
        {"year": y, "month": 11, "event_id": eid, "label": f"Diwali (November {y})"}]
    # Diwali exists in two years (event this year, tagged memory last year) -> one question
    r = await routing.resolve_place(fam["id"], "go to Diwali")
    assert r["question"].startswith("Which year of Diwali?") and len(r["candidates"]) == 2
    r = await routing.resolve_place(fam["id"], "go to last year's Holi")
    assert r["question"] is None and (r["candidates"][0]["year"], r["candidates"][0]["month"]) == (y - 1, 3)
    r = await routing.resolve_place(fam["id"], "open March 2025")
    assert r["question"] is None and (r["candidates"][0]["year"], r["candidates"][0]["month"]) == (2025, 3)
    r = await routing.resolve_place(fam["id"], f"take me to {y - 1}")
    assert r["candidates"] == [] and r["question"] == f"Which month of {y - 1}?"
    found = await events.find_events(fam["id"], "deepavali")
    assert [e["id"] for e in found] == [eid]
