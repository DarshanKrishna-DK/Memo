"""capture job: download media, speech-to-text, tag, place (saved or attic + one question), receipt."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .. import db, jobs, storage
from ..ai import stt, tagger
from ..telegram import memops, send
from ..telegram.copy import t

log = logging.getLogger("memo.capture")
BLUR_THRESHOLD_DEFAULT = 100.0


async def _download_all(mem, media) -> int:
    """Fetch + store every pending media row. Returns number of blurry photos newly found."""
    fam, blurry = str(mem["family_id"]), 0
    keep_loc = bool((mem["fsettings"] or {}).get("keep_location"))
    try:
        from app.media.images import BLUR_THRESHOLD
    except ImportError:
        BLUR_THRESHOLD = BLUR_THRESHOLD_DEFAULT
    for m in media:
        if m["storage_key"] or not m["audio_kept"] or not m["tg_file_id"]:
            continue
        try:
            data, path = await send.download_file(m["tg_file_id"])
        except send.TelegramError as e:
            if e.code == 400 or "too large" in str(e):          # over the Bot API 20 MB limit: tell the sender
                await db.execute("DELETE FROM media WHERE id=$1", m["id"])
                if mem["tg_chat_id"]:
                    await send.send_message(mem["tg_chat_id"], t(mem["flang"], "too_big"))
                continue
            raise
        if m["type"] == "voice":
            key = storage.put(storage.new_key(fam, "voice", ".ogg"), data)
            mime = m["mime"] or "audio/ogg"
            res, err = None, None
            for attempt in range(2):
                try:
                    res = await stt.transcribe(data, mime)
                    break
                except stt.SttError as e:
                    err = e
                    await asyncio.sleep(2)
            if res is None:
                log.warning("transcription failed for media %s: %s", m["id"], err)
            await db.execute(
                "UPDATE media SET storage_key=$2, transcript=$3, duration_s=$4, mime=$5 WHERE id=$1", m["id"], key,
                res["text"] if res else None, res["duration_s"] if res else None, mime)
            if res and res["language"]:
                await db.execute("UPDATE memories SET tg_meta = tg_meta || jsonb_build_object('stt_language',$2::text) "
                                 "WHERE id=$1", mem["id"], res["language"])
        elif m["type"] == "photo":
            from app.media.images import process_photo
            r = await asyncio.to_thread(process_photo, data, keep_loc)
            fk = storage.put(storage.new_key(fam, "photos", ".jpg"), r["original"])
            lk = storage.put(storage.new_key(fam, "photos", ".jpg"), r["large"])
            tk = storage.put(storage.new_key(fam, "photos", ".jpg"), r["thumb"])
            is_blur = r["blur_score"] < BLUR_THRESHOLD
            blurry += int(is_blur)
            await db.execute(
                "UPDATE media SET storage_key=$2, large_key=$3, thumb_key=$4, width=$5, height=$6, taken_at=$7, "
                "blur_score=$8, is_blurry=$9, content_hash=$10, mime='image/jpeg' WHERE id=$1",
                m["id"], fk, lk, tk, r["width"], r["height"], r["taken_at"], r["blur_score"], is_blur, r["content_hash"])
    return blurry


async def _load(mid: str):
    return await db.fetchrow(
        """SELECT m.*, f.language flang, f.timezone ftz, f.settings fsettings, f.grandma_name,
                  a.voice_keep_default vdefault, a.telegram_chat_id author_chat
           FROM memories m JOIN families f ON f.id=m.family_id LEFT JOIN members a ON a.id=m.author_id
           WHERE m.id=$1""", mid)


@jobs.handler("capture")
async def capture(payload: dict) -> dict:
    mid = payload["memory_id"]
    mem = await _load(mid)
    if mem is None or mem["status"] in ("deleted", "failed"):
        return {"skipped": True}
    chat = mem["tg_chat_id"] or mem["author_chat"]
    lang = mem["flang"]
    late = mem["status"] in ("saved", "attic")
    pending = await db.fetchval("SELECT count(*) FROM media WHERE memory_id=$1 AND storage_key IS NULL AND audio_kept "
                                "AND tg_file_id IS NOT NULL", mid)
    if late and not pending:
        return {"skipped": True}
    if not late:
        await db.execute("UPDATE memories SET status='processing', updated_at=now() WHERE id=$1", mid)
    media = await db.fetch("SELECT * FROM media WHERE memory_id=$1 ORDER BY sort_order, created_at", mid)
    blurry_new = await _download_all(mem, media)
    media = await db.fetch("SELECT * FROM media WHERE memory_id=$1 ORDER BY sort_order, created_at", mid)

    if late:                                   # a late album photo joined an already placed memory
        if chat:
            await send.send_message(chat, t(lang, "late_added"))
        return {"late": True}

    if not media and not (mem["tg_meta"] or {}).get("typed"):
        await db.execute("UPDATE memories SET status='failed', updated_at=now() WHERE id=$1", mid)
        return {"failed": "nothing to keep"}

    typed = (mem["tg_meta"] or {}).get("typed") or ""
    transcripts = [m["transcript"] for m in media if m["type"] == "voice" and m["transcript"]]
    text = "\n".join([x for x in [typed, *transcripts] if x]).strip()
    stt_lang = (mem["tg_meta"] or {}).get("stt_language")

    tags: dict = {"title": None, "summary": None, "festival": None, "people": [], "language": None,
                  "sensitivity": "none", "date_confidence": 0.0}
    date = {"year": None, "month": None, "day": None, "placed": False}
    if text:
        try:
            tags = await tagger.tag_text(text, stt_lang)
            date = tagger.resolve_date(tags["when"], tags["date_confidence"], mem["ftz"], mem["captured_at"])
        except tagger.TaggerError as e:
            log.warning("tagger failed for %s: %s; keeping undated", mid, e)
            tags["title"] = " ".join(text.split()[:6])
            tags["summary"] = text[:300]
    if not date["placed"]:                       # real EXIF capture time is metadata, not a guess
        taken = next((m["taken_at"] for m in media if m["type"] == "photo" and m["taken_at"]), None)
        if taken and taken <= datetime.now(timezone.utc):
            date = {"year": taken.year, "month": taken.month, "day": taken.day, "placed": True}
            tags["date_confidence"] = max(tags["date_confidence"], 0.6)
    if not tags["title"] and not text:
        n = sum(1 for m in media if m["type"] == "photo")
        tags["title"] = "Photo" if n == 1 else f"{n} photos" if n else "Voice note"
    if not tags["title"]:
        tags["title"] = "Voice note" if any(m["type"] == "voice" for m in media) else "Memory"

    await db.execute(
        "UPDATE memories SET title=$2, summary=$3, text_original=$4, language=coalesce($5,$6,language), festival=$7, "
        "people=$8, sensitivity=$9, date_confidence=$10, updated_at=now() WHERE id=$1",
        mid, tags["title"], tags["summary"], text or None, tags["language"], stt_lang, tags["festival"],
        tags["people"], tags["sensitivity"], tags["date_confidence"])

    has_voice = any(m["type"] == "voice" for m in media)
    voice_note = ""
    if date["placed"]:
        await memops.place(mid, date["year"], date["month"], date["day"], tags["date_confidence"])
    else:
        await db.execute("UPDATE memories SET status='attic', updated_at=now() WHERE id=$1", mid)

    mem = await _load(mid)
    if has_voice and mem["vdefault"] and mem["vdefault"] in ("voice", "words", "both"):
        await memops.apply_voice_choice(mid, mem["vdefault"])
        voice_note = "\n" + t(lang, "voice_auto", choice=t(lang, mem["vdefault"]).lower())
        has_voice = False
    blurry_total = await db.fetchval("SELECT count(*) FROM media WHERE memory_id=$1 AND is_blurry", mid)

    if chat:
        if date["placed"]:
            text_out = memops.receipt_text(mem, lang) + voice_note
            rows = memops.receipt_buttons(mid, lang)
            if blurry_total:
                text_out += "\n" + t(lang, "blurry" if blurry_total == 1 else "blurry_n", n=blurry_total)
                rows.append([{"text": t(lang, "keep"), "data": f"kp:{mid}"},
                             {"text": t(lang, "drop"), "data": f"dp:{mid}"}])
            if has_voice:
                text_out += "\n\n" + t(lang, "voice_q")
                rows += memops.voice_buttons(mid, lang)
            await send.send_message(chat, text_out, rows)
            from .followups import schedule_followup
            await schedule_followup(mid)
        else:
            await send.send_message(chat, f"{tags['title']}\n\n{t(lang, 'ask_year')}", memops.year_buttons(mid, lang))
            if has_voice:
                await send.send_message(chat, t(lang, "voice_q"), memops.voice_buttons(mid, lang))
            if blurry_total:
                await send.send_message(chat, t(lang, "blurry" if blurry_total == 1 else "blurry_n", n=blurry_total),
                                        [[{"text": t(lang, "keep"), "data": f"kp:{mid}"},
                                          {"text": t(lang, "drop"), "data": f"dp:{mid}"}]])
    if await db.fetchval("SELECT count(*) FROM media WHERE memory_id=$1 AND storage_key IS NULL AND audio_kept "
                         "AND tg_file_id IS NOT NULL", mid):      # album photo that arrived while we were working
        await jobs.enqueue("capture", {"memory_id": mid})
    return {"status": "saved" if date["placed"] else "attic"}
