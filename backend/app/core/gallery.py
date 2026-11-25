"""Photo import by metadata only (PRD "Importing photos").

Sources: the configured GALLERY_DIR (dev; never read outside it) and files uploaded by the browser picker
(stored under storage "{fid}/gallery/<hash>.<ext>", source 'browser'). The index (gallery_items) holds the capture
date (EXIF, else the file date flagged 'file_date'), size, dimensions, camera, folder, content hash and blur score.
query() turns a structured filter into a confirmed-count preview token; start_import() turns the token into a job
that creates ONE album memory in the event (the event's month), photos ordered by capture time.
"""
from __future__ import annotations

import asyncio
import mimetypes
import secrets
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo

from .. import bus, config, db, flags, jobs, storage
from ..media import images
from . import common, dates

EXTS = {".jpg", ".jpeg", ".png", ".webp"}
PREVIEW_TTL = timedelta(minutes=30)
MAX_UPLOAD_BYTES = 40 * 1024 * 1024
TYPE_ALIASES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "image/jpeg": "image/jpeg", "png": "image/png",
                "image/png": "image/png", "webp": "image/webp", "image/webp": "image/webp"}


def _gallery_root() -> Path:
    return Path(config.GALLERY_DIR).resolve()


def _safe_gallery_path(rel: str) -> Path:
    root = _gallery_root()
    p = (root / rel).resolve()
    if root not in p.parents:
        raise PermissionError("That file is outside the gallery folder.")
    return p


def _localise(dt: datetime | None, tz: str) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo(tz))


async def _insert_item(fid: str, source: str, handle: str, info: dict, taken: datetime | None, taken_src: str | None,
                       size: int, folder: str, upload_key: str | None) -> bool:
    r = await db.fetchrow(
        "INSERT INTO gallery_items(family_id, source, path_or_handle, taken_at, taken_at_source, size_bytes, width, "
        "height, camera, folder, mime, content_hash, blur_score, is_blurry, upload_key) "
        "VALUES ($1::uuid,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15) "
        "ON CONFLICT (family_id, content_hash) DO NOTHING RETURNING id",
        fid, source, handle, taken, taken_src, size, info["width"], info["height"], info["camera"], folder,
        info["mime"], info["content_hash"], info["blur_score"], info["is_blurry"], upload_key)
    return r is not None


async def scan_folder(family_id) -> dict:
    fid = str(family_id)
    fam = await common.family(fid)
    tz = fam["timezone"]
    root = _gallery_root()
    known = {r["path_or_handle"]: r["size_bytes"] for r in await db.fetch(
        "SELECT path_or_handle, size_bytes FROM gallery_items WHERE family_id=$1::uuid AND source='folder'", fid)}
    scanned = new = dup = unreadable = 0
    seen: set[str] = set()
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() not in EXTS or not p.is_file():
            continue
        rp = p.resolve()
        if root not in rp.parents:                      # symlink pointing outside: never read it
            continue
        rel = rp.relative_to(root).as_posix()
        seen.add(rel)
        scanned += 1
        st = rp.stat()
        if known.get(rel) == st.st_size:
            continue
        data = await asyncio.to_thread(rp.read_bytes)
        try:
            info = await asyncio.to_thread(images.inspect, data)
        except Exception:  # noqa: BLE001 - not a readable image
            unreadable += 1
            continue
        if info["taken_at"]:
            taken, src = _localise(info["taken_at"], tz), "exif"
        else:
            taken, src = datetime.fromtimestamp(st.st_mtime, tz=ZoneInfo(tz)), "file_date"
        folder = PurePosixPath(rel).parent.as_posix()
        folder = "" if folder == "." else folder
        if await _insert_item(fid, "folder", rel, info, taken, src, st.st_size, folder, None):
            new += 1
        else:
            dup += 1
            # same photo, new location (renamed/moved): follow it if it was not imported yet
            await db.execute(
                "UPDATE gallery_items SET path_or_handle=$3, folder=$4, size_bytes=$5 WHERE family_id=$1::uuid "
                "AND content_hash=$2 AND source='folder' AND imported_memory_id IS NULL AND path_or_handle <> $3",
                fid, info["content_hash"], rel, folder, st.st_size)
    # files that left the folder (and were never imported) leave the index
    gone = [k for k in known if k not in seen]
    if gone:
        await db.execute("DELETE FROM gallery_items WHERE family_id=$1::uuid AND source='folder' "
                         "AND imported_memory_id IS NULL AND path_or_handle = ANY($2::text[])", fid, gone)
    return {"scanned": scanned, "new": new, "duplicates": dup, "unreadable": unreadable, "removed": len(gone),
            "source": "folder"}


async def index_uploads(family_id, files: list[tuple[str, bytes, dict]]) -> dict:
    """Browser picker: files = [(filename, bytes, meta)], meta may hold path, folder, last_modified (ms epoch)."""
    fid = str(family_id)
    fam = await common.family(fid)
    tz = fam["timezone"]
    scanned = new = dup = unreadable = 0
    for name, data, meta in files:
        scanned += 1
        if len(data) > MAX_UPLOAD_BYTES:
            unreadable += 1
            continue
        try:
            info = await asyncio.to_thread(images.inspect, data)
        except Exception:  # noqa: BLE001
            unreadable += 1
            continue
        if await db.fetchval("SELECT 1 FROM gallery_items WHERE family_id=$1::uuid AND content_hash=$2",
                             fid, info["content_hash"]):
            dup += 1
            continue
        ext = mimetypes.guess_extension(info["mime"]) or ".jpg"
        ext = ".jpg" if ext in (".jpe", ".jpeg") else ext
        key = storage.put(f"{fid}/gallery/{info['content_hash']}{ext}", data)
        if info["taken_at"]:
            taken, src = _localise(info["taken_at"], tz), "exif"
        elif meta.get("last_modified"):
            taken = datetime.fromtimestamp(float(meta["last_modified"]) / 1000.0, tz=ZoneInfo(tz))
            src = "file_date"
        else:
            taken, src = None, None
        path = str(meta.get("path") or name or "upload").replace("\\", "/").lstrip("/")[:500]
        folder = meta.get("folder")
        if folder is None:
            folder = PurePosixPath(path).parent.as_posix()
            folder = "" if folder == "." else folder
        if await _insert_item(fid, "browser", path, info, taken, src, len(data), str(folder)[:200], key):
            new += 1
        else:
            dup += 1
    return {"scanned": scanned, "new": new, "duplicates": dup, "unreadable": unreadable, "source": "browser"}


def _as_date(v) -> date:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError as e:
        raise ValueError(f"'{v}' isn't a date like 2026-11-23.") from e


def _item_view(r) -> dict:
    return {"id": str(r["id"]), "name": PurePosixPath(r["path_or_handle"]).name, "folder": r["folder"],
            "source": r["source"], "taken_at": r["taken_at"].isoformat() if r["taken_at"] else None,
            "taken_at_source": r["taken_at_source"], "size_bytes": r["size_bytes"], "width": r["width"],
            "height": r["height"], "camera": r["camera"], "is_blurry": r["is_blurry"],
            "thumb_url": storage.signed_url(r["upload_key"]) if r["upload_key"] else None}


async def query(family_id, filt: dict) -> dict:
    """filt keys: date_from, date_to, when (free words), type, min_size, max_size, min_width, min_height,
    orientation, camera, folder, all, latest_n. Nothing is imported; a preview token proves the count."""
    fid = str(family_id)
    fam = await common.family(fid)
    tz = ZoneInfo(fam["timezone"])
    filt = dict(filt or {})
    where, args = ["family_id=$1::uuid"], [fid]

    def add(cond: str, val) -> None:
        args.append(val)
        where.append(cond.replace("?", f"${len(args)}"))

    restricted = False
    if filt.get("when"):
        c = dates.resolve_when(str(filt["when"]), fam["timezone"])
        if not c:
            raise ValueError(f"I couldn't work out the date in '{filt['when']}'.")
        filt.setdefault("date_from", c[0]["start"])
        filt.setdefault("date_to", c[0]["end"])
    d_from = _as_date(filt["date_from"]) if filt.get("date_from") else None
    d_to = _as_date(filt["date_to"]) if filt.get("date_to") else None
    if d_from:
        add("taken_at >= ?", datetime.combine(d_from, time.min, tzinfo=tz))
        restricted = True
    if d_to:
        add("taken_at < ?", datetime.combine(d_to + timedelta(days=1), time.min, tzinfo=tz))
        restricted = True
    if filt.get("type"):
        t = TYPE_ALIASES.get(str(filt["type"]).lower().lstrip("."))
        if not t:
            raise ValueError("Type must be jpeg, png or webp.")
        add("mime = ?", t)
        restricted = True
    for key, cond in (("min_size", "size_bytes >= ?"), ("max_size", "size_bytes <= ?"),
                      ("min_width", "width >= ?"), ("min_height", "height >= ?"),
                      ("max_width", "width <= ?"), ("max_height", "height <= ?")):
        if filt.get(key) not in (None, ""):
            add(cond, int(filt[key]))
            restricted = True
    if filt.get("orientation"):
        o = str(filt["orientation"]).lower()
        where.append({"portrait": "height > width", "landscape": "width > height",
                      "square": "width = height"}.get(o, "true"))
        restricted = True
    if filt.get("camera"):
        add("camera ILIKE ?", f"%{filt['camera']}%")
        restricted = True
    if filt.get("folder"):
        add("folder ILIKE ?", f"%{filt['folder']}%")
        restricted = True
    latest_n = int(filt["latest_n"]) if filt.get("latest_n") not in (None, "", 0) else None
    if latest_n is not None and latest_n < 1:
        raise ValueError("latest_n must be at least 1.")
    if not (restricted or filt.get("all") or latest_n):
        raise ValueError("Say which photos: a date, a folder, a camera, 'all' or 'the latest N'.")
    rows = await db.fetch(
        f"SELECT * FROM gallery_items WHERE {' AND '.join(where)} ORDER BY taken_at DESC NULLS LAST, id", *args)
    fresh = [r for r in rows if r["imported_memory_id"] is None]
    already = len(rows) - len(fresh)
    if latest_n:
        fresh = fresh[:latest_n]
    limit = int(await flags.get("max_import_photos", fid) or 200)
    over = len(fresh) > limit
    chosen = fresh[:limit]                 # newest first: the newest that fit
    total = sum(int(r["size_bytes"] or 0) for r in chosen)
    token = None
    if chosen:
        token = secrets.token_urlsafe(24)
        await db.execute(
            "INSERT INTO gallery_previews(token, family_id, item_ids, total_bytes, expires_at) "
            "VALUES ($1,$2::uuid,$3::uuid[],$4,$5)", token, fid, [r["id"] for r in chosen], total,
            datetime.now(timezone.utc) + PREVIEW_TTL)
    n = len(chosen)
    return {
        "count": n, "matched": len(fresh) if not latest_n else min(len(fresh), latest_n),
        "total_bytes": total, "total_size": common.human_bytes(total), "preview_token": token,
        "over_limit": over, "limit": limit, "already_imported": already,
        "blurry": sum(1 for r in chosen if r["is_blurry"]),
        "date_guessed": sum(1 for r in chosen if r["taken_at_source"] != "exif"),
        "date_from": d_from.isoformat() if d_from else None, "date_to": d_to.isoformat() if d_to else None,
        "confirm_text": (f"{n} photo{'s' if n != 1 else ''}, {common.human_bytes(total)}"
                         + (f" (only the newest {limit}; the limit is {limit} per import)" if over else "")),
        "sample": [_item_view(r) for r in chosen[:12]],
    }


async def start_import(family_id, member_id, preview_token, event_id) -> dict:
    fid = str(family_id)
    if not preview_token:
        raise ValueError("Confirm the photo count first (no preview token).")
    if not event_id:
        raise ValueError("Pick the event the photos belong to.")
    async with db.acquire() as c:
        async with c.transaction():
            p = await c.fetchrow("SELECT * FROM gallery_previews WHERE token=$1 AND family_id=$2::uuid FOR UPDATE",
                                 preview_token, fid)
            if not p:
                raise LookupError("That photo selection wasn't found. Ask me to pick the photos again.")
            if p["job_id"]:
                return {"job_id": p["job_id"], "count": len(p["item_ids"]), "already_started": True,
                        "event_id": common.sid(p["event_id"])}
            if p["expires_at"] < datetime.now(timezone.utc):
                raise ValueError("That selection expired. Ask me to pick the photos again.")
            ev = await c.fetchrow("SELECT id, name, year, month FROM events WHERE id=$1::uuid AND family_id=$2::uuid",
                                  str(event_id), fid)
            if not ev:
                raise LookupError("That event isn't in this family's museum.")
            jid = await jobs.enqueue("gallery_import", {"family_id": fid, "member_id": common.sid(member_id),
                                                        "token": preview_token, "event_id": str(ev["id"])}, conn=c)
            await c.execute("UPDATE gallery_previews SET used_at=now(), job_id=$2, event_id=$3::uuid WHERE token=$1",
                            preview_token, jid, str(ev["id"]))
    await db.execute("INSERT INTO audit_events(family_id, member_id, type, data) VALUES ($1::uuid,$2::uuid,"
                     "'import_confirmed',$3::jsonb)", fid, common.sid(member_id),
                     {"job_id": jid, "count": len(p["item_ids"]), "event_id": str(ev["id"])})
    return {"job_id": jid, "count": len(p["item_ids"]), "already_started": False,
            "event": {"id": str(ev["id"]), "name": ev["name"], "year": ev["year"], "month": ev["month"]}}


async def _read_item(r) -> bytes:
    if r["source"] == "browser":
        if not r["upload_key"]:
            raise FileNotFoundError("upload missing")
        return await asyncio.to_thread(storage.get, r["upload_key"])
    return await asyncio.to_thread(_safe_gallery_path(r["path_or_handle"]).read_bytes)


async def run_import(payload: dict) -> dict:
    """The job body (tasks/gallery.py). Safe to re-run: the album is keyed by the preview token and photos by
    content hash, so a worker killed mid-job resumes without duplicates."""
    fid, token = payload["family_id"], payload["token"]
    p = await db.fetchrow("SELECT * FROM gallery_previews WHERE token=$1 AND family_id=$2::uuid", token, fid)
    if not p:
        raise LookupError("preview token not found")
    ev = await db.fetchrow("SELECT * FROM events WHERE id=$1::uuid AND family_id=$2::uuid", payload["event_id"], fid)
    if not ev:
        raise LookupError("event not found")
    fam = await common.family(fid)
    keep_location = bool(fam["settings"].get("keep_location", False))
    skip_blurry = bool(await flags.get("auto_skip_blurry", fid))
    member = payload.get("member_id")
    mem = await db.fetchrow(
        "INSERT INTO memories(family_id, event_id, author_id, teller_id, kind, title, language, event_year, "
        "event_month, date_confidence, festival, status, source_update_id) "
        "VALUES ($1::uuid,$2::uuid,$3::uuid,$3::uuid,'album',$4,$5,$6,$7,1.0,$8,'processing',$9) "
        "ON CONFLICT (source_update_id) DO UPDATE SET updated_at=now() RETURNING id, status",
        fid, str(ev["id"]), member, ev["name"], fam["language"], ev["year"], ev["month"],
        ev["name"] if ev["kind"] == "festival" else None, f"gallery:{token}")
    mid = str(mem["id"])
    items = await db.fetch("SELECT * FROM gallery_items WHERE family_id=$1::uuid AND id = ANY($2::uuid[]) "
                           "ORDER BY taken_at ASC NULLS LAST, path_or_handle", fid, p["item_ids"])
    done = {r["content_hash"] for r in await db.fetch("SELECT content_hash FROM media WHERE memory_id=$1::uuid", mid)}
    skipped_blurry = skipped_dup = failed = 0
    for i, it in enumerate(items):
        h = it["content_hash"]
        if h in done:
            continue
        if it["imported_memory_id"] and str(it["imported_memory_id"]) != mid:
            skipped_dup += 1
            continue
        if await db.fetchval("SELECT 1 FROM media md JOIN memories m ON m.id=md.memory_id WHERE m.family_id=$1::uuid "
                             "AND m.status IN ('saved','processing','attic') AND md.content_hash=$2 AND m.id <> $3::uuid "
                             "LIMIT 1", fid, h, mid):
            skipped_dup += 1
            continue
        if skip_blurry and it["is_blurry"]:
            skipped_blurry += 1
            continue
        try:
            data = await _read_item(it)
            info = await asyncio.to_thread(images.process_photo, data, keep_location)
        except Exception:  # noqa: BLE001 - missing or unreadable file: count it, keep going
            failed += 1
            continue
        ext = ".jpg" if info["mime"] == "image/jpeg" else (mimetypes.guess_extension(info["mime"]) or ".jpg")
        okey = storage.put(storage.new_key(fid, "photos", ext), info["original"])
        lkey = storage.put(storage.new_key(fid, "photos", ".jpg"), info["large"])
        tkey = storage.put(storage.new_key(fid, "photos", ".jpg"), info["thumb"])
        taken = it["taken_at"] or _localise(info["taken_at"], fam["timezone"])
        await db.execute(
            "INSERT INTO media(memory_id, type, storage_key, large_key, thumb_key, mime, width, height, taken_at, "
            "sort_order, blur_score, is_blurry, content_hash) VALUES ($1::uuid,'photo',$2,$3,$4,$5,$6,$7,$8,$9,$10,"
            "$11,$12)", mid, okey, lkey, tkey, info["mime"], info["width"], info["height"], taken, i,
            info["blur_score"], info["is_blurry"], h)
        await db.execute("UPDATE gallery_items SET imported_memory_id=$2::uuid WHERE id=$1", it["id"], mid)
        done.add(h)
    await db.execute(
        "UPDATE media SET sort_order=s.rn FROM (SELECT id, row_number() OVER (ORDER BY taken_at NULLS LAST, "
        "created_at) - 1 AS rn FROM media WHERE memory_id=$1::uuid) s WHERE media.id=s.id", mid)
    count = int(await db.fetchval("SELECT count(*) FROM media WHERE memory_id=$1::uuid", mid))
    if count == 0:
        await db.execute("DELETE FROM memories WHERE id=$1::uuid", mid)
        mid_out = None
    else:
        await db.execute("UPDATE memories SET status='saved', updated_at=now() WHERE id=$1::uuid", mid)
        mid_out = mid
    result = {"memory_id": mid_out, "count": count, "skipped_blurry": skipped_blurry,
              "skipped_duplicates": skipped_dup, "failed": failed, "event_id": str(ev["id"]),
              "event_name": ev["name"], "year": ev["year"], "month": ev["month"]}
    await bus.publish(fid, {"type": "import_done", "job_id": p["job_id"], **result})
    if mid_out:
        await bus.publish(fid, {"type": "memory_saved", "memory_id": mid_out, "year": ev["year"],
                                "month": ev["month"], "title": ev["name"]})
    return result
