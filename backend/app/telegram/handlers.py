"""Telegram update processing. `await process_update(update_dict)` is the single entry used by the dev
long-poller and by POST /webhooks/telegram. Everything slow (download, STT, LLM) happens in the `capture` job."""
from __future__ import annotations

import logging
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from .. import auth, config, db, jobs
from . import memops, send
from .copy import LANG_BUTTONS, t

log = logging.getLogger("memo.tg")
RATE_PER_MIN = 30
_hits: dict[int, deque] = defaultdict(deque)
MAX_FILE = 20 * 1024 * 1024


def _rate_limited(uid: int) -> bool:
    now, q = time.monotonic(), _hits[uid]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_PER_MIN:
        return True
    q.append(now)
    return False


def _guess_lang(user: dict) -> str:
    return {"hi": "hi-IN", "kn": "kn-IN"}.get((user.get("language_code") or "")[:2], "en-IN")


def _nick(user: dict) -> str:
    return (user.get("first_name") or user.get("username") or "Member")[:40]


async def _member(uid: int):
    return await db.fetchrow(
        """SELECT m.id, m.family_id, m.nickname, m.role, m.language, m.quiet, m.voice_keep_default, m.telegram_chat_id,
                  f.name fname, f.language flang, f.invite_code, f.grandma_name, f.settings fsettings
           FROM members m JOIN families f ON f.id=m.family_id WHERE m.telegram_user_id=$1
           ORDER BY m.joined_at LIMIT 1""", uid)


async def _get_state(uid: int):
    return await db.fetchrow("SELECT state, data FROM tg_state WHERE telegram_user_id=$1", uid)


async def _set_state(uid: int, state: str, data: dict | None = None) -> None:
    await db.execute("INSERT INTO tg_state(telegram_user_id, state, data) VALUES ($1,$2,$3::jsonb) "
                     "ON CONFLICT (telegram_user_id) DO UPDATE SET state=$2, data=$3::jsonb, updated_at=now()",
                     uid, state, data or {})


async def _clear_state(uid: int) -> None:
    await db.execute("DELETE FROM tg_state WHERE telegram_user_id=$1", uid)


# ---------------------------------------------------------------- entry

async def process_update(update: dict) -> None:
    if "callback_query" in update:
        await _on_callback(update["callback_query"])
        return
    msg = update.get("message")
    if not msg or not msg.get("from") or msg["from"].get("is_bot") or msg["chat"].get("type") != "private":
        return
    uid, chat = msg["from"]["id"], msg["chat"]["id"]
    if _rate_limited(uid):
        await send.send_message(chat, t(_guess_lang(msg["from"]), "rate"))
        return
    text = msg.get("text") or ""
    if text.startswith("/"):
        await _command(msg, update["update_id"])
        return
    member = await _member(uid)
    st = await _get_state(uid)
    if st and text:
        if await _on_state_text(msg, st, member):
            return
    if member is None:
        await send.send_message(chat, t(_guess_lang(msg["from"]), "need_start"))
        return
    if member["telegram_chat_id"] != chat:
        await db.execute("UPDATE members SET telegram_chat_id=$2 WHERE id=$1", member["id"], chat)
    if msg.get("contact"):
        await _on_contact(msg, member)
        return
    await _capture(msg, update["update_id"], member)


# ---------------------------------------------------------------- onboarding + commands

async def _command(msg: dict, update_id: int) -> None:
    uid, chat, user = msg["from"]["id"], msg["chat"]["id"], msg["from"]
    parts = msg["text"].split(maxsplit=1)
    cmd = parts[0][1:].split("@")[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    member = await _member(uid)
    lang = member["flang"] if member else _guess_lang(user)
    if member and member["telegram_chat_id"] != chat:
        await db.execute("UPDATE members SET telegram_chat_id=$2 WHERE id=$1", member["id"], chat)

    if cmd == "start":
        await _clear_state(uid)
        if arg:
            fam = await db.fetchrow("SELECT id, name, language FROM families WHERE invite_code=$1", arg)
            if fam is None:
                await send.send_message(chat, t(lang, "bad_code"))
            elif member:
                await send.send_message(chat, t(lang, "already", name=member["fname"]))
            else:
                await db.execute(
                    "INSERT INTO members(family_id, telegram_user_id, telegram_chat_id, nickname, role, language) "
                    "VALUES ($1,$2,$3,$4,'editor',$5) ON CONFLICT (family_id, telegram_user_id) DO NOTHING",
                    fam["id"], uid, chat, _nick(user), fam["language"])
                await send.send_message(chat, t(fam["language"], "joined", name=fam["name"]))
        elif member:
            await send.send_message(chat, t(lang, "already", name=member["fname"]))
            if member["role"] in ("owner", "editor"):
                await send.send_message(chat, t(lang, "invite", link=await send.invite_link(member["invite_code"])))
        else:
            await _set_state(uid, "await_family_name")
            await send.send_message(chat, t(lang, "welcome_new"))
        return

    if member is None:
        await send.send_message(chat, t(lang, "need_start"))
        return
    if cmd == "help":
        await send.send_message(chat, t(lang, "help"))
    elif cmd == "invite":
        if member["role"] in ("owner", "editor"):
            await send.send_message(chat, t(lang, "invite", link=await send.invite_link(member["invite_code"])))
        else:
            await send.send_message(chat, t(lang, "no_perm"))
    elif cmd == "nickname":
        name = re.sub(r"\s+", " ", arg)[:40]
        if not name:
            await send.send_message(chat, t(lang, "nick_usage"))
        else:
            await db.execute("UPDATE members SET nickname=$2 WHERE id=$1", member["id"], name)
            await send.send_message(chat, t(lang, "nick_set", name=name))
    elif cmd == "members":
        rows = await db.fetch("SELECT nickname, role FROM members WHERE family_id=$1 ORDER BY joined_at",
                              member["family_id"])
        await send.send_message(chat, t(lang, "members", list="\n".join(f"- {r['nickname']} ({r['role']})" for r in rows)))
    elif cmd == "museum":
        link = await auth.create_signin_link(str(member["family_id"]), str(member["id"]))
        await send.send_message(chat, t(lang, "museum"), [[{"text": t(lang, "museum_btn"), "url": link}]])
    elif cmd == "quiet":
        quiet = not member["quiet"]
        await db.execute("UPDATE members SET quiet=$2 WHERE id=$1", member["id"], quiet)
        await send.send_message(chat, t(lang, "quiet_on" if quiet else "quiet_off"))
    elif cmd == "export":
        if member["role"] != "owner":
            await send.send_message(chat, t(lang, "export_owner"))
            return
        await send.send_message(chat, t(lang, "export_wait"))
        from app.core.export import build_export_zip
        path = await build_export_zip(str(member["family_id"]))
        await send.send_document(chat, path, f"{member['fname']} - Memo export")
    else:
        await send.send_message(chat, t(lang, "help"))


async def _on_state_text(msg: dict, st, member) -> bool:
    uid, chat, text = msg["from"]["id"], msg["chat"]["id"], msg["text"].strip()
    state, data = st["state"], st["data"]
    if state == "await_family_name" and member is None:
        name = text[:60]
        await _set_state(uid, "await_family_lang", {"name": name})
        await send.send_message(chat, t(_guess_lang(msg["from"]), "choose_lang"),
                                [[{"text": lbl, "data": f"lg:{code}"} for lbl, code in LANG_BUTTONS]])
        return True
    if state == "await_festival" and member is not None:
        mem = await db.fetchrow("SELECT family_id FROM memories WHERE id=$1", data["memory_id"])
        if mem and mem["family_id"] == member["family_id"]:
            fest = None if text.lower() in ("none", "no", "-") else text[:80]
            await db.execute("UPDATE memories SET festival=$2, updated_at=now() WHERE id=$1", data["memory_id"], fest)
        await _clear_state(uid)
        await send.send_message(chat, t(member["flang"], "festival_set"))
        return True
    return False


async def _create_family(cb: dict, code: str) -> None:
    uid, chat, user = cb["from"]["id"], cb["message"]["chat"]["id"], cb["from"]
    st = await _get_state(uid)
    if st is None or st["state"] != "await_family_lang" or await _member(uid):
        return
    name = st["data"].get("name") or "My family"
    fam = await db.fetchrow(
        "INSERT INTO families(name, language, grandma_name, timezone, invite_code) VALUES ($1,$2,$3,$4,$5) RETURNING id",
        name, code, config.GRANDMA_NAMES[code], config.DEFAULT_TZ, secrets.token_urlsafe(24))
    inv = await db.fetchval(
        "INSERT INTO members(family_id, telegram_user_id, telegram_chat_id, nickname, role, language) "
        "VALUES ($1,$2,$3,$4,'owner',$5) RETURNING (SELECT invite_code FROM families WHERE id=$1)",
        fam["id"], uid, chat, _nick(user), code)
    await _clear_state(uid)
    await send.send_message(chat, t(code, "created", name=name, link=await send.invite_link(inv)))


# ---------------------------------------------------------------- contacts

async def _on_contact(msg: dict, member) -> None:
    chat, lang, c = msg["chat"]["id"], member["flang"], msg["contact"]
    if member["role"] != "owner":
        await send.send_message(chat, t(lang, "contact_owner"))
        return
    name = " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x)[:80] or "Contact"
    phone = "+" + re.sub(r"\D", "", c.get("phone_number") or "")
    if len(phone) < 8:
        await send.send_message(chat, t(lang, "failed"))
        return
    cid = await db.fetchval("SELECT id FROM contacts WHERE family_id=$1 AND phone_e164=$2", member["family_id"], phone)
    if cid is None:
        cid = await db.fetchval(
            "INSERT INTO contacts(family_id, name, phone_e164, language, consent_to_calls, telegram_user_id) "
            "VALUES ($1,$2,$3,$4,false,$5) RETURNING id", member["family_id"], name, phone, member["flang"], c.get("user_id"))
    await send.send_message(chat, t(lang, "consent_q", name=name),
                            [[{"text": t(lang, "consent_yes"), "data": f"cons:{cid}:y"},
                              {"text": t(lang, "consent_no"), "data": f"cons:{cid}:n"}]])


# ---------------------------------------------------------------- capture

def _forward_from(msg: dict) -> str | None:
    o = msg.get("forward_origin")
    if not o:
        return None
    return ((o.get("sender_user") or {}).get("first_name") or o.get("sender_user_name")
            or (o.get("chat") or {}).get("title") or o.get("type"))


def _video_of(msg: dict) -> dict | None:
    """video, video_note, animation (GIF-style mp4) or a document whose mime type is video/*."""
    for k in ("video", "video_note", "animation"):
        if msg.get(k):
            return {**msg[k], "mime_type": msg[k].get("mime_type") or "video/mp4"}
    doc = msg.get("document")
    if doc and (doc.get("mime_type") or "").lower().startswith("video/"):
        return doc
    return None


async def _capture(msg: dict, update_id: int, member) -> None:
    chat, lang = msg["chat"]["id"], member["flang"]
    voice, photos, vid = msg.get("voice"), msg.get("photo"), _video_of(msg)
    typed = (msg.get("text") or msg.get("caption") or "").strip()
    if (msg.get("document") and not vid) or msg.get("audio"):
        await send.send_message(chat, t(lang, "unsupported"))
        return
    if not (typed or voice or photos or vid):
        await send.send_message(chat, t(lang, "unsupported"))
        return
    best = photos[-1] if photos else None
    size = (voice or best or vid or {}).get("file_size") or 0
    if size > MAX_FILE:
        await send.send_message(chat, t(lang, "video_too_big" if vid else "too_big"))
        return

    # an answer to Grandma's follow-up question?
    if not photos and not vid and not msg.get("forward_origin"):
        fu = await _open_followup(member, msg)
        if fu is not None:
            if fu["memory_id"] is None:                 # asked from the theater: the answer is also a new memory
                await db.execute("UPDATE followups SET answer_text=$2, answered_at=now() WHERE id=$1", fu["id"], typed or None)
            else:
                await jobs.enqueue("followup_answer", {"followup_id": str(fu["id"]), "text": typed,
                                                       "file_id": voice["file_id"] if voice else None,
                                                       "mime": (voice or {}).get("mime_type")})
                await send.send_message(chat, t(lang, "ack"))
                return

    group = msg.get("media_group_id")
    src = f"mg:{chat}:{group}" if group else str(update_id)
    kind = ("forward" if msg.get("forward_origin") else "album" if group else "voice" if voice
            else "photo" if photos else "video" if vid else "text")
    captured = datetime.fromtimestamp(msg["date"], timezone.utc)
    meta = {"typed": typed}
    if _forward_from(msg):
        meta["forward_from"] = _forward_from(msg)
    row = await db.fetchrow(
        "INSERT INTO memories(family_id, author_id, teller_id, kind, text_original, status, captured_at, "
        "source_update_id, media_group_id, tg_chat_id, tg_meta) VALUES ($1,$2,$2,$3,$4,'received',$5,$6,$7,$8,$9::jsonb) "
        "ON CONFLICT (source_update_id) DO NOTHING RETURNING id",
        member["family_id"], member["id"], kind, typed or None, captured, src, group, chat, meta)
    created = row is not None
    if not created:
        if not group:
            return                                       # Telegram redelivered this update: nothing to do
        row = await db.fetchrow("SELECT id, status FROM memories WHERE source_update_id=$1", src)
    mid = str(row["id"])
    if voice:
        await db.execute(
            "INSERT INTO media(memory_id, type, mime, duration_s, tg_file_id, tg_file_unique_id, tg_file_size, sort_order) "
            "VALUES ($1,'voice',$2,$3,$4,$5,$6,$7) ON CONFLICT DO NOTHING", mid, voice.get("mime_type") or "audio/ogg",
            voice.get("duration"), voice["file_id"], voice["file_unique_id"], voice.get("file_size"), msg["message_id"])
    if best:
        await db.execute(
            "INSERT INTO media(memory_id, type, width, height, tg_file_id, tg_file_unique_id, tg_file_size, sort_order) "
            "VALUES ($1,'photo',$2,$3,$4,$5,$6,$7) ON CONFLICT DO NOTHING", mid, best.get("width"), best.get("height"),
            best["file_id"], best["file_unique_id"], best.get("file_size"), msg["message_id"])
    if vid:
        await db.execute(
            "INSERT INTO media(memory_id, type, mime, width, height, duration_s, tg_file_id, tg_file_unique_id, "
            "tg_file_size, sort_order) VALUES ($1,'video',$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT DO NOTHING", mid,
            vid["mime_type"], vid.get("width") or vid.get("length"), vid.get("height") or vid.get("length"),
            vid.get("duration"), vid["file_id"], vid["file_unique_id"], vid.get("file_size"), msg["message_id"])
    if not created:                                     # another photo of an album already being captured
        if typed:
            await db.execute("UPDATE memories SET text_original=coalesce(text_original,$2), "
                             "tg_meta=tg_meta || jsonb_build_object('typed',$2::text) WHERE id=$1 AND "
                             "coalesce(tg_meta->>'typed','')=''", mid, typed)
        if row["status"] in ("saved", "attic"):
            await jobs.enqueue("capture", {"memory_id": mid})
        return
    await send.send_message(chat, t(lang, "ack_album" if group else "ack_video" if vid else "ack"))
    await jobs.enqueue("capture", {"memory_id": mid}, delay_s=2.5 if group else 0)


async def _open_followup(member, msg: dict):
    reply_id = (msg.get("reply_to_message") or {}).get("message_id")
    if reply_id:
        return await db.fetchrow(
            "SELECT * FROM followups WHERE member_id=$1 AND tg_message_id=$2 AND answered_at IS NULL",
            member["id"], reply_id)
    return await db.fetchrow(
        "SELECT * FROM followups WHERE member_id=$1 AND answered_at IS NULL AND asked_at > now() - interval '30 minutes' "
        "ORDER BY asked_at DESC LIMIT 1", member["id"])


# ---------------------------------------------------------------- callbacks

def _strip_rows(markup: dict | None, prefixes: tuple[str, ...]) -> list[list[dict]]:
    rows = []
    for row in (markup or {}).get("inline_keyboard", []):
        if row and (row[0].get("callback_data") or "").startswith(prefixes):
            continue
        rows.append([{"text": b["text"], "data": b["callback_data"]} if "callback_data" in b
                     else {"text": b["text"], "url": b["url"]} for b in row])
    return rows


async def _on_callback(cb: dict) -> None:
    uid, cid = cb["from"]["id"], cb["id"]
    data = cb.get("data") or ""
    m = cb.get("message") or {}
    chat, mess_id = (m.get("chat") or {}).get("id"), m.get("message_id")
    if chat is None:
        await send.answer_callback(cid)
        return
    if data.startswith("lg:"):
        code = data[3:]
        if code in config.LANGUAGES:
            await _create_family(cb, code)
        await send.answer_callback(cid)
        return
    member = await _member(uid)
    if member is None:
        await send.answer_callback(cid)
        return
    lang = member["flang"]
    parts = data.split(":")
    op = parts[0]

    if op == "cons":
        c = await db.fetchrow("SELECT id, name FROM contacts WHERE id=$1 AND family_id=$2", parts[1], member["family_id"])
        if c is None or member["role"] != "owner":
            await send.answer_callback(cid, t(lang, "no_perm"))
            return
        if parts[2] == "y":
            await db.execute("UPDATE contacts SET consent_to_calls=true, consent_by=$2, consent_at=now() WHERE id=$1",
                             c["id"], member["id"])
        await send.edit_message(chat, mess_id, t(lang, "consent_saved" if parts[2] == "y" else "consent_none", name=c["name"]))
        await send.answer_callback(cid)
        return

    mem = await db.fetchrow("SELECT * FROM memories WHERE id=$1", parts[1]) if len(parts) > 1 else None
    if mem is None or mem["family_id"] != member["family_id"] or mem["status"] == "deleted":
        await send.answer_callback(cid, t(lang, "no_perm"))
        return
    if member["role"] == "viewer" or (member["role"] == "editor" and mem["author_id"] != member["id"]
                                      and (member["fsettings"] or {}).get("editors_edit_others") is False):
        await send.answer_callback(cid, t(lang, "no_perm"))
        return
    mid = str(mem["id"])

    if op == "wd":
        await send.send_message(chat, t(lang, "ask_year_move"), memops.year_buttons(mid, lang))
    elif op == "y":
        await send.edit_message(chat, mess_id, t(lang, "ask_month", year=parts[2]), memops.month_buttons(mid, int(parts[2])))
    elif op == "m":
        year, month = int(parts[2]), int(parts[3])
        was_saved = mem["status"] == "saved"
        await memops.place(mid, year, month)
        fresh = await db.fetchrow("SELECT * FROM memories WHERE id=$1", mid)
        head = t(lang, "moved", when=memops.when_label(year, month)) + "\n" if was_saved else ""
        await send.edit_message(chat, mess_id, head + memops.receipt_text(fresh, lang), memops.receipt_buttons(mid, lang))
        if not was_saved:
            from app.tasks.followups import schedule_followup
            await schedule_followup(mid)
    elif op == "na":
        await send.edit_message(chat, mess_id, t(lang, "attic_kept"))
    elif op == "wf":
        await _set_state(uid, "await_festival", {"memory_id": mid})
        await send.send_message(chat, t(lang, "festival_q"))
    elif op == "del":
        await memops.delete_memory(mid)
        await send.edit_message(chat, mess_id, t(lang, "deleted"))
    elif op in ("vk", "vka"):
        choice = parts[2]
        if choice not in ("voice", "words", "both"):
            return
        if op == "vka":
            await db.execute("UPDATE members SET voice_keep_default=$2 WHERE id=$1", member["id"], choice)
        await memops.apply_voice_choice(mid, choice)
        rows = _strip_rows(m.get("reply_markup"), ("vk:", "vka:"))
        if op == "vk":
            rows.append([{"text": t(lang, "always", choice=t(lang, choice).lower()), "data": f"vka:{mid}:{choice}"}])
        await send.api("editMessageReplyMarkup", {"chat_id": chat, "message_id": mess_id,
                                                  "reply_markup": {"inline_keyboard": [
                                                      [({"text": b["text"], "callback_data": b["data"]} if "data" in b
                                                        else {"text": b["text"], "url": b["url"]}) for b in r] for r in rows]}})
        await send.answer_callback(cid, t(lang, "voice_done", choice=t(lang, choice).lower()))
        return
    elif op in ("kp", "dp"):
        if op == "kp":
            await db.execute("UPDATE media SET blur_kept=true WHERE memory_id=$1 AND is_blurry", mid)
        else:
            from .. import storage
            from ..media import cleanup_history
            gone = await db.fetch("SELECT id, memory_id, storage_key, large_key, thumb_key, blur_score FROM media "
                                  "WHERE memory_id=$1 AND is_blurry AND NOT blur_kept", mid)
            await cleanup_history.insert(db, await cleanup_history.prepare_deleted_media(str(mem["family_id"]), gone))
            for r in gone:
                for k in (r["storage_key"], r["large_key"], r["thumb_key"]):
                    storage.delete(k)
            await db.execute("DELETE FROM media WHERE memory_id=$1 AND is_blurry AND NOT blur_kept", mid)
            left = await db.fetchval("SELECT count(*) FROM media WHERE memory_id=$1", mid)
            if not left and not (mem["text_original"] or "").strip():
                await memops.delete_memory(mid)
        rows = _strip_rows(m.get("reply_markup"), ("kp:", "dp:"))
        await send.api("editMessageReplyMarkup", {"chat_id": chat, "message_id": mess_id, "reply_markup": {
            "inline_keyboard": [[({"text": b["text"], "callback_data": b["data"]} if "data" in b
                                  else {"text": b["text"], "url": b["url"]}) for b in r] for r in rows]}})
    await send.answer_callback(cid)
