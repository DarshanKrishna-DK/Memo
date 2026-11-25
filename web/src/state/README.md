# worldStore (zustand) for the 3D world

`import { useWorld } from '../state/worldStore'` (from `src/world/**` use `'../state/worldStore'`).
Read with selectors (`useWorld((s) => s.mode)`), or imperatively with `useWorld.getState()` inside `useFrame`.
The store implements `WorldActions` from `src/contract.ts`; the UI calls the same actions as the world.

## Fields the world READS

| Field | Meaning |
|---|---|
| `museum` | `MuseumSummary` (floors newest first, `floors[i].level`, `me`, `flags`). Null until signed in. |
| `floorRooms[year]` | `Room[]` (12) for a floor, loaded lazily by `loadFloor(year)`. Render doors from this. |
| `currentLevel` | Level the player is on (0 = ground, beside lobby). Set by `rideLift` / `startGuidedWalk`. |
| `mode` | `'lobby' \| 'floor' \| 'room' \| 'walking' \| 'riding'` |
| `activeRoute` | `MuseumRoute` while `mode === 'walking'`. Play it, then call `finishWalk()`. A 4-5 s safety timer calls `finishWalk()` if you forget. |
| `seat` | `{year, month, index} \| null`. Non-null = player is seated in that room's theater. |
| `room` | `{year, month, eventId}` of the open room; `roomExhibits` are its `Exhibit[]` (photos for frames, jukebox audio). |
| `screenMode` | When true the camera should fill the display with the screen. The UI hides itself. |
| `showcaseItems` / `showcaseIndex` / `showcasePlaying` | Playlist for the screen. Draw `showcaseItems[showcaseIndex]` (`url` for photo, `caption` for title/voice). The UI engine advances the index, you only render. |
| `showcaseSpeed`, `showcaseNarrated`, `skipVoiceNotes` | Playback options (informational). |
| `avatar` | `'man' \| 'woman'` chosen on the landing page (man = shirt + trousers, woman = saree). |
| `language` | `Lang` for scripted lines. |
| `captions`, `liveTranscript` | UI-owned; the world does not need them. |
| `agentState` | `'idle' \| 'listening' \| 'thinking' \| 'speaking'` for the receptionist or Grandma (lip-sync / robot animation). |
| `micOn`, `micLevel` | Mic on/off and a 0..1 live level. |
| `reducedMotion` | When true, replace walking scenes with a fade (UI already does this when `mode2d`/no WebGL). |
| `webgl`, `mode2d` | The shell decides 2D vs 3D (`use2d()`); the world is only mounted when 3D is chosen. |
| `panel`, `exhibitId` | Which UI panel/modal is open. While `panel !== null` ignore the E key (the HUD already does). |

## Actions the world CALLS (contract `WorldActions`)

- `setNearby(i | null)`: shows the "Press E" prompt. The HUD handles the E key itself and calls `interact(nearby)`, so the world does not need to listen for E (it may also call `interact` directly, e.g. on click).
- `interact(i)`: desk opens the reception panel, lift_panel the lift panel, door plans a route (`/api/route`) and starts the walk, seat sits, frame/plaque/jukebox open the exhibit modal, attic and directory open panels.
- `rideLift(level)`: sets `mode = 'riding'`, loads the floor, waits about 2.6 s, then sets `mode = 'floor'`. Animate the ride while `mode === 'riding'`.
- `startGuidedWalk(route)`, `skipWalk()`, `finishWalk()`: the world plays `activeRoute` and calls `finishWalk()` at the end. `finishWalk()` sits the player at seat 0 when the room is open, or leaves them at the shut door (a card shows the board text) otherwise. `skipWalk()` is the UI button / S key.
- `sit(year, month, index)` loads the room, exhibits and showcase. `standUp()`.
- `setScreenMode(on)`.

## Extras the world may use

`useWorld.getState().openExhibit(memory_id)`, `goTo(year, month, eventId?)`, `loadFloor(year)`, `loadRoom(...)`.
The shell lazy-loads `src/world/MuseumCanvas.tsx` (default export, no props) and calls `isWebGLAvailable()` from `src/world/webgl.ts` once.
