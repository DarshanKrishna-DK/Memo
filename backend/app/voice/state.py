"""Conversation state per session and character, in Postgres (`voice_state`), so a pending confirmation
("Add them to Diwali 2026?") survives an API restart and is shared by the typed, browser-voice and Agora paths.
"""
from __future__ import annotations

from typing import Any, Optional

from .. import db

TTL_MIN = 120


def key_for(session_id: str, character: str) -> str:
    return f"web:{session_id}:{character}"


async def load(key: str) -> dict[str, Any]:
    row = await db.fetchrow(
        f"SELECT state, language FROM voice_state WHERE key=$1 AND updated_at > now() - interval '{TTL_MIN} minutes'",
        key)
    if not row:
        return {}
    st = dict(row["state"] or {})
    if row["language"]:
        st.setdefault("language", row["language"])
    return st


async def save(key: str, family_id: str, member_id: Optional[str], character: str, state: dict[str, Any]) -> None:
    await db.execute(
        "INSERT INTO voice_state(key, family_id, member_id, character, language, state, updated_at) "
        "VALUES ($1,$2,$3,$4,$5,$6::jsonb, now()) ON CONFLICT (key) DO UPDATE SET state=EXCLUDED.state, "
        "language=EXCLUDED.language, member_id=EXCLUDED.member_id, updated_at=now()",
        key, family_id, member_id, character, state.get("language"), state)


async def raw(key: str) -> Optional[dict[str, Any]]:
    row = await db.fetchrow("SELECT * FROM voice_state WHERE key=$1", key)
    return dict(row) if row else None


async def family_language(family_id: str, member_id: Optional[str] = None) -> str:
    if member_id:
        v = await db.fetchval("SELECT language FROM members WHERE id=$1", member_id)
        if v:
            return v
    return await db.fetchval("SELECT language FROM families WHERE id=$1", family_id) or "en-IN"


async def set_member_language(member_id: Optional[str], language: str) -> None:
    if member_id:
        await db.execute("UPDATE members SET language=$2 WHERE id=$1", member_id, language)
