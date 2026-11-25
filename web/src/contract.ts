/**
 * Shared frontend contract between the 3D world (src/world/**, owner: web-3d agent) and the app
 * shell / UI (everything else in src/, owner: web-app agent). Keep this file stable; additive changes only.
 *
 * API types mirror backend responses (docs/BUILD_CONTRACT.md).
 */

export type Lang = 'en-IN' | 'hi-IN' | 'kn-IN';
export type RoomState = 'open' | 'locked' | 'not_yet' | 'current_empty' | 'closed';

export interface FloorSummary { year: number; open: number; total: 12; level: number /* 0 = ground */ }
export interface MuseumSummary {
  family: { id: string; name: string; language: Lang; grandma_name: string };
  me: { member_id: string | null; nickname: string | null; role: 'owner' | 'editor' | 'viewer'; is_guest: boolean; invite_room?: { year: number; month: number } | null };
  floors: FloorSummary[];             // newest first; always includes the current year
  attic_count: number;
  latest: { id: string; title: string; year: number; month: number; thumb_url: string | null } | null;
  flags: Record<string, unknown>;     // museum_3d, voice_enabled, barge_in, cinematic_walk, sarcasm_enabled, ...
  bot_username: string | null;        // for the lobby QR (t.me/<bot>)
}
export interface Room {
  year: number; month: number; state: RoomState; memory_count: number;
  hero_thumb_url: string | null; festival: string | null; board_text: string | null;
  events: { id: string; name: string; kind: string }[];
}
export interface Exhibit {
  id: string; kind: 'text' | 'voice' | 'photo' | 'album' | 'forward';
  title: string | null; text: string | null; summary: string | null; author: string | null; teller: string | null;
  event_date: { year: number; month: number; day: number | null };
  festival: string | null; event_id: string | null; sensitivity: string; narrate_ok: boolean;
  photos: { id: string; thumb_url: string; url: string; width: number | null; height: number | null; is_blurry: boolean }[];
  audio_url: string | null; transcript: string | null; duration_s: number | null;
}
export interface ShowcaseItem {
  memory_id: string; kind: 'photo' | 'title' | 'voice'; url: string | null; thumb_url: string | null;
  caption: string; transcript: string | null; audio_url: string | null; duration_s: number;
}
export interface Highlight { memory_id: string; at_s: number }
export interface Subtitle { text: string; start_s: number; end_s: number }
export interface Speech { text: string; audio_url: string | null; subtitles: Subtitle[]; highlights: Highlight[]; memory_ids: string[] }

export interface RouteWaypoint { kind: 'desk' | 'lift' | 'ride' | 'corridor' | 'door' | 'seat'; level: number; door_index?: number }
export interface MuseumRoute {
  year: number; month: number; event_id: string | null; level: number; needs_lift: boolean;
  room_state: RoomState; board_text: string | null; waypoints: RouteWaypoint[]; walk_seconds: number;
}

/* ---------------- World <-> UI bridge (zustand store in src/state/worldStore.ts, owned by web-app) -------------
 * The world READS: museum, floorRooms, currentLevel, mode, activeRoute, seatIndex, screenMode, showcase index.
 * The world WRITES via the actions below (e.g. when the player presses E at a door, the lift panel, a seat).
 * The UI calls the same actions from buttons/voice, so voice has no private powers (PRD V1).
 */
export type WorldMode = 'lobby' | 'floor' | 'room' | 'walking' | 'riding';
export type Interactable =
  | { kind: 'desk' }
  | { kind: 'lift_panel' }
  | { kind: 'door'; year: number; month: number }
  | { kind: 'seat'; year: number; month: number; index: number }
  | { kind: 'frame'; memory_id: string }
  | { kind: 'plaque'; memory_id: string }
  | { kind: 'jukebox'; memory_id: string }
  | { kind: 'attic' }
  | { kind: 'directory' };

export interface WorldActions {
  setNearby(i: Interactable | null): void;          // world -> UI: show "Press E" prompt
  interact(i: Interactable): void;                  // world or UI: perform the action
  rideLift(level: number): Promise<void>;           // 2-3 s ride; loads the floor meanwhile
  startGuidedWalk(route: MuseumRoute): void;        // 5-10 s scene; world plays it, then calls finishWalk()
  skipWalk(): void;                                 // tap / key / "skip": jump to the end (seated)
  finishWalk(): void;
  sit(year: number, month: number, index: number): void;
  standUp(): void;
  setScreenMode(on: boolean): void;                 // camera fills display with the screen; UI hides
}
