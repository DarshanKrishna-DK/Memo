from .. import jobs
from ..media import blur


@jobs.handler("cleanup_rescan")
async def cleanup_rescan(payload: dict) -> dict:
    return await blur.rescore_family(payload["family_id"])
