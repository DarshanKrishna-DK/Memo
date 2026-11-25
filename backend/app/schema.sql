-- Memo schema. Idempotent: applied on every API/worker start (app/db.py:init_schema).
-- Floors and rooms are NOT stored; they are computed from memories' event_year/event_month.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS families (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name          text NOT NULL,
  language      text NOT NULL DEFAULT 'en-IN',          -- en-IN | hi-IN | kn-IN
  grandma_name  text NOT NULL DEFAULT 'Grandma',
  timezone      text NOT NULL DEFAULT 'Asia/Kolkata',
  invite_code   text UNIQUE NOT NULL,                    -- long random code used in t.me deep link
  settings      jsonb NOT NULL DEFAULT '{}'::jsonb,     -- sarcasm_on, keep_location, editors_edit_others, followups_quiet ...
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS members (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id          uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  telegram_user_id   bigint,
  telegram_chat_id   bigint,
  nickname           text NOT NULL,
  role               text NOT NULL DEFAULT 'editor' CHECK (role IN ('owner','editor','viewer')),
  language           text NOT NULL DEFAULT 'en-IN',
  voice_keep_default text CHECK (voice_keep_default IN ('voice','words','both')),
  quiet              boolean NOT NULL DEFAULT false,
  joined_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (family_id, telegram_user_id)
);
CREATE INDEX IF NOT EXISTS members_tg_idx ON members(telegram_user_id);

CREATE TABLE IF NOT EXISTS events (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id   uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  name        text NOT NULL,
  kind        text NOT NULL DEFAULT 'other' CHECK (kind IN ('festival','trip','birthday','other')),
  year        int  NOT NULL CHECK (year BETWEEN 1900 AND 2200),
  month       int  NOT NULL CHECK (month BETWEEN 1 AND 12),
  created_by  uuid REFERENCES members(id) ON DELETE SET NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS events_family_ym ON events(family_id, year, month);

CREATE TABLE IF NOT EXISTS memories (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id         uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  event_id          uuid REFERENCES events(id) ON DELETE SET NULL,
  author_id         uuid REFERENCES members(id) ON DELETE SET NULL,
  teller_id         uuid REFERENCES members(id) ON DELETE SET NULL,
  kind              text NOT NULL CHECK (kind IN ('text','voice','photo','album','forward')),
  title             text,
  text_original     text,
  language          text,
  summary           text,
  event_year        int,
  event_month       int CHECK (event_month BETWEEN 1 AND 12),
  event_day         int CHECK (event_day BETWEEN 1 AND 31),
  date_confidence   real NOT NULL DEFAULT 0,
  festival          text,
  people            text[] NOT NULL DEFAULT '{}',
  sensitivity       text NOT NULL DEFAULT 'none' CHECK (sensitivity IN ('none','loss','illness','conflict','other')),
  narrate_ok        boolean NOT NULL DEFAULT true,
  status            text NOT NULL DEFAULT 'received' CHECK (status IN ('received','processing','attic','saved','failed','deleted')),
  captured_at       timestamptz NOT NULL DEFAULT now(),
  source_update_id  text UNIQUE,                         -- telegram update id / media_group id; idempotency key
  media_group_id    text,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS memories_room ON memories(family_id, event_year, event_month) WHERE status = 'saved';
CREATE INDEX IF NOT EXISTS memories_status ON memories(family_id, status);

CREATE TABLE IF NOT EXISTS media (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  memory_id    uuid NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
  type         text NOT NULL CHECK (type IN ('photo','voice','video')),
  audio_kept   boolean NOT NULL DEFAULT true,
  storage_key  text,               -- original (null once audio deleted by choice)
  large_key    text,               -- 1600px photo
  thumb_key    text,               -- 512px photo
  mime         text,
  width        int,
  height       int,
  taken_at     timestamptz,
  sort_order   int NOT NULL DEFAULT 0,
  duration_s   real,
  transcript   text,
  blur_score   real,               -- variance of Laplacian; lower = blurrier
  is_blurry    boolean NOT NULL DEFAULT false,
  content_hash text,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS media_memory ON media(memory_id);

CREATE TABLE IF NOT EXISTS followups (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  memory_id    uuid NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
  member_id    uuid REFERENCES members(id) ON DELETE SET NULL,
  question     text NOT NULL,
  variant      text NOT NULL DEFAULT 'a',
  source       text NOT NULL DEFAULT 'proactive',        -- proactive | grandma_gap (asked from the theater)
  asked_at     timestamptz,
  answered_at  timestamptz,
  answer_text  text,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS room_settings (
  family_id  uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  year       int NOT NULL,
  month      int NOT NULL CHECK (month BETWEEN 1 AND 12),
  mode       text NOT NULL DEFAULT 'auto' CHECK (mode IN ('auto','closed_with_care')),
  PRIMARY KEY (family_id, year, month)
);

CREATE TABLE IF NOT EXISTS jobs (
  id          bigserial PRIMARY KEY,
  type        text NOT NULL,
  payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
  status      text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','failed','dead')),
  attempts    int NOT NULL DEFAULT 0,
  max_attempts int NOT NULL DEFAULT 5,
  run_at      timestamptz NOT NULL DEFAULT now(),
  locked_at   timestamptz,
  locked_by   text,
  last_error  text,
  result      jsonb,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS jobs_claim ON jobs(run_at) WHERE status = 'queued';

CREATE TABLE IF NOT EXISTS gallery_items (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id          uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  source             text NOT NULL CHECK (source IN ('folder','browser')),
  path_or_handle     text NOT NULL,
  taken_at           timestamptz,
  taken_at_source    text CHECK (taken_at_source IN ('exif','file_date')),
  size_bytes         bigint,
  width              int,
  height             int,
  camera             text,
  folder             text,
  mime               text,
  content_hash       text NOT NULL,
  blur_score         real,
  is_blurry          boolean NOT NULL DEFAULT false,
  upload_key         text,                               -- browser source: where the uploaded bytes live
  imported_memory_id uuid REFERENCES memories(id) ON DELETE SET NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (family_id, content_hash)
);

CREATE TABLE IF NOT EXISTS gallery_previews (            -- proves a count was confirmed before import
  token       text PRIMARY KEY,
  family_id   uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  item_ids    uuid[] NOT NULL,
  total_bytes bigint NOT NULL,
  expires_at  timestamptz NOT NULL,
  used_at     timestamptz
);

CREATE TABLE IF NOT EXISTS contacts (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id        uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  name             text NOT NULL,
  relation         text,
  phone_e164       text NOT NULL,
  language         text NOT NULL DEFAULT 'en-IN',
  consent_to_calls boolean NOT NULL DEFAULT false,
  consent_by       uuid REFERENCES members(id) ON DELETE SET NULL,
  consent_at       timestamptz,
  do_not_call      boolean NOT NULL DEFAULT false,
  timezone         text NOT NULL DEFAULT 'Asia/Kolkata',
  telegram_user_id bigint,
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS invites (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id   uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  contact_id  uuid REFERENCES contacts(id) ON DELETE SET NULL,
  event_id    uuid REFERENCES events(id) ON DELETE SET NULL,
  year        int NOT NULL,
  month       int NOT NULL,
  role        text NOT NULL DEFAULT 'viewer',
  token_hash  text NOT NULL UNIQUE,
  host_member_id uuid REFERENCES members(id) ON DELETE SET NULL,
  expires_at  timestamptz NOT NULL,
  used_at     timestamptz,
  status      text NOT NULL DEFAULT 'created',
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS call_sessions (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  invite_id        uuid NOT NULL REFERENCES invites(id) ON DELETE CASCADE,
  provider_call_id text UNIQUE,
  status           text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','ringing','talking','accepted','declined','no_answer','message_left','failed')),
  turns            int NOT NULL DEFAULT 0,
  transcript       jsonb NOT NULL DEFAULT '[]'::jsonb,
  outcome_summary  text,
  message_text     text,
  started_at       timestamptz NOT NULL DEFAULT now(),
  ended_at         timestamptz,
  cost_inr         numeric(10,2)
);

CREATE TABLE IF NOT EXISTS sessions (                    -- web sessions created from /m/{token}
  id          text PRIMARY KEY,                          -- random cookie value
  family_id   uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  member_id   uuid REFERENCES members(id) ON DELETE CASCADE,
  role        text NOT NULL,                             -- owner | editor | viewer
  invite_id   uuid REFERENCES invites(id) ON DELETE CASCADE, -- set for invited guests (scoped to one room)
  expires_at  timestamptz NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signin_tokens (
  token_hash  text PRIMARY KEY,
  family_id   uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  member_id   uuid NOT NULL REFERENCES members(id) ON DELETE CASCADE,
  expires_at  timestamptz NOT NULL,
  used_at     timestamptz
);

CREATE TABLE IF NOT EXISTS reels (                       -- generated videos (ffmpeg) per room or event
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id   uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  year        int NOT NULL,
  month       int NOT NULL,
  event_id    uuid REFERENCES events(id) ON DELETE CASCADE,
  status      text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','rendering','ready','failed')),
  storage_key text,
  duration_s  real,
  narrated    boolean NOT NULL DEFAULT false,
  error       text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS festival_facts (              -- cached general knowledge, per festival + language
  festival   text NOT NULL,
  language   text NOT NULL,
  summary    text NOT NULL,
  source_url text,
  fetched_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (festival, language)
);

CREATE TABLE IF NOT EXISTS flag_overrides (              -- local runtime switches until Flagsmith is wired
  family_id  uuid REFERENCES families(id) ON DELETE CASCADE,
  key        text NOT NULL,
  value      jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS flag_overrides_key ON flag_overrides(coalesce(family_id, '00000000-0000-0000-0000-000000000000'::uuid), key);

CREATE TABLE IF NOT EXISTS audit_events (                -- product metrics (walk skipped, import confirmed, ...)
  id         bigserial PRIMARY KEY,
  family_id  uuid REFERENCES families(id) ON DELETE CASCADE,
  member_id  uuid,
  type       text NOT NULL,
  data       jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- media-tools -------------------------------------------------------------------------------
ALTER TABLE reels ADD COLUMN IF NOT EXISTS aspect text NOT NULL DEFAULT '16:9';
ALTER TABLE reels ADD COLUMN IF NOT EXISTS requested_by uuid;
ALTER TABLE media ADD COLUMN IF NOT EXISTS blur_kept boolean NOT NULL DEFAULT false;          -- user said "keep this one"
ALTER TABLE gallery_items ADD COLUMN IF NOT EXISTS blur_kept boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS media_blurry ON media(memory_id) WHERE is_blurry;
CREATE INDEX IF NOT EXISTS reels_room ON reels(family_id, year, month);


-- ===== capture-telegram =====
CREATE TABLE IF NOT EXISTS tg_state (
  telegram_user_id bigint PRIMARY KEY,
  state            text NOT NULL,
  data             jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at       timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE media ADD COLUMN IF NOT EXISTS tg_file_id text;
ALTER TABLE media ADD COLUMN IF NOT EXISTS tg_file_unique_id text;
ALTER TABLE media ADD COLUMN IF NOT EXISTS tg_file_size int;
CREATE UNIQUE INDEX IF NOT EXISTS media_tg_unique ON media(memory_id, tg_file_unique_id) WHERE tg_file_unique_id IS NOT NULL;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS tg_chat_id bigint;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS tg_meta jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE followups ADD COLUMN IF NOT EXISTS family_id uuid REFERENCES families(id) ON DELETE CASCADE;
ALTER TABLE followups ALTER COLUMN memory_id DROP NOT NULL;
ALTER TABLE followups ADD COLUMN IF NOT EXISTS tg_message_id bigint;
ALTER TABLE followups ADD COLUMN IF NOT EXISTS tg_chat_id bigint;
CREATE INDEX IF NOT EXISTS followups_open ON followups(member_id) WHERE answered_at IS NULL;

-- ============================================================ voice-ai
CREATE TABLE IF NOT EXISTS tts_cache (                   -- synthesized speech, keyed by hash(text+lang+voice)
  hash        text PRIMARY KEY,
  storage_key text NOT NULL,
  duration_s  real NOT NULL,
  provider    text NOT NULL,                             -- sarvam | murf
  voice       text NOT NULL,
  language    text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS voice_state (                 -- per web-session / Agora-session conversation state
  key         text PRIMARY KEY,                          -- "web:<session id hash>:<character>" | "agora:<voice session id>"
  family_id   uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  member_id   uuid REFERENCES members(id) ON DELETE SET NULL,
  character   text NOT NULL,                             -- receptionist | grandma
  language    text,
  state       jsonb NOT NULL DEFAULT '{}'::jsonb,        -- pending confirmation, current event, scope, agent id ...
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS voice_state_family ON voice_state(family_id);

CREATE TABLE IF NOT EXISTS grandma_tours (               -- generated tour text, reused while the room is unchanged
  family_id   uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  scope_key   text NOT NULL,                             -- "2026-11" | "2026-11:<event_id>"
  language    text NOT NULL,
  fingerprint text NOT NULL,                             -- hash of the narrated memories' ids + updated_at
  sentences   jsonb NOT NULL,                            -- [{"text","memory_ids"}]
  source      text NOT NULL,                             -- llm | template
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (family_id, scope_key, language)
);

-- ===================== core-api =====================
ALTER TABLE gallery_previews ADD COLUMN IF NOT EXISTS job_id bigint;          -- set once import starts (idempotent)
ALTER TABLE gallery_previews ADD COLUMN IF NOT EXISTS event_id uuid;
ALTER TABLE gallery_previews ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS gallery_items_family_taken ON gallery_items(family_id, taken_at DESC);
CREATE INDEX IF NOT EXISTS media_content_hash ON media(content_hash);
CREATE INDEX IF NOT EXISTS events_family_name ON events(family_id, lower(name));

-- ===================== guests =====================
-- Who sits in which theater seat right now (family member or invited guest session). Rows expire after 45 s
-- without a heartbeat (pruned by the presence routes). Seat 0 is the first family member's; 1-3 for everyone
-- else; seat NULL = in the room but watching without a seat (all four taken).
CREATE TABLE IF NOT EXISTS theater_presence (
  session_id  text PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
  id          uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
  family_id   uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  year        int NOT NULL,
  month       int NOT NULL CHECK (month BETWEEN 1 AND 12),
  member_id   uuid REFERENCES members(id) ON DELETE CASCADE,
  invite_id   uuid REFERENCES invites(id) ON DELETE CASCADE,
  is_guest    boolean NOT NULL DEFAULT false,
  name        text NOT NULL,
  avatar      text NOT NULL CHECK (avatar IN ('man','woman')),
  seat        smallint CHECK (seat BETWEEN 0 AND 3),
  joined_at   timestamptz NOT NULL DEFAULT now(),
  last_seen   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS theater_presence_seat ON theater_presence(family_id, year, month, seat) WHERE seat IS NOT NULL;
CREATE INDEX IF NOT EXISTS theater_presence_room ON theater_presence(family_id, year, month);

-- ===================== videos + cleanup history + timed reels (2026-11-25) =====================
-- memories.kind gains 'video' (media.type already allows it). Only re-created when the old definition lacks
-- 'video', so a normal start does not take a table lock.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'memories'::regclass AND conname = 'memories_kind_check'
                 AND pg_get_constraintdef(oid) LIKE '%video%') THEN
    ALTER TABLE memories DROP CONSTRAINT IF EXISTS memories_kind_check;
    ALTER TABLE memories ADD CONSTRAINT memories_kind_check
      CHECK (kind IN ('text','voice','photo','album','forward','video'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'media'::regclass AND conname = 'media_type_check'
                 AND pg_get_constraintdef(oid) LIKE '%video%') THEN
    ALTER TABLE media DROP CONSTRAINT IF EXISTS media_type_check;
    ALTER TABLE media ADD CONSTRAINT media_type_check CHECK (type IN ('photo','voice','video'));
  END IF;
END $$;
-- video media rows: storage_key = original upload, large_key = web H.264/AAC mp4, thumb_key = poster jpg.
ALTER TABLE media ADD COLUMN IF NOT EXISTS video_error text;

-- Photos removed as blurry (deleted by a person) or never imported (auto-skipped by auto_skip_blurry).
-- thumb_key is a small copy made at that moment, so history still shows the photo after the files are gone.
-- No FKs to media/gallery_items on purpose: those rows are deleted.
CREATE TABLE IF NOT EXISTS cleanup_history (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id       uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  media_id        uuid,
  gallery_item_id uuid,
  memory_id       uuid,
  event_id        uuid,
  year            int,
  month           int CHECK (month BETWEEN 1 AND 12),
  reason          text NOT NULL CHECK (reason IN ('auto_skipped','deleted')),
  blur_score      real,
  thumb_key       text,
  name            text,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cleanup_history_room ON cleanup_history(family_id, year, month);
CREATE UNIQUE INDEX IF NOT EXISTS cleanup_history_media ON cleanup_history(media_id, reason) WHERE media_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS cleanup_history_gallery ON cleanup_history(family_id, gallery_item_id, reason)
  WHERE gallery_item_id IS NOT NULL AND media_id IS NULL;

ALTER TABLE reels ADD COLUMN IF NOT EXISTS options jsonb NOT NULL DEFAULT '{}'::jsonb;  -- target_s, max_photos, title, voiceover

-- Grandma's cloned voice (Sarvam Instant Voice Cloning, beta). One per family and character; only created from a
-- consented recording uploaded by the owner (POST /api/voice/clone). docs/VOICES.md has the consent procedure.
CREATE TABLE IF NOT EXISTS family_voices (
  family_id     uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  role          text NOT NULL DEFAULT 'grandma',
  provider      text NOT NULL DEFAULT 'sarvam_clone',
  voice_id      text NOT NULL,
  name          text NOT NULL,
  language      text NOT NULL,
  consented_by  text NOT NULL,
  consent_note  text NOT NULL,
  consent_at    timestamptz NOT NULL DEFAULT now(),
  created_by    uuid REFERENCES members(id) ON DELETE SET NULL,
  PRIMARY KEY (family_id, role)
);
