"""Videos from Telegram, cleanup history and timed reels. Real Postgres, real ffmpeg; the only stub is the outbound
Telegram network (same Tg stub as test_capture_telegram). Stop the live worker while running these (it would
otherwise pick up the queued video_transcode jobs)."""
from __future__ import annotations

import asyncio
import json
import secrets
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from PIL import ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import auth, db, jobs, storage  # noqa: E402
from app.core import gallery, showcase  # noqa: E402
from app.media import reels  # noqa: E402
from app.routes import cleanup as cleanup_routes  # noqa: E402
from app.telegram import handlers  # noqa: E402
from test_capture_telegram import callback, make_family as tg_family, message, tg, uid  # noqa: E402,F401
from test_media_tools import add_memory, add_photo, drop_family, ffprobe, jpeg, make_family, sharp_image  # noqa: E402


def make_mp4(path: Path, seconds: float = 2.0, audio: bool = True, size: str = "320x240") -> bytes:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=25:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(path)]
    subprocess.run(cmd, check=True)
    data = path.read_bytes()
    path.unlink(missing_ok=True)
    return data


async def run_jobs() -> None:
    """capture + video_transcode jobs in-process, like the worker."""
    import app.tasks.capture, app.tasks.followups, app.tasks.video  # noqa: F401,E401
    while True:
        rows = await db.fetch("SELECT id, type, payload FROM jobs WHERE status='queued' AND type IN "
                              "('capture','video_transcode') AND run_at <= now() + interval '5 seconds' ORDER BY id")
        if not rows:
            return
        for r in rows:
            await db.execute("UPDATE jobs SET status='running', attempts=attempts+1 WHERE id=$1", r["id"])
            await jobs.run_one({"id": r["id"], "type": r["type"], "payload": r["payload"], "attempts": 1,
                                "max_attempts": 1})


# ---------------------------------------------------------------- 1. videos from Telegram
@pytest.mark.asyncio
async def test_video_message_is_kept_transcoded_and_shown_in_theater(tg):
    user = uid()
    fid = await tg_family(tg, user)
    tmp = Path(__file__).parent / f"_v{secrets.token_hex(3)}.mp4"
    tg.files["vid1"] = make_mp4(tmp, 2.0, audio=True)
    tg.files["note1"] = make_mp4(tmp, 1.5, audio=False, size="240x240")
    # a normal video (no caption -> attic + year question, nothing invented)
    await handlers.process_update(message(user, video={"file_id": "vid1", "file_unique_id": "uvid1", "duration": 2,
                                                       "width": 320, "height": 240, "mime_type": "video/mp4",
                                                       "file_size": len(tg.files["vid1"])}))
    assert "Got your video" in tg.sent(user)[-1]["text"]
    # a round video note (no mime type, silent) and a too-big video file sent as a document
    await handlers.process_update(message(user, video_note={"file_id": "note1", "file_unique_id": "unote1",
                                                            "duration": 1, "length": 240,
                                                            "file_size": len(tg.files["note1"])}))
    await handlers.process_update(message(user, document={"file_id": "big", "file_unique_id": "ubig",
                                                           "mime_type": "video/quicktime",
                                                           "file_size": 25 * 1024 * 1024}))
    assert "over 20 MB" in tg.sent(user)[-1]["text"]
    mems = await db.fetch("SELECT id, kind FROM memories WHERE family_id=$1 ORDER BY created_at", fid)
    assert [m["kind"] for m in mems] == ["video", "video"]             # the too-big one made no memory
    await run_jobs()
    mid = str(mems[0]["id"])
    mem = await db.fetchrow("SELECT status, title FROM memories WHERE id=$1", mid)
    assert mem["status"] == "attic" and mem["title"] == "Video"
    assert any("ready to play in the museum" in d["text"] for d in tg.sent(user))
    for m in mems:
        v = await db.fetchrow("SELECT * FROM media WHERE memory_id=$1 AND type='video'", m["id"])
        assert v["storage_key"] and storage.exists(v["storage_key"])            # original kept
        assert v["large_key"].endswith(".mp4") and v["thumb_key"].endswith(".jpg") and storage.exists(v["thumb_key"])
        info = ffprobe(storage.path(v["large_key"]))
        codecs = {s["codec_type"]: s["codec_name"] for s in info["streams"]}
        assert codecs == {"video": "h264", "audio": "aac"}                     # silent note gets a silent track
        assert v["duration_s"] == pytest.approx(float(info["format"]["duration"]), abs=0.3)
        assert 1.0 < v["duration_s"] < 2.6
    # place it via the year/month buttons, then the theater playlist carries the video item
    await handlers.process_update(callback(user, f"y:{mid}:2024"))
    await handlers.process_update(callback(user, f"m:{mid}:2024:11"))
    items = await showcase.build_showcase(fid, 2024, 11)
    vids = [i for i in items if i["type"] == "video"]
    assert len(vids) == 1
    it = vids[0]
    assert it["memory_id"] == mid and it["kind"] == "video" and it["caption"] == "Video"
    assert it["url"].startswith("/media/") and ".mp4" in it["url"] and ".jpg" in it["poster_url"]
    assert it["duration_s"] == pytest.approx(2.0, abs=0.3)


# ---------------------------------------------------------------- 2. cleanup history
def test_cleanup_history_auto_skipped_deleted_and_flagged():
    async def go():
        fam = await make_family()
        fid = fam["fid"]
        try:
            soft = sharp_image(21).filter(ImageFilter.GaussianBlur(10))
            album = await add_memory(fid, fam["owner"], "album", "Room photos", y=2031, m=3)
            p_del = await add_photo(fid, album, soft, 0)
            p_flag = await add_photo(fid, album, sharp_image(22).filter(ImageFilter.GaussianBlur(10)), 1)
            await add_photo(fid, album, sharp_image(23), 2)
            ev = await db.fetchval("INSERT INTO events(family_id, name, year, month) VALUES ($1::uuid,'Fair',2031,3) "
                                   "RETURNING id", fid)
            # a blurry gallery upload the import must auto-skip (flag auto_skip_blurry defaults to on)
            data = jpeg(sharp_image(24).filter(ImageFilter.GaussianBlur(12)))
            ukey = storage.put(storage.new_key(fid, "gallery", ".jpg"), data)
            gid = await db.fetchval(
                "INSERT INTO gallery_items(family_id, source, path_or_handle, size_bytes, mime, content_hash, blur_score, "
                "is_blurry, upload_key) VALUES ($1::uuid,'browser','soft.jpg',$2,'image/jpeg',$3,3.1,true,$4) RETURNING id",
                fid, len(data), secrets.token_hex(16), ukey)
            token = secrets.token_urlsafe(16)
            await db.execute("INSERT INTO gallery_previews(token, family_id, item_ids, total_bytes, expires_at) "
                             "VALUES ($1,$2::uuid,$3::uuid[],$4,$5)", token, fid, [gid], len(data),
                             datetime.now(timezone.utc) + timedelta(minutes=5))
            res = await gallery.run_import({"family_id": fid, "token": token, "event_id": str(ev),
                                            "member_id": fam["owner"]})
            assert res["skipped_blurry"] == 1 and res["count"] == 0

            app = FastAPI()
            app.include_router(cleanup_routes.router)
            osid = await auth.new_session(fid, fam["owner"], "owner")
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t",
                                         cookies={auth.COOKIE: osid}) as c:
                d = (await c.post("/api/cleanup/blurry/delete", json={"media_ids": [p_del["id"]]})).json()
                assert d["deleted_media"] == 1 and not storage.exists(p_del["thumb_key"])   # files purged
                h = (await c.get("/api/cleanup/history", params={"year": 2031, "month": 3})).json()
                assert h["counts"] == {"auto_skipped": 1, "deleted": 1, "flagged": 1, "total": 3}, h["counts"]
                by = {p["reason"]: p for p in h["photos"]}
                assert by["deleted"]["id"] == p_del["id"] and by["flagged"]["id"] == p_flag["id"]
                assert by["auto_skipped"]["id"] == str(gid) and by["auto_skipped"]["room"] == {"year": 2031, "month": 3}
                assert by["deleted"]["blur_score"] < 100 and by["auto_skipped"]["blur_score"] == pytest.approx(3.1)
                for p in h["photos"]:
                    assert p["thumb_url"].startswith("/media/") and p["when"]
                    key = p["thumb_url"].split("?")[0][len("/media/"):]
                    from urllib.parse import unquote
                    assert storage.exists(unquote(key)), p                  # still viewable after removal
                assert (await c.get("/api/cleanup/history", params={"year": 2031, "month": 4})).json()["counts"]["total"] == 0
                assert (await c.get("/api/cleanup/history")).json()["counts"]["total"] == 3
                assert (await c.get("/api/cleanup/history", params={"year": 2031})).status_code == 400
        finally:
            await drop_family(fid)
            await db.close()
    asyncio.run(go())


# ---------------------------------------------------------------- 3. timed reel
def test_reel_target_duration_max_photos_and_facts_script():
    async def go():
        fam = await make_family()
        fid = fam["fid"]
        try:
            album = await add_memory(fid, fam["owner"], "album", "Science fair", y=2031, m=4)
            for i in range(6):
                await add_photo(fid, album, sharp_image(30 + i), i)
            await add_photo(fid, album, sharp_image(40).filter(ImageFilter.GaussianBlur(12)), 9)  # skipped (blurry)
            rid = await db.fetchval(
                "INSERT INTO reels(family_id, year, month, narrated, aspect, options) VALUES ($1::uuid,2031,4,false,"
                "'16:9',$2::jsonb) RETURNING id", fid, {"target_s": 16, "max_photos": 4, "title": "Fair day"})
            work = Path(__file__).parent / f"_plan{secrets.token_hex(3)}"
            work.mkdir()
            try:
                plan = await reels.build_plan(fid, 2031, 4, None, (1920, 1080), work,
                                              {"target_s": 16, "max_photos": 4, "title": "Fair day"})
                assert plan.timed and [s.kind for s in plan.slots] == ["card"] + ["photo"] * 4 + ["card"]
                assert len({s.motion for s in plan.slots[1:-1]}) == 4                  # varied Ken Burns moves
                assert plan.meta["photos_in_room"] == 6 and plan.meta["shown"] == 4
                assert plan.meta["set_aside_blurry"] == 1 and plan.meta["authors"] == ["Owner"]
                script = reels.facts_script(plan.meta, "en-IN")
                assert "Fair day, April 2031" in script and "Owner sent six photos" in script
                assert "the four clearest" in script and "One blurry one was set aside" in script
                assert len(script.split()) <= 45
                assert reels.facts_script(plan.meta, "hi-IN") is None
            finally:
                import shutil
                shutil.rmtree(work, ignore_errors=True)
            await reels.render_reel(str(rid))
            row = await db.fetchrow("SELECT * FROM reels WHERE id=$1", rid)
            assert row["status"] == "ready", row["error"]
            dur = float(ffprobe(storage.path(row["storage_key"]))["format"]["duration"])
            assert dur == pytest.approx(16, abs=1.0), dur
        finally:
            await drop_family(fid)
            await db.close()
    asyncio.run(go())
