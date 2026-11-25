"""Memories as Exhibit dicts (web/src/contract.ts), plus edits, moves and deletes with role checks."""
from __future__ import annotations

from typing import Any, Optional

from .. import bus, db, storage
from . import common

_SELECT = (
    "SELECT m.*, a.nickname AS author_name, t.nickname AS teller_name FROM memories m "
    "LEFT JOIN members a ON a.id=m.author_id LEFT JOIN members t ON t.id=m.teller_id ")
_ORDER = " ORDER BY m.event_year NULLS LAST, m.event_month NULLS LAST, m.event_day NULLS LAST, m.captured_at, m.id"
SENSITIVITY = ("none", "loss", "illness", "conflict", "other")


async def _media_for(ids: list) -> dict[str, list]:
    out: dict[str, list] = {}
    if not ids:
        return out
    for r in await db.fetch("SELECT * FROM media WHERE memory_id = ANY($1::uuid[]) "
                            "ORDER BY memory_id, sort_order, taken_at NULLS LAST, created_at", ids):
        out.setdefault(str(r["memory_id"]), []).append(dict(r))
    return out


def exhibit(m: Any, media: list[dict]) -> dict:
    photos = [p for p in media if p["type"] == "photo"]
    voice = next((v for v in media if v["type"] == "voice"), None)
    return {
        "id": str(m["id"]), "kind": m["kind"], "title": m["title"], "text": m["text_original"],
        "summary": m["summary"], "author": m["author_name"], "teller": m["teller_name"] or m["author_name"],
        "event_date": {"year": m["event_year"], "month": m["event_month"], "day": m["event_day"]},
        "festival": m["festival"], "event_id": common.sid(m["event_id"]), "sensitivity": m["sensitivity"],
        "narrate_ok": m["narrate_ok"], "status": m["status"], "people": list(m["people"] or []),
        "author_id": common.sid(m["author_id"]), "captured_at": m["captured_at"].isoformat(),
        "photos": [{
            "id": str(p["id"]),
            "thumb_url": storage.signed_url(p["thumb_key"] or p["large_key"] or p["storage_key"]),
            "url": storage.signed_url(p["large_key"] or p["storage_key"]),
            "original_url": storage.signed_url(p["storage_key"]),
            "width": p["width"], "height": p["height"], "is_blurry": p["is_blurry"],
            "taken_at": p["taken_at"].isoformat() if p["taken_at"] else None,
        } for p in photos],
        "audio_url": storage.signed_url(voice["storage_key"]) if voice and voice["audio_kept"] else None,
        "transcript": voice["transcript"] if voice else None,
        "duration_s": voice["duration_s"] if voice else None,
    }


async def _exhibits(rows: list) -> list[dict]:
    media = await _media_for([r["id"] for r in rows])
    return [exhibit(r, media.get(str(r["id"]), [])) for r in rows]


async def get_memory(family_id, memory_id, any_status: bool = False) -> dict:
    r = await db.fetchrow(_SELECT + "WHERE m.id=$1::uuid AND m.family_id=$2::uuid", str(memory_id), str(family_id))
    if not r or (r["status"] == "deleted" and not any_status):
        raise LookupError("That memory isn't in this museum.")
    return (await _exhibits([r]))[0]


async def room_memories(family_id, year, month, event_id=None) -> list[dict]:
    page = await room_page(family_id, year, month, event_id=event_id, limit=None)
    return page["exhibits"]


async def room_page(family_id, year, month, event_id=None, cursor: Optional[str] = None,
                    limit: Optional[int] = 50) -> dict:
    """Saved memories of a room in date order, cursor = opaque offset string."""
    q = _SELECT + "WHERE m.family_id=$1::uuid AND m.status='saved' AND m.event_year=$2 AND m.event_month=$3"
    args: list = [str(family_id), int(year), int(month)]
    if event_id:
        args.append(str(event_id))
        q += f" AND m.event_id=${len(args)}::uuid"
    q += _ORDER
    offset = 0
    if cursor:
        try:
            offset = max(0, int(cursor))
        except ValueError as e:
            raise ValueError("Bad cursor.") from e
    if limit:
        q += f" OFFSET {offset} LIMIT {int(limit) + 1}"
    rows = await db.fetch(q, *args)
    nxt = None
    if limit and len(rows) > limit:
        rows = rows[:limit]
        nxt = str(offset + limit)
    return {"exhibits": await _exhibits(rows), "next_cursor": nxt}


async def scope_memories(family_id, scope: dict) -> list[dict]:
    q = _SELECT + "WHERE m.family_id=$1::uuid AND m.status='saved'"
    args: list = [str(family_id)]
    if scope and scope.get("year"):
        args.append(int(scope["year"]))
        q += f" AND m.event_year=${len(args)}"
        if scope.get("month"):
            args.append(int(scope["month"]))
            q += f" AND m.event_month=${len(args)}"
    # never leak rooms the family closed with care
    q += (" AND NOT EXISTS (SELECT 1 FROM room_settings rs WHERE rs.family_id=m.family_id AND rs.year=m.event_year "
          "AND rs.month=m.event_month AND rs.mode='closed_with_care')")
    return await _exhibits(await db.fetch(q + _ORDER, *args))


async def attic(family_id) -> list[dict]:
    rows = await db.fetch(_SELECT + "WHERE m.family_id=$1::uuid AND m.status='attic' ORDER BY m.captured_at DESC",
                          str(family_id))
    return await _exhibits(rows)


async def check_edit(family_id, member_id, role, memory_id) -> dict:
    """Owner may edit anything; editor only own memories unless family setting editors_edit_others."""
    r = await db.fetchrow("SELECT id, author_id, status FROM memories WHERE id=$1::uuid AND family_id=$2::uuid",
                          str(memory_id), str(family_id))
    if not r or r["status"] == "deleted":
        raise LookupError("That memory isn't in this museum.")
    if role == "owner":
        return dict(r)
    if role != "editor":
        raise PermissionError("Viewers can't change memories.")
    if common.sid(r["author_id"]) == common.sid(member_id):
        return dict(r)
    fam = await common.family(family_id)
    if fam["settings"].get("editors_edit_others"):
        return dict(r)
    raise PermissionError("Only the person who sent this memory, or the owner, can change it.")


async def move_memory(family_id, memory_id, year, month, day=None) -> None:
    year, month = int(year), int(month)
    if not (1900 <= year <= 2200 and 1 <= month <= 12):
        raise ValueError("That isn't a valid year and month.")
    if day is not None:
        from calendar import monthrange
        day = int(day)
        if not (1 <= day <= monthrange(year, month)[1]):
            raise ValueError("That day doesn't exist in that month.")
    r = await db.fetchrow(
        "UPDATE memories m SET event_year=$3, event_month=$4, event_day=$5, date_confidence=1.0, "
        "  status = CASE WHEN status IN ('attic','received','processing') THEN 'saved' ELSE status END, "
        "  event_id = CASE WHEN EXISTS (SELECT 1 FROM events e WHERE e.id=m.event_id AND e.year=$3 AND e.month=$4) "
        "             THEN event_id ELSE NULL END, updated_at=now() "
        "WHERE id=$1::uuid AND family_id=$2::uuid AND status <> 'deleted' RETURNING id, title, summary",
        str(memory_id), str(family_id), year, month, day)
    if not r:
        raise LookupError("That memory isn't in this museum.")
    await bus.publish(str(family_id), {"type": "memory_saved", "memory_id": str(r["id"]), "year": year,
                                       "month": month, "title": r["title"] or r["summary"]})


async def edit_memory(family_id, memory_id, fields: dict) -> dict:
    allowed = {"title", "text", "summary", "festival", "people", "sensitivity", "narrate_ok", "event_id", "teller_id"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"Can't change: {', '.join(sorted(bad))}.")
    sets, args = [], [str(memory_id), str(family_id)]

    def add(col: str, val: Any, cast: str = "") -> None:
        args.append(val)
        sets.append(f"{col}=${len(args)}{cast}")

    if "title" in fields:
        add("title", (fields["title"] or "").strip()[:200] or None)
    if "text" in fields:
        add("text_original", fields["text"])
    if "summary" in fields:
        add("summary", fields["summary"])
    if "festival" in fields:
        add("festival", (fields["festival"] or "").strip() or None)
    if "people" in fields:
        ppl = fields["people"] or []
        if not isinstance(ppl, list) or not all(isinstance(p, str) for p in ppl):
            raise ValueError("people must be a list of names.")
        add("people", [p.strip() for p in ppl if p.strip()], "::text[]")
    if "sensitivity" in fields:
        if fields["sensitivity"] not in SENSITIVITY:
            raise ValueError(f"sensitivity must be one of {', '.join(SENSITIVITY)}.")
        add("sensitivity", fields["sensitivity"])
    if "narrate_ok" in fields:
        add("narrate_ok", bool(fields["narrate_ok"]))
    if "teller_id" in fields:
        tid = fields["teller_id"]
        if tid and not await db.fetchval("SELECT 1 FROM members WHERE id=$1::uuid AND family_id=$2::uuid",
                                         str(tid), str(family_id)):
            raise ValueError("That teller isn't in this family.")
        add("teller_id", common.sid(tid), "::uuid")
    if "event_id" in fields:
        eid = fields["event_id"]
        if eid:
            e = await db.fetchrow("SELECT year, month FROM events WHERE id=$1::uuid AND family_id=$2::uuid",
                                  str(eid), str(family_id))
            if not e:
                raise ValueError("That event isn't in this family.")
            cur = await db.fetchrow("SELECT event_year, event_month FROM memories WHERE id=$1::uuid", str(memory_id))
            if cur and (cur["event_year"], cur["event_month"]) != (e["year"], e["month"]):
                raise ValueError("That event is in a different month; move the memory first.")
        add("event_id", common.sid(eid), "::uuid")
    if sets:
        await db.execute(f"UPDATE memories SET {', '.join(sets)}, updated_at=now() "
                         "WHERE id=$1::uuid AND family_id=$2::uuid AND status <> 'deleted'", *args)
    return await get_memory(family_id, memory_id)


async def delete_memory(family_id, memory_id) -> None:
    """User-initiated delete: media files and rows go; the memory row stays as 'deleted' so a Telegram
    redelivery of the same update cannot resurrect it (idempotency key)."""
    rows = await db.fetch("SELECT md.storage_key, md.large_key, md.thumb_key FROM media md JOIN memories m "
                          "ON m.id=md.memory_id WHERE m.id=$1::uuid AND m.family_id=$2::uuid",
                          str(memory_id), str(family_id))
    r = await db.fetchrow(
        "UPDATE memories SET status='deleted', text_original=NULL, summary=NULL, title=NULL, people='{}', "
        "updated_at=now() WHERE id=$1::uuid AND family_id=$2::uuid AND status <> 'deleted' "
        "RETURNING event_year, event_month", str(memory_id), str(family_id))
    if not r:
        raise LookupError("That memory isn't in this museum.")
    await db.execute("DELETE FROM media WHERE memory_id=$1::uuid", str(memory_id))
    await db.execute("UPDATE gallery_items SET imported_memory_id=NULL WHERE imported_memory_id=$1::uuid",
                     str(memory_id))
    for x in rows:
        for k in (x["storage_key"], x["large_key"], x["thumb_key"]):
            storage.delete(k)
