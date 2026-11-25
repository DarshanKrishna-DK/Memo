# Flagsmith (self-hosted)

Memo reads every switch through `await flags.get(key, family_id)` (`backend/app/flags.py`). Flagsmith is one layer
of that lookup, never a hard dependency:

```
flag_overrides row for the family  ->  global flag_overrides row  ->  Flagsmith  ->  flags.DEFAULTS
```

- **Local evaluation.** The official Python SDK (`flagsmith==6.7.0`) downloads the environment document in a
  background thread every 20 s and evaluates segments in memory. Reading a flag never calls the network; resolved
  values are cached 30 s, so a dashboard change shows up within about a minute.
- **Identity = family_id**, with traits read from Postgres (cached 30 s): `family_id`, `language`, `member_count`,
  `created_days_ago`, `has_phone_invites` (an invite was sent to a phone contact), `has_call_consent` (a contact
  consented to calls and is not do-not-call). Traits are not stored in Flagsmith (local evaluation).
- **Types** follow the type of the key's code default: booleans are plain flags (the enabled state is the value);
  numbers, strings and JSON objects are remote-config features (enabled + value; JSON stored as a string).
  A **disabled remote-config feature means "no opinion"** and the code default applies (it never sends an
  empty/zero value). A value that does not parse as the expected type is ignored the same way (logged).
- **Degrades to the old behaviour**: `FLAGSMITH_ENVIRONMENT_KEY` unset, a non-`ser.` key, or the server down at
  start-up -> the provider returns None and overrides/defaults apply. The SDK keeps polling, so it recovers on its
  own. The first reads after a process starts use defaults for about a second while the client loads.
- **Status**: `GET /api/ops/flags` now also returns `sources` (`override:family | override:global | flagsmith |
  default` per key) and `provider`; `GET /api/ops/flags/status` returns just the provider status
  (`provider`, `environment_loaded`, `last_refresh_at`, `last_error`, ...). Keys are never included. The Operator
  panel shows the source next to each flag. The web app does not use the Flagsmith JS SDK: it gets flags from the
  backend (`/api/museum`, `/api/ops/flags`).

## Run locally

```bash
# from D:/Memo. --env-file passes FLAGSMITH_DJANGO_SECRET_KEY into compose.
docker compose --env-file .env.local --profile flags up -d flagsmith
```

- Dashboard + API: <http://localhost:8001> (API schema: <http://localhost:8001/api/v1/docs/>). Sign in with
  `FLAGSMITH_ADMIN_EMAIL` / `FLAGSMITH_ADMIN_PASSWORD` from `.env.local`.
- It runs as one container (`migrate-and-serve`, 1 gunicorn worker x 2 threads, tasks in a thread), about 300 MB RAM,
  storing its data in a separate database `flagsmith` on the existing `db` Postgres (created idempotently by the
  one-shot `flagsmith-db-init` service). Sign-up is disabled (`PREVENT_SIGNUP`).
- Stop it: `docker compose --profile flags stop flagsmith`. The plain `docker compose up -d` still starts only `db`.

First-time admin (once per fresh `flagsmith` database), using Django's `createsuperuser`:

```bash
# FLAGSMITH_ADMIN_EMAIL / FLAGSMITH_ADMIN_PASSWORD / FLAGSMITH_DJANGO_SECRET_KEY are in .env.local (generate your own)
docker compose --env-file .env.local --profile flags exec -T -e DJANGO_SUPERUSER_PASSWORD="$FLAGSMITH_ADMIN_PASSWORD" \
  flagsmith python manage.py createsuperuser --noinput --email "$FLAGSMITH_ADMIN_EMAIL" \
  --first_name Memo --last_name Admin --sign_up_type NO_INVITE
```

## Seed

```bash
cd backend && .venv/Scripts/python scripts/flagsmith_seed.py            # --env Production to write that env's key
```

Idempotent. Logs in (admin email/password, or `FLAGSMITH_ADMIN_API_KEY`), creates organisation + project `Memo`,
environments `Development` and `Production`, one feature per key in `flags.DEFAULTS`, the segments below, an
organisation API key (saved as `FLAGSMITH_ADMIN_API_KEY`), and a server-side key `memo-backend`. It writes
`FLAGSMITH_ENVIRONMENT_KEY` and `FLAGSMITH_API_URL` into `.env.local`. Existing features are not touched, so values
changed in the dashboard survive a re-run; segment rules and the two overrides below are re-asserted.

| Segment | Rule | Override |
|---|---|---|
| `phone_pilot` | trait `family_id` IN `$FLAGSMITH_PHONE_PILOT_FAMILIES` (comma-separated uuids; empty = nobody) | `phone_allowlist` on |
| `hindi_or_kannada` | trait `language` IN `hi-IN,kn-IN` | `tts_voice_by_language` = `{"hi-IN":{"grandma":"neha"},"kn-IN":{"grandma":"neha"}}` (pins today's voice; change it in the dashboard to try another) |

- `phone_allowlist`: on for everyone in **Development**, off in **Production** except the `phone_pilot` segment.
- `followup_variant` is multivariate: control `a` 50 % / `b` 50 %, hashed per family (sticky).
- Restart the API / worker after the seed so they read the new key (they load `.env.local` at start).

## Self-host on Render

`render.yaml` defines `memo-flags` (Docker image `flagsmith/flagsmith:2.295.2`, same tag as compose) sharing the
`memo-db` Postgres instance through a separate `flagsmith` database; follow `docs/DEPLOY_RENDER.md` for the deploy
order. Env vars on `memo-flags`: `DATABASE_URL` (memo-db connection string with database `flagsmith`),
`DJANGO_SECRET_KEY` (generated), `DJANGO_ALLOWED_HOSTS` (its host), `FLAGSMITH_DOMAIN` (its host),
`GUNICORN_WORKERS=1`, `GUNICORN_THREADS=2`, `TASK_RUN_METHOD=SEPARATE_THREAD`, `ENVIRONMENT=production`, then
`PREVENT_SIGNUP=true` and `ALLOW_REGISTRATION_WITHOUT_INVITE=false` once the admin exists.
Then seed it from your machine:

```bash
cd backend && FLAGSMITH_ADMIN_EMAIL=... FLAGSMITH_ADMIN_PASSWORD=... .venv/Scripts/python scripts/flagsmith_seed.py \
  --url https://<memo-flags host>/api/v1/ --env Production --env-file ../.env.render-flags   # a gitignored scratch file
```

and copy `FLAGSMITH_ENVIRONMENT_KEY` (the `ser.` key) and `FLAGSMITH_API_URL` from that file into the `memo` service
env. On `memo`: only those two are needed.

## Env vars

| Var | Where | Purpose |
|---|---|---|
| `FLAGSMITH_ENVIRONMENT_KEY` | API / worker | server-side `ser.` key; unset = Flagsmith off |
| `FLAGSMITH_API_URL` | API / worker, seed | e.g. `http://localhost:8001/api/v1/` |
| `FLAGSMITH_DJANGO_SECRET_KEY` | compose (`--env-file .env.local`) | Django secret for the container |
| `FLAGSMITH_ADMIN_EMAIL`, `FLAGSMITH_ADMIN_PASSWORD` | seed, createsuperuser | first admin |
| `FLAGSMITH_ADMIN_API_KEY` | seed | organisation API key (written by the seed) |
| `FLAGSMITH_PHONE_PILOT_FAMILIES` | seed | family uuids for `phone_pilot` |
