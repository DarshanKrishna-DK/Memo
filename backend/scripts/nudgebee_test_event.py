r"""Send one `info` test event to NudgeBee, then resolve it. Run from backend/:

    .venv\Scripts\python scripts\nudgebee_test_event.py

Needs NUDGEBEE_WEBHOOK_URL and NUDGEBEE_TOKEN in D:\\Memo\\.env.local. Prints the HTTP status of each call
(200 = accepted; 400 "webhook validation failed" = wrong token; 404 = wrong path, must end /api/webhooks/event).
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.observability import nudgebee as nb  # noqa: E402


async def main() -> int:
    if not nb.configured():
        print("Set NUDGEBEE_WEBHOOK_URL and NUDGEBEE_TOKEN in D:\\Memo\\.env.local first.")
        return 2
    fp = nb.fingerprint("test_event", ("cli",))
    eid = f"test-{int(time.time())}"
    labels = {"service": "api", "env": nb.config.env("MEMO_ENV", "local") or "local", "test": "true"}
    common = dict(id=eid, fingerprint=fp, title="Memo test event (safe to ignore)", rule_name="test_event",
                  severity="info", description="Sent by backend/scripts/nudgebee_test_event.py", labels=labels,
                  starts_at=nb._now())
    for status in ("firing", "resolved"):
        ev = nb.build_event(status=status, ends_at=nb._now() if status == "resolved" else None, **common)
        code, body = await nb._post([ev])
        print(f"{status}: HTTP {code} {body[:200]}")
        if code != 200:
            return 1
        if status == "firing":
            await asyncio.sleep(2)
    print("OK. Check NudgeBee for a closed info event titled 'Memo test event'.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
