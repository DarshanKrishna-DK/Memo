"""core-api: gallery index + filters + import job, with real JPEGs (EXIF, GPS) in a temp gallery dir."""
from __future__ import annotations

import io
import os
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from PIL import Image

from _core_fixtures import (blurry_image, drop_family, fresh_pool, jpeg_bytes, make_family, run_job_now,
                            sharp_image)
from app import config, db, flags, storage
from app.core import common, events, gallery, memories, showcase
from app.media import images

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def env(tmp_path_factory):
    await fresh_pool()
    f = await make_family()
    gdir = tmp_path_factory.mktemp("gallery")
    old = config.GALLERY_DIR
    config.GALLERY_DIR = gdir
    now = common.tz_now()
    today = now.date()
    at = lambda d, h: datetime(d.year, d.month, d.day, h, 0, 0)  # noqa: E731  naive camera time
    y1 = today - timedelta(days=1)
    files = {
        "trip/y_a.jpg": jpeg_bytes(sharp_image(1), at(y1, 9)),
        "trip/y_b.jpg": jpeg_bytes(sharp_image(2), at(y1, 12)),
        "trip/y_c.jpg": jpeg_bytes(sharp_image(3), at(y1, 18), camera=("Apple", "iPhone 13")),
        "t_a.jpg": jpeg_bytes(sharp_image(4), at(today, 0)),
        "t_b.jpg": jpeg_bytes(sharp_image(5), at(today, 0) + timedelta(minutes=5)),
        "old/d3.jpg": jpeg_bytes(sharp_image(6), at(today - timedelta(days=3), 10)),
        "old/m2.jpg": jpeg_bytes(sharp_image(7), at(today - timedelta(days=60), 10)),
        "trip/blur.jpg": jpeg_bytes(blurry_image(), at(y1, 15)),
        "noexif.jpg": jpeg_bytes(sharp_image(8), None, camera=None, gps=False),
        "notes.txt": b"not a photo",
    }
    for rel, data in files.items():
        p = gdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    ten_days = (now - timedelta(days=10)).timestamp()
    os.utime(gdir / "noexif.jpg", (ten_days, ten_days))
    (gdir / "trip" / "y_a_copy.jpg").write_bytes(files["trip/y_a.jpg"])        # duplicate content
    yield {**f, "dir": gdir, "today": today, "y1": y1}
    config.GALLERY_DIR = old
    await drop_family(f["id"])
    await db.close()


def names(res: dict) -> set[str]:
    return {s["name"] for s in res["sample"]}


async def test_images_process_photo_strips_gps_and_reads_exif():
    data = jpeg_bytes(sharp_image(11), datetime(2026, 11, 23, 9, 30))
    assert 0x8825 in Image.open(io.BytesIO(data)).getexif()
    out = images.process_photo(data)
    kept = Image.open(io.BytesIO(out["original"]))
    ex = kept.getexif()
    assert 0x8825 not in ex                                        # location gone
    assert ex.get_ifd(0x8769)[36867] == "2026:11:23 09:30:00"       # capture date kept
    assert kept.size == (900, 600)
    assert out["taken_at"] == datetime(2026, 11, 23, 9, 30) and out["camera"] == "Canon EOS 200D"
    assert max(Image.open(io.BytesIO(out["thumb"])).size) == 512
    assert max(Image.open(io.BytesIO(out["large"])).size) == 900    # never upscaled
    assert out["is_blurry"] is False
    assert 0x8825 in Image.open(io.BytesIO(images.process_photo(data, keep_location=True)["original"])).getexif()
    assert images.blur_score(blurry_image()) < images.BLUR_THRESHOLD < images.blur_score(sharp_image(1))


async def test_scan_indexes_folder_only(env):
    res = await gallery.scan_folder(env["id"])
    assert res["scanned"] == 10 and res["new"] == 9 and res["duplicates"] == 1
    rows = await db.fetch("SELECT * FROM gallery_items WHERE family_id=$1::uuid", env["id"])
    by = {r["path_or_handle"].split("/")[-1]: r for r in rows}
    assert by["noexif.jpg"]["taken_at_source"] == "file_date"
    assert by["y_b.jpg"]["taken_at_source"] == "exif" and by["y_b.jpg"]["camera"] == "Canon EOS 200D"
    assert by["y_b.jpg"]["folder"] == "trip" and by["y_b.jpg"]["width"] == 900
    assert by["blur.jpg"]["is_blurry"] is True and by["y_b.jpg"]["is_blurry"] is False
    again = await gallery.scan_folder(env["id"])
    assert again["new"] == 0
    with pytest.raises(PermissionError):
        gallery._safe_gallery_path("../outside.jpg")


async def test_filters_select_exact_sets(env):
    y = await gallery.query(env["id"], {"when": "yesterday"})
    assert y["count"] == 4 and names(y) == {"y_a.jpg", "y_b.jpg", "y_c.jpg", "blur.jpg"}
    assert y["blurry"] == 1 and y["over_limit"] is False and y["preview_token"]
    assert y["date_from"] == y["date_to"] == env["y1"].isoformat()
    a = await gallery.query(env["id"], {"all": True})
    assert a["count"] == 9
    latest = await gallery.query(env["id"], {"latest_n": 20})
    assert latest["count"] == 9
    l3 = await gallery.query(env["id"], {"latest_n": 3})
    assert names(l3) == {"t_a.jpg", "t_b.jpg", "y_c.jpg"}
    cam = await gallery.query(env["id"], {"camera": "iphone"})
    assert names(cam) == {"y_c.jpg"}
    fold = await gallery.query(env["id"], {"folder": "old"})
    assert names(fold) == {"d3.jpg", "m2.jpg"}
    rng = await gallery.query(env["id"], {"date_from": (env["today"] - timedelta(days=3)).isoformat(),
                                          "date_to": env["y1"].isoformat()})
    assert rng["count"] == 5
    assert (await gallery.query(env["id"], {"min_size": 10 ** 9}))["count"] == 0
    with pytest.raises(ValueError):
        await gallery.query(env["id"], {})
    total = sum(s["size_bytes"] for s in y["sample"])
    assert y["total_bytes"] == total


async def test_cap_by_flag(env):
    await flags.set_override("max_import_photos", 5, env["id"])
    try:
        a = await gallery.query(env["id"], {"all": True})
        assert a["over_limit"] is True and a["limit"] == 5 and a["count"] == 5 and a["matched"] == 9
        assert names(a) == {"t_a.jpg", "t_b.jpg", "y_c.jpg", "blur.jpg", "y_b.jpg"}    # the newest that fit
    finally:
        await db.execute("DELETE FROM flag_overrides WHERE family_id=$1::uuid", env["id"])
        flags._cache.clear()


async def test_import_album_idempotent(env):
    t = env["today"]
    ev = (await events.create_event(env["id"], env["owner"], "Cousins visit", "trip", t.year, t.month))["event"]
    q = await gallery.query(env["id"], {"when": "yesterday"})
    started = await gallery.start_import(env["id"], env["owner"], q["preview_token"], ev["id"])
    assert started["count"] == 4 and started["already_started"] is False
    twice = await gallery.start_import(env["id"], env["owner"], q["preview_token"], ev["id"])
    assert twice["job_id"] == started["job_id"] and twice["already_started"] is True
    job = await run_job_now(started["job_id"])
    assert job["status"] == "done", job
    res = job["result"]
    assert res["count"] == 3 and res["skipped_blurry"] == 1          # auto_skip_blurry is on by default
    mid = res["memory_id"]
    m = await db.fetchrow("SELECT * FROM memories WHERE id=$1::uuid", mid)
    assert (m["kind"], m["status"], m["event_year"], m["event_month"]) == ("album", "saved", t.year, t.month)
    assert str(m["event_id"]) == ev["id"]
    ex = await memories.get_memory(env["id"], mid)
    taken = [p["taken_at"] for p in ex["photos"]]
    assert taken == sorted(taken) and len(taken) == 3                # ordered by capture time
    orig = await db.fetch("SELECT storage_key, thumb_key FROM media WHERE memory_id=$1::uuid", mid)
    for r in orig:
        assert 0x8825 not in Image.open(io.BytesIO(storage.get(r["storage_key"]))).getexif()   # GPS stripped
        assert storage.exists(r["thumb_key"])
    # running the same job body again (a replay or a worker killed mid-job) creates nothing new
    again = await gallery.run_import({"family_id": env["id"], "member_id": env["owner"],
                                      "token": q["preview_token"], "event_id": ev["id"]})
    assert again["memory_id"] == mid and again["count"] == 3
    assert await db.fetchval("SELECT count(*) FROM memories WHERE family_id=$1::uuid AND kind='album'",
                             env["id"]) == 1
    assert await db.fetchval("SELECT count(*) FROM media WHERE memory_id=$1::uuid", mid) == 3
    # imported photos are not offered again
    q2 = await gallery.query(env["id"], {"when": "yesterday"})
    assert q2["count"] == 1 and q2["already_imported"] == 3 and names(q2) == {"blur.jpg"}
    # showcase plays the album photos in taken order
    items = await showcase.build_showcase(env["id"], t.year, t.month, ev["id"])
    assert [i["kind"] for i in items] == ["photo"] * 3 and all(i["duration_s"] == 6.0 for i in items)
    assert items[0]["caption"] == "Cousins visit"


async def test_browser_upload_source(env):
    data = jpeg_bytes(sharp_image(21), datetime(2025, 3, 14, 11, 0))
    res = await gallery.index_uploads(env["id"], [("holi.jpg", data, {"path": "Holi 2025/holi.jpg"}),
                                                  ("holi-again.jpg", data, {})])
    assert res == {"scanned": 2, "new": 1, "duplicates": 1, "unreadable": 0, "source": "browser"}
    r = await db.fetchrow("SELECT * FROM gallery_items WHERE family_id=$1::uuid AND source='browser'", env["id"])
    assert r["folder"] == "Holi 2025" and storage.exists(r["upload_key"])
    q = await gallery.query(env["id"], {"when": "March 2025"})
    assert q["count"] == 1 and q["sample"][0]["thumb_url"].startswith("/media/")
