"""media-tools tests: real images, real ffmpeg, real Postgres. Test rows are removed afterwards."""
from __future__ import annotations

import asyncio
import io
import json
import secrets
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import numpy as np
import pytest
from fastapi import FastAPI
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import auth, db, storage  # noqa: E402
from app.media import blur, reels  # noqa: E402
from app.routes import cleanup as cleanup_routes  # noqa: E402
from app.routes import reels as reels_routes  # noqa: E402


# ---------------------------------------------------------------- fixtures: real images
def sharp_image(seed: int = 0, size=(1200, 800)) -> Image.Image:
    rng = np.random.default_rng(seed)
    img = Image.new("RGB", size, (240, 240, 230))
    d = ImageDraw.Draw(img)
    step = 40
    for y in range(0, size[1], step):
        for x in range(0, size[0], step):
            if ((x // step) + (y // step)) % 2 == 0:
                d.rectangle([x, y, x + step, y + step], fill=tuple(int(v) for v in rng.integers(0, 90, 3)))
    f = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 64)
    d.text((60, 60), "Diwali at Nani's house", font=f, fill=(255, 255, 255))
    return img


def jpeg(img: Image.Image) -> bytes:
    b = io.BytesIO()
    img.save(b, "JPEG", quality=92)
    return b.getvalue()


def test_blur_scores_separate_sharp_from_blurred():
    sharp = sharp_image()
    blurred = sharp.filter(ImageFilter.GaussianBlur(9))
    a, b = blur.analyze(jpeg(sharp)), blur.analyze(jpeg(blurred))
    assert a["score"] > 10 * b["score"], (a, b)
    assert not blur.is_blurry(a["score"], a["hf_ratio"])
    assert blur.is_blurry(b["score"], b["hf_ratio"])
    assert a["hf_ratio"] > b["hf_ratio"]
    assert blur.score_image(jpeg(sharp)) == pytest.approx(a["score"])
    # path input works too
    p = Path(__file__).parent / "_tmp_sharp.jpg"
    try:
        p.write_bytes(jpeg(sharp))
        assert blur.score_image(p) == pytest.approx(a["score"])
    finally:
        p.unlink(missing_ok=True)


# ---------------------------------------------------------------- DB scaffolding
async def make_family() -> dict:
    fid = await db.fetchval(
        "INSERT INTO families(name, invite_code) VALUES ('Test Rao family', $1) RETURNING id", secrets.token_hex(8))
    fid = str(fid)
    owner = str(await db.fetchval(
        "INSERT INTO members(family_id, nickname, role) VALUES ($1::uuid,'Owner','owner') RETURNING id", fid))
    editor = str(await db.fetchval(
        "INSERT INTO members(family_id, nickname, role) VALUES ($1::uuid,'Editor','editor') RETURNING id", fid))
    return {"fid": fid, "owner": owner, "editor": editor}


async def add_memory(fid, author, kind, title, text=None, y=2031, m=3, day=None) -> str:
    return str(await db.fetchval(
        "INSERT INTO memories(family_id, author_id, kind, title, text_original, event_year, event_month, event_day, status) "
        "VALUES ($1::uuid,$2::uuid,$3,$4,$5,$6,$7,$8,'saved') RETURNING id", fid, author, kind, title, text, y, m, day))


async def add_photo(fid, mem_id, img: Image.Image, order=0) -> dict:
    data = jpeg(img)
    keys = {k: storage.put(storage.new_key(fid, "photos", ".jpg"), data) for k in ("storage_key", "large_key", "thumb_key")}
    a = blur.analyze(data)
    mid = str(await db.fetchval(
        "INSERT INTO media(memory_id, type, storage_key, large_key, thumb_key, mime, width, height, sort_order, "
        "blur_score, is_blurry) VALUES ($1::uuid,'photo',$2,$3,$4,'image/jpeg',$5,$6,$7,$8,$9) RETURNING id",
        mem_id, keys["storage_key"], keys["large_key"], keys["thumb_key"], img.width, img.height, order,
        a["score"], blur.is_blurry(a["score"], a["hf_ratio"])))
    return {"id": mid, **keys}


async def drop_family(fid: str) -> None:
    await db.execute("DELETE FROM families WHERE id=$1::uuid", fid)   # cascades to everything else
    storage.delete_prefix(fid)


def ffprobe(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                       capture_output=True, check=True)
    return json.loads(r.stdout)


def make_tone(path: Path, seconds=3):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    "-c:a", "libopus", str(path)], check=True)


# ---------------------------------------------------------------- reel render (real ffmpeg, real DB)
def test_render_reel_from_photos_text_voice_and_hindi():
    async def go():
        fam = await make_family()
        fid = fam["fid"]
        try:
            m1 = await add_memory(fid, fam["owner"], "photo", "Rangoli at the door", day=1)
            m2 = await add_memory(fid, fam["owner"], "album", "Lighting the diyas", day=2)
            m3 = await add_memory(fid, fam["editor"], "photo", "A portrait one", day=3)
            for i, (mm, img) in enumerate([(m1, sharp_image(1)), (m2, sharp_image(2)), (m2, sharp_image(3, (800, 1200))),
                                           (m3, sharp_image(4, (900, 900)))]):
                await add_photo(fid, mm, img, i)
            blurry_mem = await add_memory(fid, fam["owner"], "photo", "Blurry one should be skipped", day=4)
            await add_photo(fid, blurry_mem, sharp_image(5).filter(ImageFilter.GaussianBlur(12)))
            await add_memory(fid, fam["owner"], "text", "Dadi's story",
                             "Every Diwali Dadi made kaju katli and hid the best piece for the smallest child.", day=5)
            await add_memory(fid, fam["owner"], "text", "\u0926\u093f\u0935\u093e\u0932\u0940 \u0915\u0940 \u092f\u093e\u0926",
                             "\u0939\u092e \u0938\u092c \u0926\u0940\u092f\u0947 \u091c\u0932\u093e\u0924\u0947 \u0925\u0947\u0964", day=6)
            vm = await add_memory(fid, fam["owner"], "voice", "Grandpa sings", day=7)
            tone = Path(__file__).parent / "_tone.ogg"
            make_tone(tone)
            vkey = storage.put(storage.new_key(fid, "voice", ".ogg"), tone.read_bytes())
            tone.unlink(missing_ok=True)
            await db.execute("INSERT INTO media(memory_id,type,storage_key,duration_s,audio_kept) "
                             "VALUES ($1::uuid,'voice',$2,3,true)", vm, vkey)

            for aspect, size in (("16:9", (1920, 1080)), ("9:16", (1080, 1920))):
                rid = await db.fetchval(
                    "INSERT INTO reels(family_id, year, month, narrated, aspect) VALUES ($1::uuid,2031,3,false,$2) RETURNING id",
                    fid, aspect)
                res = await reels.render_reel(str(rid))
                row = await db.fetchrow("SELECT * FROM reels WHERE id=$1", rid)
                assert row["status"] == "ready", row["error"]
                out = storage.path(row["storage_key"])
                assert out.exists() and out.stat().st_size > 10_000
                info = ffprobe(out)
                v = [s for s in info["streams"] if s["codec_type"] == "video"]
                a = [s for s in info["streams"] if s["codec_type"] == "audio"]
                assert v and a
                assert v[0]["codec_name"] == "h264" and a[0]["codec_name"] == "aac"
                assert (v[0]["width"], v[0]["height"]) == size
                dur = float(info["format"]["duration"])
                assert dur > 0 and row["duration_s"] == pytest.approx(dur, abs=0.5)
                # opening + 4 photos + 2 text cards + voice card + closing; blurry photo is skipped
                assert dur > 30, dur
                assert res["duration_s"] > 0
            # deleting via the route removes the file
            app = FastAPI()
            app.include_router(reels_routes.router)
            sid = await auth.new_session(fid, fam["owner"], "owner")
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t",
                                         cookies={auth.COOKIE: sid}) as c:
                lst = (await c.get("/api/reels", params={"year": 2031, "month": 3})).json()["reels"]
                assert len(lst) == 2 and all(r["url"] for r in lst)
                one = (await c.get(f"/api/reels/{lst[0]['id']}")).json()
                assert one["status"] == "ready"
                key = (await db.fetchval("SELECT storage_key FROM reels WHERE id=$1::uuid", lst[0]["id"]))
                assert storage.exists(key)
                assert (await c.delete(f"/api/reels/{lst[0]['id']}")).status_code == 200
                assert not storage.exists(key)
                empty = await c.post("/api/reels", json={"year": 2031, "month": 9})
                assert empty.status_code == 400
        finally:
            await drop_family(fid)
            await db.close()
    asyncio.run(go())


# ---------------------------------------------------------------- cleanup routes
def test_cleanup_list_delete_keep_and_permissions():
    async def go():
        fam = await make_family()
        fid = fam["fid"]
        try:
            sharp, soft = sharp_image(7), sharp_image(8).filter(ImageFilter.GaussianBlur(10))
            solo = await add_memory(fid, fam["owner"], "photo", "Only a blurry photo")
            p_solo = await add_photo(fid, solo, soft)
            album = await add_memory(fid, fam["owner"], "album", "Album with two")
            p_blur = await add_photo(fid, album, soft, 0)
            p_ok = await add_photo(fid, album, sharp, 1)
            ed_mem = await add_memory(fid, fam["editor"], "photo", "Editor photo")
            p_ed = await add_photo(fid, ed_mem, soft)
            keep_mem = await add_memory(fid, fam["owner"], "photo", "Dear but blurry")
            p_keep = await add_photo(fid, keep_mem, soft)

            app = FastAPI()
            app.include_router(cleanup_routes.router)
            osid = await auth.new_session(fid, fam["owner"], "owner")
            esid = await auth.new_session(fid, fam["editor"], "editor")
            T = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=T, base_url="http://t", cookies={auth.COOKIE: osid}) as owner, \
                    httpx.AsyncClient(transport=T, base_url="http://t", cookies={auth.COOKIE: esid}) as editor:
                lo = (await owner.get("/api/cleanup/blurry")).json()
                ids = {p["media_id"] for p in lo["photos"]}
                assert ids == {p_solo["id"], p_blur["id"], p_ed["id"], p_keep["id"]} and p_ok["id"] not in ids
                assert all(p["thumb_url"].startswith("/media/") for p in lo["photos"])
                le = (await editor.get("/api/cleanup/blurry")).json()
                assert {p["media_id"] for p in le["photos"]} == {p_ed["id"]}
                # editor cannot delete the owner's photo, can delete their own
                r = (await editor.post("/api/cleanup/blurry/delete",
                                       json={"media_ids": [p_blur["id"], p_ed["id"]]})).json()
                assert r["deleted_media"] == 1 and r["not_allowed_or_missing"] == [p_blur["id"]]
                assert not storage.exists(p_ed["large_key"]) and storage.exists(p_blur["large_key"])
                assert r["memories_deleted"] == [ed_mem]
                # owner: keep one, delete the rest; album keeps its sharp photo, solo memory is marked deleted
                k = (await owner.post("/api/cleanup/blurry/keep", json={"media_ids": [p_keep["id"]]})).json()
                assert k["kept_media"] == 1
                d = (await owner.post("/api/cleanup/blurry/delete",
                                      json={"media_ids": [p_solo["id"], p_blur["id"]]})).json()
                assert d["deleted_media"] == 2 and d["memories_deleted"] == [solo]
                for p in (p_solo, p_blur):
                    assert not storage.exists(p["storage_key"]) and not storage.exists(p["thumb_key"])
                assert await db.fetchval("SELECT status FROM memories WHERE id=$1::uuid", solo) == "deleted"
                assert await db.fetchval("SELECT status FROM memories WHERE id=$1::uuid", album) == "saved"
                assert storage.exists(p_ok["large_key"])
                # a rescan must not re-flag the kept photo, and the job is enqueued
                stats = await blur.rescore_family(fid)
                assert stats["media"] == 2 and stats["flagged"] == 0
                assert (await owner.post("/api/cleanup/rescan")).status_code == 202
                after = (await owner.get("/api/cleanup/blurry")).json()
                assert after["count"] == 0
        finally:
            await db.execute("DELETE FROM jobs WHERE type='cleanup_rescan' AND payload->>'family_id'=$1", fid)
            await drop_family(fid)
            await db.close()
    asyncio.run(go())
