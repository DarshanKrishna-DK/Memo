# src/world: the 3D museum (owner: web-3d)

## Mounting

```tsx
import MuseumCanvas from '../world/MuseumCanvas';   // default export, lazy-load friendly
import { isWebGLAvailable } from '../world/webgl';   // false → render the 2D grid (PRD M4)

<div style={{ position: 'relative', height: '100dvh' }}>
  <MuseumCanvas />            {/* full-bleed, position:absolute inset:0; UI layers on top */}
</div>
```

Props (all optional): `avatar?: 'man' | 'woman'` (overrides store `avatar`), `quality?: 'high' | 'low'`
(default auto: low on coarse pointers, PerformanceMonitor drops to low / lower DPR when fps < 28; `?fx=low|high`
forces it), `joystick?: boolean` (default: on for coarse pointers).

Mount it only once `museum` is loaded (phase `world`). It renders nothing while `museum` is null.

## Store fields read (`useWorld` from `src/state/worldStore.ts`)

| Field | Use |
|---|---|
| `museum` | floors (directory, lift indicator, level ↔ year), `attic_count`, `latest` (lobby plaque), `bot_username` (QR to `t.me/<bot>`; a "not configured" board when null), `family.name/language` |
| `floorRooms[year]` | the 12 rooms of the floor on display (door state, sign, board text). The world calls `loadFloor(year)` if missing |
| `currentLevel` | floor to show. During a walk / ride the world keeps its own displayed level and swaps it under closed lift doors |
| `mode` | `walking` (with `activeRoute`) plays the guided walk; `riding` plays the lift ride. Leaving `walking` early = skip → snap to the end |
| `activeRoute` | the walk plan input (`level`, `month`, `room_state`, `walk_seconds`) |
| `room` | the month room to render behind its door (only when it is on the displayed floor and `open`, or the visitor is seated there) |
| `seat` | sit the avatar in seat `index` of that room (teleports under a fade if far) |
| `roomExhibits` | frames (≤6 photos), plaques (≤4 text stories), jukebox (voice notes) |
| `showcaseItems`, `showcaseIndex` | the theater screen (photo with slow zoom + caption, title card, voice card). The world never advances the index |
| `screenMode` | camera dolly until the screen fills the view, avatar hidden (only while seated) |
| `avatar`, `reducedMotion`, `language`, `panel`, `agentState` | avatar rig; reduced-motion walk = short fade; E disabled while a panel is open; Grandma / receptionist talk animation while `agentState === 'speaking'` |

## Actions called

- `setNearby(i | null)`: whenever the interactable the visitor stands at (and faces) changes.
- `interact(i)`: on **E** or a tap/click on the object (desk, lift panel, directory, attic, latest-memory plaque,
  doors, seats, frames, plaques, jukebox; the jukebox cycles through the room's voice notes).
- `finishWalk()`: at the natural end of the guided walk.
- `standUp()`: when the seated visitor moves (WASD / joystick).
- `leaveRoom()`: when the visitor walks back out through the room's door.
- `setScreenMode(false)`: on **Escape** in screen mode (the UI may also call it).
- `loadFloor(year)`: lazy floor load for the displayed floor.

The world never calls `rideLift` or `startGuidedWalk`; it reacts to the state those actions set.

## Files

- `MuseumCanvas.tsx`: canvas, store wiring, ride/seat/room reconciliation, colliders, interaction spots.
- `layout.ts`: all positions (lobby, lift, corridor doors Jan–Dec, month room template, colliders).
- `Lobby.tsx` (lobby + upper-floor landing), `Lift.tsx`, `Corridor.tsx` (instanced doors, sign/board atlases),
  `Room.tsx` + `TheaterScreen.tsx` (theater), `Cast.tsx` + `Robot.tsx` (receptionist + guide robots),
  `WalkDirector.tsx` (guided walk), `Player.tsx` (third-person controls), `Interactions.tsx`, `Joystick.tsx`.
- `characters/`: MedSim's rigged humans (Xbot clips retargeted per rig). Player man = male rig with the top cut
  at the hip (shirt) over trousers; player woman and Grandma = the Blender-built saree rig (pleats + pallu).
- `textures.ts`: canvas text, atlases (one GPU upload for 12 door signs), QR, budgeted photo cache.
- `webgl.ts`: `isWebGLAvailable()`.

## Performance notes

One floor at a time; door parts, seats, frames instanced; 12 door signs and 12 boards share two atlas uploads per
floor (disposed on floor change); photo textures are ref-counted with a budget of 24 and flushed when the floor
changes; one global pool of 4 point lights hops to the fixtures nearest the player; one follow shadow light
(1024²). Dev builds expose `window.__memo3d = { gl, scene, rt }` for inspection.
