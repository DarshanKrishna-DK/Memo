# Memo MVP build contract

Every agent reads this first, plus `docs/Memo — Product Requirements Document.md` (the PRD). The PRD is the spec,
with these owner overrides: **generated video reels and blurry-photo detection/deletion ARE in the MVP** (the PRD lists
them as non-goals; the owner asked for them). **Flags go through `app/flags.py`** (DB overrides -> self-hosted Flagsmith -> defaults;
see the Flagsmith section below and `docs/FLAGSMITH.md`); NudgeBee is wired via the ops endpoints.

**No mocks, no dummy data, no fake responses.** Everything reads and writes Postgres and calls the real services
(Sarvam, Groq fallback, Murf, Agora, Twilio, Telegram). If a call fails, surface an honest error; never fabricate.

## Layout and run

```
D:/Memo
  .env.local                 secrets (SARVAM_API_KEY, GROQ_API_KEY, MURF_API_KEY, AGORA_*, TWILIO_*, TELEGRAM_BOT_TOKEN ...)
  docker-compose.yml         Postgres 16 on localhost:5433 (user/pass/db = memo) -- already running
  backend/                   FastAPI, Python 3.12, venv at backend/.venv  (run: .venv/Scripts/python ...)
    app/config.py db.py storage.py flags.py jobs.py auth.py bus.py main.py worker.py schema.sql   (FOUNDATION, done)
    app/ai/llm.py            chat() with Sarvam -> Groq fallback (done, ported from MedSim)
  web/                       React 18 + TS + Vite + R3F. `npm run dev` on :5173, proxies /api /media /m /i /webhooks /twilio to :8000
  data/storage               object storage root (signed URLs only)
  data/gallery               dev gallery folder (PRD "Gallery folder" source)
```

- API: `cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000 --reload`
- Worker: `cd backend && .venv/Scripts/python -m app.worker`
- Telegram bot (dev, long polling): `cd backend && .venv/Scripts/python -m app.telegram.bot`
- Schema changes: edit `backend/app/schema.sql` only with additive, idempotent statements
  (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...`) appended at the end, in a section headed with your agent name.
- New pip deps: append to `backend/requirements.txt` and install into the venv. New npm deps: `npm i` in web/.
- Routers: create `backend/app/routes/<name>.py` exposing `router = APIRouter()`; main.py includes it automatically.
- Job handlers: create `backend/app/tasks/<name>.py` with `@jobs.handler("type")`; the worker imports it automatically.
- Live events: `await bus.publish(family_id, {...})`; GET /api/stream fans them out (see app/bus.py for event types).
- Flags: `await flags.get("phone_calls_enabled", family_id)`. Do not hardcode switch values.
- Auth: `s: Session = Depends(current_session)`; family always from `s.family_id`. Writes need
  `Depends(require_role("owner","editor"))`. Guests (`s.is_guest`) may read only their invite room.
- Media: store with `storage.put(storage.new_key(fid, "photos", ".jpg"), bytes)`; return `storage.signed_url(key)`.
- MedSim (reference code to port, don't import): `D:/Med-Sim/backend/*.py`, `D:/Med-Sim/src/**`.

## Module ownership (only edit files you own; read anything)

| Agent | Owns |
|---|---|
| core-api | `app/core/*` (services below), `app/media/images.py`, routes `signin.py media.py museum.py events.py memories.py rooms.py route.py showcase.py gallery.py stream.py ops.py family.py export.py`, tasks `gallery.py` `media.py` |
| capture-telegram | `app/telegram/*`, `app/ai/stt.py`, `app/ai/tagger.py`, tasks `capture.py followups.py`, route `telegram_webhook.py` |
| voice-ai | `app/ai/tts.py`, `app/ai/facts.py`, `app/voice/*`, routes `grandma.py reception.py voice.py tts.py guide.py` |
| phone-invites | `app/phone/*`, routes `contacts.py invites.py twilio.py`, tasks `calls.py` |
| media-tools | `app/media/reels.py`, `app/media/blur.py`, routes `reels.py cleanup.py`, tasks `reels.py cleanup.py` |
| web-3d | `web/src/world/**` |
| web-app | everything else in `web/src/**` and `web/public/**` |

## Shared service signatures (implement exactly; others call them)

core-api, `app/core/`:
```python
# dates.py
def resolve_when(expr: str, tz: str = "Asia/Kolkata", today: date | None = None) -> list[dict]
    # -> candidates [{"year":2026,"month":11,"day":23|None,"start":date,"end":date,"label":"23 November 2026"}]; [] if none
# museum.py
def floor_level(first_year: int, year: int) -> int            # first memory year = 0 (ground, beside lobby)
async def room_state(family_id, year, month) -> dict            # {"state","memory_count","board_text"}
def board_text(family_id, year, month, state, grandma_name, sarcasm_on) -> str | None   # deterministic per family/year/month
# events.py
async def create_event(family_id, member_id, name, kind, year, month) -> dict   # {"event","level","room":{year,month},"room_state"}
async def find_events(family_id, name: str | None, year: int | None = None) -> list[dict]
# routing.py
async def plan_route(family_id, year, month, event_id=None) -> dict              # MuseumRoute in web/src/contract.ts
async def resolve_place(family_id, text: str) -> dict   # {"candidates":[{year,month,event_id,label}], "question": str|None}
# gallery.py
async def scan_folder(family_id) -> dict                                         # {"scanned","new"}
async def query(family_id, filt: dict) -> dict   # filt keys: date_from,date_to,type,min_size,max_size,camera,folder,all,latest_n
                                                 # -> {"count","total_bytes","preview_token","over_limit","limit","sample":[...]}
async def start_import(family_id, member_id, preview_token, event_id) -> dict    # {"job_id","count"}
# memories.py
async def room_memories(family_id, year, month, event_id=None) -> list[dict]     # Exhibit dicts, saved only, date order
async def scope_memories(family_id, scope: dict) -> list[dict]                   # scope {"year","month"} | {"year"} | {}
async def move_memory(family_id, memory_id, year, month, day=None) -> None       # wrong-date correction; publishes memory_saved
# showcase.py
async def build_showcase(family_id, year, month, event_id=None) -> list[dict]    # ShowcaseItem dicts
# settings.py
async def change_setting(family_id, key, value) -> dict   # language, grandma_name, sarcasm, closed_with_care(year,month), keep_location
# export.py
async def build_export_zip(family_id) -> Path
```
core-api `app/media/images.py`:
```python
def process_photo(data: bytes, keep_location: bool=False) -> dict
    # -> {"original": bytes (EXIF GPS stripped unless keep_location), "large": jpeg bytes 1600px, "thumb": jpeg 512px,
    #     "width","height","taken_at": datetime|None,"camera": str|None,"content_hash": sha256 hex,"blur_score": float}
def blur_score(img: PIL.Image) -> float     # variance of Laplacian on 512px grayscale; is_blurry = score < BLUR_THRESHOLD (100)
```
capture-telegram:
```python
# app/ai/stt.py
async def transcribe(audio: bytes, mime: str, language: str | None = None) -> dict  # {"text","language","duration_s"} (ffmpeg->wav)
# app/telegram/send.py
async def send_message(chat_id: int, text: str, buttons: list[list[dict]] | None = None) -> dict  # buttons: [{"text","data"}|{"text","url"}]
async def send_document(chat_id: int, path: Path, caption: str = "") -> None
async def send_video(chat_id: int, path: Path, caption: str = "") -> None
async def ask_family_followup(family_id, question: str, memory_id: str | None, source: str = "grandma_gap") -> None
```
voice-ai:
```python
# app/ai/tts.py
async def synthesize(text: str, language: str, voice: str | None = None, fmt: str = "mp3") -> dict
    # -> {"storage_key","url","duration_s"} (cached by hash of text+lang+voice)
# app/voice/grandma.py
async def tour(family_id, year, month, event_id=None, language=None) -> dict      # Speech in contract.ts
async def talk(family_id, question: str, scope: dict, language=None) -> dict      # Speech + {"transcript", "source": "family|general|none"}
```

## Product decisions already taken (don't re-litigate)
- Languages: en-IN, hi-IN, kn-IN. Grandma names default Grandma / Dadi / Ajji.
- Floors: first memory year is level 0 beside the lobby; each later year +1. Floors exist from first year to current year.
  With no memories yet, the current year is level 0.
- Room states: open / locked / not_yet / current_empty / closed (closed_with_care). Board text from server, deterministic.
- Attic: memories with status 'attic' (date unknown). Shown in the lobby.
- Sign-in: bot `/museum` -> `auth.create_signin_link()` -> `GET /m/{token}` sets cookie `memo_session`, redirects to WEB_BASE_URL.
- Guest invite link: `GET /i/{token}` -> viewer session scoped to one room, redirects to `WEB_BASE_URL/?room=YYYY-MM`.
- Characters in the 3D museum: the player (man in shirt + trousers, or woman in saree, chosen on the landing page),
  the receptionist robot, the guide robot, Grandma (saree). Nobody else. GTA-style low-poly look as in MedSim.
- Design language: MedSim's "night ward" pixel system (web/src/styles/tokens.css, live at https://medsim-band.onrender.com/),
  adapted to Memo (warm museum accents allowed). Agent thinking states use the `thinking-orbs` npm package.

## phone-invites: endpoints
Service `app/phone/invites.py`: `create_invite(family_id, host_member_id, contact_id, year, month, event_id=None) -> {"invite","link","confirm_text","call_refusal"}`,
`find_contacts(family_id, name_or_relation)`, `place_call(family_id, invite_id)` (raises `CallRefused(code, message, status)`; codes: kill_switch, not_allowlisted,
do_not_call, no_consent, quiet_hours, hourly_limit, daily_cap, invite_expired, no_public_url, twilio_not_configured, twilio_error, not_found).
Family settings (families.settings jsonb) `call_quiet_hours` / `call_hourly_limit` (default true) switch those two rules off.
- `GET/POST /api/contacts`, `PATCH/DELETE /api/contacts/{id}` (owner writes; body: name, phone (typed, E.164), relation, language, consent_to_calls, timezone, telegram_user_id; do_not_call=false needs consent_to_calls=true in the same PATCH)
- `POST /api/invites {contact_id, year, month, event_id?}` -> 201 {invite, link, confirm_text, call_refusal|null}; `GET /api/invites` -> {invites:[{..., link (while open), call:{status,summary,message,...}}]}
- `POST /api/invites/{id}/call` (only after the host's yes) -> 200 {placed:true, call_session_id} or 409/503 {placed:false, reason, message}
- `GET /i/{token}` guest join: single use, 24 h, viewer session cookie `memo_session`, 302 to WEB_BASE_URL/?room=YYYY-MM; 410 if used/expired; link-preview bots do not consume it
- `POST /api/sync {year,month,index,playing}` (owner/editor) -> bus `playback_sync`
- Twilio (signature-checked against PUBLIC_BASE_URL): `/twilio/voice/{cs_id}/twiml|turn|status`; `POST /webhooks/voice-agent` (header `X-Memo-Signature: sha256=HMAC-SHA256(raw body, VOICE_AGENT_WEBHOOK_SECRET or APP_SECRET)`, body {call_session_id|provider_call_id, outcome, summary, message?})
- Bus events: call_progress {invite_id,status[,contact_name]} (status also 'joined' when the guest opens the link), call_outcome {invite_id,status,contact_name,summary[,message,delivery('telegram'|'sms'|'host_must_share'),link when host_must_share]}, guest_message {invite_id,contact_name,text}
- Jobs: `calls_sweep` (every 5 min, >15 min without outcome -> failed), `calls_purge` (30-day delete); scheduled by a startup hook in routes/invites.py (needs the API to boot once)
- Tests: `cd backend && .venv/Scripts/python -m pytest tests/test_phone_*.py --asyncio-mode=auto` (needs pytest + pytest-asyncio, added to requirements.txt)

## media-tools: endpoints

Blur (`app/media/blur.py`): `score_image(path|bytes|PIL) -> float` (Laplacian variance, 512px gray; same metric as
`images.blur_score`), `analyze(...) -> {"score","hf_ratio"}`, `is_blurry(score, hf_ratio=None)` (threshold env
`BLUR_THRESHOLD`, default 100), `await rescore_family(family_id)`. core-api: `images.blur_score` may simply
`from .blur import _gray, _laplacian_var` or keep its own; either gives the same numbers. Schema additions: `reels.aspect`,
`reels.requested_by`, `media.blur_kept`, `gallery_items.blur_kept` (user "keep" override that rescans respect).
Auto-skip of blurry photos in reels follows flag `auto_skip_blurry`.

Cleanup (owner/editor; editor sees/deletes only photos in memories they authored; gallery items are owner-only):
- `GET /api/cleanup/blurry` -> `{threshold, count, photos:[{media_id, memory_id, memory_title, room:{year,month}|null, attic, score, taken_at, thumb_url}], gallery:[{gallery_item_id, name, folder, score, taken_at, thumb_url}]}`
- `POST /api/cleanup/blurry/delete` `{media_ids:[], gallery_item_ids:[]}` -> `{deleted_media, deleted_gallery, gallery_files_removed, memories_deleted:[ids], not_allowed_or_missing:[ids]}`.
  Removes storage objects + rows; a photo/album memory left with no photos gets status 'deleted'. Folder files are removed only if inside GALLERY_DIR.
- `POST /api/cleanup/blurry/keep` same body -> `{kept_media, kept_gallery, not_allowed_or_missing}` (is_blurry=false, blur_kept=true)
- `POST /api/cleanup/rescan` -> 202 `{job_id}` (job `cleanup_rescan` {family_id}; result `{media,gallery,flagged,unreadable}`)

Reels (flag `video_reels`; reads allowed for any session, guests only their invite room; writes owner/editor):
- `POST /api/reels` `{year, month, event_id?, narrated=false, aspect:"16:9"|"9:16"}` -> 202 reel; 400 if the room has no saved memories; returns the existing reel if an identical one is queued/rendering
- `GET /api/reels?year=&month=` -> `{reels:[Reel]}`; `GET /api/reels/{id}` -> Reel; `DELETE /api/reels/{id}` -> `{ok}` (409 while rendering)
- `Reel = {id, year, month, event_id, status:"queued|rendering|ready|failed", narrated, aspect, duration_s, error, url (signed, only when ready), created_at, updated_at}`
- Job `render_reel` {reel_id} publishes bus `reel_ready {reel_id, year, month, url}`. If narration was requested but
  `app.voice.grandma.tour` failed, the reel is still rendered un-narrated, `narrated=false`, and `error` says "narration skipped: ...".
- Python: `app.media.reels.render_reel(reel_id)`, `send_reel_to_telegram(reel_id, chat_id)` (uses `app.telegram.send.send_video`).
- Reels read memories + media directly (same order as showcase) instead of `build_showcase`, because showcase gives short-lived signed URLs, not storage keys.

## core-api: implemented endpoints

All JSON. Auth = cookie `memo_session` (or header `x-memo-session`). Errors: `{"detail": "<human sentence>"}` with
400 bad input, 401 not signed in, 403 role/guest, 404 not found, 410 used/expired sign-in link.
Types `MuseumSummary`, `Room`, `Exhibit`, `ShowcaseItem`, `MuseumRoute` are as in `web/src/contract.ts`; extra
fields listed here are additive. All media URLs are relative signed `/media/...` URLs valid 15 min (refetch after).

**Sign-in**
- `GET /m/{token}` → 303 to `WEB_BASE_URL/` + cookie (httponly, samesite=lax, 30 days). Reused/expired → 410 HTML page.
- `GET /api/me` → `{family_id, member_id, nickname, role, is_guest, invite_room: {year,month}|null}`
- `POST /api/logout` → 204, cookie cleared.
- Dev only (`MEMO_DEV=1` and a loopback request): `POST /api/dev/signin {member_id}` → sets cookie,
  `{ok, family_id, member_id, role, nickname}`; `GET /api/dev/members` → `{members:[{id,nickname,role,family_id,family_name}]}`.

**Museum**
- `GET /api/museum` → `MuseumSummary` + `today` ("YYYY-MM-DD", family tz). `flags` = all of `flags.DEFAULTS` resolved.
  `bot_username` null when TELEGRAM_BOT_TOKEN unset/unreachable. Guests: only their floor, no attic/latest.
- `GET /api/museum/{year}` → `{year, level, open, total:12, floor_board: str|null, rooms: Room[12]}`
  (`floor_board` = whole-floor-empty line for a past year with no memories). Guests: other rooms come back `closed`.
- `GET /api/museum/{year}/{month}?cursor=&limit=50&event_id=` → `{...Room, level, exhibits: Exhibit[], next_cursor: str|null}`.
  Exhibits only when state is `open`. Exhibit extras: `status, people[], author_id, captured_at`,
  photos[] extras `original_url, taken_at`. Order: day (undated last), then capture time.
- `GET /api/attic` → `{memories: Exhibit[]}` (status attic; `event_date` fields may be null).

**Memories** (writes: owner any; editor own, or any when family setting `editors_edit_others`)
- `GET /api/memories/{id}` → Exhibit
- `PATCH /api/memories/{id}` body any of `{title, text, summary, festival, people[], sensitivity, narrate_ok, event_id, teller_id}` → Exhibit
- `DELETE /api/memories/{id}` → 204 (media files removed; row kept as status `deleted` for idempotency)
- `POST /api/memories/{id}/narrate_ok {narrate_ok: bool}` → Exhibit
- `POST /api/memories/{id}/date` (alias `/move`) `{year, month, day?}` → Exhibit (attic → saved; publishes `memory_saved`)

**Events, rooms, route, showcase**
- `POST /api/events {name, kind?, year?, month?, when?}` (`when` = free words like "November 2026") →
  `{event:{id,name,kind,year,month,created_by,created_at}, level, room:{year,month}, room_state:{state,memory_count,board_text}, created: bool}`
  (same name+month again returns the existing event, `created:false`). Kind auto-detected (festival list) when omitted.
- `GET /api/events?name=&year=` → `{events:[event + memory_count]}` (festival aliases match: Deepavali = Diwali). `GET /api/events/{id}`.
- `POST /api/rooms/{y}/{m}/mode {mode: "auto"|"closed_with_care"}` (owner/editor) → `{year, month, mode, state, memory_count, board_text}`
- `POST /api/route` body `{year, month, event_id?}` | `{event_id}` | `{text: "last year's Holi"}` →
  `{route: MuseumRoute|null, question: str|null, candidates:[{year,month,event_id,label}]}`. `route` null ⇒ ask `question`
  (e.g. "Which year of Diwali? 2026, 2025?"), then call again with the chosen `{year, month, event_id}`.
  Waypoints: desk(0) → [lift(0) → ride(level)] → corridor(level) → door(level, door_index=month-1) → seat (only when open).
  `walk_seconds`: 0 if `cinematic_walk.enabled` is false; 5 on the ground floor; with lift = flag seconds clamped 5..10.
- `GET /api/showcase/{y}/{m}?event_id=` → `{year, month, event_id, room_state, items: ShowcaseItem[], total_s}`.
  Item extras: `text` (body for title cards), `photo_id`, `index_in_memory`, `count_in_memory`. Empty unless the room is open.

**Gallery import** (owner/editor)
- `POST /api/gallery/scan` empty/JSON → scans GALLERY_DIR. `multipart/form-data` with `meta` = JSON list aligned with
  repeated `files` parts (`[{name, path (webkitRelativePath), folder?, last_modified (ms)}]`) → stores + indexes as source
  `browser`. → `{scanned, new, duplicates, unreadable, removed?, source}`
- `POST /api/gallery/query` filter `{when?, date_from?, date_to? (YYYY-MM-DD), type? (jpeg|png|webp), min_size?, max_size?,
  min_width?, min_height?, orientation?, camera?, folder?, all?, latest_n?}` → `{count, matched, total_bytes, total_size,
  preview_token|null, over_limit, limit, already_imported, blurry, date_guessed, date_from, date_to, confirm_text, sample:[{id,
  name, folder, source, taken_at, taken_at_source, size_bytes, width, height, camera, is_blurry, thumb_url|null}]}`.
  An empty filter is a 400 ("Say which photos..."). Over the `max_import_photos` cap the newest that fit are chosen.
- `POST /api/gallery/import {preview_token, event_id}` → `{job_id, count, already_started, event}` (same token again → same job).
  The job publishes `import_done {job_id, count, memory_id, skipped_blurry, skipped_duplicates, failed, event_id, event_name, year, month}`.
- `GET /api/gallery/import/{job_id}` → `{job_id, status, attempts, result, error}`; `GET /api/gallery/items?limit&offset&source`.

**Live** — `GET /api/stream` (SSE): every message is `data: {json with "type"}` → use `EventSource.onmessage`.
First message `{type:"hello"}`; `: heartbeat` comment every 15 s. Guests only get events whose year+month is their room
or whose `invite_id` is theirs.

**Ops** (owner session, or header `x-ops-key: $OPS_API_KEY` for global access)
- `GET /api/ops/jobs?status=failed|dead|queued|running|done&type=&limit=` → `{jobs:[...], stuck_running}`
  (`failed` = erroring and waiting to retry). `POST /api/ops/jobs/{id}/replay` → `{job}`.
- `GET /api/ops/flags` → `{flags, defaults, overrides:[{scope,key,value,updated_at}]}`;
  `POST /api/ops/flags {key, value, scope:"family"|"global"}` (global needs the ops key) → `{key, value, scope}`.

**Family**
- `GET /api/family` → `{id, name, language, grandma_name, timezone, settings:{sarcasm_on, keep_location, editors_edit_others, ...}}`
  + owner only `invite_code, invite_link`. `PATCH /api/family {name?, language?, grandma_name?, settings?}` (owner) → same.
  Changing language also switches a default Grandma name (Grandma/Dadi/Ajji).
- `GET /api/family/members` → `{members:[{id, nickname, role, language, voice_keep_default, quiet, joined_at, on_telegram}]}`
- `PATCH /api/family/members/{id} {role?: editor|viewer, nickname?}` (owner) · `POST /api/family/transfer {member_id}` (owner)
- `DELETE /api/family {confirm: "<exact family name>"}` (owner) → rows + `storage/{family_id}/` removed, cookie cleared.
- `GET /api/export` → zip download (`memo.json` + `media/<storage key>`); also `core.export.build_export_zip(fid) -> Path`
  (stored under `{fid}/exports/`, so `storage.signed_url(key, absolute=True)` works for the bot).

**Python services others may call** (beyond the signatures above): `core.museum.year_rooms(fid, year)`,
`core.museum.floors(fid)`, `core.memories.get_memory / edit_memory / delete_memory / attic / check_edit`,
`core.events.festival_in(text)`, `core.gallery.scan_folder / index_uploads / query / start_import`,
`media.images.inspect(bytes)` (metadata + blur, no derivatives) and `media.images.derivatives(bytes)`.
Jobs: `gallery_import`, `media_regen {media_id|memory_id|family_id, force?}`.

## voice-ai: endpoints

All need a session (`memo_session` cookie or `x-memo-session` header). Guests are held to their invite room.
`language` everywhere: `en-IN | hi-IN | kn-IN`; when omitted: session language (after "speak Kannada") → member → family.

**Speech** (returned by Grandma and the receptionist) = contract.ts `Speech` plus extras:
```
{ text, audio_url,                      // audio_url = all sentences joined into one mp3 (per-sentence clips below)
  subtitles:[{text,start_s,end_s}], highlights:[{memory_id,at_s}], memory_ids:[...],
  sentences:[{index, text, audio_url, duration_s, start_s, end_s, memory_ids}],   // play one at a time; stop between
  language, start_index, total_sentences }
```
Timings are relative to the start of this Speech. Remember the last finished `sentences[i].index` and pass it back
as `resume_from` to carry on after an interruption.

- `POST /api/grandma/greet {year, month, event_id?, language?, audio?=true}` → Speech + `{source:"facts", memory_count}`
  ("Welcome back. November 2026 has eleven memories, three of them voice notes." + offer line).
- `POST /api/grandma/tour {year, month, event_id?, resume_from?=0, language?, audio?=true}` → Speech + `{source:"llm"|"template"}`.
  Facts from code, model writes connecting words, entity-checked, one regeneration, else template. Cached per
  room+language until the room's memories change. narrate_ok=false memories never appear.
- `POST /api/grandma/talk` — JSON `{text, scope:{year?,month?}, language?}` or multipart `audio=<file>` (+ `scope` JSON
  string or `year`/`month` fields, `language?`) → Speech + `{transcript, source:"family"|"general"|"none", scope_used,
  action:{type,data}, heard, heard_language, general?:{festival, source_url}}`. Empty transcript → `heard:false`.
  `source:"none"` ends with "Shall I ask the family on Telegram?"; a following "yes" calls
  `telegram.send.ask_family_followup` (`action.type:"followup_asked"`). "speak Kannada" → `action.type:"setting_changed"`.
  "invite Priya" is handed to the receptionist's invite flow (confirm aloud first).
- `POST /api/reception/act` — JSON `{text, language?, room?:{year,month,event_id?}, audio_reply?=true}` or multipart
  `audio=<file>` → `{reply, speech: Speech, action:{type, data}, source:"llm"|"keywords"|"state", steps:[...], language,
  pending: null|"need_when"|"need_name"|"confirm_import"|"need_event"|"choose_place"|"need_place"|"choose_contact"|
  "confirm_invite"|..., transcript, heard}`.
  `action.type`: `route` (data = MuseumRoute → start the guided walk) · `event_created` (data = core create_event result)
  · `import_started` (data = `{job_id, count, event}`; completion arrives as `import_done` on /api/stream)
  · `setting_changed` (data = `{key, value, scope}`) · `invite_called` (data = `{invite, call, contact}`) · `none`.
  Yes/no confirmations are matched in code (en/hi/kn), never by the model.
- `POST /api/tts {text, language?, voice?}` (voice: `grandma|receptionist|guide`, a Sarvam speaker or a Murf voice id)
  → `{url, duration_s, provider:"sarvam"|"murf", voice, language, cached}`.
- `GET /api/guide/lines?lang=` → `{language, lines:{follow_me, to_lift, here_we_are, locked_door, enjoy: {text, audio_url, duration_s}}}`.
- `GET /api/voice/health` → `{agora_configured, convoai_configured, murf_configured, public_url_ready, public_base_url,
  voice_enabled, browser_path:{grandma, receptionist}}`.
- `POST /api/voice/start {character:"receptionist"|"grandma", language?, year?, month?, event_id?}` →
  `{appId, channel, uid, rtcToken, rtmToken, token, agentUid, agentId, voiceSessionId, character, language, greeting}`.
  **503 `{detail:{code:"browser_voice_fallback", message, fallback:{grandma, receptionist}}}` while PUBLIC_BASE_URL is
  not public https** → use the browser path (record mic → /api/grandma/talk or /api/reception/act). 403 `voice_disabled`.
- `POST /api/voice/stop {agentId}` (sendBeacon text/plain OK) → `{ok, alreadyStopped?}`.
- `POST /api/voice/context {voiceSessionId, year?, month?, event_id?, language?}` → `{ok, scope, language}` (Grandma's room
  changed; restart the session after a language change: the Agora TTS voice is fixed per session).
- `POST /api/voice/llm/{character}/{voiceSessionId}/chat/completions` — Agora only (bearer token minted at start).
- Live-voice results on `GET /api/stream`: `{type:"voice_action", character, voice_session, transcript, reply, source,
  action:{type,data}}` and `{type:"voice_highlight", voice_session, memory_ids, text}`.

Python: `app.ai.tts.synthesize(text, language, voice=None, fmt="mp3", family_id=None)` →
`{storage_key, url, duration_s, provider, voice, cached}`; `app.ai.facts.festival_summary(name, language, family_id)`;
`app.voice.grandma.tour/greet/talk/answer`; `app.voice.reception.act/act_core`.

## guests: endpoints
Invited viewers (and family members) sit together in a room's four theater seats. Table `theater_presence` (schema.sql
"guests" section): one row per web session — room, member_id|invite_id, is_guest, name, avatar man|woman, seat 0-3 or
NULL (watching without a seat), joined_at, last_seen. Rows expire 45 s after the last heartbeat (pruned by the routes).
Seats: the first family member to sit keeps seat 0; family members and guests get 1-3; full room = watch without a seat.
Guests may only join/read their invite room (403 otherwise). Router `app/routes/presence.py`.
- `POST /api/presence/join {year, month, avatar:"man"|"woman", name?, prefer_seat?: 0-3}` → `{year, month, seats:[Person], watchers:[Person], me: Person|null}`
  (`Person = {id, index|null, name, avatar, is_guest, is_me}`; name defaults to the member nickname / the invite's contact name;
  `prefer_seat` is honoured when free and allowed; re-joining keeps your seat; joining another room moves you)
- `POST /api/presence/heartbeat` (every 15 s) → `{ok:true, year, month, index}` or `{ok:false, rejoin:true}` after expiry
- `POST /api/presence/leave` (body optional; `navigator.sendBeacon` on pagehide) → `{ok, left}`
- `GET /api/presence/{year}/{month}` → same shape as join
- `GET /api/guest/welcome` → guest: `{is_guest:true, host_name, contact_name, event_name|null, year, month, family_name, grandma_name}`; member: `{is_guest:false, name}`
- Bus/SSE `{type:"presence", year, month, seats:[Person], watchers:[Person], change:{kind:"joined"|"left"|"moved", id, name, avatar, is_guest, index}|null}`.
  Published with each person's hashed session id; `/api/stream` turns it into `is_me` per subscriber and strips it. Guests get it only for their room.
- Web: `pages/presence.ts` (`usePresence` join/heartbeat/leave, `onPresenceEvent` → store `presence` + join/leave card, Grandma pauses
  for the card), guest landing in `pages/Entry.tsx`, 3D `world/Audience.tsx` (seated avatars in per-seat colours `rigs.seatLook`, name tags,
  wave on arrival; back bench when all seats are taken). Host re-sends `/api/sync` when someone sits down so the newcomer follows at once.
- Tests: `cd backend && .venv/Scripts/python -m pytest tests/test_guests_presence.py`

**voice-ai additions (2026-11-25: voices, natural speech, code-mixed input)**
- Voices: one Sarvam bulbul:v3 speaker per character for all three languages, with prosody (Grandma `neha` pace 0.85
  pitch -0.15; receptionist `priya` pace 1.05; guide `rohan` pace 1.1; phone agent `advait` pace 0.92), Murf Falcon
  as fallback. Briefs + measured F0 / pace in `docs/VOICES.md`. `POST /api/tts` also accepts `voice:"phone"`.
  `tts_voice_by_language` may now be `{"hi-IN": "<voice>"}` or `{"hi-IN": {"grandma": "<voice>" | {provider, voice, params}}}`.
  Agora sessions use the same voice (vendor `sarvam`, same speaker/params) and the character's own filler lines.
- `GET /api/voice/fillers?character=grandma|receptionist&lang=en-IN|hi-IN|kn-IN|hinglish|kanglish` (lang defaults to the
  session language) → `{character, language, register, fillers:[{text, audio_url, duration_s}]}`. Short thinking clips
  in the character's voice, pre-synthesized and cached; play one if a reply takes > 700 ms. 422 for another character.
- `POST /api/voice/interrupt {agentId}` (sendBeacon text/plain OK) → `{ok:true, cancelled_llm, alreadyIdle?}`. Calls Agora
  ConvoAI `POST /v2/projects/{appid}/agents/{agentId}/interrupt` and cancels Memo's in-flight custom-LLM work (tool loop /
  grounded answer) for that voice session (the cut-off turn answers with nothing). Idempotent (idle or gone agent = ok).
  404 when the agent belongs to another family; 422 without agentId; 502 on other Agora errors.
- Mirroring: Grandma talk and the receptionist reply in the user's register for that turn. Devanagari / Kannada script
  or Roman Hindi (Hinglish) / Roman Kannada (Kanglish) input → reply voiced in hi-IN / kn-IN, written the same way
  (Hinglish in → Roman Hinglish out). Plain English keeps the session language. The session language is not changed by
  a mirrored turn (only by "speak Kannada" etc.). Speech `language` is the voice language of that reply.
- Code-mixed understanding: dates via `app.voice.register.to_english_dates` (kal, parso, ninne, monne, pichle mahine,
  last year wala, kalada tingalu, Hindi/Kannada month names in both scripts, Roman spellings, typos; "Nov 26" in a room
  request = November 2026) before `core.dates.resolve_when`; yes/no in code (haan, ha, theek hai, chalo, haudu, sari,
  ok done / nahi, beda, rehne do; "haan nahi" = no). "last Holi" with several Holi rooms goes to the most recent past one.

## NudgeBee (observability): wired
`app/observability/nudgebee.py` sends Memo incidents to NudgeBee's Generic Event Webhook so its AI-SRE can group and RCA them.
No-op unless `NUDGEBEE_WEBHOOK_URL` + `NUDGEBEE_TOKEN` are set; gated by flag `nudgebee_alerts` (default true). Never sends personal data
(labels are allow-listed, `family_id` only as an opaque id). Details: `docs/NUDGEBEE.md`.
- `await nudgebee.emit(rule, title, severity=, fingerprint_parts=, description=, labels=, status="firing"|"resolved")`, `emit_nowait(...)` from sync code. Never raises, never blocks.
- Signals: job failures/exhausted retries (hooks in `jobs.run_one`), API 5xx (`nudgebee.install(app)` in main.py), provider degradation
  (`nudgebee.record_http(provider, status)` / `record_provider_error(provider, kind)` / `record_provider_ok(provider)` at the Sarvam, Groq, Murf, Twilio, Telegram, Agora call points), worker watchdog (DB + queue backlog, started from `jobs.worker_loop`).
- Verify: `cd backend && .venv/Scripts/python scripts/nudgebee_test_event.py`. Tests: `tests/test_nudgebee.py`.

**Deploy (Render, prepared not deployed)** — full walkthrough in `docs/DEPLOY_RENDER.md`.
- `Dockerfile` (node 20 builds `web/dist`; python 3.12-slim + ffmpeg + Noto/DejaVu fonts; entrypoint chowns the disk then drops to user `memo`),
  `docker-entrypoint.sh`, `.dockerignore`, `render.yaml` (Blueprint: `memo` web service + disk at `/var/data`, `memo-db` Postgres, `memo-flags` Flagsmith image), all region singapore.
- `app/spa.py`: when `web/dist` exists (or `WEB_DIST_DIR`), FastAPI serves it with a SPA fallback registered after all routers; paths starting
  `api/ media/ m/ i/ webhooks/ twilio/` that match no route return a JSON 404 and are never answered with index.html. Dev is unchanged (no dist = no mount).
- `app/deploy.py` (installed by one line at the end of `main.py`, pushes onto `STARTUP_HOOKS`):
  `RUN_WORKER_IN_PROCESS=1` runs `jobs.worker_loop` as a background task with reconnect (it never closes the shared pool);
  `TELEGRAM_MODE=webhook` + `TELEGRAM_REGISTER_WEBHOOK=1` calls `setWebhook(PUBLIC_BASE_URL/webhooks/telegram, secret_token=TELEGRAM_WEBHOOK_SECRET)` at boot;
  `FLAGSMITH_DB_NAME=flagsmith` creates that database on the same Postgres server if missing.
  Telegram allows one consumer per bot token: a set webhook breaks local long polling (`python -m app.telegram.bot` calls `deleteWebhook` on start and takes it back).
- `config.py`: `PUBLIC_BASE_URL` / `WEB_BASE_URL` fall back to `RENDER_EXTERNAL_URL` when unset. `media/reels.py` finds Noto Sans / Devanagari / Kannada under `/usr/share/fonts` on Linux (Windows lookup unchanged).

## Flagsmith (flags agent)

- Interface unchanged: `await flags.get(key, family_id)`. Order: family override -> global override -> Flagsmith ->
  `flags.DEFAULTS`. New keys: add to `DEFAULTS`, then re-run `backend/scripts/flagsmith_seed.py` (idempotent).
- Provider: official SDK `flagsmith==6.7.0`, local evaluation (no network per read), identity = family_id, traits
  `family_id, language, member_count, created_days_ago, has_phone_invites, has_call_consent` from Postgres.
  Bool defaults map to the feature's enabled state; int/str/dict defaults to the remote-config value (JSON for dicts).
  A disabled remote-config feature = use the code default. Unset/invalid key or server down = previous behaviour.
- Ops: `GET /api/ops/flags` adds `sources` (per key: `override:family|override:global|flagsmith|default`) and
  `provider` (status, no keys); `GET /api/ops/flags/status` returns the provider status only.
- Local: `docker compose --env-file .env.local --profile flags up -d flagsmith` -> dashboard http://localhost:8001,
  data in database `flagsmith` on the `db` service. Segments: `phone_pilot` (family_id IN list -> phone_allowlist),
  `hindi_or_kannada` (language -> tts_voice_by_language); `followup_variant` is a 50/50 a/b multivariate.
- Env: `FLAGSMITH_ENVIRONMENT_KEY` (`ser.` key), `FLAGSMITH_API_URL`; container/seed: `FLAGSMITH_DJANGO_SECRET_KEY`,
  `FLAGSMITH_ADMIN_EMAIL`, `FLAGSMITH_ADMIN_PASSWORD`, `FLAGSMITH_ADMIN_API_KEY`, `FLAGSMITH_PHONE_PILOT_FAMILIES`.
