import { create } from 'zustand';
import type { Exhibit, Interactable, Lang, MuseumRoute, MuseumSummary, Room, ShowcaseItem, WorldActions, WorldMode } from '../contract';
import { ApiError, get, listOf, post } from '../api/client';
import { playGuideLine } from '../voice/guideVoice';
import { yearOfLevel } from '../lib/floors';

export type Phase = 'boot' | 'signin' | 'landing' | 'world';
export type Avatar = 'man' | 'woman';
/** Showcase items may arrive as {type:'video', url, poster_url, ...}: fold `type` into `kind` and fill the gaps. */
function normalizeItem(it: ShowcaseItem & { type?: ShowcaseItem['kind'] }): ShowcaseItem {
  const kind = it.kind ?? it.type ?? 'photo';
  return { ...it, kind, url: it.url ?? null, thumb_url: it.thumb_url ?? it.poster_url ?? null, caption: it.caption ?? '', transcript: it.transcript ?? null, audio_url: it.audio_url ?? null, duration_s: it.duration_s ?? 0, poster_url: it.poster_url ?? (kind === 'video' ? it.thumb_url ?? null : null) };
}

export type Panel = null | 'reception' | 'lift' | 'directory' | 'attic' | 'settings' | 'cleanup' | 'reels' | 'ops' | 'members' | 'exhibit' | 'help';
export type AgentState = 'idle' | 'listening' | 'thinking' | 'speaking';
export interface Caption { id: number; who: 'you' | 'receptionist' | 'grandma' | 'system'; text: string; final: boolean }
export interface Card { id: number; kind: 'call' | 'outcome' | 'message' | 'info' | 'error' | 'presence'; title: string; text: string; ts: number }
export interface SeatRef { year: number; month: number; index: number }
export interface RoomRef { year: number; month: number; eventId: string | null }
/** One person in the theater (GET /api/presence, SSE `presence`). index null = watching without a seat. */
export interface PresencePerson { id: string; index: number | null; name: string; avatar: Avatar; is_guest: boolean; is_me?: boolean }
export interface Presence { year: number; month: number; seats: PresencePerson[]; watchers: PresencePerson[] }
/** Seat index used locally when every seat is taken (the player watches from the back bench). */
export const NO_SEAT = 4;

const LS = 'memo:prefs:v1';
interface Prefs { avatar: Avatar; language: Lang; reducedMotion: boolean; mode2d: boolean | null; displayName?: string | null }
function loadPrefs(): Prefs {
  const mq = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const d: Prefs = { avatar: 'woman', language: 'en-IN', reducedMotion: mq, mode2d: null };
  try { return { ...d, ...(JSON.parse(localStorage.getItem(LS) || '{}') as Partial<Prefs>) }; } catch { return d; }
}
function savePrefs(s: Prefs) {
  try { localStorage.setItem(LS, JSON.stringify({ avatar: s.avatar, language: s.language, reducedMotion: s.reducedMotion, mode2d: s.mode2d, displayName: s.displayName ?? null })); } catch { /* storage blocked */ }
}

export interface WorldState extends WorldActions {
  phase: Phase;
  authError: string | null;
  museum: MuseumSummary | null;
  floorRooms: Record<number, Room[]>;          // year -> 12 rooms (lazy)
  room: RoomRef | null;                        // the room currently open (theater or 2D)
  roomExhibits: Exhibit[];
  currentLevel: number;
  mode: WorldMode;
  nearby: Interactable | null;
  activeRoute: MuseumRoute | null;
  seat: SeatRef | null;
  screenMode: boolean;
  showcaseItems: ShowcaseItem[];
  showcaseIndex: number;
  showcasePlaying: boolean;
  showcaseNarrated: boolean;
  showcaseSpeed: number;
  skipVoiceNotes: boolean;
  avatar: Avatar;
  language: Lang;
  captions: Caption[];
  liveTranscript: string;
  agentState: AgentState;
  /** Who currently holds the floor (set only by voice/speechArbiter): drives the HUD and the 3D speaking cues. */
  speaking: { source: 'agent' | 'guide' | 'filler'; who: string } | null;
  setSpeaking(s: WorldState['speaking']): void;
  micOn: boolean;
  micLevel: number;
  reducedMotion: boolean;
  mode2d: boolean | null;                      // user preference (null = auto)
  webgl: boolean;
  panel: Panel;
  exhibitId: string | null;
  cards: Card[];
  invitesTick: number;                         // bumps when the SSE stream says invites changed
  guestSync: { index: number; playing: boolean; ts: number } | null;
  presence: Presence | null;                   // who sits in the theater with us (this room only)
  displayName: string | null;                  // name shown on our seat tag (guests type it on the landing)
  presenceCardUntil: number;                   // a join/leave card is on screen until then (Grandma holds her words)

  boot(): Promise<void>;
  refreshMuseum(): Promise<void>;
  enter(): void;
  loadFloor(year: number, force?: boolean): Promise<Room[]>;
  loadRoom(year: number, month: number, eventId?: string | null): Promise<void>;
  /** keep: a refresh (new memory arrived, an edit): stay on the same item and keep playing instead of starting over. */
  loadShowcase(opts?: { keep?: boolean }): Promise<void>;
  goTo(year: number, month: number, eventId?: string | null): Promise<void>;
  openPanel(p: Panel): void;
  openExhibit(id: string): void;
  closeExhibit(): void;
  leaveRoom(): void;
  setShowcase(patch: Partial<Pick<WorldState, 'showcaseIndex' | 'showcasePlaying' | 'showcaseNarrated' | 'showcaseSpeed' | 'skipVoiceNotes'>>): void;
  nextItem(): void;
  prevItem(): void;
  restartShowcase(): void;
  setAvatar(a: Avatar): void;
  setLanguage(l: Lang): void;
  setReducedMotion(v: boolean): void;
  setMode2d(v: boolean | null): void;
  pushCaption(c: Omit<Caption, 'id'> & { id?: number }): number;
  clearCaptions(): void;
  setVoice(p: Partial<Pick<WorldState, 'agentState' | 'micOn' | 'micLevel' | 'liveTranscript'>>): void;
  addCard(c: Omit<Card, 'id' | 'ts'>): void;
  dismissCard(id: number): void;
  setWebgl(v: boolean): void;
  bumpInvites(): void;
  setGuestSync(index: number, playing: boolean): void;
  setPresence(p: Presence | null): void;
  setDisplayName(n: string | null): void;
  presenceCard(title: string, text: string): void;
}

let walkTimer: number | null = null;
let capId = 1;
let cardId = 1;
const clearWalk = () => { if (walkTimer != null) { clearTimeout(walkTimer); walkTimer = null; } };
const prefs = loadPrefs();
if (typeof document !== 'undefined') document.documentElement.dataset.reduced = prefs.reducedMotion ? '1' : '0';

export const useWorld = create<WorldState>((set, getS) => ({
  phase: 'boot', authError: null, museum: null, floorRooms: {}, room: null, roomExhibits: [],
  currentLevel: 0, mode: 'lobby', nearby: null, activeRoute: null, seat: null, screenMode: false,
  showcaseItems: [], showcaseIndex: 0, showcasePlaying: false, showcaseNarrated: true, showcaseSpeed: 1, skipVoiceNotes: false,
  avatar: prefs.avatar, language: prefs.language, captions: [], liveTranscript: '', agentState: 'idle', speaking: null, micOn: false, micLevel: 0,
  reducedMotion: prefs.reducedMotion, mode2d: prefs.mode2d, webgl: true, panel: null, exhibitId: null, cards: [], invitesTick: 0,
  guestSync: null, presence: null, displayName: prefs.displayName ?? null, presenceCardUntil: 0,

  async boot() {
    try {
      const m = await get<MuseumSummary>('/api/museum', { quiet401: true });
      set({ museum: m, phase: 'landing', authError: null });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) set({ phase: 'signin', authError: null });
      else set({ phase: 'signin', authError: e instanceof Error ? e.message : 'Could not reach the museum.' });
    }
  },
  async refreshMuseum() {
    try { set({ museum: await get<MuseumSummary>('/api/museum') }); } catch { /* keep old */ }
  },
  enter() {
    const { museum } = getS();
    set({ phase: 'world', mode: 'lobby', currentLevel: 0 });
    const inv = museum?.me.invite_room;
    if (museum?.me.is_guest && inv) void getS().goTo(inv.year, inv.month);
  },

  async loadFloor(year, force) {
    const cached = getS().floorRooms[year];
    if (cached && !force) return cached;
    const data = await get<unknown>(`/api/museum/${year}`);
    const rooms = listOf<Room>(data, 'rooms').sort((a, b) => a.month - b.month);
    set((s) => ({ floorRooms: { ...s.floorRooms, [year]: rooms } }));
    return rooms;
  },
  async loadRoom(year, month, eventId = null) {
    set({ room: { year, month, eventId } });
    const q = eventId ? `?event_id=${encodeURIComponent(eventId)}` : '';
    const data = await get<unknown>(`/api/museum/${year}/${month}${q}`);
    set({ roomExhibits: listOf<Exhibit>(data, 'exhibits') });
  },
  async loadShowcase(opts) {
    const r = getS().room;
    if (!r) return;
    const q = r.eventId ? `?event_id=${encodeURIComponent(r.eventId)}` : '';
    const data = await get<unknown>(`/api/showcase/${r.year}/${r.month}${q}`);
    const items = listOf<ShowcaseItem & { type?: ShowcaseItem['kind'] }>(data, 'items').map(normalizeItem);
    const cur = getS();
    if (opts?.keep && cur.room === r && cur.showcaseItems.length) {
      const was = cur.showcaseItems[cur.showcaseIndex];
      const at = was ? items.findIndex((i) => i.memory_id === was.memory_id && i.kind === was.kind && (i.url ?? '').split('?')[0] === (was.url ?? '').split('?')[0]) : -1;
      set({ showcaseItems: items, showcaseIndex: at >= 0 ? at : Math.min(cur.showcaseIndex, Math.max(0, items.length - 1)) });
      return;
    }
    set({ showcaseItems: items, showcaseIndex: 0, showcasePlaying: false });
  },

  async goTo(year, month, eventId = null) {
    try {
      const r = await post<{ route: MuseumRoute | null; question: string | null }>('/api/route', { year, month, event_id: eventId });
      if (!r.route) { getS().addCard({ kind: 'info', title: 'Which room?', text: r.question ?? 'I could not place that room.' }); return; }
      set({ panel: null, room: { year, month, eventId }, seat: null });
      getS().startGuidedWalk(r.route);
    } catch (e) {
      getS().addCard({ kind: 'error', title: 'Could not plan the walk', text: e instanceof Error ? e.message : 'Try again.' });
    }
  },
  openPanel(p) { set({ panel: p }); },
  openExhibit(id) { set({ exhibitId: id, panel: 'exhibit' }); },
  closeExhibit() { set({ exhibitId: null, panel: null }); },
  leaveRoom() { getS().standUp(); set({ room: null, roomExhibits: [], showcaseItems: [], mode: 'floor' }); },

  setNearby(i) { set({ nearby: i }); },
  interact(i) {
    const s = getS();
    switch (i.kind) {
      case 'desk': set({ panel: 'reception' }); break;
      case 'lift_panel': set({ panel: 'lift' }); break;
      case 'directory': set({ panel: 'directory' }); break;
      case 'attic': set({ panel: 'attic' }); break;
      case 'door': void s.goTo(i.year, i.month); break;
      case 'seat': {
        const p = s.presence;
        const other = p && p.year === i.year && p.month === i.month ? p.seats.find((x) => x.index === i.index && !x.is_me) : null;
        if (other) { s.addCard({ kind: 'info', title: 'Seat taken', text: `${other.name} is sitting there.` }); break; }
        if (s.museum?.me.is_guest && i.index === 0) { s.addCard({ kind: 'info', title: 'Seat kept', text: 'The front seat is kept for the family host.' }); break; }
        s.sit(i.year, i.month, i.index);
        break;
      }
      case 'frame': case 'plaque': case 'jukebox': s.openExhibit(i.memory_id); break;
    }
  },
  async rideLift(level) {
    const s = getS();
    set({ mode: 'riding', currentLevel: level, panel: null });
    const year = s.museum?.floors.find((f) => f.level === level)?.year ?? yearOfLevel(level);   // fixed calendar fallback
    await s.loadFloor(year).catch(() => undefined);
    const quick = s.reducedMotion || !s.webgl || s.mode2d === true;
    await new Promise((r) => setTimeout(r, quick ? 150 : 2600));
    set({ mode: 'floor' });
  },
  startGuidedWalk(route) {
    clearWalk();
    const s = getS();
    set({ activeRoute: route, mode: 'walking', currentLevel: route.level, panel: null, screenMode: false });
    void s.loadFloor(route.year).catch(() => undefined);
    void playGuideLine(route.needs_lift ? 'to_lift' : 'follow_me', s.language);
    const noWorld = s.reducedMotion || !s.webgl || s.mode2d === true;
    // The 3D world calls finishWalk(); this timer is the safety net (and the whole scene in 2D).
    walkTimer = window.setTimeout(() => getS().finishWalk(), noWorld ? 350 : (route.walk_seconds + 5) * 1000);
  },
  skipWalk() { if (getS().mode === 'walking') getS().finishWalk(); },
  finishWalk() {
    clearWalk();
    const r = getS().activeRoute;
    set({ activeRoute: null });
    if (!r) return;
    // PRD: only open rooms open their door; locked, not-yet, current-empty and closed rooms stay shut with their board.
    if (r.room_state === 'open') {
      void playGuideLine('here_we_are', getS().language);
      getS().sit(r.year, r.month, 0);
    } else {
      // PRD: at a shut door the board is shown and read aloud; nobody sits down.
      void playGuideLine('locked_door', getS().language);
      set({ mode: 'floor', room: null });
      getS().addCard({ kind: 'info', title: 'The door is shut', text: r.board_text || 'This room is not open yet.' });
    }
  },
  sit(year, month, index) {
    const prev = getS().room;
    const eventId = prev && prev.year === year && prev.month === month ? prev.eventId : null;
    set({ seat: { year, month, index }, mode: 'room', panel: null, showcaseIndex: 0, showcasePlaying: false });
    void (async () => {
      await getS().loadRoom(year, month, eventId).catch(() => undefined);
      await getS().loadShowcase().catch(() => undefined);
    })();
  },
  standUp() { set({ seat: null, screenMode: false, showcasePlaying: false, mode: 'floor', presence: null }); },
  setScreenMode(on) { set({ screenMode: on }); },

  setShowcase(patch) { set(patch); },
  nextItem() {
    const s = getS();
    if (s.showcaseIndex < s.showcaseItems.length - 1) set({ showcaseIndex: s.showcaseIndex + 1 });
    else set({ showcasePlaying: false });
  },
  prevItem() { set({ showcaseIndex: Math.max(0, getS().showcaseIndex - 1) }); },
  restartShowcase() { set({ showcaseIndex: 0, showcasePlaying: true }); },

  setAvatar(avatar) { set({ avatar }); savePrefs({ ...getS(), avatar }); },
  setLanguage(language) { set({ language }); savePrefs({ ...getS(), language }); },
  setReducedMotion(reducedMotion) {
    set({ reducedMotion });
    savePrefs({ ...getS(), reducedMotion });
    document.documentElement.dataset.reduced = reducedMotion ? '1' : '0';
  },
  setMode2d(mode2d) { set({ mode2d }); savePrefs({ ...getS(), mode2d }); },
  pushCaption(c) {
    const id = c.id ?? capId++;
    set((s) => ({ captions: [...s.captions.filter((x) => x.id !== id), { ...c, id }].slice(-6) }));
    return id;
  },
  clearCaptions() { set({ captions: [], liveTranscript: '' }); },
  setVoice(p) { set(p); },
  setSpeaking(speaking) { set({ speaking }); },
  addCard(c) {
    const id = cardId++;
    set((s) => ({ cards: [...s.cards, { ...c, id, ts: Date.now() }].slice(-4) }));
    window.setTimeout(() => getS().dismissCard(id), 10_000);
  },
  dismissCard(id) { set((s) => ({ cards: s.cards.filter((c) => c.id !== id) })); },
  setWebgl(webgl) { set({ webgl }); },
  bumpInvites() { set((s) => ({ invitesTick: s.invitesTick + 1 })); },
  setGuestSync(index, playing) { set({ guestSync: { index, playing, ts: Date.now() } }); },
  setPresence(presence) { set({ presence }); },
  setDisplayName(displayName) { set({ displayName }); savePrefs({ ...getS(), displayName }); },
  presenceCard(title, text) {
    getS().addCard({ kind: 'presence', title, text });
    set({ presenceCardUntil: Date.now() + 4000 });
  },
}));

/** True when the app should render the 2D grid instead of the Three.js museum (PRD M4). */
export function use2d(): boolean {
  const mode2d = useWorld((s) => s.mode2d);
  const webgl = useWorld((s) => s.webgl);
  const flag = useWorld((s) => s.museum?.flags?.museum_3d);
  if (mode2d !== null) return mode2d;
  return !webgl || flag === false;
}
