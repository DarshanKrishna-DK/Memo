"""voice-ai test helpers: a throwaway family with real memories in the real Postgres (deleted afterwards)."""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db, storage  # noqa: E402


async def fresh_pool() -> None:
    db._pool = None
    await db.init_schema()


async def make_family(language: str = "en-IN", grandma: str = "Ajji") -> dict:
    fid = await db.fetchval(
        "INSERT INTO families(name, language, grandma_name, invite_code) VALUES ($1,$2,$3,$4) RETURNING id",
        f"pytest-voice-{secrets.token_hex(4)}", language, grandma, "pytest-voice-" + secrets.token_urlsafe(16))
    owner = await db.fetchval(
        "INSERT INTO members(family_id, nickname, role, language) VALUES ($1,'Asha','owner',$2) RETURNING id", fid, language)
    editor = await db.fetchval(
        "INSERT INTO members(family_id, nickname, role, language) VALUES ($1,'Ravi','editor',$2) RETURNING id", fid, language)
    return {"id": str(fid), "owner": str(owner), "editor": str(editor)}


async def drop_family(fid: str) -> None:
    await db.execute("DELETE FROM families WHERE id=$1::uuid", fid)
    storage.delete_prefix(fid)


async def add_memory(fid: str, author: str, year: int, month: int, day: int | None, kind: str, title: str, text: str,
                     *, festival: str | None = None, people: list[str] | None = None, sensitivity: str = "none",
                     narrate_ok: bool = True, transcript: str | None = None) -> str:
    mid = str(await db.fetchval(
        "INSERT INTO memories(family_id, author_id, teller_id, kind, title, text_original, summary, event_year, event_month,"
        " event_day, festival, people, sensitivity, narrate_ok, status, date_confidence) "
        "VALUES ($1::uuid,$2::uuid,$2::uuid,$3,$4,$5,$4,$6,$7,$8,$9,$10,$11,$12,'saved',1) RETURNING id",
        fid, author, kind, title, text, year, month, day, festival, people or [], sensitivity, narrate_ok))
    if kind == "voice":
        await db.execute("INSERT INTO media(memory_id, type, transcript, duration_s, audio_kept) VALUES ($1,'voice',$2,12,false)",
                         mid, transcript or text)
    return mid


async def seed_november_room(f: dict) -> dict:
    """November 2026: Diwali memories from Asha and Ravi, one voice note, one gentle memory, one 'don't narrate'."""
    fid, asha, ravi = f["id"], f["owner"], f["editor"]
    ids = {
        "lamps": await add_memory(fid, asha, 2026, 11, 8, "text", "Lighting the lamps on the terrace",
                                  "Asha and Meera lit forty diyas on the terrace while Ravi burst crackers.",
                                  festival="Diwali", people=["Meera", "Ravi"]),
        "sweets": await add_memory(fid, ravi, 2026, 11, 9, "voice", "Kaju katli from Lakshmi Sweets",
                                   "Ravi bought two boxes of kaju katli from Lakshmi Sweets in Jayanagar.",
                                   festival="Diwali", people=["Ravi"]),
        "nani": await add_memory(fid, asha, 2026, 11, 12, "text", "Missing Nani this Diwali",
                                 "Our first Diwali without Nani. We kept her brass lamp lit all night.",
                                 festival="Diwali", people=["Nani"], sensitivity="loss"),
        "secret": await add_memory(fid, asha, 2026, 11, 14, "text", "Surprise for Kumar",
                                   "Planning a surprise party for Kumar, do not tell anyone.", people=["Kumar"],
                                   narrate_ok=False),
    }
    return ids
