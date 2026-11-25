# NudgeBee integration

NudgeBee is an agentic ops / AI-SRE platform. Memo sends it its own incidents through NudgeBee's **Generic Event Webhook**,
so NudgeBee can group, dedupe and run root-cause analysis on them. Spec: https://docs.nudgebee.com/docs/integrations/Webhooks/event_webhook/

## Why not self-host NudgeBee?
Self-hosting NudgeBee needs Kubernetes (a Helm umbrella chart). Memo runs on Render without a cluster, so the SaaS
(app.nudgebee.com) plus the webhook is the right fit. Nothing is deployed alongside Memo.

## What is sent
One `firing` event per problem (re-sent at most every 5 min while it stays open), and a `resolved` event with the same
`id` + `fingerprint` + `labels` when it recovers. Events are batched (2 s window) and posted with a 3 s timeout in the
background; a failure to reach NudgeBee is swallowed and never affects a request.

| rule_name | When it fires | Severity | Resolves when |
|---|---|---|---|
| `job_failed` | job kind failed 3+ times (low) or exhausted retries / dead (high) | low/high | the same job kind succeeds |
| `api_5xx` | unhandled exception or 5xx on a route (route template, e.g. `/api/memories/{id}`) | high | that route returns a non-5xx |
| `provider_degraded` | 5+ errors (network, 5xx, 429) in 5 min from Sarvam, Groq, Murf, Twilio, Telegram or Agora | high | 3 successes in a row |
| `db_unreachable` | worker watchdog (every 60 s) cannot run `SELECT 1` | critical | DB answers again |
| `queue_backlog` | oldest runnable job has waited > `NUDGEBEE_BACKLOG_MIN` (10) min | high | queue drains |

Each event has `subject` = `memo-api` / `memo-worker` (type `service`), `source_tool` = `memo`, and labels from this allow-list only:
`service` (api|worker), `env` (`MEMO_ENV`, default `local`), `family_id` (opaque UUID, job events only), `kind`, `provider`,
`route`, `method`, `error_type` (exception class name), `status_code`, `check`.

**Never sent:** names, phone numbers, emails, memory text, transcripts, exception messages, raw URLs. Descriptions contain
only the job kind / route template / exception class; digit runs of 6+ and email-like strings are redacted as a backstop.

State (what is open, dedupe windows) is in memory per process, so a restart forgets open incidents (they just re-fire).

## Setup
1. In app.nudgebee.com: **Integrations -> Webhooks -> Event Webhook**, create the integration and copy its token
   (shown once). The Event Webhook page gives the exact URL; also see https://docs.nudgebee.com/docs/features/api-tokens/
   (avatar menu -> API Tokens -> Create Token, if your account uses account-level tokens instead).
2. Put in `D:\Memo\.env.local` (and the Render env vars):
   ```
   NUDGEBEE_WEBHOOK_URL=https://app.nudgebee.com/api/webhooks/event   # path must be exactly /api/webhooks/event
   NUDGEBEE_TOKEN=<token>
   MEMO_ENV=local                                                      # or production
   ```
3. Verify once: `cd backend && .venv\Scripts\python scripts\nudgebee_test_event.py` sends an `info` event and resolves it.
   200 = accepted; 400 "webhook validation failed" = bad token; 404 = wrong path.
4. Restart the API and worker. Switch it off any time with flag `nudgebee_alerts` = false (ops flags endpoint) or by unsetting the env vars.

## Credits
The "$1k AI credits" is not confirmed in public NudgeBee material. Check your NudgeBee account (billing / plan) or ask
NudgeBee directly; this integration does not depend on it.
