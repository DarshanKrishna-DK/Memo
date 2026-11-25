# Memo voices

Who sounds like what, why, and the numbers behind each choice. Owner: voice-ai. Code: `backend/app/voice/lang.py`
(`VOICE_PROFILES`, `MURF_VOICES`, `MURF_PARAMS`, `FILLER_LINES`), `backend/app/ai/tts.py`, `backend/app/voice/agora.py`
(`tts_config`). Measuring tool: `backend/scripts/voice_measure.py` (raw results in `backend/scripts/voice_measure_*.json`).

Every default can be overridden per language with the `tts_voice_by_language` flag:
`{"hi-IN": "neha"}` (every character in Hindi), `{"hi-IN": {"grandma": "neha", "receptionist": "priya"}}` (per
character), or a full profile `{"hi-IN": {"grandma": {"provider": "sarvam", "voice": "neha", "params": {"pace": 0.8}}}}`.

## Voice briefs

**Grandma** (the guide in the theater). A warm Indian grandmother in her seventies. Slow, unhurried pace; soft,
lower pitch; she smiles while she talks. Gentle teasing, never about tender memories. She pauses before a tender
detail ("..." in the text gives the TTS a beat). She reacts before she answers ("Arre, you remember that Diwali?")
and tells things like family stories, not reports. Mirrors the visitor: Hinglish in, Hinglish out; Kanglish in,
Kanglish out; native script in, native script out.

**Receptionist robot** (front desk). Friendly, crisp, upbeat, mid-pitch. Efficient but warm: a short reaction, the
fact, the one question ("Okay, I found 12 photos from 24 November 2026, about 36 MB. Shall I add them to Diwali
2026?"). Never "How can I help you today?".

**Guide robot** (walks you to rooms). Cheerful and bright, short lines ("Follow me.", "Here we are.").

**Phone agent** (calls a guest to invite them; phone-invites owns the call flow). Polite, clear, measured: steady
pitch, unhurried, every number and name easy to catch on a phone line. Available as TTS role `phone`.

## Chosen voices

One Sarvam bulbul:v3 speaker per character, the same speaker for en-IN, hi-IN and kn-IN (bulbul:v3 speakers are
shared across languages), so a character keeps one voice when the session language changes or a Hinglish reply is
voiced in hi-IN. Sarvam bulbul:v3 honours `pace` (0.5-2.0), `pitch` (-0.5..0.5; verified: pitch -0.3 lowered
kavitha's median F0 from ~272 Hz to ~246 Hz over two takes each), `loudness` and `temperature` (expressiveness).

| Character | Vendor / model | Speaker (all 3 languages) | Params | Murf fallback (en / hi / kn) | Murf params |
|---|---|---|---|---|---|
| Grandma | Sarvam bulbul:v3 + aged-voice chain | `neha` | pace 0.85, pitch -0.15, temperature 0.5, then `GRANDMA_AGE_FX` (default strong) | en-IN-alia / bn-IN-ishani / hi-IN-namrita | rate -20, pitch -8 |
| Receptionist | Sarvam bulbul:v3 | `priya` | pace 1.05, temperature 0.6 | en-IN-priya / en-IN-priya / en-IN-pooja | 0 / 0 |
| Guide robot | Sarvam bulbul:v3 | `rohan` | pace 1.1, temperature 0.7 | en-IN-aarav / en-IN-aarav / en-IN-nikhil | rate 5, pitch 5 |
| Phone agent | Sarvam bulbul:v3 | `advait` | pace 0.92, temperature 0.45 | en-IN-aarav / en-IN-aarav / en-IN-nikhil | rate -5 |

Agora live sessions use the same voice: `agora.tts_config()` sends the character's Sarvam speaker and params through
Agora's `sarvam` TTS vendor (`api_subscription_key`, `speaker`, `target_language_code`, `model`, `pace`; `pitch` and
`temperature` pass through to Sarvam), and falls back to the Murf voice with its rate / pitch when no Sarvam key is
set. Agora's filler words are the character's own thinking lines (`FILLER_LINES`).

## How the voices were chosen (measured 2026-11-24/25)

Method: the same sentence per language ("Arre, you remember that Diwali? Your father lit every single lamp on the
terrace, and then he burnt his finger, poor thing. We laughed so much that night." and its Hindi / Kannada versions)
was synthesized live with every candidate female voice: 14 bulbul:v3 speakers, the female bulbul:v4-flash personas
of that language (12 en, 14 hi, 3 kn), and every female Murf Falcon voice that lists the locale (9 en, 12 hi, 7 kn).
Each clip was decoded with ffmpeg (16 kHz mono) and measured in numpy: median F0 by YIN (70-400 Hz, threshold 0.15),
F0 spread in semitones, aperiodicity (YIN dip depth: higher = breathier), and words per second over the speech span.
Targets for an elderly woman: median F0 ~160-190 Hz, pace ~0.8-0.9 of normal, warm (some pitch movement), slightly
breathy. Kannada words are long and agglutinative, so its words/s is lower for every voice; compare within a language.

Lowest-F0 female candidates at default settings (one take each) and the old Grandma voice:

| Lang | Vendor | Voice | Median F0 (Hz) | F0 spread (st) | Words/s |
|---|---|---|---|---|---|
| en-IN | Sarvam v4-flash | aparna_en_companion | 166 | 2.0 | 2.67 |
| en-IN | Sarvam v4-flash | zarina_en_conversation | 181 | 2.8 | 3.12 |
| en-IN | Murf | en-IN-anisha | 185 | 2.1 | 3.61 |
| en-IN | **Sarvam v3** | **neha** | **189** | 5.3 | **2.01** (slowest of all 35) |
| en-IN | Sarvam v4-flash | shalini_en_companion | 195 | 3.5 | 2.60 |
| en-IN | Sarvam v3 | kavitha (old Grandma) | 263 | 2.6 | 2.47 |
| hi-IN | Murf | bn-IN-ishani ("Middle-Aged") | 178 | 5.7 | 3.80 |
| hi-IN | **Sarvam v3** | **neha** | **197** | 5.8 | **2.05** (2nd slowest of 37) |
| hi-IN | Murf | en-IN-alia ("Middle-Aged") | 205 | 3.8 | 3.35 |
| hi-IN | Sarvam v4-flash | shalini_hi_companion | 210 | 3.1 | 2.19 |
| hi-IN | Sarvam v3 | kavitha (old Grandma) | 283 | 2.7 | 2.63 |
| kn-IN | **Sarvam v3** | **neha** | **160** | 3.5 | **1.44** |
| kn-IN | Murf | hi-IN-namrita | 172 | 3.0 | 2.02 |
| kn-IN | Sarvam v3 | shreya | 192 | 2.9 | 1.58 |
| kn-IN | Sarvam v4-flash | chaitra_kn_narration | 220 | 2.8 | 1.83 |
| kn-IN | Sarvam v3 | kavitha (old Grandma) | 268 | 2.1 | 1.41 |

Why `neha`: it is the only voice in the low-F0 band in all three languages, and among the slowest natural paces,
with the widest pitch movement (warm, story-telling rather than flat). The old Grandma voice, `kavitha`, sat at
263-283 Hz, a young woman's pitch; that is why she did not sound like a grandmother. `aparna_en_companion` is lower
in English but exists only in English (a Hindi or Kannada reply would switch to a different woman), and is faster.
Murf: no Murf voice is labelled older than "Middle-Aged"; `bn-IN-ishani` is low (178 Hz) but speaks fast (3.8 w/s,
still 3.7 w/s at rate -15), so Murf has no clearly older voice in any of the three languages and stays the fallback.

Chosen settings, measured live (each row two takes unless noted; bulbul samples with temperature, so takes vary):

| Character | Lang | Median F0 (Hz) per take | Words/s per take | Aperiodicity |
|---|---|---|---|---|
| Grandma (neha, pace 0.85, pitch -0.1) | en-IN | 175, 186 | 1.84, 1.78 | 0.04, 0.03 |
| | hi-IN | 173, 240 | 1.84, 1.87 | 0.05, 0.04 |
| | kn-IN | 168, 175 | 1.27, 1.19 | 0.04, 0.03 |
| Grandma, temperature 0.5 (4 takes) | hi-IN / en-IN | 171, 171, 175 / 226 | 1.75-1.87 | 0.05 |
| **Grandma as shipped (pace 0.85, pitch -0.15, temp 0.5)** | en-IN | **162, 165, 168** | 1.90, 1.84, 1.91 | 0.03-0.04 |
| | hi-IN | **161, 185, 194** | 1.84, 1.76, 1.79 | 0.04 |
| | kn-IN | **156, 160** | 1.15, 1.25 | 0.03 |
| Receptionist (priya, pace 1.05) | en-IN | 228, 253 | 3.19, 2.95 | 0.06, 0.07 |
| | hi-IN | 223, 244 | 3.08, 3.12 | 0.06, 0.09 |
| | kn-IN | 205, 220 | 1.79, 1.87 | 0.08, 0.09 |
| Guide (rohan, pace 1.1) | en-IN | 189, 194 | 3.23, 3.18 | 0.08 |
| | hi-IN | 184, 187 | 3.21, 3.63 | 0.09 |
| | kn-IN | 167, 172 | 2.22, 2.07 | 0.08, 0.09 |
| Phone (advait, pace 0.92) | en-IN | 156, 163 | 2.97, 3.20 | 0.07 |
| | hi-IN | 158, 170 | 2.84, 2.94 | 0.08 |
| | kn-IN | 144, 198 | 1.75, 1.71 | 0.07, 0.09 |
| Grandma Murf fallback (rate -20, pitch -8) | en / hi / kn | 219 / 214 / 173 | 2.18 / 3.26 / 1.78 | 0.03-0.06 |

Grandma: at pitch -0.1, 8 of 10 takes had a median F0 of 167-186 Hz, with occasional bright takes (226 / 240 Hz),
so `pitch` went to -0.15. As shipped, all 8 takes sit at 156-194 Hz (median 163 Hz), and she speaks at 1.76-1.91
words/s in English and Hindi against 2.0-2.15 for neha at default pace (about 12% slower). Honest limits:
`neha` is not breathy by this measure (aperiodicity ~0.04, the same as the other Sarvam women; the Murf voices and the
male voices measure 0.06-0.09), and no available voice is an actual elderly voice; the age comes from the lower
pitch, the slower pace and the way she talks (pauses, reactions, fillers). Receptionist is mid-pitch (205-253 Hz)
and brisk (~3.1 w/s); the guide is a bright, quick, youthful voice (F0 ~185 Hz with wide movement, 3.2-3.6 w/s);
the phone agent is the steadiest (F0 spread 2.0-3.6 st, the lowest of the four) at a measured ~2.9-3.2 w/s.

Roman script: Sarvam reads Roman Hinglish / Kanglish as well as native script. Round trip (TTS with `kavitha`, then
Sarvam STT, compared with the native-script text): Roman 0.97 / 1.00 / 1.00 / 1.00 character similarity, native
0.97 / 1.00 / 1.00 / 1.00 (`backend/scripts/roman_tts_check.py`). So Hinglish / Kanglish replies stay in Roman
letters on screen and are voiced with the hi-IN / kn-IN voice.

## Aged voice for Grandma (2026-11-25)

The owner heard the stock `neha` voice as still too young. Vendor re-check first (docs.sarvam.ai, Murf API docs):
Sarvam has no style / age / description / emotion field (unknown request fields are ignored); `pitch` is -0.5..0.5,
`pace` 0.5..2.0. No bulbul:v3 speaker and none of the 200+ bulbul:v4-flash personas is labelled elderly. Murf Falcon is
"Conversational" only, `pitch` / `rate` are -50..50 (our fallback already uses -8 / -20), no voice is older than
"Middle-Aged". So the age comes from (1) the lowest-F0 / slowest voice, (2) an ffmpeg post-processing chain, (3) a cloned
voice if the family provides a consented recording (below).

**Persona scan.** Every bulbul:v4-flash persona usable in en-IN (62), hi-IN (116 + 13 code-mixed) and kn-IN (4), plus all 37
v3 speakers, was synthesized in each language (pace 0.85, temperature 0.5; 306 clips) and measured (median F0, F0 spread,
words/s, frame-to-frame pitch jitter, spectral centroid, aperiodicity). Raw table: `data/voice-samples/personas/scan-all-306.json`.
Lowest-F0 *female* voices: en-IN zarina_en_conversation 173 Hz (fast, 2.7 w/s, bright), `neha` 180 Hz (1.84 w/s, centroid 313 Hz,
the slowest and darkest), then 204+ for the rest; hi-IN simran_hi_conversation 193 / simran_hi_latenight 196 (2.4-2.8 w/s,
centroid 630-880 Hz), `neha` 205 Hz (1.79 w/s, centroid 446); kn-IN `neha` 163 Hz (next 190 Hz). Every other female persona
is 200-240 Hz. The remaining low-F0 entries (135-150 Hz) are men. Verdict: `neha` stays the base voice (lowest, slowest,
darkest, and the only one that is the same speaker in all three languages); no persona is elderly. Listen-and-compare
samples are in `data/voice-samples/personas/` (named `<lang>__<model>__<persona>.mp3`).

**Post-processing chain** (`tts.age_audio`, only for the `grandma` role and her fillers; Receptionist / Guide / Phone are
untouched). ffmpeg, in this order: decode to 24 kHz mono, numpy lengthens every pause of 150 ms+ (x1.45 strong, x1.20 subtle,
max +0.5 s each), then `rubberband` (tempo 0.93, pitch x0.94 = -1.05 semitone, formant preserved so it stays one throat, not a
deeper person), `vibrato f=5.1 Hz d=0.20` (about +-27 cents wobble; measured on a pure tone), `tremolo f=4.4 d=0.10`,
`equalizer` +1.5 dB at 220 Hz (warmth), `lowpass` 6 kHz, `highshelf` -5 dB at 4.5 kHz, `acompressor` ratio 2 (less
loudness dynamics), a pink-noise breath bed at -48 dB gated by the speech (`sidechaingate`), `alimiter`. Subtle: pitch x0.98,
tempo 0.96, pause x1.2, vibrato d=0.09, lowpass 7.5 kHz, shelf -2 dB, breath -54 dB, ratio 1.4. Output is mp3 24 kHz, so
`tts.concat` still joins the clips.

Switching: env `GRANDMA_AGE_FX=off|subtle|strong` (default `strong`); per language / family with the `tts_voice_by_language`
flag: `{"hi-IN": {"age_fx": "subtle"}}` or `{"hi-IN": {"grandma": {"voice": "neha", "age_fx": "off"}}}`. The cache key carries
`agefx:<level>:v<AGE_FX_VERSION>` (now 2); bump `AGE_FX_VERSION` in `tts.py` after changing the chain and every aged clip is
re-made on next use (with `off` the key is the old one, so old plain clips are reused). If ffmpeg fails the plain clip is
used. Tune a level by editing `AGE_FX_LEVELS` and re-running `scripts/voice_age_samples.py`.

Measured (same sentence, one take each; bulbul varies take to take, so compare within a row; before / subtle / strong):

| Lang | Median F0 (Hz) | Words/s | Spectral centroid (Hz) | Energy above 4 kHz | STT similarity |
|---|---|---|---|---|---|
| en-IN | 199 / 194 / 190 | 1.85 / 1.72 / 1.60 | 319 / 318 / 321 | 0.0027 / 0.0019 / 0.0015 | 0.99 / 0.97 / 0.98 |
| hi-IN | 176 / 171 / 168 | 1.85 / 1.71 / 1.59 | 451 / 439 / 436 | 0.0033 / 0.0025 / 0.0018 | 0.96 / 0.95 / 0.95 |
| kn-IN | 163 / 161 / 155 | 1.25 / 1.15 / 1.07 | 282 / 313 / 288 | 0.0034 / 0.0036 / 0.0022 | 0.97 / 0.97 / 0.98 |

Strong is 5-6% lower in F0 and 14% slower (plus the longer pauses: 16-19 s vs 15 s for the same text; Hindi and Kannada stay
at 1.1-1.6 w/s, natural for those languages), with about 45% less energy above 4 kHz. Intelligibility: the Sarvam STT round
trip of every aged clip is 0.95-0.98 character similarity against the source text (un-aged takes score 0.96-0.99, so the chain
costs <= 0.02; the bar was 0.9). Honest limits: median F0 barely moves (the pitch shift is deliberately small so she stays a
woman), so the age is carried by the pace, pauses, wobble, dark / soft timbre and the longer breaths, and the frame-to-frame
jitter metric (10 ms) does not show a 5 Hz wobble; judge by ear with the samples
`data/voice-samples/grandma-{en,hi,kn}-{before,after-subtle,after-strong}.mp3` (`-after.mp3` = the default, strong).
`backend/scripts/voice_age_samples.py` regenerates the samples and the table.

Live sessions (Agora): Agora streams the vendor's audio straight to the user, so the ffmpeg chain cannot run on it. Instead
`agora.tts_config` shifts Grandma's Sarvam controls (`LIVE_GRANDMA_DELTA`: pace -0.05, pitch -0.08, giving pace 0.80, pitch
-0.23), which is only the lower and slower part. The browser voice path (`/api/grandma/talk`, `/api/tts`, fillers, reel
narration, phone calls without a role) all go through `tts.synthesize` and get the full aged voice.

## Cloned Grandma voice (built, off until the family records one)

Sarvam Instant Voice Cloning (beta; docs.sarvam.ai/api-reference/voice-cloning). Verified request shapes: `POST
/voices/create` multipart `file` (wav recommended; mp3/flac/opus/aac OK; 50 MB max; 10-15 s recommended, no hard minimum
documented), `name` (1-100), `language` (BCP-47 of the recording), optional `style`, `gender`,
`remove_background_noise` (default true) -> `data.voice_id` (`svc-<uuid>`, usable at once). `POST /voices/clone` multipart `text`
(max 1000 chars), `voice_id` (or a one-off `ref_audio` of <= 15 s), `language_code`, `pace`, `output_audio_codec`,
`speech_sample_rate` -> `audio_b64`. Cross-lingual: a Hindi recording can speak English and Kannada. The API has no consent
field and no model field; billing is per character on a separate `text_to_speech_voice_cloning` meter; the Starter plan
allows 50 saved voices. Our key can reach it: `GET /voices` returned 200 (0 voices) and a `/voices/clone` call with an unknown
id reached the lookup ("Voice not found"), so the request shape is accepted. No voice was created.

Memo side: `app/ai/voice_clone.py`, owner-only route `app/routes/voice_clone.py`, table `family_voices`. `POST /api/voice/clone`
(multipart: `file`, `language`, `consent=true`, `consented_by` = her name, optional `name`) stores the voice id, who consented,
the confirmed statement and the time; `GET` shows it; `DELETE` removes it at Sarvam and in Memo. When present, `tts.synthesize`
uses it first for that family's Grandma (aged-voice FX off, text split at sentence ends under 1000 chars) and falls back to the
stock voice if the clone call fails. Not recorded or cloned by us: the PRD defers cloning a real relative's voice, and there
is no consented recording.

What the owner must record: one adult woman who is the actual grandmother (or an elderly volunteer who agreed to be the
voice), told that an AI voice will be made from her recording for this family's Memo only and that it can be deleted; she
says so on the recording or in writing. A quiet room, phone held about 20 cm away, no music or fan. 30-60 s of her natural
storytelling voice (a family story with her normal pauses and laughs, not read in a flat tone), one speaker only. Sarvam
recommends 10-15 s, so the longer take lets us trim the cleanest 15 s. Language: the one she is most natural in (Hindi or
Kannada for most families); the clone speaks English too (cross-lingual) but the accent follows her. Upload as wav or mp3.

## Other Sarvam features and recommendations

| Feature | What it is | Recommendation |
|---|---|---|
| Streaming TTS (`wss://api.sarvam.ai/text-to-speech/ws`, `POST /text-to-speech/stream`) | config / text / flush messages, base64 mp3 chunks, up to 24 kHz, `min_buffer_size`, `max_chunk_length` | Worth it for first-word latency in the browser path (now one request per sentence). Not done: needs a client change to play chunks, and the aged-voice chain needs the whole clip. |
| `dict_id` pronunciation dictionary (10 dictionaries, 100 words) | fixes names and brand words | Good for family names bulbul mispronounces; build from the contact list later. |
| `enable_preprocessing` | normalizes English words and numbers | Already on for Agora. |
| `/transliterate` (en-IN to hi-IN / kn-IN, `spoken_form`) | Roman to native script | Measured (`scripts/translit_check.py`, 5 Hinglish / Kanglish sentences, STT round trip): Hindi Roman 0.974 vs native 0.978 (no gain); Kannada native scores 1.0 against its own transliteration, but the transliterator changed a word's meaning ("sutkondru" became a different word) while Roman TTS spoke the intended one. Not adopted: no measurable benefit, extra latency, meaning risk. |
| `/text-lid` language identification | language + script of a text (<= 1000 chars) | Cheap way to pick hi-IN / kn-IN / en-IN for a reply or caption; `lang.norm` is enough today. Optional. |
| Saaras v4 modes (`transcribe`, `translate`, `verbatim`, `translit`, `codemix`) | one STT call that can also translate to English | `translate` could feed English-only search; not needed yet. |
| Realtime streaming STT (WebSocket, raw PCM) | partial transcripts | Candidate if Agora is dropped; Agora does its own ASR now. |
| sarvam-105b tool calling (`tools`, `tool_choice`, JSON-schema output) | function calls from chat | Matches the receptionist's keyword actions; could replace the regex `keyword_plan`, but that is a behaviour change to test separately. |
| Instant Voice Cloning | see above | Built behind the owner route. |

## Thinking fillers

`GET /api/voice/fillers?character=grandma|receptionist&lang=en-IN|hi-IN|kn-IN|hinglish|kanglish` returns short
pre-synthesized clips (cached in `tts_cache`) in the character's own voice, for the client to play when a reply
takes longer than ~700 ms. Grandma: "Hmm, let me think...", "Achha... one second.", "Arre, yaad karne do...",
"Nodu... nenapu maadkothini." Receptionist: "Sure, one sec!", "Dekhti hoon...", "Sari, check maadtini...".
