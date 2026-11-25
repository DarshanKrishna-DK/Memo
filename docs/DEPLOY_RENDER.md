# Deploying Memo on Render

Prepared, not deployed. Everything below is driven by `render.yaml`, `Dockerfile` and `docker-entrypoint.sh` at the repo root.

## What gets created (region singapore)

| Resource | Type / plan | Role | $/month |
|---|---|---|---|
| `memo` | Web service, Docker, `starter` (0.5c-512mb) | FastAPI + built React app + in-process job worker + Telegram webhook | 7.00 |
| `memo` disk | Persistent disk 10 GB at `/var/data` ($0.25/GB) | photos, voice notes, reels (`STORAGE_DIR`, `GALLERY_DIR`) | 2.50 |
| `memo-db` | Postgres `basic-256mb` (= `0.1c-256mb`), 5 GB storage ($0.30/GB) | Memo DB and the Flagsmith DB | 6.00 + 1.50 |
| `memo-flags` | Web service, image `flagsmith/flagsmith:2.295.2`, `starter` | Flagsmith dashboard + API | 7.00 |
| **Total** | | | **about 24** |

Prices from render.com/pricing (checked 2026-11-25). Free Postgres is not used (free databases expire). Notes:
- 512 MB is tight for ffmpeg reels and for Flagsmith (Django). If either is OOM-killed, move that service to `1c-2g` ($25 each).
- A service with a disk is a single instance and redeploys with a few seconds of downtime (no zero-downtime deploys).
- Skipping Flagsmith (delete the `memo-flags` block) saves $7.

## Steps

1. Push the repo to GitHub (the owner does this; `.env*`, `data/` and `gallery/` are git-ignored and docker-ignored). Build the image locally first if you like: `docker build -t memo .`
2. Render Dashboard > New > Blueprint > pick the repo. Render reads `render.yaml` and asks for every `sync: false` value (the secrets below). Leave unknown ones blank and fill them later under the service's Environment tab.
3. Wait for the first deploy of `memo` (health check `/api/health`). On boot the app applies the schema, starts the worker and, because `FLAGSMITH_DB_NAME=flagsmith`, runs `CREATE DATABASE flagsmith` on `memo-db` if it is missing. If the database user is not allowed to (log line "startup hook _ensure_flagsmith_db failed"), create it once from the memo-db page > Connect > PSQL: `CREATE DATABASE flagsmith;`
4. `memo-flags` starts once that database exists (redeploy it if it failed first). Then set its `FLAGSMITH_DOMAIN` to its host (for example `memo-flags.onrender.com`) and redeploy.
5. Flagsmith first admin: open `https://<memo-flags host>/signup`, create the admin account, create a project and an environment, copy the server-side environment key into `memo` as `FLAGSMITH_ENVIRONMENT_KEY` and set `FLAGSMITH_API_URL=https://<memo-flags host>/api/v1/`. Then lock sign-up: on `memo-flags` set `PREVENT_SIGNUP=true` and `ALLOW_REGISTRATION_WITHOUT_INVITE=false`. Optionally tighten `DJANGO_ALLOWED_HOSTS` to the host.
6. Seed the flags (see `docs/FLAGSMITH.md` once the Flagsmith work lands: flag names and defaults).
7. Webhooks (see next section), then open `https://<memo host>/`.

## Telegram: one consumer per bot token

Telegram delivers updates either to a webhook or to `getUpdates` long polling, never both. The owner's laptop bot (`python -m app.telegram.bot`, started by `start-memo.ps1`) long-polls the same token and calls `deleteWebhook` at start.
- Registering the production webhook breaks local polling; starting local polling removes the production webhook. Only one can run.
- Registration is opt-in. `render.yaml` ships `TELEGRAM_REGISTER_WEBHOOK=0`. At cutover: stop the local bot, set `TELEGRAM_REGISTER_WEBHOOK=1` (and keep `TELEGRAM_MODE=webhook`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_BOT_TOKEN` set) and redeploy; the app calls `setWebhook` with `secret_token`. Manual alternative: `curl -s "https://api.telegram.org/bot<TOKEN>/setWebhook" -d url=https://<memo host>/webhooks/telegram -d secret_token=<SECRET>`.
- Going back to local dev: stop (or delete the webhook for) production first: `curl -s "https://api.telegram.org/bot<TOKEN>/deleteWebhook"`, then run the local bot. Consider a second bot token for local development.

## Other webhook URLs

- Twilio voice / status callbacks: `https://<memo host>/twilio/...` (same paths as in dev, see `app/routes/twilio.py`); update the number's webhook in the Twilio console to the Render URL.
- Agora ConvoAI calls back to `PUBLIC_BASE_URL`, and Telegram sign-in links use `WEB_BASE_URL`. Both default to `RENDER_EXTERNAL_URL` (the `onrender.com` URL). Set `PUBLIC_BASE_URL` and `WEB_BASE_URL` explicitly only when you add a custom domain. Render Blueprints cannot interpolate one service's URL into another variable, hence the fallback.

## Environment variables (names only)

Set by the Blueprint: `DATABASE_URL` (from `memo-db`), `STORAGE_DIR`, `GALLERY_DIR`, `RUN_WORKER_IN_PROCESS`, `TELEGRAM_MODE`, `TELEGRAM_REGISTER_WEBHOOK`, `FLAGSMITH_DB_NAME`, `DEFAULT_TZ`, `LLM_PROVIDER`, `MEMO_ENV`, `APP_SECRET` (generated).

You enter (secrets, `sync: false`): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `SARVAM_API_KEY`, `GROQ_API_KEY`, `MURF_API_KEY`, `MURF_REGION`, `AGORA_APP_ID`, `AGORA_APP_CERTIFICATE`, `AGORA_CUSTOMER_ID`, `AGORA_CUSTOMER_SECRET`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_VOICE_FROM`, `FLAGSMITH_API_URL`, `FLAGSMITH_ENVIRONMENT_KEY`, `NUDGEBEE_API_KEY`, `NUDGEBEE_WEBHOOK_URL`, `NUDGEBEE_TOKEN`; on `memo-flags`: `FLAGSMITH_DOMAIN`.

Optional: `PUBLIC_BASE_URL`, `WEB_BASE_URL` (custom domain), `WEB_DIST_DIR`, `NUDGEBEE_BACKLOG_MIN`.

## How it fits together

- The image builds `web/dist` (node 20) and copies it next to the backend. `app/spa.py` serves it with an `index.html` fallback for client routes; `/api`, `/media`, `/m/{token}`, `/i/{token}`, `/webhooks`, `/twilio` stay with FastAPI and return a JSON 404 rather than the SPA when nothing matches.
- `RUN_WORKER_IN_PROCESS=1` runs the Postgres job worker inside the API process (reconnects after database blips), so no separate worker service is needed. To split later, unset it and add a worker service running `python -m app.worker` (it would need the same disk, which Render does not allow sharing, so keep one service while media lives on local disk).
- Fonts for reels: Noto Sans, Noto Sans Devanagari and Kannada (`fonts-noto-core`), DejaVu fallback; `ffmpeg` from Debian includes libass.
- The container starts as root only to `chown` the disk (Render mounts it root-owned) and then runs as the unprivileged `memo` user.
- Backups: check the current Render plan pages for disk snapshots and Postgres recovery windows; `/api/export` and `pg_dump` against the external connection string are the portable fallback.
