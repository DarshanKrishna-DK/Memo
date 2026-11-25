"""Family settings changes (used by the family route, the receptionist and the bot)."""
from __future__ import annotations

from .. import config, db
from . import common

BOOL_SETTINGS = {"sarcasm": "sarcasm_on", "sarcasm_on": "sarcasm_on", "keep_location": "keep_location",
                 "editors_edit_others": "editors_edit_others"}


def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.lower() in ("true", "on", "yes", "1"):
        return True
    if isinstance(v, str) and v.lower() in ("false", "off", "no", "0"):
        return False
    if isinstance(v, (int, float)):
        return bool(v)
    raise ValueError("Expected on or off.")


async def change_setting(family_id, key, value) -> dict:
    """keys: language, grandma_name, sarcasm, closed_with_care ({year, month, closed}), keep_location,
    editors_edit_others, name. Returns {"key","value","family":{...public + settings}}."""
    fid = str(family_id)
    fam = await common.family(fid)
    if key == "language":
        if value not in config.LANGUAGES:
            raise ValueError(f"Language must be one of {', '.join(config.LANGUAGES)}.")
        gname = fam["grandma_name"]
        if gname == config.GRANDMA_NAMES.get(fam["language"]):
            gname = config.GRANDMA_NAMES[value]          # keep the default name in step with the language
        await db.execute("UPDATE families SET language=$2, grandma_name=$3 WHERE id=$1::uuid", fid, value, gname)
    elif key == "grandma_name":
        v = (value or "").strip() if isinstance(value, str) else ""
        if not v or len(v) > 40:
            raise ValueError("Grandma's name should be 1 to 40 characters.")
        value = v
        await db.execute("UPDATE families SET grandma_name=$2 WHERE id=$1::uuid", fid, v)
    elif key == "name":
        v = (value or "").strip() if isinstance(value, str) else ""
        if not v or len(v) > 80:
            raise ValueError("The family name should be 1 to 80 characters.")
        value = v
        await db.execute("UPDATE families SET name=$2 WHERE id=$1::uuid", fid, v)
    elif key in BOOL_SETTINGS:
        b = _bool(value)
        value = b
        await db.execute("UPDATE families SET settings = settings || jsonb_build_object($2::text, $3::boolean) "
                         "WHERE id=$1::uuid", fid, BOOL_SETTINGS[key], b)
    elif key == "closed_with_care":
        if not isinstance(value, dict):
            raise ValueError("closed_with_care needs {year, month, closed}.")
        y, m = int(value.get("year", 0)), int(value.get("month", 0))
        if not (1900 <= y <= 2200 and 1 <= m <= 12):
            raise ValueError("That isn't a valid year and month.")
        mode = "closed_with_care" if _bool(value.get("closed", True)) else "auto"
        await db.execute(
            "INSERT INTO room_settings(family_id, year, month, mode) VALUES ($1::uuid,$2,$3,$4) "
            "ON CONFLICT (family_id, year, month) DO UPDATE SET mode=EXCLUDED.mode", fid, y, m, mode)
        value = {"year": y, "month": m, "mode": mode}
    else:
        raise ValueError(f"Unknown setting '{key}'.")
    fam = await common.family(fid)
    return {"key": key, "value": value, "family": family_view(fam)}


def family_view(fam: dict) -> dict:
    s = fam["settings"]
    return {**common.family_public(fam), "timezone": fam["timezone"], "settings": {
        "sarcasm_on": s.get("sarcasm_on", True) is not False,
        "keep_location": bool(s.get("keep_location", False)),
        "editors_edit_others": bool(s.get("editors_edit_others", False)),
        **{k: v for k, v in s.items() if k not in ("sarcasm_on", "keep_location", "editors_edit_others")},
    }}
