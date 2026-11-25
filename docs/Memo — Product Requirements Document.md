# Memo — Product Requirements Document

Nov 23, 2026 · @DK

## Summary

Memo turns a family's memories of any kind, festivals included, into a walkable 3D museum that fills itself from Telegram and is run by voice: a robot receptionist takes your requests, a robot guide walks you to the room, and a grandma tells the story and answers questions without inventing anything about the family. Everything can also be done with buttons and keys.

Voice is the interface, and three ideas carry the product:

1. **Capture by chat.** A family member sends a text, voice note or photo to a Telegram bot. There is no album to sort and no app to open.
2. **The museum is a view of the memories.** Each floor is a year, each room is a month, and the lift is the navigation. A month with no memory keeps its door shut and shows a sarcastic board.
3. **Grandma.** A guide agent sits with you in the theater, can be interrupted at any moment, tells the month's story in the family's language, answers questions, and asks gentle follow-ups that grow the museum.

The sponsor stack is used where it changes the product: Sarvam hears and speaks Indian languages, Flagsmith holds the switches that make risky behaviour safe to ship, and NudgeBee operates the pipeline that must never lose a memory. Section 11 tests each of these honestly and cuts what is not earning its place.

**Status:** draft v0.2, revised to be voice-native. No user research exists yet; every target here is a hypothesis. The Three.js client is built separately, so this document defines the product, the backend and the contract between them.

## The problem

Families capture festival moments in the moment and then never find them again, because the effort of organising them falls on one person who never has time.

- **They drown.** Festival photos, voice notes and chat messages sit among thousands of other items. Finding "Diwali two years ago" means scrolling.
- **Albums need work.** Someone must sort, caption and share. That someone is usually one person, and the work does not happen.
- **The story is missing.** A photo does not say who gave the bike or why everyone laughed. That story lives in someone's head, often an elder's, and in a mother tongue that most tools handle badly.

The insight behind Memo: everyone builds nicer albums, but nobody removes the friction of filling them. If recording a memory costs one message, and the museum builds itself, the archive grows by itself.

**Evidence level: low.** This problem comes from the founder's own experience, not from research. A validation plan is in section 15.

## Who it is for

Memo has one primary user, the memory-keeper, and two supporting users who must never be forced into the web app.

| Persona | Who they are | What they do in Memo | Must never need |
| --- | --- | --- | --- |
| Memory-keeper (primary, decided) | Any family member who joins, usually whoever starts the space | Sends memories to the bot, opens the museum on a phone or laptop | To sort, caption or upload anything |
| Storyteller (secondary) | An elder or any member who prefers speaking in their mother tongue | Sends voice notes, answers Grandma's questions | The web app |
| Visitor (secondary) | A relative in another city or country, invited by the family | Joins a room's showcase, listens, reads, can leave a message | To install anything or create an account |

Decision: the users are family members. Anyone can join at any time with the space's invite code, or a whole family can join together in one go. A family can run one shared space, or each person can keep a personal space and choose what to share into the family museum. Joining never requires the web app: the invite code works inside Telegram.

In a shared space the owner sets permissions, the way a shared folder in Google Drive works. Every member gets a nickname taken from their Telegram account, which they can change, and every memory records both who sent it and who told the story.

| Role | Can do |
| --- | --- |
| Owner | Invite and remove members, set roles, edit or delete any memory, export or delete the space, transfer ownership |
| Editor | Add memories, edit or delete their own, and edit others' only if the owner allows it |
| Viewer | Walk the museum, listen to Grandma, read memories |

## Goals and non-goals

Memo succeeds if saving a memory feels effortless, the museum is a pleasure to walk, and Grandma never says anything the family did not record.

### Goals

1. **Effortless capture.** After joining, saving a memory takes one message and under 15 seconds of the user's time.
2. **A museum that grows by itself.** Every floor, room and exhibit is generated from saved memories, with no manual curation.
3. **Faithful narration.** At least 98% of sampled narrations contain no name, date or event that is not in the family's memories.
4. **No lost memories.** At least 99.5% of messages reach the saved state, and every failure is retried and visible to an operator.
5. **Locked doors that pull people back.** The sarcastic boards turn empty rooms into a reason to send a memory (hypothesis, measured in section 13).

### Non-goals

| Not doing | Why |
| --- | --- |
| Blur removal and photo enhancement | Not what makes Memo different; add after capture works. |
| Google Photos or Drive import | Third-party API access is restricted. Photos come from the Telegram bot, a local gallery folder in development, or a folder the user picks in the browser. |
| Generated reel videos | The theater screen plays a browser slideshow instead. Video generation is heavy and unvalidated. |
| One agent per festival | One guide agent over filtered memories does the same job with less to maintain. |
| Self-built media servers | Agora's managed engine, already working in MedSim, carries the audio, so Memo builds no audio path of its own. |
| Face recognition | Large privacy cost and a separate product. |
| Public sharing, feeds, social features | Memo is private by default. Visitors are invited, never public. |
| WhatsApp | Telegram first. A WhatsApp adapter is a later phase. |
| Cloning a real relative's voice | Needs a consent design of its own. |

## The museum

The museum is a view of the memory database: nothing is built by hand, and every floor, room and exhibit is generated from saved memories.

&#91;embedded content: museum cross-section · 3 floors, 12 rooms each\]

In this example February 2026 has no memory, so its door stays shut and shows a board, while the lift carries visitors between floors.

### Lobby

The ground floor is where every visit starts. It holds the reception desk with the robot receptionist, the lift, a directory board listing each year and how many of its 12 rooms are open, a plaque with the latest memory, a QR code that opens the Telegram bot, and an Attic door for memories whose date is still unknown.

### Lift

The panel has one button per year, newest on top. Pressing one starts a ride of two to three seconds, and the guided walk wraps the same ride in a 5 to 10 second scene. The ride is not decoration: it hides the loading of the next floor's textures, so floors load on demand and the building can grow without slowing the lobby.

### Floors and rooms

Each floor is a corridor with 12 doors, January to December, and a plaque showing how many are open. Floors exist from the family's first memory year to the current year. The building grows upward: the first year sits on the ground floor beside the lobby and each later year is one floor higher, so only rooms above the ground floor need the lift. A room's state comes only from the data:

| State | When | Door | Board |
| --- | --- | --- | --- |
| Open | At least one saved memory that month | Opens | None |
| Locked | A past month with no memory | Stays shut | Sarcastic line plus a prompt to tell Grandma on Telegram |
| Not yet | A future month | Stays shut | "Hasn't happened yet" style line |
| Current, empty | The current month with no memory | Stays shut | "Still loading" style line |
| Closed with care | The family chose to keep this month private | Stays shut | A neutral, kind line with no sarcasm |

### Inside a room

One room template is filled from data. Up to about six highlighted photos hang as frames on the side walls, and every memory plays on the screen. Written stories become plaques. Voice notes become a jukebox: press to play, with the transcript shown. The big screen plays the room's showcase, a slideshow built in the browser from the month's memories. One row of four seats faces the screen, and sitting down starts Grandma. Section 8 describes the theater.

### Moving around

Everything can be done by voice or by hand. Players walk with WASD or a touch joystick, open doors, press the lift panel and sit down themselves, and each of those is also a spoken request. A 2D mode shows the same data as a grid, for low-end phones, failed WebGL and accessibility.

### Tone

Memo's voice is warm and a little cheeky. Sarcasm is allowed only on empty rooms, never on what the family recorded, and any room can be switched to "closed with care". Sample board lines are in the appendix.

## Capture

Capturing a memory is sending one message to the Memo bot; everything else happens after the message is sent.

&#91;embedded content: capture flow · 1 decision\]

A clear date goes straight to its room. An unclear date triggers one tap-to-answer question, and a question left unanswered waits safely in the Attic.

1. **Join.** The family creator gets an invite link (a Telegram deep link carrying a code). Each member taps it once and is added to that family.
2. **Send.** Text, a voice note, one or more photos with an optional caption, or a forwarded message. A photo album sent together counts as one memory.
3. **Acknowledge.** The bot replies at once in Grandma's voice, so the sender knows it arrived.
4. **Process, in the background.** A voice note goes to speech-to-text, which handles Indian languages and code-mixing. A language model then extracts a title, a short summary, when it happened (year, month, day, with a confidence), the festival if any, the people named, the language and a sensitivity flag.
5. **Place.** If the date is confident, the memory lands in that month's room. If not, the bot asks one question with tap buttons (which year, which month). Until it is answered the memory waits in the Attic and is never dropped.
6. **Receipt and correction.** Every save ends with a one-line receipt such as "Diwali, Nov 2025: Dad's bike" with buttons for wrong date, wrong festival and delete. After a voice note a second row asks "Keep the voice, the words, or both?" with an "always do this" button. There is no mandatory confirmation step, because confirming would add the friction Memo exists to remove.
7. **Follow-up (optional).** Within a day Grandma may ask one question to enrich the memory ("Who gave the bike?"). The reply is appended to the same memory. The limits are one question per memory and a per-family weekly cap, and `/quiet` pauses all of it.

### Rules

- Telegram may deliver an update twice, so saving is idempotent on the update id.
- Original photos are stored untouched. After a voice note the bot asks whether to keep the voice, the words or both, and keeps both until the sender answers.
- Nothing is deleted automatically, except audio the sender chose not to keep.
- Commands: `/start`, `/museum` (replies with a sign-in link), `/quiet`, `/export`, `/help`.
- Telegram compresses photos and caps the size of files a bot can download, so videos are not in v1 (to verify against the current Bot API limits).
- Telegram voice notes arrive in OGG/Opus, so the worker converts audio with ffmpeg if the speech API does not accept that format (to verify).

## Grandma, the guide

Grandma is one agent with two jobs, narrating a room and answering questions, and about the family she may only say what has been recorded. General facts about a festival are allowed but are always labelled as general.

### Persona

Warm, patient and slightly teasing. She speaks in the family's chosen language and carries the local word for grandmother as her name (Ajji, Paati, Ammamma and so on; see the appendix). She is a character, not a copy of any real person.

### Two modes

- **Tour.** When the user sits down in the theater, the server gathers the room's memories and works out the facts in code: how many, which dates, who contributed, which festival. The model turns these into a 60 to 90 second story, text-to-speech speaks it, subtitles show it, and the screen shows each memory she mentions.
- **Talk.** The user simply speaks, or holds a button if the room is noisy, and can interrupt her at any moment. The question is transcribed and answered from the room's memories, widening to the floor or the whole museum only when the question needs it. The first spoken word should arrive within 2.5 seconds at the 95th percentile, a hypothesis to test in Phase 0.

### How accuracy is protected

1. **Facts come from code, tone comes from the model.** Dates, counts and names are inserted by the server from the database. The model only writes the connecting words.
2. **Structured output with a check.** The model returns the spoken text plus the ids of the memories it used. The server rejects ids that do not exist and any name or date not found in the supplied memories, then regenerates once. If it fails again, a plain template line is used instead.
3. **She admits gaps.** For anything not recorded she says so and offers to ask the family on Telegram, which creates a follow-up question.
4. **No advice.** No medical, legal or financial statements and no invented relationships.

### Deliberate simplifications

There is no free-running tool loop and no vector database in v1. The only lookup beyond the family's memories is one festival-facts fetch per question. Retrieval is a plain query by room, floor or family, and a family's memories for one scope fit in the model's context. If a scope grows beyond what fits, a stored month digest, regenerated when the month changes, replaces the raw list.

### Sensitive memories

The tagger flags memories about loss, illness or conflict. Grandma tells those gently and without jokes, and any memory can be marked "don't narrate".

### Language

Speech output covers fewer languages than speech input, so a family picks from the languages the voice supports. Launch languages are English, Hindi and Kannada, and Sarvam's text-to-speech lists all three (en-IN, hi-IN, kn-IN). If their language is unsupported, Grandma shows subtitles only and uses the nearest supported voice.

## The voice experience

Memo is voice-native: a whole visit can be done by speaking, and everything that can be said can also be done with buttons, keys or touch. The museum stays a normal playable game; voice is the fastest way through it.

### Principles

- **One set of actions, two ways in.** Voice is a command layer over the same actions the buttons call: create an event, import photos, go to a room, play, invite. Voice has no private powers, so nothing breaks without a microphone.
- **The server speaks the outcome.** After each action the server writes the confirmation from facts (counts, floor, room) and the model only shapes the tone. Sahay worked the same way.
- **Interruption always wins.** When the user speaks, whoever is talking stops within 300 milliseconds.
- **Ask once before anything big.** Bulk imports and phone calls are confirmed aloud first. A single save is not.
- **Three languages at launch.** English, Hindi and Kannada are understood and spoken.

### The cast

Four characters appear, and only three of them use a language model. The guide robot is an animation, not an agent.

| Character | What it is | Where | Job | What it knows |
| --- | --- | --- | --- | --- |
| Receptionist | Robot, voice agent | Reception desk in the lobby | Takes requests: create an event, add photos, go to a room, change settings | The museum's structure, the events and the gallery index. Not the content of memories |
| Guide robot | Scripted character, no model | Lobby to the room, then by the door | Walks you to the room | The route only. A few pre-recorded lines |
| Grandma | Voice agent | The theater | Greets, narrates, answers, invites people | The room's memories, plus general facts about the festival, always labelled |
| Phone agent | Voice agent on a phone call | The guest's phone | Invites a contact and takes a message | The host's name, the event title and the room's month and year. No memories |

&#91;embedded content: one visit by voice · 8 steps\]

The visit runs from the reception desk to the theater and back out through an invitation. The next sections describe each step.

### Landing and spawn

The landing page has one button, Enter the museum, which also unlocks audio and the microphone because browsers require a click first. The visitor then spawns at the reception desk in the lobby. A microphone button, a text box and captions stay on screen, so the receptionist can be reached by voice or by hand.

### The receptionist

The receptionist is a short tool loop, at most four steps per request, over a fixed list of tools, the same pattern as the front-desk agent in MedSim. The tools are create\_event, query\_gallery, import\_gallery, plan\_route and change\_setting. The model chooses a tool and fills in its arguments. The server checks every argument, runs the same action the buttons call, and writes the spoken result from the facts. If the model cannot be reached, a keyword router runs the same tools so the desk still works. The user can say a request any way they like, because the model maps wording to a tool, and anything the tools cannot do gets an honest "I can't do that here".

Dates are never worked out by the model. It returns an expression such as "yesterday" or "November 2026", and the server resolves it against today's date and the user's time zone (Asia/Kolkata by default). If two readings are close, the receptionist asks which one was meant.

| The user says | What happens |
| --- | --- |
| "I want to add a new festival called Diwali" | Intent: create event. The year and month are missing, so: "Which year and month was that?" |
| "November 2026" | The event Diwali 2026 is created and placed from its year and month: "Diwali 2026 is added. It lives on floor 2, in the November room. Want to add photos?" |
| "Upload everything from yesterday" | The server filters the gallery index: "I found 38 photos from 23 November, 112 MB. Add them to Diwali 2026?" After a yes: "Done. 38 photos are in Diwali 2026, floor 2, November room." |
| "Select all the photos" | If the match is over the batch limit, the receptionist offers the newest ones that fit and asks. |
| "Add the ones with my dad in them" | Declined honestly: "I can't recognise faces. I can choose by date, size, camera or folder." |

### Creating an event

An event has a name, an optional kind (festival, trip, birthday or other), a year and a month. The year and month decide the floor and room, using the same rule as every other memory. Several events in one month share the room and each gets its own showcase. A festival name matching a curated list (Diwali, Holi, Eid, Christmas, Pongal, Onam and others) is only used to recognise it, never required. An event with no memories yet leaves its door shut, so the receptionist says so.

### Importing photos

Photos can arrive from three places, and the receptionist works the same way for all of them.

| Source | Used for | How |
| --- | --- | --- |
| Gallery folder | Development on a laptop | A folder in the code base named in config. The server reads it and never reads outside it |
| Browser pick | Production on a laptop | The user picks a folder with the browser's directory picker (Chromium only, to verify) or selects files in any browser. The browser reads the metadata and uploads only the chosen files |
| Telegram | Phones | Unchanged, as in the Capture section |

The receptionist chooses photos by metadata only. For each file the index holds the capture date (from the EXIF data, otherwise the file date, flagged as a guess), size, dimensions, camera, folder name and a content hash. Supported filters are a date or range, file type, size, dimensions, camera, folder, "all" and "the latest N". Anything that needs looking inside the picture is declined.

- Count and size are always confirmed aloud before anything is imported.
- Duplicates are skipped by content hash.
- The size of one import is capped by a remote-config number, 200 photos by default.
- An import is a job like any other. It creates one album memory in the event, with the photos ordered by capture time, and the receptionist announces the result when it finishes.
- The album belongs to the event's month, not to the photos' own dates, so a photo taken in October still sits in the November room if the user chose it.
- Stored copies drop location data unless the owner turns it on.

### The guided walk

"Take me to the Diwali 2026 room", "go to last year's Holi" and "open March 2025" all mean the same action. The server resolves the words to a year, a month and optionally an event, asks one question if it is ambiguous ("Which year of Diwali?"), and returns a route. The client then plays a scene of 5 to 10 seconds.

| Step | Plays when | Takes about |
| --- | --- | --- |
| The guide robot steps out from the desk and says "Follow me" | Always | 1 s |
| Walk to the lift | Room is above the ground floor | 2 s |
| Ride to the floor and the doors open | Room is above the ground floor | 3 s |
| Walk down the corridor to the room's door | Always | 2 s |
| The door opens, you sit down, and the robot stays by the door | Always | 2 s |

A room on the ground floor skips the lift and takes about 5 seconds. A room higher up takes about 10.

- The server computes the route from the data (the floor from the year, the door from the month), so the client never decides where a room is.
- The scene can be skipped by tap, key or by saying "skip", and skipping places you in the seat.
- If the room is locked, the robot walks you to the shut door and the board is shown and read aloud. Nobody sits down.
- The guide robot costs nothing to run: its lines are recorded once per language and played from storage.
- With reduced motion switched on, the scene becomes a short fade.
- Every step has a manual twin: walk, press the lift panel, open the door, sit down.

### The theater

Each open room is a small theater: one row of four seats facing a big screen, a few framed photos on the side walls, and the guide robot waiting by the door. Grandma is there when you sit.

**Screen mode.** When the showcase starts, the camera moves in until the screen fills the display. The avatar and the interface disappear, leaving only subtitles and a small microphone dot, so the photos and videos use the whole display. Saying "step back" or pressing Escape returns to the seat view.

**The showcase.** The server builds a playlist from the room's memories, or from one event, in date order. A photo shows for about 6 seconds with a slow zoom and its caption. A written memory appears as a title card. A voice note plays with its transcript if the transcript was kept. An album plays its photos in the order they were taken. Short video clips are P1. The user chooses whether Grandma narrates over the showcase or it plays silently.

**Playback by voice.** Pause, resume, next, back, start over, skip voice notes, faster and "go to the bike photo" all work by voice and by key. The common commands are matched in the browser from the live transcript and a small word list in each language, with no model call, so "pause" stops at once. Anything the list does not recognise goes to Grandma.

**The other seats.** Three seats are free for invited viewers. Avatars in the seats are P1; synced viewing without avatars is P0.

### Grandma in the theater

When the user sits down, Grandma greets them with facts the server supplies, such as "Welcome back. November 2026 has eleven memories, three of them voice notes." Then she waits. The user can say "start playing my memories", ask a question, or ask her to tell the story.

**She can be interrupted at any moment.** The browser detects the user's voice and stops playback within 300 milliseconds, and the server cancels any pending model and speech work. Grandma speaks one sentence at a time, so the cut lands cleanly, and she remembers the last sentence she finished. After answering she can offer to carry on from there.

**She has two sources, and she never blends them.**

| Question about | Source | How she says it |
| --- | --- | --- |
| The family: who, what, when | The room's memories, widening to the floor or the whole museum only when needed. The same checks as before apply: invented names and dates are rejected | As a story the family told |
| The festival in general, such as "what is the essence of Diwali?" | One encyclopedia summary fetched on demand (Wikipedia, to verify) and cached per festival and language. A flag can switch it off | "That isn't from your family's memories, but..." |
| Anything else | Nothing | "I don't have that", with an offer to ask the family on Telegram |

### Inviting people

The user says "invite my girlfriend into this room", or uses her name. The steps below are the whole flow, and the example name is a placeholder.

1. **Find the contact.** Grandma looks in the family's contacts by name or relation. With no match she says so and points to the reception desk. With several matches she asks which.
2. **Confirm aloud.** "Call Priya, number ending 4417, and invite her to Diwali 2026?" Only a yes places the call, because calls cost money and interrupt people.
3. **Create the invite.** A single-use invite for this room, with viewer access, valid for 24 hours.
4. **The phone agent calls.** It says first that it is an automated assistant calling for Memo, who invited her and to which room, and asks whether she would like to join. She can ask who, what, when and how. The agent knows only the host's name, the event title and the room's month and year, so it never shares a memory with someone who has not joined.
5. **The outcome comes back.** Accepted, declined, no answer, message left, or failed. On accepted, she is sent the invite link.
6. **The theater is told at once.** A short card shows on the screen, even in screen mode: who, what they said, for about 10 seconds. Grandma reads it aloud only if asked.
7. **She joins.** Opening the link puts her in the same room as a viewer. Her screen follows the host's playback position, so both watch the same photo at the same time.

**Contacts.** The owner adds contacts at the reception desk. Phone numbers are never taken by voice, because a misheard digit calls a stranger: they are typed, or shared as a Telegram contact. The owner must tick that the person has agreed to receive calls from Memo.

**Call safety.**

- No call without the consent tick, and the first sentence always says it is an automated assistant.
- No calls between 9 pm and 8 am in the contact's local time, and at most one call per contact per hour. Both are switchable settings.
- A daily cap per family, set in remote config, and a kill switch that stops all calls at once.
- "Stop calling me" marks the contact do-not-call immediately.
- Calls are not recorded. Only the outcome and any message are stored, for 30 days.
- Phone rules are strict. Twilio trial accounts can only call [verified numbers, with 10 minutes per call and 75 minutes in total](https://www.twilio.com/docs/usage/trials/try-out-voice), and [outbound calls to India can only come from non-Indian numbers, with unconsented calls treated as unsolicited under TRAI rules](https://www.twilio.com/en-us/guidelines/in/voice). Development calls the owner's own verified number. How calls reach Indian contacts in production is an open question.

### How voice works

All in-museum voices share one turn pipeline. Each character is a configuration of it (prompt, allowed intents, voice, language), so there is one thing to build and test.

| Stage | What does it | Notes |
| --- | --- | --- |
| Hear | Agora's voice engine with Sarvam speech-to-text, language detected automatically | English, Hindi and Kannada. Partial transcripts show as captions while the user speaks |
| Understand | Receptionist: a tool loop of at most four steps. Grandma: grounded answer from the room's memories | The chat model sits behind the `llm` interface, as before |
| Act | The server runs the same action the buttons call and checks every id and date | The model never writes to the database |
| Speak | Murf Falcon or Sarvam speech, chosen per language by a Phase 0 listening test | Streamed sentence by sentence through the same Agora session |
| Interrupt | Agora's turn detection: 200 ms of the user's speech interrupts, 560 ms of silence ends a turn (MedSim's settings) | Playback stops, queued sentences are dropped, the server cancels in-flight work |

**Latency targets.** These are hypotheses to test in Phase 0, not promises: the first spoken word within 2.5 seconds at p95 for Grandma, within 1.5 seconds for common receptionist intents, and playback stopping within 300 milliseconds of the user speaking. MedSim's voice metrics code already measures each stage.

**Echo.** On laptop speakers the microphone hears Grandma. Agora's engine handles echo, and MedSim already runs it in a browser. Phase 0 retests it on laptop speakers. If echo defeats interruption, the default becomes push-to-talk, and the fallback is a browser-only voice path.

**Language.** The user picks a language once. The receptionist and Grandma answer in it, and a spoken switch such as "speak Kannada" changes it. Scripted lines exist in all three languages.

### Phone calls

Phone invites reuse the call that MedSim already runs (see Reuse from MedSim below). Twilio places the call, then asks Memo's own server for instructions one spoken turn at a time. The opening line plays inside a speech-gathering element, so the guest can talk over it and the line stops. Memo's server decides each reply, so it controls exactly what the agent can say, and no extra voice platform is needed.

1. The server places the call through Twilio's Calls API, giving a public address for the instructions and another for status updates.
2. Twilio fetches the opening line. It says it is an automated assistant calling for Memo, names the host and the event, and asks whether she would like to join.
3. Each time the guest speaks, Twilio sends the words to Memo. Memo asks the language model for a short answer (at most about 22 words, and at most six turns) that may use only the call context: the host's name, the event title and the room's month and year. Memo makes the audio and returns the next instruction.
4. The guest can ask who, what, when and how, accept, decline, or leave a message. Up to five messages are kept.
5. When the call ends, Twilio's status update records the outcome, and Memo stores it and pushes it to the theater.

**To confirm in Phase 0.** MedSim's call uses English (India) only, so Twilio's speech gathering must be tested in Hindi and Kannada, and Murf voices must be tested for all three languages on a phone line. Twilio needs a public address while developing, which MedSim gets from a tunnel. A Twilio trial account reaches only verified numbers and rejects inline instructions, so the call must use a public address, as MedSim does. If Hindi or Kannada is poor on the phone, the agent speaks English only, or the call becomes a keypad call (press 1 to accept, 2 to decline).

### Events in the theater

A server-sent events connection carries three kinds of events to the theater: call progress (dialling, ringing, talking), the call's outcome, and a message from a guest. A message appears as a card over the screen, in screen mode too, and the same event updates the invite list in the reception area.

### New switches in Flagsmith

| Flag | Type | Purpose |
| --- | --- | --- |
| `voice_enabled` | On or off | Turns all voice off for a family, leaving buttons only |
| `barge_in` | On or off | Interruption on, or push-to-talk |
| `cinematic_walk` | On or off, with a length in seconds | The guided walk, or a straight cut |
| `phone_calls_enabled` | On or off | The kill switch for all calls |
| `max_calls_per_day` | Number | Daily call cap per family |
| `phone_allowlist` | Segment | Families allowed to place calls while the feature is in testing |
| `general_knowledge` | On or off | Grandma's festival-facts lookup |
| `max_import_photos` | Number | Photos per import |

### What was left out

- **No media server.** Audio runs through Agora's managed engine, as in MedSim, so Memo builds no audio path of its own.
- **No face or object search in the importer.** It chooses by metadata only.
- **No voice-entered phone numbers.** A misheard digit calls a stranger.
- **No model-driven navigation.** The model returns an intent and a place name. The server draws the route.
- **No generated video.** The showcase is a slideshow, as before.
- **No recording of calls by default.**

### Operations

A call that never reports back, or an import that never finishes, is found by the same sweep that already looks for stuck jobs. If NudgeBee is adopted in Phase 5, these two become its first signals.

### Reuse from MedSim

[MedSim](https://github.com/DarshanKrishna-DK/MedSim) is the clinic simulator already built with Twilio, Sarvam and Three.js, and it contains most of Memo's voice and 3D plumbing. Memo should lift these pieces rather than rebuild them. The files below are the starting points.

| Memo needs | MedSim file | What it already does | What changes in Memo |
| --- | --- | --- | --- |
| Interruptible voice in the room | `backend/voice.py`, `src/voice/conversationStore.ts` | Starts an Agora Conversational AI agent with Sarvam speech-to-text (language auto-detected), a custom language model, Murf Falcon speech and voice-activity turn taking. Captions and latency numbers return over Agora's message channel | One persona per character. Grandma's context is refreshed with `/voice/context` when the room changes |
| One config per character | `src/voice/receptionistPersona.ts`, `teacherPersona.ts`, `humanVoice.ts` | A persona is a name, voice, greeting and system prompt on the same pipeline | Receptionist and Grandma personas |
| Interrupt and latency settings | `TURN_DETECTION` in `voice.py`, `src/voice/voiceMetrics.ts` | Speech for 200 ms interrupts the agent, 560 ms of silence ends the turn. Per-turn speech, model and voice latency is parsed from Agora's metrics | Use as the test harness for V7 and the latency targets |
| Receptionist | `backend/reception.py`, `src/agents/receptionAgent.ts`, `src/components/reception/` | A tool loop capped at four steps, a keyword router when the model is down, and a tool whose recipient is fixed in code | New tools: create\_event, query\_gallery, import\_gallery, plan\_route, change\_setting |
| Language model | `backend/llm_provider.py`, `llm_proxy.py` | Calls sarvam-105b-conversations with a Groq fallback. The proxy drops blank noise turns that Sarvam rejects | Same |
| Phone invite | `backend/observer_call.py`, `src/observer/observerCall.ts`, `backend/integrations/notify.py` | "Invite Darshan" finds a contact, sends the link, places a Twilio call, answers questions from a fixed context, keeps messages and shows them to the host. Checks Twilio's signature and caps calls per contact and per day | The observer becomes the invited guest and a message appears on the theater screen |
| Guest joins live | `backend/observer.py` | An invite code gives a listen-only Agora token for one session and lets the guest read the transcript | The guest watches the showcase with the host |
| Languages | `backend/lang.py` | English, Hindi and Kannada locales, Murf voices for each, filler lines and a natural "say that again" when the model fails | Add Grandma's voices and the guide robot's lines |
| Telegram | `backend/telegram_bot.py` | A long-polling bot with one question at a time per chat and inline buttons | Memo's capture flow and the voice-keep buttons. Webhook in production |
| 3D characters and player | `src/components/world/HumanCharacter.tsx`, `rigs.ts`, `retarget.ts`, `ThirdPersonPlayer.tsx` | Rigged people with idle, walk, run and sit, a shared player state, wall colliders, and a sit action on seats | The robots and Grandma reuse the rig. Four theater seats use the sit action |
| 3D building | `src/components/world/Corridor.tsx`, `corridorLayout.ts`, `src/components/three/interactions.ts` | A lobby with reception, a corridor of doors with signs, and an interaction bus for door and desk prompts | Floors and month rooms drawn from data. The lift is new |

New for Memo, with no MedSim equivalent: the lift and guided walk (MedSim has no lift or escort), the theater screen and screen mode, the museum generated from memory data, events and the gallery importer, Grandma's grounding checks, and Telegram capture of memories.

**What this changes in the plan.**

- **In-room voice uses Agora, as MedSim does.** This reverses the earlier choice of browser-side voice detection. Agora's managed engine already gives interruption and echo handling and is built, and it returns the latency numbers the targets need. The costs are a per-minute fee and one more vendor, so the browser-only path stays as a fallback.
- **The phone agent uses Twilio with Memo's own server, not Sarvam Voice Agents.** It is proven on a trial account and gives full control of what is said.
- **Speech output is Murf or Sarvam.** MedSim uses Murf Falcon voices, including Hindi and Kannada. Sarvam's voices remain a candidate, and a listening test in Phase 0 chooses per language.
- **The receptionist is a bounded tool loop,** not a single structured call.
- **Language model:** sarvam-105b-conversations with a fallback, as in MedSim.

Three short excerpts show the shape of the code. They are trimmed from `backend/voice.py` and `backend/observer_call.py`.

```python
# backend/voice.py: the Agora agent's listening, thinking and speaking
"asr": {"vendor": "sarvam", "params": {"api_key": sarvam_key, "language": "unknown"}},
"llm": _llm_block(req.systemPrompt, req.initialLine, lang=lang),
"turn_detection": {"mode": "default", "config": {
    "speech_threshold": 0.6,
    "start_of_speech": {"mode": "vad", "vad_config": {"interrupt_duration_ms": 200, "prefix_padding_ms": 800}},
    "end_of_speech": {"mode": "vad", "vad_config": {"silence_duration_ms": 560}}}},
"tts": {"vendor": "murf", "params": {"voiceId": voice, "model": "FALCON", "locale": locale, "sample_rate": 24000}},
```

```python
# backend/observer_call.py: place the call. Trial accounts need a public Url, not inline TwiML
form = {"From": voice_from(), "To": phone, "Url": twiml_url, "Method": "POST",
        "StatusCallback": status_url,
        "StatusCallbackEvent": ["initiated", "ringing", "answered", "completed"], "Timeout": "30"}
r = await client.post(TWILIO_CALLS_URL.format(sid=sid), data=form, auth=(sid, auth))
```

```python
# backend/observer_call.py: the line plays inside Gather, so the guest's speech cuts it off
'<Gather input="speech" language="en-IN" speechTimeout="auto" actionOnEmptyResult="true" '
f'action="{turn_url}" method="POST">' + f"<Play>{audio_url}</Play>" + "</Gather>"
```

In Memo the Gather language follows the contact's language (hi-IN or kn-IN), which Phase 0 must test.

### Voice requirements (P0)

These rows belong to the P0 list in section 9 and use the same ID scheme. The thresholds are hypotheses and are tested in Phase 0 and Phase 3.

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| V1 | Voice never required | With the microphone blocked, a tester creates an event, adds photos, goes to a room, plays the showcase and sends an invite using buttons and keys only. |
| V2 | Receptionist creates an event | From 20 phrasings across English, Hindi and Kannada, the right intent is chosen at least 90% of the time. A missing year or month is asked for, never guessed. The event lands on the correct floor and room. |
| V3 | Photo import by voice | On a folder of 300 test photos with known dates, "yesterday", "all" and "the last 20" each select exactly the expected set. The count is confirmed aloud before import, duplicates are skipped, and the result is announced with floor and room. |
| V4 | Guided walk | "Take me to Diwali 2026" plays a 5 to 10 second scene, with no lift for ground-floor rooms. It ends seated in the room with the guide robot by the door. A skip works at any moment. |
| V5 | Theater and screen mode | Each open room has four seats and a screen. Starting the showcase fills the display with the screen, with no avatar and no interface. "Step back" or Escape returns to the seat. |
| V6 | Showcase control by voice | Pause, resume, next, back and start over respond within 1 second of the user finishing the word, because the client matches these words from the live transcript without a model call. |
| V7 | Grandma can be interrupted | While she speaks, the user's voice stops her audio within 300 ms at p95. The next question is answered, with no overlapping audio. |
| V8 | Grounded plus labelled general knowledge | On 30 test questions about the family, no invented person, date or event is spoken. General festival answers are labelled as not from the family's memories. An unrecorded fact gets "I don't have that". |
| V9 | Voice invite by phone | A call needs the contact's consent tick and a spoken yes from the host, states that it is automated and is blocked outside 8 am to 9 pm. "Stop calling me" marks the contact do-not-call. The kill switch stops a call in progress from being placed. |
| V10 | Call outcome and message on screen | The outcome and any message show on the theater screen within 5 seconds of the call ending, including in screen mode. |
| V11 | Telegram voice-note choice | After a voice note the bot offers keep voice, keep words or both. A choice of words only deletes the audio once transcription is saved. An "always do this" choice is remembered per member. |
| V12 | Three languages | The receptionist, Grandma, the guide robot's lines and the phone agent work in English, Hindi and Kannada, or say clearly that a language is unavailable. |

## Requirements

The P0 list is the smallest product that delivers the promise: send a memory, say where you want to go, and hear Grandma tell it truthfully. The voice requirements V1 to V12 are in section 8 and are also P0.

### P0: must ship

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| C1 | Join a family by invite link | A valid link adds the user to exactly one family and shows a welcome in the family's language. An expired or used code gives a clear message. |
| C2 | Accept text, voice, photo, photo album, forwarded message | Twenty mixed messages produce twenty memories with originals stored. Redelivery by Telegram creates no duplicate. |
| C3 | Transcribe voice notes | A voice note up to 2 minutes is saved with transcript and detected language within 30 seconds at the 95th percentile. |
| C4 | Extract date, festival and people | On a labelled set of 50 memories the month is correct at least 90% of the time when stated. When not stated, the bot asks instead of guessing. |
| C5 | Receipt with correction buttons | Tapping wrong date moves the memory to the correct room within 5 seconds. |
| C6 | Attic for undated memories | Undated memories are visible in the lobby and asked about once, then wait. None are lost. |
| M1 | Museum generated from data | With five years of test data, rooms are open exactly where saved memories exist, and boards match each state. |
| M2 | Lift and floors with lazy loading | The panel lists every year with data plus the current year. A manual ride takes at most 3 seconds, and the guided walk takes 5 to 10 seconds and can be skipped. Floors load on demand. |
| M3 | Room exhibits | Side-wall frames, plaques and the voice jukebox work. The four-seat theater and its screen play any number of memories. |
| M4 | 2D fallback | All data is reachable without WebGL. A flag and an automatic WebGL check switch to it. |
| M5 | Closed with care | A family can mark any month closed, and its board shows a neutral line with no sarcasm. |
| G1 | Tour narration | Every open room narrates in 90 seconds or less with subtitles. In a 30-room review no invented name or date appears. |
| G2 | Talk mode | At least 90% of 50 test questions about recorded facts are answered correctly. Unrecorded facts get an honest "I don't have that". She can be interrupted (V7), and general festival answers are labelled (V8). |
| A1 | Sign-in by link from the bot | `/museum` returns a single-use link valid for 15 minutes. Only family members can open a family's museum. |
| A2 | Private by default and export | No media is reachable without a short-lived signed URL. `/export` delivers all memories and media. |
| F1 | Runtime switches | Flipping `museum_3d`, `proactive_followups``, llm_model, voice_enabled or phone_calls_enabled` changes behaviour in production within one minute, with no deploy. |
| O1 | Reliable processing | Killing the worker mid-job leaves the job to finish after restart. Failed jobs are listed for an operator. |

### P1: fast follows

- Follow-up interviews with an A/B test of wording.
- Festival-aware nudges before major festivals, using a curated festival list.
- Invited viewers sit in the other three seats with avatars and watch together.
- Caption translation for visitors.
- Semantic search for "the one with the bike", only once memory counts require it.
- Short video clips.
- Month digests for large scopes.
- Neutral boards for empty months in a year that holds a sensitive memory.

### P2: designed for, not built

- A WhatsApp adapter.
- Voice chat between invited viewers in the theater.
- A consenting relative's own voice for Grandma.
- A printed or PDF memory book.
- Museums shared between cousin families.
- Photo quality tools and generated reels.

## Data model and API contract

Floors and rooms are not stored; they are computed from the year and month of saved memories, so the museum can never disagree with the data.

### Tables

| Table | Key fields |
| --- | --- |
| families | id, name, language, grandma\_name, settings, created\_at |
| members | id, family\_id, telegram\_user\_id, nickname (taken from the Telegram account, editable), role (owner, editor or viewer), language, voice\_keep\_default (voice, words, both or unset), joined\_at |
| memories | id, family\_id, event\_id (nullable), author\_id (who sent it), teller\_id (who told the story, defaults to the sender), kind, text\_original, language, summary, event\_year, event\_month, event\_day (nullable), date\_confidence, festival, people, sensitivity, narrate\_ok, status, captured\_at, source\_update\_id (unique) |
| media | id, memory\_id, type (photo or voice), audio\_kept (true or false), storage\_key, thumb\_key, duration\_s, transcript |
| followups | id, memory\_id, question, variant, asked\_at, answered\_at, answer\_text |
| room\_settings | family\_id, year, month, mode (auto or closed\_with\_care) |
| jobs | id, type, payload, status, attempts, run\_at, last\_error |

The voice experience adds these tables.

| Table | Key fields |
| --- | --- |
| events | id, family\_id, name, kind (festival, trip, birthday or other), year, month, created\_by, created\_at. Several events may share one year and month |
| gallery\_items | id, family\_id, source (folder or browser), path\_or\_handle, taken\_at, taken\_at\_source (exif or file date), size\_bytes, width, height, camera, folder, content\_hash, imported\_memory\_id (nullable). One row per photo seen in a gallery, so filters never read the files again |
| contacts | id, family\_id, name, relation, phone\_e164, consent\_to\_calls (true or false), consent\_by, consent\_at, do\_not\_call, timezone |
| invites | id, family\_id, contact\_id, event\_id, year, month, role (viewer), token\_hash, expires\_at, used\_at, status |
| call\_sessions | id, invite\_id, provider\_call\_id, status (queued, ringing, talking, accepted, declined, no\_answer, message\_left, failed), outcome\_summary, message\_text, started\_at, ended\_at, cost\_inr |

The `jobs` table is a plain Postgres queue: workers claim rows with `SELECT ... FOR UPDATE SKIP LOCKED`. Photos get a 512 px thumbnail and a 1600 px version at upload so the 3D client never loads originals.

### What the 3D client calls

The server picks board text and decides room state, so copy can change without a client release. Board text is chosen deterministically from the family, year and month, so a room shows the same line on every visit.

| Endpoint | Returns |
| --- | --- |
| `GET /m/{token}` | Sets a session cookie from the sign-in link, then redirects to the museum. |
| `GET /api/museum` | Family name, language, Grandma's name, the list of floors with open and total room counts, the Attic count, the latest memory, and the client flags (`museum_3d` and others). |
| `GET /api/museum/{year}` | Twelve rooms, each with month, state (open, locked, not\_yet, current\_empty, closed), memory count, hero thumbnail, festival and board text. |
| `GET /api/museum/{year}/{month}` | Exhibits with id, kind, thumbnail and full URLs, title, text, author, event date, transcript, audio URL, and a page cursor. |
| `POST /api/grandma/tour` | For a room: spoken text, audio URL, subtitle timings, and highlights that name which memory to look at and when. |
| `POST /api/grandma/talk` | For recorded audio and a scope: the transcript, reply text, audio URL and highlights. |

The voice experience adds these calls. Every voice intent ends in the same calls the buttons use, so the museum can be driven with no microphone.

| Endpoint | Returns |
| --- | --- |
| POST /api/voice/start | Starts an Agora voice session for the receptionist or Grandma and returns the channel and tokens. POST /api/voice/stop ends it and POST /api/voice/context refreshes the character's context. Captions and action results return over Agora's message channel. Typed requests use POST /api/reception/act, which runs the same tool loop |
| POST /api/events | Creates an event from a name, kind, year and month. Returns the event and its floor and room |
| POST /api/gallery/scan | Reads the configured gallery folder, or accepts metadata sent by the browser, and updates the gallery index |
| POST /api/gallery/query | A structured filter (dates, size, camera, folder, all, latest N) in, and a count, total size and preview token out. Nothing is imported |
| POST /api/gallery/import | A preview token and the event in, and a job id out. The token proves the count was confirmed |
| POST /api/route | A year and month, or an event name, in, and a route out: the floor, whether the lift is needed, waypoints and the door |
| GET /api/showcase/{year}/{month} | The playlist for the room or one event: items, durations, captions and transcripts kept |
| POST /api/contacts | Adds a contact with the consent tick. Numbers are typed, never spoken |
| POST /api/invites | Creates an invite for a contact and a room. Returns the invite and the spoken confirmation text |
| POST /api/invites/{id}/call | Places the call after the host's confirmation. Refused by the kill switch, daily cap, quiet hours, or a missing consent |
| POST /webhooks/voice-agent | The signed result from the calling platform: outcome, summary and message |
| GET /api/stream | Server-sent events: call progress, call outcome and guest messages for the theater |

All media URLs are short-lived signed URLs. The family comes from the session, never from a request parameter.

## Architecture and tech decisions

The simplest architecture that meets the requirements is one API service, one worker, Postgres, object storage and the Telegram Bot API, with Sarvam and a language model as outside calls.

&#91;embedded content: system architecture · 3 outside services\]

Telegram and the browser both enter through the API. Slow jobs run in the worker from a Postgres queue, both call Sarvam, and both use object storage. NudgeBee is dashed because it joins in Phase 5.

### Stack

- **Client:** React, TypeScript, Vite and Three.js, the same stack as MedSim, so the 3D patterns carry over.
- **Backend:** Python with FastAPI, one codebase run as two processes, `api` and `worker`.
- **Data:** Postgres for everything including the job queue, and S3-compatible object storage for photos and audio. Pillow makes thumbnails and ffmpeg converts audio.
- **Telegram:** the official Bot API through a webhook in production, with a secret token on the webhook.
- **AI:** Sarvam for speech in and chat, Murf or Sarvam for speech out, Agora for live voice sessions and Twilio for phone calls, behind a single `llm` interface so the model can change without touching the product.
- **Hosting:** a managed platform through Phase 4, Kubernetes from Phase 5 (see NudgeBee below).

**Voice and live events.** The browser joins one Agora voice session per character it is talking to, and live captions and latency numbers come back over Agora's message channel. The theater listens to one server-sent events stream for call progress and guest messages. A phone call is placed through Twilio, and Memo's own server answers Twilio's requests one turn at a time. The worker never touches audio.

### What was cut, and why

| Cut | Why it is not needed | Comes back when |
| --- | --- | --- |
| A self-built real-time voice path | Agora's managed engine, already working in MedSim, handles listening, interruption and speaking | Agora's cost or terms rule it out |
| Vector database | One family's memories for a room or floor fit in the model's context | A scope outgrows the context, around 150 memories |
| Message broker or workflow engine | A Postgres jobs table handles this volume | Throughput or multi-step workflows outgrow it |
| One agent per festival | One agent plus filtered data does the same | Not expected |
| Tool-calling agent loop | The receptionist is bounded: at most four tool steps, a fixed tool list and server-side checks, so no free-running loop is needed | Questions that need real multi-step search |
| Microservices | A modular monolith is faster to build and debug | A team boundary forces it |
| Separate auth provider | A sign-in link sent through the bot is enough | Email or web sign-up becomes a requirement |

### Do the sponsor tools earn their place?

**Sarvam**

| Part | Used for | Without it | Verdict |
| --- | --- | --- | --- |
| Speech-to-text | Voice notes in Indian languages, including code-mixed speech, and live speech to the receptionist and Grandma through Agora, as in MedSim | A general speech model might work but is untested on this speech | Keep, core |
| Text-to-speech | The receptionist's and Grandma's voices in the family's language. MedSim uses Murf Falcon for this | Subtitles only, which removes the character | Conditional. A Phase 0 listening test against Murf, which MedSim already uses, decides per language. Sarvam's supports fewer languages than its speech-to-text |
| Chat model | Writing narration and answers in Indian languages, and choosing the receptionist's tools | Any capable model, if quality is equal | Conditional. Choose by test in Phase 0 and switch with a flag. Sarvam's current docs point to sarvam-105b, which lists structured output and tool calling; sarvam-m is deprecated |
| Translation | Showing captions to visitors in another language | A general model can translate | P1, only if the test shows it is better |
| Document vision, voice cloning | Not used |  | Out of scope |

**Voice Agents** is Sarvam's managed platform for voice calls. The first plan does not use it, because MedSim's Twilio call already does the same job with the same pieces and gives Memo full control of what the agent says. It stays a fallback if Twilio's speech gathering is poor in Hindi or Kannada.

**Flagsmith.** Each flag below is something we would genuinely want to change in production without a deploy.

| Flag | Kind | Why it must be switchable at runtime |
| --- | --- | --- |
| `museum_3d` | Boolean, targeted by device tier | If 3D misbehaves, fall back to the 2D mode at once. Low-end phones start in 2D |
| `proactive_followups` | Boolean with percentage rollout | Grandma messaging people unprompted is the riskiest behaviour, so roll out slowly and kill instantly |
| `followup_variant` | Multivariate | Two wordings of the follow-up question. The outcome, reply rate, is counted in our database. Meaningful only with enough families, so P1 |
| `llm_model` | Remote config, text | Swap the narration model without a deploy when quality or cost shifts |
| `tts_voice_by_language` | Remote config, JSON | Replace a voice that sounds wrong without a deploy |
| `max_followups_per_week` | Remote config, number | Tune how chatty Grandma is |

The voice experience adds eight flags, listed in section 8: voice\_enabled, barge\_in, cinematic\_walk, phone\_calls\_enabled, max\_calls\_per\_day, phone\_allowlist, general\_knowledge and max\_import\_photos. The call switches are the strongest case in the plan for runtime control, because a misbehaving agent must stop at once and a redeploy is too slow.

The rule: flags hold switches and dials, not data. The festival list, board copy and persona names stay in the database or code. Putting them in flags would use Flagsmith in name only. Verdict: keep.

**NudgeBee** is the weakest fit, so the honest position is conditional. It is an AI operations tool for Kubernetes and cloud accounts, and Memo as designed would run happily on one managed service with no Kubernetes at all.

The case for it is real but narrow. Memo's promise is that no memory is lost, memories arrive in bursts on festival nights, and the recovery actions (replay failed jobs, restart or scale the worker) are what approval-gated runbooks are for. So from Phase 5 the API, worker and web run on a small Kubernetes cluster and NudgeBee is connected to it.

Three limits apply. NudgeBee sees infrastructure, not Sarvam or model spend. Self-hosting it needs several services of its own, and its public README lists Postgres, Redis, RabbitMQ, Qdrant and Temporal. Its website lists a hosted cloud option with a free trial and no-code runbooks with approval gates, so Memo need not self-host it. The docs I could read did not show an API, though the site says it extends through MCP, so Phase 0 confirms what Memo can call.

**Decision gate:** if the Phase 5 failure tests show NudgeBee cannot diagnose them, run on a managed platform instead of keeping it for show.

## Build plan by phase

The plan builds the data and capture first, because the museum and Grandma are only views of it, and puts every risky assumption into a test before it becomes a feature.

Sizes are relative (S, M, L) because team capacity and dates are not known. Each phase ends at an exit gate; if a gate fails, fix it before starting the next phase.

&#91;embedded content: roadmap · 7 phases, 3 gates\]

Phases 1 to 5 each end at an exit gate listed in the table below. The three marked gates can change the plan, not only delay it.

| Phase | Scope | Exit gate | Size |
| --- | --- | --- | --- |
| 0. Spikes | Speech-to-text on 20 real voice notes in the family's languages. A listening test of the speech voices. A narration test of Sarvam's chat model against one alternative on 10 synthetic rooms, scored by an entity check. The Telegram voice-to-text path including ffmpeg. A Three.js greybox of a 12-door corridor on a mid-range Android phone. Install and capability checks for NudgeBee and Flagsmith. Voice spikes: port MedSim's Agora voice session with a receptionist and a Grandma persona and test interruption on laptop speakers, a listening test of Murf and Sarvam voices in all three languages, MedSim's Twilio call to a verified number with Hindi and Kannada speech gathering, Twilio's rules for Indian numbers, and the browser folder picker on Chrome and Safari. | A one-page go or no-go note per spike. The language model is chosen. NudgeBee's API and runbook support are confirmed or ruled out. The voice path is chosen: interruption or push-to-talk, the speech vendor for each language, and a spoken or keypad phone call for each language. | S |
| 1. Capture core | The bot, invites, memories, media, the Postgres job queue, speech-to-text, tagging, receipts and correction, the Attic, sign-in links, and a plain 2D list page as ground truth. Flagsmith SDK wired with `llm_model`. Events, contacts, the gallery index and the photo importer. | 50 mixed messages land in the right rooms. Killing the worker mid-job loses nothing. A redelivered update creates no duplicate. Three date filters on 300 test photos select exactly the expected sets. | M |
| 2. The museum | Lobby with the reception desk, lift, floors, rooms in all five states, boards, side-wall exhibits, the four-seat theater with its screen and screen mode, the showcase slideshow, the guided walk with the guide robot, the 2D fallback with the `museum_3d` flag, signed media URLs and thumbnails. | Ten floors of 12 rooms with synthetic data run at 30 frames per second or better on a mid-range Android phone. A manual floor change takes 3 seconds or less, and the guided walk takes 5 to 10 seconds and can be skipped. Every step also works by hand. The 2D mode is complete. | L |
| 3. Grandma | The shared voice pipeline, the receptionist (create event, import photos, go to a room), interruptible Grandma in tour and talk modes, the grounding checks, labelled festival facts, voices and persona per language, subtitles, and an evaluation harness. | In a 30-room review no name or date is invented. At least 90% of 50 test questions are answered correctly. The first spoken word comes within 2.5 seconds at p95, and speech stops within 300 ms when the user talks. At least 90% of 20 receptionist phrasings in each language choose the right intent. | M |
| 4. Loop and controls | Follow-up interviews, festival nudges, Attic reminders, closed with care, the sarcasm switch, phone invites with messages on the theater screen, the follow-up A/B test and the `proactive_followups` rollout. | A pilot with about 10 families for 4 weeks. Follow-up answer rate and opt-outs are measured. The kill switch is tested in production. One real call to a consenting tester completes end to end, and the call kill switch stops the next one. | M |
| 5. Operate | Move to Kubernetes, connect NudgeBee, add approval-gated runbooks (replay failed jobs, restart and scale the worker), alerts, backups and a festival-night burst test. | Induced failures (worker out of memory, speech API errors, queue backlog) are diagnosed correctly and recovered through an approved runbook with no lost memory. Otherwise the decision gate in section 11 applies. | M |
| 6. Launch readiness | Onboarding with a demo museum, privacy notice, export and delete, a name and domain check, and native-speaker review of board copy and persona names. | Ten families onboard without help. Provider terms are reviewed, and the calling terms of Sarvam and Twilio are confirmed in writing, including calls to India. | S |

The burst test size is a parameter to set after the pilot, from how many memories a family really sends on a festival night.

## Success metrics

Every target below is a hypothesis with no baseline; set the real thresholds after a pilot with about ten families.

| Metric | Kind | Target | How measured |
| --- | --- | --- | --- |
| New families whose creator sends a memory within 24 hours | Leading | 70% | Join and first memory events |
| Families with two or more members within 7 days | Leading | 50% | Members table |
| Time from sending a voice note up to 60 seconds to saved | Leading | 30 seconds at p95 | Job timestamps |
| Messages that reach the saved state | Leading | 99.5% or more | Jobs table |
| Narrations passing the faithfulness review | Leading | 98% or more | Weekly sample of 30 |
| Grandma reply time | Leading | First spoken word in 2.5 seconds at p95 | API timing |
| Follow-up questions answered | Leading | 30% | Followups table |
| Past-year rooms open after 90 days | Lagging | 50% | Room states |
| Active families visiting the museum monthly | Lagging | 60% | Session events |
| Families with a memory in the last 30 days, at day 90 | Lagging | 40% | Memories table |
| Narrations rated down | Guardrail | 5% or less | Thumbs on each narration |
| Families that switch Grandma's questions off | Guardrail | 10% or less | `/quiet` use |

The voice experience adds these targets. They are hypotheses to set properly after the pilot.

| Metric | Kind | Target | How measured |
| --- | --- | --- | --- |
| Receptionist requests that choose the right intent | Leading | 90% or more | A labelled set of phrasings per language |
| Time from the user speaking to Grandma stopping | Leading | 300 ms at p95 | Client timestamps |
| Photo imports confirmed after the count is read out | Leading | 80% or more | Gallery import events |
| Guided walks skipped | Guardrail | 40% or less | Walk events. If higher, the scene is too long |
| Phone invites that reach an outcome other than failed | Leading | 70% or more | call\_sessions |
| Do-not-call requests and complaints | Guardrail | 0 complaints | call\_sessions and support |
| Voice notes kept as words only | Leading | Recorded | Members table. This shows whether families want the audio |

## Privacy, safety and sensitivity

These are family photos and the voices of elders, so Memo is private by default and every sensitive moment has an owner-controlled exit.

- **Private by default.** No public URLs. Access is by invite only. Media is served through short-lived signed URLs. The family always comes from the session, never from the request.
- **Sign-in.** Links come from the bot, are single-use, and expire after 15 minutes. Telegram webhooks carry a secret token and are rate limited.
- **Consent.** Joining a family shows what is stored and where it is sent. Audio and text go to Sarvam, to the language model provider and, for voice and calls, to Agora, Murf and Twilio, so their retention and training terms must be checked before launch (open question).
- **Ownership.** `/export` returns everything. Deleting a family removes its database rows and media.
- **Children.** Photos of children are private to the family. There is no face recognition.
- **Sensitive memories.** The tagger flags loss, illness and conflict. Narration of those is gentle and has no jokes, and any memory can be marked "don't narrate".
- **Sarcasm safety.** Sarcasm appears only on empty rooms. Any room can be set to closed with care, and the family can turn sarcasm off entirely.
- **Voices.** Memo does not clone a real person's voice in v1.
- **Abuse.** Invite codes are long and random, file sizes are limited, and per-user rate limits apply to the bot.

* **Microphone.** The microphone is open only while a voice session is active, a visible indicator shows it, and audio is not kept after it has been transcribed unless the sender chose to keep a voice note.
* **Photo folders.** Only the folder the owner picks is read. The server stores metadata and the photos the user imports, and location data is dropped from stored copies unless the owner turns it on.
* **Phone calls and contacts.** A contact is called only with a recorded consent tick. The agent says it is automated, calls are not recorded, only the outcome and any message are kept for 30 days, and the contact can say "stop calling me" at any time.
* **What a guest is told.** The phone agent knows the host's name, the event title and the month and year, and nothing else. It never describes the family's memories to someone who has not joined.
* **General knowledge.** A festival-facts lookup sends the festival name only, never family content.

## Risks and open questions

The biggest risks are whether families will use Telegram, whether 3D runs well on ordinary phones, and whether NudgeBee earns its place.

### Risks

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Families live on WhatsApp, not Telegram | Capture only works where people already are | Test with five families first. Forwarding to the bot works from any chat. A WhatsApp adapter is P2 |
| 3D is slow on low-end phones | Walking the museum is the core experience | Instancing, a texture budget, lazy floors and a 2D fallback behind a flag |
| Narration invents facts | One invented detail destroys trust in a family archive | Grounding rules, the entity check and an evaluation gate in Phase 3 |
| Speech accuracy on regional, code-mixed or elderly voices | A bad transcript becomes a wrong memory | A Phase 0 test with real notes, transcripts shown in receipts, correction buttons |
| An empty museum feels punishing on day one | Locked doors everywhere at the start | A demo museum at onboarding, gentle copy, and a switch to turn sarcasm off |
| Elders will not use Telegram | The storyteller is the most valuable voice | A relative can forward their voice notes. See the question on speaker below |
| NudgeBee adds cost without value | The highest risk of using a sponsor in name only | Phase 0 pre-check and the Phase 5 decision gate |
| Wrong dates | A memory in the wrong room | Ask when unsure, show receipts, offer correction buttons |
| Provider data terms | Family data goes to outside services | Review terms before launch and disclose them when joining |
| "Memo" is a crowded name | Hard to find and a possible conflict | Search domains, app stores and trademarks before launch |

The voice experience adds these risks.

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Echo defeats interruption on laptop speakers | Interruption is the headline feature of the voice experience | Agora's engine, already used in MedSim, a push-to-talk fallback, and a laptop-speaker test in Phase 0 |
| Speech misheard as an action | A wrong event or import is annoying, a wrong call is worse | Fixed intent list, schema checks, spoken confirmation before imports and calls, undo for events |
| Phone agent says something wrong or goes off script | It speaks for the family to an outsider | Fixed instructions, minimal context, an AI disclosure, no memories, a kill switch and a keypad fallback |
| Calling Indian numbers is restricted | Twilio's India rules require non-Indian caller numbers and consented calls | Consent tick, development calls to a verified number, legal review before launch |
| Twilio's speech gathering is weak in Hindi or Kannada | The guest is misheard and the call fails. MedSim's call is English only | Phase 0 test, then English-only calls or a keypad call |
| Agora, Murf and Twilio add per-minute costs and their own terms | Three more vendors handle family voices and phone numbers | Review terms before launch, cap minutes with flags, and keep a browser-only voice path as a fallback |
| Folder picker is Chromium only | Safari and Firefox users cannot pick a whole folder | A multi-file picker fallback and the Telegram path |
| The guided walk becomes slow on a second visit | A 10 second scene repeated daily annoys | Skip by tap or voice, and a setting to shorten it after the first few uses |

### Open questions

| Question | Owner | Blocking? |
| --- | --- | --- |
| Is Memo only for festival memories, or any memory? Decided: any memory. Festivals are an event type, and an event gets its own showcase on the theater screen | Decided | Before Phase 1 |
| Which NudgeBee API or MCP endpoint can Memo's runbooks call? Hosted cloud and approval gates are confirmed on its site; the API is not | NudgeBee docs | Before Phase 5 |
| Does sarvam-105b follow a JSON schema reliably on Kannada and Hindi input? Its docs list structured output, but tagging quality is untested | Engineering, Phase 0 | Before Phase 3 |
| Confirm provider terms in writing, including Agora, Murf and Twilio. Sarvam's developer page says API inputs are not used for training and are deleted after processing, but one third-party summary says its terms allow training as the law permits. Anthropic's API deletes inputs within 30 days and does not train on them under commercial terms. Until an API key is in use, build with test data only | Legal | Before launch |
| Bots can download only 20 MB through the public Telegram Bot API. Run a local Bot API server (no download cap) so family videos work? | Engineering | No |

The voice experience adds these questions.

| Question | Owner | Blocking? |
| --- | --- | --- |
| Does Twilio's speech gathering understand Hindi and Kannada well enough for the phone agent? MedSim's call is English only | Engineering, Phase 0 | Before Phase 4 |
| How can Memo call Indian numbers legally and affordably in production, given Twilio's non-Indian caller number rule and consent requirement? | Legal and engineering | Before launch |
| Which speech vendor sounds best in Hindi and Kannada for Grandma, Murf or Sarvam? | Engineering, Phase 0 | Before Phase 3 |
| Which source supplies general festival facts, and does it cover Kannada and Hindi well enough? Wikipedia is the first candidate | Engineering, Phase 0 | No |
| Should an invited guest only watch, or also add a memory from the theater? | Product | No |
| Should the guide robot and the receptionist share one design or look different? | Design | No |

### Validation before building much

Build one family's museum by hand from their real festival messages and show it to five families. Run eight to ten short interviews on how families store and revisit festival memories. If few of them ever look back at old photos, the problem is weaker than assumed and the plan should change.

## Reference projects

These are the closest projects I found. Searching Reddit directly returned nothing relevant, so every link below comes from GitHub, Devpost, forums and project pages. None of them, in what I could see, pairs chat capture, a spoken guide and a calendar-shaped building like Memo's floors and month rooms.

| Project | What it does | What to take from it | Links |
| --- | --- | --- | --- |
| Mnemosyne (CalgaryHacks 2026) | Turns uploaded photos, text and audio into a first-person 3D museum, with exhibits grouped by theme | The closest match. Its own next step was one gallery per cluster, which Memo already has as month rooms | [Devpost](https://devpost.com/software/mnemosyne-memory-made-spatial), [GitHub](https://github.com/ZainKhan708/calgaryHacks2026) |
| MindSpace | An LLM places each memory in a room and generates a walkable 3D world per room | A memory-palace take on rooms and objects at eye level | [GitHub](https://github.com/Nazym-MU/la-hack), [live site](https://mindspace-dun.vercel.app), [demo video](https://youtu.be/9xrII0xIUzk) |
| Photo to World | A WebXR gallery of 18 lit photo frames in a 20 by 20 metre room, built on Three.js | A small Three.js photo gallery that runs in a phone browser | [Live demo](https://papaya-longma-d02e97.netlify.app/), [poster](https://immerse.illinois.edu/symposium-posters/82378) |
| Virtual art museum | A Three.js gallery with an Express backend where people upload and browse artwork | Upload, storage and annotation wiring for a gallery | [GitHub](https://github.com/PaulleDemon/art-museum), [write-up](https://dev.to/paul_freeman/art-museum-g99) |
| LinkWalk | A 3D museum whose rooms are filled on the fly from the Wikipedia API | Proof that rooms can be computed from data, as Memo's rooms come from the database | [GitHub](https://github.com/notbigmuzzy/linkwalk), [write-up](https://dev.to/nbm/virtual-3d-museum-threejs-1n5k) |
| 3D art gallery tutorial | A step-by-step Three.js gallery with frames, lighting and movement | A starting point for the greybox and walking controls | [GitHub](https://github.com/theringsofsaturn/3D-art-gallery-threejs) |
| The Museum of All Things | An endless walkable museum where each exhibit is a Wikipedia article, made in Godot | Shows that a generated, ever-growing museum feels natural to walk | [Interview](https://godotengine.org/article/museum-of-all-things/) |
| Personal photo album | A Three.js flipping photo album set on a cosy desk | Warmth and small-object detail for the room exhibits | [Forum post](https://discourse.threejs.org/t/customizable-flipping-photo-album/94153) |
| Revisitation | A research project on a VR archive of embodied family memory across generations | Research on how families share memory, useful for Grandma's design | [Paper](https://openresearch.ocadu.ca/id/eprint/4993/1/Revisitation.pdf) |

## Appendix

The board lines below set the tone; native speakers should rewrite them per language rather than translate them.

### Locked-door board copy (English)

| State | Sample lines |
| --- | --- |
| Locked, past month | "Nothing happened here. Or nobody told me." / "Life got boring. Allegedly." / "No memories, no door. Rules are rules." / "Dust only. Tell me something and I'll open up." / "A whole month and not one story? Bold." |
| Not yet | "Hasn't happened yet. Stop peeking." / "Come back after you've lived it." |
| Current month, empty | "This month is still loading. Give it a few days." |
| Whole floor empty | "A whole year with nothing. Impressive, honestly." |
| Closed with care, or sarcasm off | "Closed with care." / "No memories here yet." |

Every locked board ends with a prompt: "Tell Ajji on Telegram to open this door," using the family's Grandma name.

### Grandma's name by language

Families choose; native speakers should confirm these, and the choice is limited to languages the speech voice supports.

| Language | Names for grandmother |
| --- | --- |
| Kannada | Ajji |
| Tamil | Paati |
| Telugu | Ammamma or Nanamma |
| Malayalam | Ammumma |
| Hindi | Dadi or Nani |
| Marathi | Aaji |
| Bengali | Dida or Thakuma |
| Gujarati | Ba |
| English | Grandma |
