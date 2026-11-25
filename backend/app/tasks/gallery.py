"""Job: gallery_import {family_id, member_id, token, event_id} -> one album memory in the event's room.
Publishes import_done (and memory_saved) on the bus. Idempotent; see app/core/gallery.run_import."""
from __future__ import annotations

from .. import jobs
from ..core import gallery


@jobs.handler("gallery_import")
async def gallery_import(payload: dict) -> dict:
    return await gallery.run_import(payload)
