"""Family export: one zip with memo.json (all rows that belong to the family) and every stored media file.

The zip is written to storage under "{family_id}/exports/" (so a signed URL can hand it to Telegram) and is
itself excluded from later exports.
"""
from __future__ import annotations

import asyncio
import json
import time
import zipfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from .. import config, db, storage

TABLES = {
    "family": "SELECT id, name, language, grandma_name, timezone, settings, created_at FROM families WHERE id=$1::uuid",
    "members": "SELECT id, nickname, role, language, voice_keep_default, quiet, joined_at FROM members "
               "WHERE family_id=$1::uuid ORDER BY joined_at",
    "events": "SELECT * FROM events WHERE family_id=$1::uuid ORDER BY year, month, created_at",
    "memories": "SELECT * FROM memories WHERE family_id=$1::uuid AND status <> 'deleted' "
                "ORDER BY event_year NULLS LAST, event_month NULLS LAST, event_day NULLS LAST, captured_at",
    "media": "SELECT md.* FROM media md JOIN memories m ON m.id=md.memory_id WHERE m.family_id=$1::uuid "
             "AND m.status <> 'deleted' ORDER BY md.memory_id, md.sort_order",
    "followups": "SELECT f.* FROM followups f JOIN memories m ON m.id=f.memory_id WHERE m.family_id=$1::uuid",
    "room_settings": "SELECT * FROM room_settings WHERE family_id=$1::uuid",
    "contacts": "SELECT id, name, relation, phone_e164, language, consent_to_calls, consent_at, do_not_call, "
                "timezone, created_at FROM contacts WHERE family_id=$1::uuid",
    "invites": "SELECT id, contact_id, event_id, year, month, role, expires_at, used_at, status, created_at "
               "FROM invites WHERE family_id=$1::uuid",
}


def _default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, (UUID, Decimal)):
        return str(o)
    if isinstance(o, (bytes, bytearray)):
        return None
    raise TypeError(type(o).__name__)


def _write_zip(target: Path, doc: dict, files: list[tuple[Path, str]]) -> None:
    tmp = target.with_suffix(".part")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        z.writestr("memo.json", json.dumps(doc, default=_default, ensure_ascii=False, indent=2))
        z.writestr("README.txt",
                   "Memo export\n\nmemo.json holds the family, members, events, memories and media rows.\n"
                   "media/ holds every stored file; each media row's storage_key / large_key / thumb_key\n"
                   "points to media/<key>.\n")
        for src, arc in files:
            if src.exists():
                # photos and audio are already compressed
                z.write(src, arc, compress_type=zipfile.ZIP_STORED)
    tmp.replace(target)


async def build_export_zip(family_id) -> Path:
    fid = str(family_id)
    doc: dict = {"format": "memo-export-1", "exported_at": datetime.now().astimezone().isoformat()}
    for name, q in TABLES.items():
        rows = [dict(r) for r in await db.fetch(q, fid)]
        doc[name] = rows[0] if name == "family" else rows
    if not doc.get("family"):
        raise LookupError("Family not found.")
    root = storage.path(fid)
    files: list[tuple[Path, str]] = []
    if root.is_dir():
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(config.STORAGE_DIR).as_posix()
            if p.is_file() and not rel.startswith(f"{fid}/exports/"):
                files.append((p, f"media/{rel}"))
    key = f"{fid}/exports/memo-export-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    target = storage.path(key)
    target.parent.mkdir(parents=True, exist_ok=True)
    for old in target.parent.glob("memo-export-*.zip"):     # keep only the newest export on disk
        old.unlink(missing_ok=True)
    await asyncio.to_thread(_write_zip, target, doc, files)
    return target
