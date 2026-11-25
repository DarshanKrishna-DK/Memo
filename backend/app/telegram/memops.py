"""Memory operations shared by the update handlers and the capture job: placing, receipts, voice choice, delete."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .. import bus, db, storage
from .copy import MONTHS, t


def when_label(year: int | None, month: int | None) -> str:
    return f"{MONTHS[month - 1]} {year}" if year and month else ""


def receipt_text(mem, lang: str) -> str:
    title = (mem["title"] or "").strip() or "Memory"
    when = when_label(mem["event_year"], mem["event_month"])
    head = ", ".join(x for x in (mem["festival"], when) if x)
    return f"{head}: {title}" if head else title


def receipt_buttons(mid: str, lang: str) -> list[list[dict]]:
    return [[{"text": t(lang, "wrong_date"), "data": f"wd:{mid}"},
             {"text": t(lang, "wrong_fest"), "data": f"wf:{mid}"},
             {"text": t(lang, "delete"), "data": f"del:{mid}"}]]


def year_buttons(mid: str, lang: str, prefix: str = "y") -> list[list[dict]]:
    now = datetime.now(ZoneInfo("Asia/Kolkata")).year
    years = [now - i for i in range(0, 6)]
    rows = [[{"text": str(y), "data": f"{prefix}:{mid}:{y}"} for y in years[i:i + 3]] for i in (0, 3)]
    rows.append([{"text": t(lang, "not_sure"), "data": f"na:{mid}"}])
    return rows


def month_buttons(mid: str, year: int) -> list[list[dict]]:
    return [[{"text": MONTHS[m - 1], "data": f"m:{mid}:{year}:{m}"} for m in range(r, r + 4)] for r in (1, 5, 9)]


def voice_buttons(mid: str, lang: str) -> list[list[dict]]:
    return [[{"text": t(lang, c), "data": f"vk:{mid}:{c}"} for c in ("voice", "words", "both")]]


async def place(memory_id: str, year: int, month: int, day: int | None = None, confidence: float = 1.0) -> None:
    """Give an attic/processing memory its room (status saved). Already-saved memories go through core move_memory."""
    mem = await db.fetchrow("SELECT family_id, status, title FROM memories WHERE id=$1", memory_id)
    if mem is None or mem["status"] == "deleted":
        return
    if mem["status"] == "saved":
        try:
            from app.core.memories import move_memory
        except ImportError:   # core-api not merged yet: same effect, direct
            await db.execute("UPDATE memories SET event_year=$2, event_month=$3, event_day=$4, date_confidence=1, "
                             "updated_at=now() WHERE id=$1", memory_id, year, month, day)
            await bus.publish(str(mem["family_id"]), {"type": "memory_saved", "memory_id": str(memory_id),
                                                      "year": year, "month": month, "title": mem["title"]})
            return
        await move_memory(str(mem["family_id"]), memory_id, year, month, day)
        return
    await db.execute("UPDATE memories SET event_year=$2, event_month=$3, event_day=$4, date_confidence=$5, "
                     "status='saved', updated_at=now() WHERE id=$1", memory_id, year, month, day, confidence)
    await bus.publish(str(mem["family_id"]), {"type": "memory_saved", "memory_id": str(memory_id),
                                              "year": year, "month": month, "title": mem["title"]})


async def delete_memory(memory_id: str) -> None:
    rows = await db.fetch("SELECT storage_key, large_key, thumb_key FROM media WHERE memory_id=$1", memory_id)
    for r in rows:
        for k in (r["storage_key"], r["large_key"], r["thumb_key"]):
            storage.delete(k)
    await db.execute("DELETE FROM media WHERE memory_id=$1", memory_id)
    await db.execute("UPDATE memories SET status='deleted', text_original=NULL, summary=NULL, updated_at=now() "
                     "WHERE id=$1", memory_id)


async def apply_voice_choice(memory_id: str, choice: str) -> None:
    """voice: keep audio, drop the transcript text. words: delete the audio file only if the transcript is saved.
    both: keep everything. Nothing is removed until a choice is made."""
    if choice == "words":
        rows = await db.fetch("SELECT id, storage_key FROM media WHERE memory_id=$1 AND type='voice' "
                              "AND coalesce(transcript,'') <> ''", memory_id)
        for r in rows:
            storage.delete(r["storage_key"])
            await db.execute("UPDATE media SET storage_key=NULL, audio_kept=false WHERE id=$1", r["id"])
    elif choice == "voice":
        await db.execute("UPDATE media SET transcript=NULL WHERE memory_id=$1 AND type='voice' AND storage_key IS NOT NULL",
                         memory_id)
        await db.execute("UPDATE memories SET text_original = coalesce(tg_meta->>'typed','') WHERE id=$1", memory_id)
