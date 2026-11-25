import logging

from .. import jobs
from ..media import reels

log = logging.getLogger("memo.tasks.reels")


@jobs.handler("render_reel")
async def render_reel(payload: dict) -> dict:
    try:
        return await reels.render_reel(payload["reel_id"])
    except Exception as e:  # noqa: BLE001
        # render_reel already stored status='failed' + the error on the row; retrying a deterministic failure is noise
        log.warning("reel %s failed: %s", payload.get("reel_id"), e)
        return {"failed": str(e)[:500]}
