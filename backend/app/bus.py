"""Live events for the theater (SSE). Any process publishes with
`await bus.publish(family_id, {"type": "call_progress", ...})` -> Postgres NOTIFY on channel memo_live.
The API's GET /api/stream (app/routes/stream.py) LISTENs and fans out to that family's browsers.

Event types: call_progress {invite_id, status}, call_outcome {invite_id, status, contact_name, summary},
guest_message {invite_id, contact_name, text}, memory_saved {memory_id, year, month, title},
import_done {job_id, count, year, month, event_name}, reel_ready {reel_id, year, month, url},
playback_sync {year, month, index, playing} (host -> guests).
"""
from __future__ import annotations

from typing import Any

from . import db

CHANNEL = "memo_live"


async def publish(family_id: str, event: dict[str, Any]) -> None:
    await db.notify(CHANNEL, {"family_id": str(family_id), **event})
