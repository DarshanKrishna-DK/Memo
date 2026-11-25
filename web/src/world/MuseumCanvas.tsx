import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { PerformanceMonitor, useProgress } from '@react-three/drei';
import type { Interactable, Room } from '../contract';
import { NO_SEAT, useWorld } from '../state/worldStore';
import { BENCH_DZ } from './Audience';
import { GuideRobot, ReceptionistRobot } from './Cast';
import { WarmCharacters, preloadCharacters } from './characters/HumanCharacter';
import { Corridor } from './Corridor';
import { MuseumEnvironment, PostFX, type FxQuality } from './FX';
import { Interactions, type Spot } from './Interactions';
import { Joystick } from './Joystick';
import {
  ATTIC, CORR_CEIL, DESK, DIRECTORY, DOORS, GUIDE_HOME, LANDING, LATEST_PLAQUE, LIFT, LIFT_IN, LIFT_OUT, LOBBY, ROOM, SEAT_H, SEAT_Z,
  SPAWN, corridorColliders, doorForMonth, landingColliders, lobbyColliders, roomColliders, roomFrame, roomPlaces, toWorld,
  type RoomFrame,
} from './layout';
import { Lift } from './Lift';
import { Landing, Lobby } from './Lobby';
import { FollowKey, LightPool } from './parts';
import { Player } from './Player';
import { MonthRoom } from './Room';
import { RuntimeContext, makeWorldRuntime, useRuntime, type WorldRuntime } from './runtime';
import { flushPhotos } from './textures';
import { WalkDirector } from './WalkDirector';
import { levelOfYear as fixedLevelOfYear, yearOfLevel } from '../lib/floors';

preloadCharacters();

export interface MuseumCanvasProps {
  /** Overrides the store's `avatar` (the landing page choice). */
  avatar?: 'man' | 'woman';
  /** Force post-processing quality; default: auto (high on desktop, low on phones, adaptive). */
  quality?: FxQuality;
  /** Show the touch joystick; default: on for coarse pointers (phones / tablets). */
  joystick?: boolean;
}

function pickQuality(): FxQuality {
  try {
    const q = new URLSearchParams(window.location.search).get('fx');
    if (q === 'low' || q === 'high') return q;
    if (matchMedia('(pointer: coarse)').matches) return 'low';
  } catch { /* ignore */ }
  return 'high';
}

/**
 * The 3D museum. Reads the world store (src/state/worldStore.ts) and writes through its
 * WorldActions only. Mount it full-bleed inside a positioned container; the UI layers on top.
 */
export default function MuseumCanvas({ avatar: avatarProp, quality: qualityProp, joystick }: MuseumCanvasProps) {
  const rt = useMemo(makeWorldRuntime, []);
  const [quality, setQuality] = useState<FxQuality>(() => qualityProp ?? pickQuality());
  const [dpr, setDpr] = useState(() => Math.min(window.devicePixelRatio || 1, quality === 'low' ? 1.0 : 1.25));
  const showJoy = useMemo(() => joystick ?? (typeof matchMedia === 'function' && matchMedia('(pointer: coarse)').matches), [joystick]);

  return (
    <div style={{ position: 'absolute', inset: 0, background: '#061431', overflow: 'hidden', userSelect: 'none' }} data-world="museum">
      <Canvas
        shadows
        dpr={dpr}
        gl={{ antialias: false, powerPreference: 'high-performance', stencil: false }}
        camera={{ fov: 58, near: 0.08, far: 90, position: [SPAWN.x + 3, 1.8, SPAWN.z] }}
        style={{ position: 'absolute', inset: 0 }}
        onCreated={(st) => {
          if (import.meta.env.DEV) Object.assign(window, { __memo3d: { gl: st.gl, scene: st.scene, rt } });
        }}
      >
        <color attach="background" args={['#061431']} />
        <PerformanceMonitor
          bounds={() => [28, 55]}
          flipflops={3}
          onDecline={() => {
            if (!qualityProp && quality === 'high') setQuality('low');
            else setDpr((d) => Math.max(0.6, d - 0.15));
          }}
          onIncline={() => setDpr((d) => Math.min(quality === 'low' ? 1.0 : 1.25, d + 0.1))}
        />
        <RuntimeContext.Provider value={rt}>
          <Suspense fallback={null}>
            <MuseumEnvironment />
            <WarmCharacters />
            <WorldScene avatarProp={avatarProp} />
            <PostFX quality={quality} />
          </Suspense>
        </RuntimeContext.Provider>
      </Canvas>
      {showJoy && <Joystick rt={rt} />}
      <FadeOverlay rt={rt} />
      <LoadingOverlay />
    </div>
  );
}

function FadeOverlay({ rt }: { rt: WorldRuntime }) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      rt.fade += (rt.fadeTarget - rt.fade) * Math.min(1, dt * 8);
      if (Math.abs(rt.fade - rt.fadeTarget) < 0.01) rt.fade = rt.fadeTarget;
      if (el.current) {
        el.current.style.opacity = String(rt.fade);
        el.current.style.pointerEvents = rt.fade > 0.5 ? 'auto' : 'none';
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [rt]);
  return <div ref={el} aria-hidden="true" style={{ position: 'absolute', inset: 0, background: '#050b1a', opacity: 0, pointerEvents: 'none' }} />;
}

/** Shown for the first load only (models, environment). Later loads (photos, a lazily fetched asset) never blank
 *  the museum again: the scene stays visible and they pop in when ready. */
let firstLoadDone = false;
function LoadingOverlay() {
  const { active, progress } = useProgress();
  const [shown, setShown] = useState(!firstLoadDone);
  useEffect(() => {
    if (firstLoadDone) return;
    if (!active && progress >= 100) {
      const t = setTimeout(() => { firstLoadDone = true; setShown(false); }, 250);
      return () => clearTimeout(t);
    }
  }, [active, progress]);
  if (!shown) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', background: '#061431', color: '#f3f1e2',
        fontFamily: '"Jersey 10", ui-monospace, monospace', fontSize: 32, letterSpacing: '0.04em', zIndex: 2,
      }}
    >
      <div style={{ textAlign: 'center' }}>
        <div>Opening the museum…</div>
        <div style={{ marginTop: 12, width: 220, height: 10, background: '#112a60', boxShadow: '0 0 0 2px #2b4c8a' }}>
          <div style={{ width: `${Math.round(progress)}%`, height: '100%', background: '#a8e27c' }} />
        </div>
      </div>
    </div>
  );
}

/** Snap the player somewhere under a short fade. */
function teleport(rt: WorldRuntime, x: number, z: number, yaw: number) {
  rt.fade = 1;
  rt.fadeTarget = 0;
  rt.player.pos.set(x, 0, z);
  rt.player.yaw = yaw;
  rt.player.camYaw = yaw + Math.PI;
  rt.player.speed = 0;
}

function WorldScene({ avatarProp }: { avatarProp?: 'man' | 'woman' }) {
  const rt = useRuntime();
  const museum = useWorld((s) => s.museum);
  const floorRooms = useWorld((s) => s.floorRooms);
  const currentLevel = useWorld((s) => s.currentLevel);
  const mode = useWorld((s) => s.mode);
  const activeRoute = useWorld((s) => s.activeRoute);
  const seat = useWorld((s) => s.seat);
  const presence = useWorld((s) => s.presence);
  const room = useWorld((s) => s.room);
  const exhibits = useWorld((s) => s.roomExhibits);
  const showcase = useWorld((s) => s.showcaseItems);
  const showcaseIndex = useWorld((s) => s.showcaseIndex);
  const screenMode = useWorld((s) => s.screenMode);
  const storeAvatar = useWorld((s) => s.avatar);
  const reduced = useWorld((s) => s.reducedMotion);
  const language = useWorld((s) => s.language);
  const panel = useWorld((s) => s.panel);
  const setNearby = useWorld((s) => s.setNearby);
  const interact = useWorld((s) => s.interact);
  const finishWalk = useWorld((s) => s.finishWalk);
  const standUp = useWorld((s) => s.standUp);
  const leaveRoom = useWorld((s) => s.leaveRoom);
  const loadFloor = useWorld((s) => s.loadFloor);
  const setScreenMode = useWorld((s) => s.setScreenMode);

  const avatar = avatarProp ?? storeAvatar;
  const lang = museum?.family.language ?? language;
  const floors = useMemo(() => museum?.floors ?? [], [museum]);
  const [displayLevel, setDisplayLevel] = useState(currentLevel);
  const walking = mode === 'walking' && !!activeRoute;
  const riding = mode === 'riding';

  // Fixed calendar (lib/floors): level 0 = 2002 (ground, beside the lobby), level 24 = 2026 (Floor 25). Only the
  // floor on display is built, so a 25-floor building costs the same as a one-floor one.
  const floor = floors.find((f) => f.level === displayLevel) ?? null;
  const year = floor?.year ?? yearOfLevel(displayLevel);
  const rooms: Room[] | undefined = floorRooms[year];
  // The server's floor list is the truth (it is what routes use); the fixed calendar fills years it does not list.
  const levelOfYear = useCallback((y: number) => floors.find((f) => f.year === y)?.level ?? fixedLevelOfYear(y), [floors]);

  // Lazy floor loading: only the floor on display (listed or not: a route can go to an empty year).
  useEffect(() => {
    if (!floorRooms[year]) void loadFloor(year).catch(() => undefined);
  }, [year, floorRooms, loadFloor]);

  // Free photo textures of the floor we left.
  const prevLevel = useRef(displayLevel);
  useEffect(() => {
    if (prevLevel.current !== displayLevel) {
      prevLevel.current = displayLevel;
      flushPhotos();
    }
  }, [displayLevel]);

  // The month room on display: the store's room when it lives on this floor and can be entered
  // (open, or the store has seated us there).
  const shown = useMemo(() => {
    if (!room || levelOfYear(room.year) !== displayLevel) return null;
    const r = rooms?.find((x) => x.month === room.month);
    const seatedHere = !!seat && seat.year === room.year && seat.month === room.month;
    const routeHere = !!activeRoute && activeRoute.year === room.year && activeRoute.month === room.month &&
      (activeRoute.room_state === 'open' || activeRoute.room_state === 'current_empty');
    if (r?.state !== 'open' && !seatedHere && !routeHere) return null;
    return { year: room.year, month: room.month, frame: roomFrame(doorForMonth(room.month)), memoryCount: r?.memory_count ?? null };
  }, [room, rooms, seat, activeRoute, displayLevel, levelOfYear]);
  const frame: RoomFrame | null = shown?.frame ?? null;
  rt.room = frame;

  // ── manual lift ride: doors close, indicator counts, floor swaps, doors open ──
  const ride = useRef({ active: false, from: 0, to: 0, t: 0, swapped: false });
  useEffect(() => {
    if (riding && !rt.walkActive) {
      const p = rt.player.pos;
      const inCabin = Math.abs(p.x - LIFT.x) < LIFT.w / 2 && p.z < 0 && p.z > -LIFT.d;
      if (!inCabin) teleport(rt, LIFT_IN.x, LIFT_IN.z, 0);
      rt.player.seated = false;
      rt.player.seat = null;
      ride.current = { active: true, from: displayLevel, to: currentLevel, t: 0, swapped: false };
      rt.lift.doorsTarget = 0;
    } else if (!riding && ride.current.active) {
      ride.current.active = false;
      if (!ride.current.swapped) setDisplayLevel(currentLevel);
      rt.lift.indicator = currentLevel;
      rt.lift.doorsTarget = 1;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [riding]);
  useFrame((_, dt) => {
    const r = ride.current;
    if (!r.active) return;
    r.t += dt;
    if (r.to !== currentLevel) r.to = currentLevel;
    const k = Math.max(0, Math.min(1, (r.t - 0.6) / 1.4));
    rt.lift.indicator = r.from + (r.to - r.from) * (k * k * (3 - 2 * k));
    if (k >= 1 && !r.swapped) {
      r.swapped = true;
      setDisplayLevel(r.to);
      rt.lift.doorsTarget = 1;
    }
  });

  // Outside a walk or ride the display follows the store (e.g. enter(), a guest link, 2D→3D).
  useEffect(() => {
    if (walking || riding || rt.walkActive) return;
    if (displayLevel !== currentLevel) {
      setDisplayLevel(currentLevel);
      rt.lift.indicator = currentLevel;
      if (currentLevel === 0) teleport(rt, SPAWN.x, SPAWN.z, SPAWN.yaw);
      else teleport(rt, LIFT_OUT.x, LIFT_OUT.z + 0.4, 0);
    }
  }, [walking, riding, currentLevel, displayLevel, rt]);

  // Doors: the shown room's door stays open (the walk director drives them during a walk).
  useEffect(() => {
    if (rt.walkActive) return;
    rt.doors.target.fill(0);
    if (shown) rt.doors.target[shown.month - 1] = 1;
  }, [shown, walking, rt]);

  // Seat: the store's seat → the avatar sits there (walks there under a fade if it is far).
  useEffect(() => {
    if (!seat) {
      if (rt.player.seated) {
        rt.player.seated = false;
        rt.player.seat = null;
      }
      return;
    }
    if (!frame || !shown || seat.year !== shown.year || seat.month !== shown.month) return;
    const P = roomPlaces(frame);
    // NO_SEAT (all four taken): the back bench behind the row.
    const sp = seat.index >= NO_SEAT ? { x: 0, z: SEAT_Z + BENCH_DZ, yaw: Math.PI } : P.seats[Math.max(0, Math.min(3, seat.index))];
    const w = toWorld(frame, sp.x, sp.z);
    const yaw = sp.yaw + frame.rotY;
    rt.player.seat = { x: w.x, z: w.z, yaw, height: SEAT_H };
    if (!rt.walkActive) {
      const d = Math.hypot(rt.player.pos.x - w.x, rt.player.pos.z - w.z);
      if (d > 1.2) teleport(rt, w.x, w.z, yaw);
      rt.player.seated = true;
    }
  }, [seat, frame, shown, rt]);

  // Guide robot rest spot when no walk is running.
  useEffect(() => {
    if (walking || rt.walkActive) return;
    const g = rt.guide;
    if (frame) {
      const P = roomPlaces(frame);
      const w = toWorld(frame, P.guideWait.x, P.guideWait.z);
      g.x = w.x; g.z = w.z; g.yaw = P.guideWait.yaw + frame.rotY;
    } else if (displayLevel === 0) {
      g.x = GUIDE_HOME.x; g.z = GUIDE_HOME.z; g.yaw = GUIDE_HOME.yaw;
    } else {
      g.x = LIFT_OUT.x - 1.4; g.z = LIFT_OUT.z + 0.6; g.yaw = Math.PI * 0.8;
    }
    g.speed = 0;
    g.say = null;
  }, [frame, displayLevel, walking, rt]);

  // Leaving the room on foot: crossing back out through the door = leaveRoom().
  const inRoom = useRef(false);
  useFrame(() => {
    if (!frame || rt.walkActive || walking) { inRoom.current = false; return; }
    const p = rt.player.pos;
    const cs = Math.cos(frame.rotY), sn = Math.sin(frame.rotY);
    const dx = p.x - frame.ox, dz = p.z - frame.oz;
    const lz = dx * sn + dz * cs;
    const lx = dx * cs - dz * sn;
    const inside = lz < -0.35 && Math.abs(lx) < ROOM.halfW + 0.2;
    if (inside) inRoom.current = true;
    else if (inRoom.current && lz > 0.15) {
      inRoom.current = false;
      leaveRoom();
    }
  });

  // Screen mode: Escape steps back.
  useEffect(() => {
    if (!screenMode) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.code === 'Escape') setScreenMode(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [screenMode, setScreenMode]);
  useEffect(() => { if (!frame) rt.screenTarget = 0; }, [frame, rt]);

  // Input ownership + camera ceiling per region.
  useFrame(() => {
    rt.player.inputEnabled = !walking && !riding && !rt.walkActive && !(screenMode && rt.player.seated);
    const p = rt.player.pos;
    if (frame && inRoom.current) rt.ceiling = ROOM.h;
    else if (Math.abs(p.x - LIFT.x) < LIFT.w / 2 && p.z < 0) rt.ceiling = LIFT.h;
    else if (p.z < 0) rt.ceiling = CORR_CEIL;
    else rt.ceiling = displayLevel === 0 ? LOBBY.ceil : LANDING.ceil;
  });

  // Colliders for what is on display.
  useEffect(() => {
    const liftOpen = !riding;
    rt.colliders = [
      ...(displayLevel === 0 ? lobbyColliders(liftOpen) : landingColliders(liftOpen)),
      ...corridorColliders(shown ? shown.month : null),
      ...(frame ? roomColliders(frame) : []),
    ];
  }, [displayLevel, riding, shown, frame, rt]);

  // Interaction spots.
  const spots = useMemo<Spot[]>(() => {
    const out: Spot[] = [];
    if (!museum) return out;
    if (displayLevel === 0) {
      out.push({ i: { kind: 'desk' }, x: DESK.x + 1.35, z: DESK.z, r: 1.7, fx: DESK.x, fz: DESK.z });
      out.push({ i: { kind: 'directory' }, x: DIRECTORY.x - 1.2, z: DIRECTORY.z, r: 1.6, fx: DIRECTORY.x, fz: DIRECTORY.z });
      out.push({ i: { kind: 'attic' }, x: ATTIC.x - 1.1, z: ATTIC.z, r: 1.4, fx: ATTIC.x, fz: ATTIC.z });
      if (museum.latest) out.push({ i: { kind: 'plaque', memory_id: museum.latest.id }, x: LATEST_PLAQUE.x, z: 1.1, r: 1.2, fx: LATEST_PLAQUE.x, fz: 0 });
    }
    out.push({ i: { kind: 'lift_panel' }, x: LIFT_OUT.x - 0.3, z: LIFT_OUT.z - 0.2, r: 1.3, fx: LIFT.x, fz: 0 });
    out.push({ i: { kind: 'lift_panel' }, x: LIFT_IN.x, z: LIFT_IN.z, r: 0.95 });
    for (const d of DOORS) {
      if (shown && shown.month === d.month) continue;
      out.push({ i: { kind: 'door', year, month: d.month }, x: d.standX, z: d.standZ, r: 1.35, fx: d.x, fz: d.z });
    }
    if (frame && shown) {
      const P = roomPlaces(frame);
      const W = (x: number, z: number) => toWorld(frame, x, z);
      P.seats.forEach((sp, i) => {
        const w = W(sp.x, sp.z - 0.55);
        const c = W(sp.x, sp.z);
        out.push({ i: { kind: 'seat', year: shown.year, month: shown.month, index: i }, x: w.x, z: w.z, r: 0.75, fx: c.x, fz: c.z });
      });
      // frames / plaques / jukebox follow the same picks the room draws
      const photos = exhibits.filter((e) => e.photos.length && (e.kind === 'photo' || e.kind === 'album' || e.kind === 'forward'));
      P.frames.forEach((f, i) => {
        const e = photos[i];
        if (!e) return;
        const w = W(f.x - Math.sign(f.x) * 1.0, f.z);
        const c = W(f.x, f.z);
        out.push({ i: { kind: 'frame', memory_id: e.id }, x: w.x, z: w.z, r: 1.0, fx: c.x, fz: c.z });
      });
      const stories = exhibits.filter((e) => e.kind === 'text' || (e.kind === 'forward' && !e.photos.length)).slice(0, 4);
      stories.forEach((e, i) => {
        const pl = P.plaques[i];
        const w = W(pl.x, pl.z - 0.9);
        const c = W(pl.x, pl.z);
        out.push({ i: { kind: 'plaque', memory_id: e.id }, x: w.x, z: w.z, r: 0.8, fx: c.x, fz: c.z });
      });
      const voice = exhibits.find((e) => e.kind === 'voice' && e.audio_url);
      if (voice) {
        const j = P.jukebox;
        const w = W(j.x + frame.s * 0.9, j.z);
        const c = W(j.x, j.z);
        out.push({ i: { kind: 'jukebox', memory_id: voice.id }, x: w.x, z: w.z, r: 1.1, fx: c.x, fz: c.z });
      }
    }
    return out;
  }, [museum, displayLevel, year, shown, frame, exhibits]);

  const onStand = useCallback(() => { standUp(); }, [standUp]);
  const grandmaSpeaking = useCallback(() => {
    const s = useWorld.getState();
    return s.agentState === 'speaking' && !!s.seat;
  }, []);
  const receptionSpeaking = useCallback(() => {
    const s = useWorld.getState();
    return s.agentState === 'speaking' && !s.seat && s.currentLevel === 0;
  }, []);

  // Initial placement.
  const placed = useRef(false);
  useEffect(() => {
    if (placed.current) return;
    placed.current = true;
    rt.lift.indicator = currentLevel;
    if (currentLevel !== 0) {
      rt.player.pos.set(LIFT_OUT.x, 0, LIFT_OUT.z + 0.4);
      rt.player.yaw = 0;
      rt.player.camYaw = Math.PI;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!museum) return null;
  const audience = shown && presence && presence.year === shown.year && presence.month === shown.month
    ? presence.seats.filter((p) => !p.is_me) : [];
  const act = (i: Interactable) => interact(i);

  return (
    <>
      <ambientLight intensity={0.12} color="#ffe6c4" />
      <hemisphereLight args={['#ffe9c9', '#2b1d14', 0.35]} />
      <FollowKey />
      <LightPool count={4} intensity={5} />
      {displayLevel === 0 ? <Lobby museum={museum} act={act} /> : <Landing floor={floor} level={displayLevel} />}
      <Lift floors={floors} onInteract={act} />
      <Corridor year={year} level={displayLevel} rooms={rooms} openMonth={shown?.month ?? null} lang={lang} act={act} />
      {shown && frame && (
        <MonthRoom
          key={`${shown.year}-${shown.month}`}
          frame={frame}
          year={shown.year}
          month={shown.month}
          exhibits={room && room.year === shown.year && room.month === shown.month ? exhibits : []}
          showcase={seat ? showcase : []}
          showcaseIndex={showcaseIndex}
          memoryCount={shown.memoryCount}
          lang={lang}
          screenMode={screenMode}
          act={act}
          grandmaSpeaking={grandmaSpeaking}
          audience={audience}
          overflow={!!seat && seat.year === shown.year && seat.month === shown.month && seat.index >= NO_SEAT}
        />
      )}
      {displayLevel === 0 && <ReceptionistRobot speaking={receptionSpeaking} />}
      <GuideRobot />
      <Player avatar={avatar} onStand={onStand} seatIndex={seat && presence ? seat.index : 0} />
      <WalkDirector
        route={activeRoute}
        active={walking}
        displayLevel={displayLevel}
        setDisplayLevel={setDisplayLevel}
        reduced={reduced}
        lang={lang}
        finishWalk={finishWalk}
      />
      <Interactions spots={spots} enabled={!walking && !riding && panel === null} setNearby={setNearby} interact={interact} />
    </>
  );
}
