"""Capture tests: real Postgres, real update-shaped dicts through process_update, the real capture job.
The ONLY stub is the outbound Telegram network (send.api / send.download_file) which records what the bot would
send and serves real sample files. STT and the LLM tests call Sarvam / the LLM provider for real."""
from __future__ import annotations

import random
import secrets
import time
from pathlib import Path

import pytest
import pytest_asyncio

from app import db, jobs, storage
from app.telegram import handlers, send

pytestmark = pytest.mark.asyncio
SPEECH = Path(__file__).parent / "speech_sample.wav"      # real synthesized speech (Windows SAPI)


def _core(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


class Tg:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.files: dict[str, bytes] = {}
        self._mid = 1000

    async def api(self, method, data=None, files=None, timeout=30.0):
        self.calls.append((method, data or {}))
        if method == "sendMessage":
            self._mid += 1
            return {"message_id": self._mid}
        if method == "getMe":
            return {"username": "memo_test_bot"}
        return {}

    async def download(self, file_id):
        return self.files[file_id], "x"

    def sent(self, chat):
        return [d for m, d in self.calls if m == "sendMessage" and d["chat_id"] == chat]


@pytest_asyncio.fixture
async def tg(monkeypatch):
    t = Tg()
    monkeypatch.setattr(send, "api", t.api)
    monkeypatch.setattr(send, "download_file", t.download)
    monkeypatch.setattr(send, "_username", "memo_test_bot")
    handlers._hits.clear()
    await db.init_schema()
    made: list[str] = []
    t.made = made
    yield t
    for fid in made:
        await db.execute("DELETE FROM families WHERE id=$1", fid)
    await db.execute("DELETE FROM tg_state WHERE telegram_user_id > 9000000000")
    await db.close()


_uid = [9_000_000_000 + random.randint(0, 10**8)]
_upd = [int(time.time())]


def uid() -> int:
    _uid[0] += 1
    return _uid[0]


def upd() -> int:
    _upd[0] += 1
    return _upd[0]


def message(user: int, **kw) -> dict:
    m = {"message_id": upd(), "date": int(time.time()), "chat": {"id": user, "type": "private"},
         "from": {"id": user, "is_bot": False, "first_name": "Asha", "language_code": "en"}}
    m.update(kw)
    return {"update_id": upd(), "message": m}


def callback(user: int, data: str, message_id: int = 5, markup=None) -> dict:
    return {"update_id": upd(), "callback_query": {
        "id": secrets.token_hex(4), "from": {"id": user, "is_bot": False, "first_name": "Asha"}, "data": data,
        "message": {"message_id": message_id, "chat": {"id": user, "type": "private"}, "reply_markup": markup}}}


async def make_family(tg: Tg, user: int, name="Rao family", lang="en-IN") -> str:
    await handlers.process_update(message(user, text="/start"))
    await handlers.process_update(message(user, text=name))
    await handlers.process_update(callback(user, f"lg:{lang}"))
    fid = str(await db.fetchval("SELECT family_id FROM members WHERE telegram_user_id=$1", user))
    tg.made.append(fid)
    return fid


async def run_jobs() -> None:
    """Run queued capture/followup jobs in-process (what the worker does)."""
    import app.tasks.capture, app.tasks.followups  # noqa: F401,E401  registers handlers
    while True:
        rows = await db.fetch("SELECT id, type, payload FROM jobs WHERE status='queued' AND type IN "
                              "('capture','followup','followup_answer') ORDER BY id")
        if not rows:
            return
        for r in rows:
            await db.execute("UPDATE jobs SET status='running', attempts=attempts+1 WHERE id=$1", r["id"])
            await jobs.run_one({"id": r["id"], "type": r["type"], "payload": r["payload"], "attempts": 1, "max_attempts": 1})


# ------------------------------------------------------------------ onboarding

async def test_create_family_invite_join_and_one_family_rule(tg):
    owner, joiner = uid(), uid()
    fid = await make_family(tg, owner, lang="hi-IN")
    fam = await db.fetchrow("SELECT * FROM families WHERE id=$1", fid)
    assert fam["language"] == "hi-IN" and fam["grandma_name"] == "Dadi" and len(fam["invite_code"]) >= 24
    assert (await db.fetchval("SELECT role FROM members WHERE telegram_user_id=$1", owner)) == "owner"
    assert f"https://t.me/memo_test_bot?start={fam['invite_code']}" in tg.sent(owner)[-1]["text"]

    await handlers.process_update(message(joiner, text=f"/start {fam['invite_code']}"))
    m = await db.fetchrow("SELECT role, nickname FROM members WHERE telegram_user_id=$1", joiner)
    assert m["role"] == "editor" and m["nickname"] == "Asha"
    await handlers.process_update(message(joiner, text=f"/start {fam['invite_code']}"))
    assert await db.fetchval("SELECT count(*) FROM members WHERE telegram_user_id=$1", joiner) == 1
    await handlers.process_update(message(uid(), text="/start not-a-real-code"))
    assert "not valid" in tg.sent(_uid[0])[-1]["text"]
    await handlers.process_update(message(joiner, text="/nickname Meena"))
    assert (await db.fetchval("SELECT nickname FROM members WHERE telegram_user_id=$1", joiner)) == "Meena"


# ------------------------------------------------------------------ idempotency, albums, attic

async def test_text_is_idempotent_on_update_id_and_goes_to_attic(tg):
    user = uid()
    fid = await make_family(tg, user)
    up = message(user, text="We had warm chai with Grandma and talked for hours.")
    await handlers.process_update(up)
    await handlers.process_update(up)                         # Telegram redelivery
    rows = await db.fetch("SELECT id, kind, status, source_update_id FROM memories WHERE family_id=$1", fid)
    assert len(rows) == 1 and rows[0]["source_update_id"] == str(up["update_id"])
    acks = [d for d in tg.sent(user) if "keeping this safe" in d["text"]]
    assert len(acks) == 1
    await run_jobs()
    mem = await db.fetchrow("SELECT * FROM memories WHERE id=$1", rows[0]["id"])
    assert mem["title"] and mem["status"] == "attic" and mem["event_year"] is None   # no date stated: never invented
    q = tg.sent(user)[-1]
    assert "Which year" in q["text"]
    assert any(b["callback_data"].startswith(f"y:{mem['id']}:") for r in q["reply_markup"]["inline_keyboard"] for b in r)


async def test_attic_year_month_buttons_place_the_memory(tg):
    user = uid()
    fid = await make_family(tg, user)
    await handlers.process_update(message(user, text="Everyone gathered on the terrace and sang old songs."))
    await run_jobs()
    mid = str(await db.fetchval("SELECT id FROM memories WHERE family_id=$1", fid))
    await handlers.process_update(callback(user, f"y:{mid}:2024"))
    await handlers.process_update(callback(user, f"m:{mid}:2024:11"))
    mem = await db.fetchrow("SELECT status, event_year, event_month FROM memories WHERE id=$1", mid)
    assert (mem["status"], mem["event_year"], mem["event_month"]) == ("saved", 2024, 11)
    edit = [d for m, d in tg.calls if m == "editMessageText"][-1]
    assert "Nov 2024" in edit["text"]
    row = edit["reply_markup"]["inline_keyboard"][0]
    assert [b["callback_data"].split(":")[0] for b in row] == ["wd", "wf", "del"]


async def test_album_groups_into_one_memory(tg):
    user = uid()
    fid = await make_family(tg, user)
    gid = "album-" + secrets.token_hex(3)
    for i in range(3):
        tg.files[f"f{gid}{i}"] = b"x"
        await handlers.process_update(message(user, media_group_id=gid, caption="Diwali at home" if i == 0 else None,
                                              photo=[{"file_id": f"f{gid}{i}", "file_unique_id": f"u{gid}{i}",
                                                      "width": 90, "height": 90, "file_size": 1}]))
    await handlers.process_update(message(user, media_group_id=gid, photo=[
        {"file_id": f"f{gid}0", "file_unique_id": f"u{gid}0", "width": 90, "height": 90, "file_size": 1}]))  # duplicate photo
    mems = await db.fetch("SELECT id, kind, text_original FROM memories WHERE family_id=$1", fid)
    assert len(mems) == 1 and mems[0]["kind"] == "album" and mems[0]["text_original"] == "Diwali at home"
    assert await db.fetchval("SELECT count(*) FROM media WHERE memory_id=$1", mems[0]["id"]) == 3
    assert len([d for d in tg.sent(user) if "photos" in d["text"]]) == 1          # one ack for the whole album
    job = await db.fetchrow("SELECT run_at > now() delayed FROM jobs WHERE type='capture' "
                            "AND payload->>'memory_id'=$1", str(mems[0]["id"]))
    assert job["delayed"]                                                         # debounce


async def test_too_big_file_and_unsupported_and_rate_limit(tg):
    user = uid()
    await make_family(tg, user)
    await handlers.process_update(message(user, voice={"file_id": "a", "file_unique_id": "b", "duration": 5,
                                                       "file_size": 30 * 1024 * 1024}))
    assert "too big" in tg.sent(user)[-1]["text"]
    await handlers.process_update(message(user, audio={"file_id": "a1", "file_unique_id": "a1u"}, caption="song"))
    assert "can't keep audio files" in tg.sent(user)[-1]["text"]
    await handlers.process_update(message(user, document={"file_id": "d1", "file_unique_id": "d1u",
                                                          "mime_type": "application/pdf"}))
    assert "can't keep audio files" in tg.sent(user)[-1]["text"]
    for _ in range(35):
        await handlers.process_update(message(user, text="/help"))
    assert "Slow down" in tg.sent(user)[-1]["text"]


async def test_forward_is_kind_forward_and_contact_consent(tg):
    owner = uid()
    fid = await make_family(tg, owner)
    await handlers.process_update(message(owner, text="Forwarded: we met at the temple.",
                                          forward_origin={"type": "user", "sender_user": {"first_name": "Uncle"}}))
    row = await db.fetchrow("SELECT kind, tg_meta FROM memories WHERE family_id=$1", fid)
    assert row["kind"] == "forward" and row["tg_meta"]["forward_from"] == "Uncle"

    phone = "+9198" + str(random.randint(10**7, 10**8 - 1))
    await handlers.process_update(message(owner, contact={"phone_number": phone, "first_name": "Priya"}))
    c = await db.fetchrow("SELECT id, consent_to_calls FROM contacts WHERE family_id=$1", fid)
    assert c["consent_to_calls"] is False
    assert "agreed to receive calls" in tg.sent(owner)[-1]["text"]
    await handlers.process_update(callback(owner, f"cons:{c['id']}:y"))
    c = await db.fetchrow("SELECT consent_to_calls, consent_by, consent_at FROM contacts WHERE id=$1", c["id"])
    assert c["consent_to_calls"] and c["consent_by"] and c["consent_at"]


async def test_delete_removes_memory(tg):
    user = uid()
    fid = await make_family(tg, user)
    await handlers.process_update(message(user, text="A quiet evening with the neighbours."))
    mid = str(await db.fetchval("SELECT id FROM memories WHERE family_id=$1", fid))
    await handlers.process_update(callback(user, f"del:{mid}"))
    assert (await db.fetchrow("SELECT status, text_original FROM memories WHERE id=$1", mid))["status"] == "deleted"


# ------------------------------------------------------------------ real STT + LLM

async def test_real_stt_transcribes_speech():
    from app.ai import stt
    res = await stt.transcribe(SPEECH.read_bytes(), "audio/wav")
    assert res["duration_s"] > 5
    assert "diwali" in res["text"].lower() or "bike" in res["text"].lower(), res
    assert res["language"]


async def test_real_tagger_returns_valid_fields():
    from app.ai import tagger
    t = await tagger.tag_text("Dad gave my brother a new bike at Diwali. Everyone cheered. Last year I think.")
    assert t["title"] and t["summary"] and t["sensitivity"] in tagger.SENSITIVITIES
    assert (t["festival"] or "").lower().startswith("diwali")
    t2 = await tagger.tag_text("Grandpa passed away peacefully in his sleep last night.")
    assert t2["sensitivity"] == "loss"


@pytest.mark.skipif(not _core("app.core.dates"), reason="core-api app.core.dates not merged yet")
async def test_real_dated_voice_note_lands_in_room(tg):
    user = uid()
    fid = await make_family(tg, user)
    tg.files["voice1"] = SPEECH.read_bytes()
    await handlers.process_update(message(user, voice={"file_id": "voice1", "file_unique_id": "uv1", "duration": 9,
                                                       "mime_type": "audio/wav", "file_size": 280000}))
    await run_jobs()
    mem = await db.fetchrow("SELECT * FROM memories WHERE family_id=$1", fid)
    assert mem["status"] in ("saved", "attic") and mem["text_original"]


async def test_real_voice_note_keep_choice(tg):
    """Voice note with no stated time (-> attic). Audio is kept until the sender answers; 'words' then deletes
    the audio file only because the transcript is saved; 'always do this' is remembered per member."""
    import subprocess
    user = uid()
    fid = await make_family(tg, user)
    wav = Path(__file__).parent / "speech_sample2.wav"
    if not wav.exists():
        subprocess.run(["powershell", "-c",
                        "Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                        f"$s.SetOutputToWaveFile('{wav.as_posix()}'); $s.Speak('Grandma made sweet payasa and everyone laughed together at the table.'); $s.Dispose()"],
                       check=True)
    tg.files["voice2"] = wav.read_bytes()
    await handlers.process_update(message(user, voice={"file_id": "voice2", "file_unique_id": "uv2", "duration": 6,
                                                       "mime_type": "audio/wav", "file_size": 200000}))
    await run_jobs()
    mid = str(await db.fetchval("SELECT id FROM memories WHERE family_id=$1", fid))
    media = await db.fetchrow("SELECT storage_key, transcript, audio_kept FROM media WHERE memory_id=$1", mid)
    assert media["transcript"] and media["audio_kept"] and storage.exists(media["storage_key"])   # kept until answered
    key = media["storage_key"]
    assert any("Keep the voice" in d["text"] for d in tg.sent(user))
    await handlers.process_update(callback(user, f"vk:{mid}:words"))
    media = await db.fetchrow("SELECT storage_key, transcript, audio_kept FROM media WHERE memory_id=$1", mid)
    assert media["storage_key"] is None and media["audio_kept"] is False and media["transcript"]
    assert not storage.exists(key)
    await handlers.process_update(callback(user, f"vka:{mid}:both"))
    assert (await db.fetchval("SELECT voice_keep_default FROM members WHERE telegram_user_id=$1", user)) == "both"


# ------------------------------------------------------------------ follow-ups

async def test_followup_answer_is_appended(tg):
    from app.tasks import followups
    user = uid()
    fid = await make_family(tg, user)
    await handlers.process_update(message(user, text="Dad rode the new bike around the courtyard."))
    await run_jobs()
    mid = str(await db.fetchval("SELECT id FROM memories WHERE family_id=$1", fid))
    await db.execute("UPDATE memories SET status='saved', event_year=2025, event_month=11 WHERE id=$1", mid)
    out = await followups.followup({"memory_id": mid})
    assert "asked" in out, out
    fu = await db.fetchrow("SELECT * FROM followups WHERE memory_id=$1", mid)
    assert fu["question"] and fu["asked_at"] and fu["tg_message_id"]
    assert (await followups.followup({"memory_id": mid}))["skipped"] == "already asked"      # one per memory
    await handlers.process_update(message(user, text="His uncle Raju gave it to him.",
                                          reply_to_message={"message_id": fu["tg_message_id"]}))
    await run_jobs()
    fu = await db.fetchrow("SELECT * FROM followups WHERE id=$1", fu["id"])
    mem = await db.fetchrow("SELECT text_original FROM memories WHERE id=$1", mid)
    assert fu["answer_text"] == "His uncle Raju gave it to him." and "Raju" in mem["text_original"]
    assert await db.fetchval("SELECT count(*) FROM memories WHERE family_id=$1", fid) == 1   # not a new memory


async def test_followup_never_for_sensitive_or_quiet(tg):
    from app.tasks import followups
    user = uid()
    fid = await make_family(tg, user)
    await handlers.process_update(message(user, text="Grandpa passed away peacefully last night."))
    await run_jobs()
    mid = str(await db.fetchval("SELECT id FROM memories WHERE family_id=$1", fid))
    await db.execute("UPDATE memories SET status='saved', sensitivity='loss' WHERE id=$1", mid)
    assert not await followups.schedule_followup(mid)
    assert "skipped" in await followups.followup({"memory_id": mid})
    await db.execute("UPDATE memories SET sensitivity='none' WHERE id=$1", mid)
    await handlers.process_update(message(user, text="/quiet"))
    assert (await followups.followup({"memory_id": mid}))["skipped"] == "quiet or no chat"
