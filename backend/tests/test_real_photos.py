"""Image tests with the owner's REAL photos (D:/Memo/data/gallery, or REAL_PHOTOS_DIR): DSLR + phone JPEGs of 0.1-17 MB,
portrait/rotated frames, WhatsApp images without EXIF. No image data is faked. The folder is never written to:
tests that change files work on a copy in a temp dir. Throwaway families are deleted at the end.

Run:  cd backend && .venv/Scripts/python -m pytest tests/test_real_photos.py -s
(stop the live worker first: it would steal the import/capture jobs; see docs). Set REAL_PHOTOS_OUT=<dir> to keep the
extracted reel frames for looking at.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import os
import shutil
import statistics
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pytest
import pytest_asyncio
from fastapi import FastAPI
from PIL import Image, ImageFilter, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REAL = Path(os.environ.get("REAL_PHOTOS_DIR") or Path(__file__).resolve().parents[2] / "gallery")
FILES = sorted(p for p in REAL.glob("*") if p.suffix.lower() in (".jpg", ".jpeg")) if REAL.is_dir() else []
if not FILES:
    pytest.skip(f"real photo folder {REAL} not found or empty", allow_module_level=True)

from app import auth, config, db, jobs, storage  # noqa: E402
from app.core import common, events, gallery  # noqa: E402
from app.media import blur, images, reels  # noqa: E402
from app.routes import cleanup as cleanup_routes  # noqa: E402
from app.telegram import handlers, send  # noqa: E402

from _core_fixtures import drop_family, fresh_pool, make_family, run_job_now  # noqa: E402

pytestmark = pytest.mark.asyncio(loop_scope="module")
GPS_IFD, EXIF_IFD = 0x8825, 0x8769
OUT = Path(os.environ["REAL_PHOTOS_OUT"]) if os.environ.get("REAL_PHOTOS_OUT") else None


def report(capsys, *lines: str) -> None:
    with capsys.disabled():
        print()
        for ln in lines:
            print(ln)


def oriented_size(path_or_bytes) -> tuple[int, int, int]:
    im = Image.open(io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, bytes) else path_or_bytes)
    o = im.getexif().get(274, 1)
    w, h = im.size
    return (h, w, o) if o in (5, 6, 7, 8) else (w, h, o)


# ------------------------------------------------------------------------------------------ process_photo
def test_process_photo_every_real_file(capsys):
    rows, times, gps_sources = [], [], 0
    for p in FILES:
        data = p.read_bytes()
        src_ex = Image.open(io.BytesIO(data)).getexif()
        has_gps = bool(src_ex.get_ifd(GPS_IFD))
        gps_sources += has_gps
        t0 = time.perf_counter()
        r = images.process_photo(data)
        dt = time.perf_counter() - t0
        times.append(dt)
        w, h, ori = oriented_size(data)
        # orientation applied: reported size is the display size, derivatives have the same aspect
        assert (r["width"], r["height"]) == (w, h), p.name
        lg, th = Image.open(io.BytesIO(r["large"])), Image.open(io.BytesIO(r["thumb"]))
        assert max(lg.size) == min(1600, max(w, h)) and max(th.size) == min(512, max(w, h)), p.name
        for im in (lg, th):
            assert abs(im.width / im.height - w / h) < 0.01, f"{p.name}: derivative is sideways/cropped"
            assert not im.getexif().get(274, 1) in (5, 6, 7, 8)       # nothing left to rotate
        # original: location gone, capture date and camera kept, pixels untouched
        kept = Image.open(io.BytesIO(r["original"]))
        assert not kept.getexif().get_ifd(GPS_IFD), f"{p.name}: GPS leaked into the stored original"
        assert b"GPSLatitude" not in r["original"][:200_000]
        assert kept.size == Image.open(io.BytesIO(data)).size
        assert len(r["original"]) <= len(data)
        # EXIF date / camera where present, none where the file has none (WhatsApp, edited exports)
        sub = src_ex.get_ifd(EXIF_IFD)
        has_date = bool(sub.get(36867) or sub.get(36868) or src_ex.get(306))
        assert (r["taken_at"] is not None) == has_date, p.name
        assert (r["camera"] is not None) == bool(src_ex.get(271) or src_ex.get(272)), p.name
        assert r["content_hash"] == hashlib.sha256(data).hexdigest()
        rows.append((p.name[:34], len(data) // 1024, f"{w}x{h}", ori, str(r["taken_at"] or "-")[:19],
                     r["camera"] or "-", f"{r['blur_score']:.0f}", f"{dt:.2f}s", "GPS" if has_gps else ""))
    report(capsys, f"{'file':34} {'KB':>6} {'size':>10} ori {'taken_at':19} {'camera':22} {'blur':>5} {'time':>6}",
           *[f"{a:34} {b:>6} {c:>10} {d!s:>3} {e:19} {f:22} {g:>5} {h:>6} {i}" for a, b, c, d, e, f, g, h, i in rows],
           f"process_photo: n={len(FILES)} median {statistics.median(times):.2f}s max {max(times):.2f}s "
           f"total {sum(times):.1f}s; {gps_sources} source files carried GPS")
    assert max(times) < 30
    assert any(r[3] in (5, 6, 7, 8) for r in rows), "no rotated real photo in the folder: orientation untested"


def test_keep_location_keeps_gps_when_asked():
    for p in FILES:
        data = p.read_bytes()
        if Image.open(io.BytesIO(data)).getexif().get_ifd(GPS_IFD):
            assert images.process_photo(data, keep_location=True)["original"] == data
            assert not Image.open(io.BytesIO(images.process_photo(data)["original"])).getexif().get_ifd(GPS_IFD)
            return
    pytest.skip("no real photo with GPS in the folder")


def test_orientation_matches_exif_transpose_pixels():
    """Not just the aspect ratio: the thumbnail is the upright picture (compare to Pillow's own transpose)."""
    for p in FILES:
        data = p.read_bytes()
        if oriented_size(data)[2] in (1, None):
            continue
        r = images.process_photo(data)
        up = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        up.thumbnail((512, 512))
        a = np.asarray(Image.open(io.BytesIO(r["thumb"])).convert("L").resize((64, 64)), dtype=float)
        b = np.asarray(up.convert("L").resize((64, 64)), dtype=float)
        assert np.corrcoef(a.ravel(), b.ravel())[0, 1] > 0.95, p.name
        raw = Image.open(io.BytesIO(data)).convert("L")
        raw.thumbnail((512, 512))
        c = np.asarray(raw.resize((64, 64)), dtype=float)
        assert np.corrcoef(a.ravel(), c.ravel())[0, 1] < 0.9, f"{p.name}: thumb is not rotated vs the raw pixels"


def test_biggest_photos_do_not_blow_memory(capsys):
    """Process the biggest files in a fresh interpreter and read its PEAK working set (Windows)."""
    big = sorted(FILES, key=lambda p: p.stat().st_size)[-2:]
    code = (
        "import sys, ctypes, time\n"
        "from ctypes import wintypes\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})\n"
        "from app.media import images\n"
        "t=time.time()\n"
        "for p in sys.argv[1:]:\n"
        "    r = images.process_photo(open(p,'rb').read())\n"
        "class C(ctypes.Structure):\n"
        "    _fields_=[('cb',wintypes.DWORD),('pf',wintypes.DWORD),('peak',ctypes.c_size_t),('ws',ctypes.c_size_t),"
        "('a',ctypes.c_size_t),('b',ctypes.c_size_t),('c',ctypes.c_size_t),('d',ctypes.c_size_t),('pm',ctypes.c_size_t),"
        "('pp',ctypes.c_size_t)]\n"
        "k=ctypes.windll.kernel32; k.GetCurrentProcess.restype=ctypes.c_void_p\n"
        "ps=ctypes.windll.psapi; ps.GetProcessMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.POINTER(C),wintypes.DWORD]\n"
        "m=C(); m.cb=ctypes.sizeof(m); ps.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(m), m.cb)\n"
        "print('PEAK_MB', m.peak/1e6, 'SECS', time.time()-t)\n")
    if sys.platform != "win32":
        pytest.skip("peak RSS probe is Windows-only")
    out = subprocess.run([sys.executable, "-c", code, *map(str, big)], capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr
    peak = float(out.stdout.split("PEAK_MB")[1].split()[0])
    report(capsys, f"peak working set processing {[f'{p.name} {p.stat().st_size / 1e6:.1f}MB' for p in big]}: "
                   f"{peak:.0f} MB")
    assert peak < 1200


# ------------------------------------------------------------------------------------------ blur threshold
def test_blur_scores_and_threshold_on_real_photos(capsys):
    thr = images.BLUR_THRESHOLD
    assert blur.threshold() == thr == 100.0
    scored = []
    for p in FILES:
        data = p.read_bytes()
        a = blur.analyze(data)
        s_img = images.inspect(data)["blur_score"]
        assert s_img == pytest.approx(a["score"], rel=0.06), f"{p.name}: the two metrics disagree"
        scored.append((a["score"], a["hf_ratio"], p.name))
    scored.sort()
    report(capsys, f"blur threshold = {thr:g}; lowest 12 of {len(scored)} real photos (score = Laplacian variance, 512px)",
           *[f"  {s:8.1f}  hf={h:.3f}  {'BLURRY' if blur.is_blurry(s, h) else 'ok':6} {n}" for s, h, n in scored[:12]],
           f"  median {statistics.median(s for s, _, _ in scored):.0f}, max {scored[-1][0]:.0f}")
    # I looked at the lowest ones (shallow depth-of-field DSLR frames, subject sharp, background bokeh): all fine.
    assert not [n for s, h, n in scored if blur.is_blurry(s, h)], "sharp real photos flagged as blurry"
    assert scored[0][0] > 1.5 * thr, "a real photo scores within 1.5x of the threshold: margin too thin"
    # ... and the threshold still catches real photos that ARE out of focus (mild defocus = 0.4% of the width)
    caught = 0
    worst = 0.0
    for p in FILES:
        im = ImageOps.exif_transpose(Image.open(p))
        im.thumbnail((1600, 1600))
        s = images.blur_score(im.filter(ImageFilter.GaussianBlur(0.004 * im.width)))
        worst = max(worst, s)
        caught += s < thr
    report(capsys, f"  defocused copies of the same photos: {caught}/{len(FILES)} below threshold, max score {worst:.0f}")
    assert caught == len(FILES)


# ------------------------------------------------------------------------------------------ gallery + db
@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def env(tmp_path_factory):
    await fresh_pool()
    f = await make_family("pytest-real-photos")
    gdir = tmp_path_factory.mktemp("real_gallery")
    for p in FILES:
        shutil.copy2(p, gdir / p.name)                 # copy2 keeps the file date (WhatsApp files rely on it)
    old = config.GALLERY_DIR
    config.GALLERY_DIR = gdir
    fam = await common.family(f["id"])
    tz = ZoneInfo(fam["timezone"])
    # independent expectation per file: what the scanner should store
    exp, seen = {}, set()
    for p in sorted(gdir.glob("*")):
        d = p.read_bytes()
        info = images.inspect(d)
        h = info["content_hash"]
        taken = info["taken_at"]
        src = "exif" if taken else "file_date"
        taken = (taken if taken.tzinfo else taken.replace(tzinfo=tz)) if taken else datetime.fromtimestamp(
            p.stat().st_mtime, tz=tz)
        exp[p.name] = {"hash": h, "taken": taken, "src": src, "camera": info["camera"], "dup": h in seen,
                       "w": info["width"], "h": info["height"], "size": len(d)}
        seen.add(h)
    yield {**f, "dir": gdir, "tz": tz, "exp": exp, "unique": {k: v for k, v in exp.items() if not v["dup"]}}
    config.GALLERY_DIR = old
    await db.execute("DELETE FROM jobs WHERE payload->>'family_id'=$1", f["id"])
    await db.execute("DELETE FROM reels WHERE family_id=$1::uuid", f["id"])
    await drop_family(f["id"])
    await db.close()


def names(res: dict) -> list[str]:
    return [s["name"] for s in res["sample"]]


async def test_scan_real_folder_copy_dates_and_duplicates(env, capsys):
    t0 = time.perf_counter()
    res = await gallery.scan_folder(env["id"])
    dt = time.perf_counter() - t0
    n_dup = sum(v["dup"] for v in env["exp"].values())
    assert res["scanned"] == len(FILES) and res["unreadable"] == 0
    assert res["new"] == len(FILES) - n_dup and res["duplicates"] == n_dup
    rows = {r["path_or_handle"]: r for r in await db.fetch("SELECT * FROM gallery_items WHERE family_id=$1::uuid",
                                                           env["id"])}
    for name, e in env["unique"].items():
        r = rows[name]
        assert r["taken_at_source"] == e["src"], name
        assert abs((r["taken_at"] - e["taken"]).total_seconds()) < 1, name
        assert (r["width"], r["height"]) == (e["w"], e["h"]) and r["size_bytes"] == e["size"]
        assert r["camera"] == e["camera"] and r["is_blurry"] is False
    assert sum(1 for e in env["unique"].values() if e["src"] == "file_date") >= 1   # WhatsApp: file date fallback
    assert (await gallery.scan_folder(env["id"]))["new"] == 0
    # a copy of a real photo under another name is a duplicate, not a new item
    shutil.copy2(env["dir"] / "DSC_1022.JPG", env["dir"] / "copy of DSC_1022 renamed.jpg")
    again = await gallery.scan_folder(env["id"])
    assert again["new"] == 0 and again["duplicates"] >= 1
    assert await db.fetchval("SELECT count(*) FROM gallery_items WHERE family_id=$1::uuid", env["id"]) == len(
        env["unique"])
    (env["dir"] / "copy of DSC_1022 renamed.jpg").unlink()
    gone = await gallery.scan_folder(env["id"])
    assert gone["new"] == 0
    report(capsys, f"scan of {len(FILES)} real files (temp copy): {dt:.1f}s, {res['new']} new, {res['duplicates']} dup, "
                   f"{sum(1 for e in env['unique'].values() if e['src'] == 'file_date')} dated by file date")


async def test_query_filters_on_real_photos(env):
    uniq = env["unique"]
    a = await gallery.query(env["id"], {"all": True})
    assert a["count"] == len(uniq) and a["over_limit"] is False and a["preview_token"] and a["blurry"] == 0
    assert a["total_bytes"] == sum(e["size"] for e in uniq.values())
    l10 = await gallery.query(env["id"], {"latest_n": 10})
    assert l10["count"] == 10
    want = sorted(((e["taken"], n) for n, e in uniq.items()), reverse=True)[:10]
    got = [datetime.fromisoformat(s["taken_at"]) for s in l10["sample"]]
    assert [g.timestamp() for g in got] == pytest.approx([w[0].timestamp() for w in want], abs=1)
    # one shoot day: the Nikon day (naive EXIF clock, same calendar day in the family timezone)
    day = "2025-07-13"
    exp_day = {n for n, e in uniq.items() if e["taken"].astimezone(env["tz"]).date().isoformat() == day}
    assert len(exp_day) >= 5 and all(uniq[n]["camera"] == "NIKON D3200" for n in exp_day)
    d1 = await gallery.query(env["id"], {"date_from": day, "date_to": day})
    assert set(names(d1)) == exp_day and d1["count"] == len(exp_day)
    d2 = await gallery.query(env["id"], {"when": day})
    assert set(names(d2)) == exp_day
    # a range spanning the Nikon day and the Canon days
    rng = await gallery.query(env["id"], {"date_from": "2025-07-13", "date_to": "2026-02-28"})
    exp_rng = {n for n, e in uniq.items() if "2025-07-13" <= e["taken"].astimezone(env["tz"]).date().isoformat() <= "2026-02-28"}
    assert rng["count"] == len(exp_rng) and set(names(rng)) <= exp_rng      # sample shows at most 12
    # DSLR vs phone
    nikon = await gallery.query(env["id"], {"camera": "nikon"})
    assert set(names(nikon)) == {n for n, e in uniq.items() if (e["camera"] or "").upper().startswith("NIKON")}
    iphone = await gallery.query(env["id"], {"camera": "iPhone"})
    assert len(iphone["sample"]) == 3 and all("iPhone" in s["camera"] for s in iphone["sample"])
    samsung = await gallery.query(env["id"], {"camera": "samsung"})
    assert names(samsung) == ["20251208_131731.jpg"]
    canon = await gallery.query(env["id"], {"camera": "canon"})
    assert canon["count"] == 7
    port = await gallery.query(env["id"], {"camera": "nikon", "orientation": "portrait"})
    assert names(port) == ["DSC_1007.JPG"]                       # the rotated (EXIF orientation 8) frame
    big = await gallery.query(env["id"], {"min_size": 10 * 1024 * 1024})
    assert {n for n in names(big)} == {n for n, e in uniq.items() if e["size"] >= 10 * 1024 * 1024}
    assert (await gallery.query(env["id"], {"max_size": 100}))["count"] == 0
    assert (await gallery.query(env["id"], {"type": "jpeg"}))["count"] == len(uniq)    # MPO JPEGs count as jpeg


async def test_import_latest_eight_into_event_month_in_capture_order(env, capsys):
    ev = (await events.create_event(env["id"], env["owner"], "Tech events 2026", "other", 2026, 5))["event"]
    q = await gallery.query(env["id"], {"latest_n": 8})
    assert q["count"] == 8
    env["event"], env["eight_taken"] = ev, sorted(datetime.fromisoformat(s["taken_at"]) for s in q["sample"][:8])
    started = await gallery.start_import(env["id"], env["owner"], q["preview_token"], ev["id"])
    t0 = time.perf_counter()
    job = await run_job_now(started["job_id"], timeout=300)
    dt = time.perf_counter() - t0
    assert job["status"] == "done", job
    res = job["result"]
    assert res["count"] == 8 and res["skipped_blurry"] == 0 and res["failed"] == 0 and (res["year"], res["month"]) == (2026, 5)
    mid = res["memory_id"]
    env["album"] = mid
    m = await db.fetchrow("SELECT * FROM memories WHERE id=$1::uuid", mid)
    assert (m["kind"], m["status"], m["event_year"], m["event_month"]) == ("album", "saved", 2026, 5)
    assert str(m["event_id"]) == ev["id"]
    assert await db.fetchval("SELECT count(*) FROM memories WHERE family_id=$1::uuid AND kind='album'", env["id"]) == 1
    media = await db.fetch("SELECT * FROM media WHERE memory_id=$1::uuid ORDER BY sort_order", mid)
    taken = [r["taken_at"] for r in media]
    assert taken == sorted(taken) and [t.timestamp() for t in taken] == pytest.approx(
        [t.timestamp() for t in env["eight_taken"]], abs=1)          # capture order
    assert [r["sort_order"] for r in media] == list(range(8))
    for r in media:
        orig = storage.get(r["storage_key"])
        assert not Image.open(io.BytesIO(orig)).getexif().get_ifd(GPS_IFD)
        assert max(Image.open(io.BytesIO(storage.get(r["large_key"]))).size) <= 1600
        assert max(Image.open(io.BytesIO(storage.get(r["thumb_key"]))).size) <= 512
    again = await gallery.run_import({"family_id": env["id"], "member_id": env["owner"], "token": q["preview_token"],
                                      "event_id": ev["id"]})
    assert again["memory_id"] == mid and again["count"] == 8
    assert await db.fetchval("SELECT count(*) FROM media WHERE memory_id=$1::uuid", mid) == 8
    report(capsys, f"import of 8 real photos (incl. originals 6-16 MB): {dt:.1f}s ({dt / 8:.1f}s per photo)")


async def test_import_nikon_shoot_second_event(env):
    ev = (await events.create_event(env["id"], env["owner"], "Summit July 2025", "other", 2025, 7))["event"]
    q = await gallery.query(env["id"], {"camera": "nikon"})
    assert q["count"] == 6 and q["date_guessed"] == 0
    job = await run_job_now((await gallery.start_import(env["id"], env["owner"], q["preview_token"], ev["id"]))["job_id"],
                            timeout=300)
    assert job["status"] == "done" and job["result"]["count"] == 6 and (job["result"]["year"], job["result"]["month"]) == (2025, 7)
    media = await db.fetch("SELECT width, height FROM media WHERE memory_id=$1::uuid", job["result"]["memory_id"])
    assert sum(1 for r in media if r["height"] > r["width"]) == 1            # the rotated one is portrait, not sideways
    # already-imported photos are not offered again
    assert (await gallery.query(env["id"], {"camera": "nikon"}))["count"] == 0


async def test_cleanup_gallery_blurry_list_keep_delete(env):
    # defocused copies of two real photos dropped into the (temp) gallery folder
    for name, src in (("soft_keep.jpg", "IMG_4925.jpg"), ("soft_delete.jpg", "121A1306.JPG")):
        im = ImageOps.exif_transpose(Image.open(env["dir"] / src))
        im.thumbnail((2000, 2000))
        im.filter(ImageFilter.GaussianBlur(0.008 * im.width)).save(env["dir"] / name, "JPEG", quality=90)
    res = await gallery.scan_folder(env["id"])
    assert res["new"] == 2
    app = FastAPI()
    app.include_router(cleanup_routes.router)
    sid = await auth.new_session(env["id"], env["owner"], "owner")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", cookies={auth.COOKIE: sid}) as c:
        lst = (await c.get("/api/cleanup/blurry")).json()
        assert {g["name"] for g in lst["gallery"]} == {"soft_keep.jpg", "soft_delete.jpg"} and lst["count"] == 2
        ids = {g["name"]: g["gallery_item_id"] for g in lst["gallery"]}
        assert (await c.post("/api/cleanup/blurry/keep", json={"gallery_item_ids": [ids["soft_keep.jpg"]]})).json()["kept_gallery"] == 1
        d = (await c.post("/api/cleanup/blurry/delete", json={"gallery_item_ids": [ids["soft_delete.jpg"]]})).json()
        assert d["deleted_gallery"] == 1 and d["gallery_files_removed"] == 1
        assert not (env["dir"] / "soft_delete.jpg").exists() and (env["dir"] / "soft_keep.jpg").exists()
        assert (REAL / "IMG_4925.jpg").exists() and not (REAL / "soft_delete.jpg").exists()   # real folder untouched
        await blur.rescore_family(env["id"])                      # rescan respects the keep
        assert (await c.get("/api/cleanup/blurry")).json()["count"] == 0


async def test_export_zip_contains_originals(env):
    path = await __import__("app.core.export", fromlist=["x"]).build_export_zip(env["id"])
    media = await db.fetch("SELECT md.storage_key, md.large_key, md.thumb_key FROM media md JOIN memories m ON m.id=md.memory_id "
                           "WHERE m.family_id=$1::uuid", env["id"])
    assert len(media) == 14
    with zipfile.ZipFile(path) as z:
        n = set(z.namelist())
        assert "memo.json" in n
        for r in media:
            assert f"media/{r['storage_key']}" in n and f"media/{r['thumb_key']}" in n
            assert z.read(f"media/{r['storage_key']}") == storage.get(r["storage_key"])
        # original = the real photo minus location, pixels bit-identical
        src = (env["dir"] / "DSC_1022.JPG").read_bytes()
        h = hashlib.sha256(src).hexdigest()
        row = await db.fetchrow("SELECT storage_key FROM media WHERE content_hash=$1 LIMIT 1", h)
        orig = z.read(f"media/{row['storage_key']}")
        assert np.array_equal(np.asarray(Image.open(io.BytesIO(orig))), np.asarray(Image.open(io.BytesIO(src))))


# ------------------------------------------------------------------------------------------ reel with Hindi + Kannada
HI_TITLE, HI_BODY = "दिवाली की याद", "हम सब दीये जलाते थे। क्षत्रिय, विद्यार्थी और प्रश्न।"
KN_TITLE, KN_BODY = "ಹಬ್ಬದ ನೆನಪು", "ನಮ್ಮ ಮನೆಯಲ್ಲಿ ಹಬ್ಬ ಸಂಭ್ರಮ. ಕ್ಷೇತ್ರ, ಪ್ರಶ್ನೆ."


def shaped_ink_width(img: Image.Image, box) -> int:
    a = np.asarray(img.crop(box).convert("L"), dtype=int)
    cols = np.where((a > 120).any(axis=0))[0]
    return int(cols.max() - cols.min()) if len(cols) else 0


async def test_reel_8_real_photos_hindi_and_kannada_cards(env, capsys, tmp_path):
    ev = env["event"]
    for title, body in ((HI_TITLE, HI_BODY), (KN_TITLE, KN_BODY)):
        await db.fetchval(
            "INSERT INTO memories(family_id, author_id, event_id, kind, title, text_original, event_year, event_month, status, "
            "date_confidence) VALUES ($1::uuid,$2::uuid,$3::uuid,'text',$4,$5,2026,5,'saved',1) RETURNING id",
            env["id"], env["owner"], ev["id"], title, body)
        await asyncio.sleep(0.05)
    rid = await db.fetchval("INSERT INTO reels(family_id, year, month, narrated, aspect) VALUES ($1::uuid,2026,5,false,'16:9') "
                            "RETURNING id", env["id"])
    work = Path(await asyncio.to_thread(__import__("tempfile").mkdtemp, prefix="plan_"))
    try:
        plan = await reels.build_plan(env["id"], 2026, 5, None, (1920, 1080), work)
        assert [s.kind for s in plan.slots] == ["card"] + ["photo"] * 8 + ["card", "card", "card"]
        st = reels.starts(plan.slots)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    t0 = time.perf_counter()
    res = await reels.render_reel(str(rid))
    dt = time.perf_counter() - t0
    row = await db.fetchrow("SELECT * FROM reels WHERE id=$1", rid)
    assert row["status"] == "ready", row["error"]
    out = storage.path(row["storage_key"])
    info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height", "-show_entries",
                           "format=duration", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout
    assert "h264,1920,1080" in info and float(info.split()[-1]) == pytest.approx(res["duration_s"], abs=0.6)
    folder = Path(OUT or tmp_path)
    folder.mkdir(parents=True, exist_ok=True)
    frames = {}
    for label, idx in (("hindi", 9), ("kannada", 10)):
        at = st[idx] + 2.5                                          # well after the 0.8s crossfade in
        png = folder / f"reel_card_{label}.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", str(out), "-frames:v", "1", str(png)],
                       check=True)
        frames[label] = Image.open(png).convert("RGB")
    # heading ink width must match the HarfBuzz-shaped width (an unshaped line is visibly wider/narrower)
    from PIL import ImageFont
    for label, title in (("hindi", HI_TITLE), ("kannada", KN_TITLE)):
        font = reels._font(title, int(1080 * 0.095), True)
        want = reels._shaped_width(title, font)
        im = frames[label]
        got = shaped_ink_width(im, (140, 190, 1500, 360))
        assert abs(got - want) / want < 0.12, (label, got, want)
    report(capsys, f"reel: 8 real photos + Hindi + Kannada text memory, 1080p, {res['duration_s']:.0f}s long, rendered in "
                   f"{dt:.0f}s; title-card frames: {folder / 'reel_card_hindi.png'} , {folder / 'reel_card_kannada.png'}")


# ------------------------------------------------------------------------------------------ telegram capture
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


_uid = [9_100_000_000 + int(time.time()) % 10**7]
_upd = [int(time.time())]


def _n(counter) -> int:
    counter[0] += 1
    return counter[0]


def message(user: int, **kw) -> dict:
    m = {"message_id": _n(_upd), "date": int(time.time()), "chat": {"id": user, "type": "private"},
         "from": {"id": user, "is_bot": False, "first_name": "Asha", "language_code": "en"}}
    m.update(kw)
    return {"update_id": _n(_upd), "message": m}


def callback(user: int, data: str) -> dict:
    return {"update_id": _n(_upd), "callback_query": {
        "id": "cb" + str(_n(_upd)), "from": {"id": user, "is_bot": False, "first_name": "Asha"}, "data": data,
        "message": {"message_id": 5, "chat": {"id": user, "type": "private"}}}}


async def run_capture_jobs() -> None:
    import app.tasks.capture, app.tasks.followups  # noqa: F401,E401
    for _ in range(3):
        rows = await db.fetch("SELECT id, type, payload FROM jobs WHERE status='queued' AND type IN "
                              "('capture','followup','followup_answer') ORDER BY id")
        if not rows:
            return
        for r in rows:
            await db.execute("UPDATE jobs SET status='running', attempts=attempts+1 WHERE id=$1", r["id"])
            await jobs.run_one({"id": r["id"], "type": r["type"], "payload": r["payload"], "attempts": 1, "max_attempts": 1})


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def tg():
    mp = pytest.MonkeyPatch()
    t = Tg()
    mp.setattr(send, "api", t.api)
    mp.setattr(send, "download_file", t.download)
    mp.setattr(send, "_username", "memo_test_bot")
    handlers._hits.clear()
    await fresh_pool()
    user = _n(_uid)
    await handlers.process_update(message(user, text="/start"))
    await handlers.process_update(message(user, text="Pytest real photos family"))
    await handlers.process_update(callback(user, "lg:en-IN"))
    t.user = user
    t.fid = str(await db.fetchval("SELECT family_id FROM members WHERE telegram_user_id=$1", user))
    t.owner = str(await db.fetchval("SELECT id FROM members WHERE telegram_user_id=$1", user))
    yield t
    await db.execute("DELETE FROM jobs WHERE payload->>'family_id'=$1 OR payload->>'memory_id' IN "
                     "(SELECT id::text FROM memories WHERE family_id=$1::uuid)", t.fid)
    await db.execute("DELETE FROM families WHERE id=$1::uuid", t.fid)
    storage.delete_prefix(t.fid)
    await db.execute("DELETE FROM tg_state WHERE telegram_user_id=$1", t.user)
    mp.undo()


def photo_msg(tg: Tg, user: int, path_or_bytes, tag: str, **kw) -> dict:
    data = path_or_bytes if isinstance(path_or_bytes, bytes) else Path(path_or_bytes).read_bytes()
    fid = f"real-{tag}"
    tg.files[fid] = data
    # Telegram sends several sizes, smallest first; the handler takes the last one
    return message(user, photo=[{"file_id": fid + "-s", "file_unique_id": "u" + tag + "s", "width": 90, "height": 60, "file_size": 2000},
                                {"file_id": fid, "file_unique_id": "u" + tag, "width": 1280, "height": 853, "file_size": len(data)}], **kw)


async def test_telegram_single_real_photo_capture(tg, capsys):
    p = REAL / "DSC_1007.JPG"                                  # Nikon, EXIF orientation 8 (portrait), naive EXIF clock
    await handlers.process_update(photo_msg(tg, tg.user, p, "single"))
    t0 = time.perf_counter()
    await run_capture_jobs()
    dt = time.perf_counter() - t0
    mem = await db.fetchrow("SELECT * FROM memories WHERE family_id=$1::uuid AND kind='photo'", tg.fid)
    assert mem and mem["status"] == "saved" and (mem["event_year"], mem["event_month"]) == (2025, 7)   # placed by EXIF date
    m = await db.fetchrow("SELECT * FROM media WHERE memory_id=$1", mem["id"])
    assert m["storage_key"] and m["large_key"] and m["thumb_key"] and m["is_blurry"] is False
    assert m["content_hash"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert m["height"] > m["width"]                              # upright portrait
    th = Image.open(io.BytesIO(storage.get(m["thumb_key"])))
    assert th.height == 512 and th.width < 512
    assert max(Image.open(io.BytesIO(storage.get(m["large_key"]))).size) == 1600
    assert not Image.open(io.BytesIO(storage.get(m["storage_key"]))).getexif().get_ifd(GPS_IFD)
    assert any("keeping this safe" in d["text"] for d in tg.sent(tg.user))
    report(capsys, f"telegram single real photo ({p.stat().st_size / 1e6:.1f} MB): capture job {dt:.1f}s, placed in "
                   f"{mem['event_year']}-{mem['event_month']:02d}")


async def test_telegram_album_of_three_real_photos(tg):
    gid = "real-album-" + str(_n(_upd))
    picks = ["120A8910.JPG", "IMG_4935.jpg", "WhatsApp Image 2026-04-07 at 19.11.26.jpeg"]   # DSLR, phone, no EXIF
    before = len(tg.sent(tg.user))
    for i, n in enumerate(picks):
        await handlers.process_update(photo_msg(tg, tg.user, REAL / n, f"alb{i}", media_group_id=gid))
    await handlers.process_update(photo_msg(tg, tg.user, REAL / picks[0], "alb0", media_group_id=gid))   # redelivery
    mems = await db.fetch("SELECT id, kind FROM memories WHERE family_id=$1::uuid AND kind='album'", tg.fid)
    assert len(mems) == 1
    assert await db.fetchval("SELECT count(*) FROM media WHERE memory_id=$1", mems[0]["id"]) == 3
    assert len([d for d in tg.sent(tg.user)[before:] if "photos" in d["text"]]) == 1       # one ack for the album
    await db.execute("UPDATE jobs SET run_at=now() WHERE type='capture' AND payload->>'memory_id'=$1", str(mems[0]["id"]))
    await run_capture_jobs()
    media = await db.fetch("SELECT * FROM media WHERE memory_id=$1 ORDER BY sort_order, created_at", mems[0]["id"])
    assert len(media) == 3 and all(r["storage_key"] and r["thumb_key"] and r["large_key"] for r in media)
    assert sorted(r["taken_at"] is not None for r in media) == [False, True, True]       # WhatsApp has no EXIF date
    assert all(not Image.open(io.BytesIO(storage.get(r["storage_key"]))).getexif().get_ifd(GPS_IFD) for r in media)
    st = await db.fetchval("SELECT status FROM memories WHERE id=$1", mems[0]["id"])
    assert st in ("saved", "attic")


async def test_telegram_blurry_photo_then_cleanup_delete(tg):
    im = ImageOps.exif_transpose(Image.open(REAL / "IMG_4946.jpg"))
    im.thumbnail((2000, 2000))
    buf = io.BytesIO()
    im.filter(ImageFilter.GaussianBlur(0.008 * im.width)).save(buf, "JPEG", quality=90)
    await handlers.process_update(photo_msg(tg, tg.user, buf.getvalue(), "blurry"))
    await run_capture_jobs()
    m = await db.fetchrow("SELECT md.* FROM media md JOIN memories mem ON mem.id=md.memory_id WHERE mem.family_id=$1::uuid "
                          "AND md.is_blurry", tg.fid)
    assert m and m["blur_score"] < images.BLUR_THRESHOLD
    app = FastAPI()
    app.include_router(cleanup_routes.router)
    sid = await auth.new_session(tg.fid, tg.owner, "owner")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", cookies={auth.COOKIE: sid}) as c:
        lst = (await c.get("/api/cleanup/blurry")).json()
        assert [p["media_id"] for p in lst["photos"]] == [str(m["id"])] and lst["photos"][0]["thumb_url"].startswith("/media/")
        d = (await c.post("/api/cleanup/blurry/delete", json={"media_ids": [str(m["id"])]})).json()
        assert d["deleted_media"] == 1 and len(d["memories_deleted"]) == 1
    assert not storage.exists(m["storage_key"]) and not storage.exists(m["thumb_key"])
