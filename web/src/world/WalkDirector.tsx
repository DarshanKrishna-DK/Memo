import { useEffect, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import type { MuseumRoute } from '../contract';
import { CORR_HALF_W, DOORS, LIFT, LIFT_OUT, SEAT_H, doorForMonth, roomFrame, roomPlaces, toWorld } from './layout';
import { useRuntime, wrapAngle, type WorldRuntime } from './runtime';
import { guideLine } from './Cast';
import { floorWithYear } from '../lib/floors';

// The guided walk (PRD "The guided walk", V4): the guide robot steps out and says "Follow me",
// walks to the lift, rides, walks the corridor, the door opens and the visitor sits. The plan
// is computed from where the visitor actually is, then scaled to route.walk_seconds (5-10 s).
// The store owns the outcome: at the natural end the world calls finishWalk(); a skip (or the
// store's safety timer) ends `mode === 'walking'` early and the director snaps to the end.

interface Pt { x: number; z: number }
type Seg =
  | { kind: 'say'; dur: number; gFrom: Pt; gTo: Pt; text: string }
  | { kind: 'move'; dur: number; p: Pt[]; g: Pt[]; faceEnd?: number; gFaceEnd?: number }
  | { kind: 'ride'; dur: number; from: number; to: number }
  | { kind: 'door'; dur: number; month: number; open: boolean }
  | { kind: 'hold'; dur: number }
  | { kind: 'sit'; dur: number; seat: Pt & { yaw: number } };

const CABIN_P: Pt = { x: LIFT.x + 0.35, z: -0.75 };
const CABIN_G: Pt = { x: LIFT.x - 0.45, z: -1.45 };

function len(pts: Pt[]) {
  let L = 0;
  for (let i = 1; i < pts.length; i++) L += Math.hypot(pts[i].x - pts[i - 1].x, pts[i].z - pts[i - 1].z);
  return L;
}

function along(pts: Pt[], u: number): Pt & { dx: number; dz: number } {
  const total = len(pts);
  if (pts.length < 2 || total < 1e-6) return { ...pts[pts.length - 1], dx: 0, dz: 0 };
  let d = Math.max(0, Math.min(1, u)) * total;
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i];
    const l = Math.hypot(b.x - a.x, b.z - a.z);
    if (d <= l || i === pts.length - 1) {
      const k = l > 0 ? Math.min(1, d / l) : 1;
      return { x: a.x + (b.x - a.x) * k, z: a.z + (b.z - a.z) * k, dx: b.x - a.x, dz: b.z - a.z };
    }
    d -= l;
  }
  return { ...pts[pts.length - 1], dx: 0, dz: 0 };
}

const ease = (t: number) => t * t * (3 - 2 * t);

/** Where the visitor is, coarsely: inside a month room (behind a corridor wall), the cabin,
 *  the corridor, or the lobby / landing. */
function where(p: Pt): 'room' | 'cabin' | 'corridor' | 'hall' {
  if (Math.abs(p.x - LIFT.x) < LIFT.w / 2 && p.z < 0 && p.z > -LIFT.d) return 'cabin';
  if (p.z < 0 && Math.abs(p.x) > CORR_HALF_W + 0.15) return 'room';
  if (p.z < 0) return 'corridor';
  return 'hall';
}

export interface Plan { segs: Seg[]; start: Pt; enter: boolean; month: number; level: number; endGuide: Pt & { yaw: number }; endPlayer: Pt & { yaw: number } }

export function buildPlan(route: MuseumRoute, player: Pt, guide: Pt, displayLevel: number, lang: string): Plan {
  const door = doorForMonth(route.month);
  const enter = route.room_state === 'open' || route.room_state === 'current_empty';
  let start = { ...player };
  // Visitor inside another month room: start them at that room's door in the corridor.
  if (where(start) === 'room') {
    const side = start.x < 0 ? 'L' : 'R';
    const near = DOORS.filter((d) => d.side === side).sort((a, b) => Math.abs(a.z - start.z) - Math.abs(b.z - start.z))[0];
    start = { x: near.standX, z: near.standZ };
  }
  const segs: Seg[] = [];
  const gStart = Math.hypot(guide.x - start.x, guide.z - start.z) > 6 ? { x: start.x + 0.9, z: start.z - 0.9 } : guide;
  // 1. "Follow me": the guide steps out beside the visitor.
  const toward = (a: Pt, b: Pt, d: number) => {
    const l = Math.hypot(b.x - a.x, b.z - a.z) || 1;
    return { x: a.x + ((b.x - a.x) / l) * d, z: a.z + ((b.z - a.z) / l) * d };
  };
  const needsRide = route.level !== displayLevel;
  const firstGoal = needsRide ? LIFT_OUT : { x: 0, z: 0.6 };
  const gStep = toward(start, where(start) === 'corridor' ? { x: 0, z: door.z } : firstGoal, 1.1);
  segs.push({ kind: 'say', dur: 1.0, gFrom: gStart, gTo: gStep, text: guideLine(lang) });

  let cur = start;
  let gcur = gStep;
  // 2. To the lift and ride (only if the room is on another floor).
  if (needsRide) {
    const p: Pt[] = [cur];
    if (where(cur) === 'corridor') p.push({ x: 0, z: Math.min(cur.z, -0.5) }, { x: 0.8, z: 0.7 });
    if (where(cur) !== 'cabin') p.push(LIFT_OUT, CABIN_P);
    const g: Pt[] = [gcur, ...p.slice(1, -1), { x: LIFT.x, z: 0.2 }, CABIN_G];
    segs.push({ kind: 'move', dur: len(p) / 3.0, p, g, faceEnd: 0, gFaceEnd: 0 });
    segs.push({ kind: 'ride', dur: 2.6, from: displayLevel, to: route.level });
    cur = CABIN_P;
    gcur = CABIN_G;
  }
  // 3. Down the corridor to the door.
  {
    const lane = door.side === 'L' ? -0.35 : 0.35;
    const p: Pt[] = [cur];
    const c = where(cur);
    if (c === 'cabin') p.push(LIFT_OUT, { x: 0.4, z: 0.4 });
    else if (c === 'hall') p.push({ x: 0, z: 0.6 });
    p.push({ x: lane, z: Math.min(-0.6, door.z + 1.6) }, { x: door.standX, z: door.standZ });
    const gEnd = { x: door.standX + (door.side === 'L' ? 0.25 : -0.25), z: door.z - 1.0 };
    const g: Pt[] = [gcur];
    if (c === 'cabin') g.push(LIFT_OUT, { x: 0.2, z: 0.1 });
    else if (c === 'hall') g.push({ x: 0, z: 0.2 });
    g.push({ x: -lane, z: Math.min(-1.0, door.z + 0.8) }, gEnd);
    const faceDoor = Math.atan2(door.x - door.standX, 0);
    segs.push({ kind: 'move', dur: Math.max(0.8, len(p) / 3.2), p, g, faceEnd: faceDoor, gFaceEnd: faceDoor + Math.PI * 0.6 * (door.side === 'L' ? -1 : 1) });
    cur = p[p.length - 1];
    gcur = gEnd;
  }
  // 4. The door opens (or shakes, with its board), then in and sit down.
  segs.push({ kind: 'door', dur: 0.8, month: route.month, open: enter });
  const f = roomFrame(door);
  const P = roomPlaces(f);
  let endPlayer: Plan['endPlayer'] = { ...cur, yaw: Math.atan2(door.x - door.standX, 0) };
  let endGuide: Plan['endGuide'] = { ...gcur, yaw: endPlayer.yaw };
  if (enter) {
    const L = (x: number, z: number) => toWorld(f, x, z);
    const seat = P.seats[0];
    const s = f.s;
    const p: Pt[] = [cur, L(f.doorLX, 0.2), L(f.doorLX, -0.9), L(s * 2.85, -2.2), L(s * 2.85, -5.2), L(seat.x, -5.2), L(seat.x, -5.0)];
    const gw = L(P.guideWait.x, P.guideWait.z);
    const g: Pt[] = [gcur, L(f.doorLX, 0.5), L(f.doorLX, -0.5), gw];
    segs.push({ kind: 'move', dur: len(p) / 3.0, p, g, faceEnd: seat.yaw + f.rotY, gFaceEnd: P.guideWait.yaw + f.rotY });
    const sp = L(seat.x, seat.z);
    endPlayer = { ...sp, yaw: seat.yaw + f.rotY };
    endGuide = { ...gw, yaw: P.guideWait.yaw + f.rotY };
    segs.push({ kind: 'sit', dur: 0.6, seat: endPlayer });
  } else {
    segs.push({ kind: 'hold', dur: 1.4 });
  }

  // Scale to the server's walk_seconds (5-10 s); the ride keeps its own pace.
  const target = Math.max(5, Math.min(10, route.walk_seconds || 7));
  const fixed = segs.reduce((a, s) => a + (s.kind === 'ride' || s.kind === 'sit' || s.kind === 'hold' ? s.dur : 0), 0);
  const flex = segs.reduce((a, s) => a + (s.kind === 'move' || s.kind === 'say' || s.kind === 'door' ? s.dur : 0), 0);
  const k = Math.max(0.3, Math.min(1.8, (target - 0.3 - fixed) / Math.max(0.1, flex)));
  segs.forEach((s) => { if (s.kind === 'move' || s.kind === 'say' || s.kind === 'door') s.dur *= k; });
  return { segs, start, enter, month: route.month, level: route.level, endGuide, endPlayer };
}

export function WalkDirector({
  route, active, displayLevel, setDisplayLevel, reduced, lang, finishWalk,
}: {
  route: MuseumRoute | null; active: boolean; displayLevel: number; setDisplayLevel: (l: number) => void;
  reduced: boolean; lang: string; finishWalk: () => void;
}) {
  const rt = useRuntime();
  const st = useRef<{ plan: Plan | null; t: number; seg: number; segT: number; done: boolean; rode: boolean; route: MuseumRoute | null }>({
    plan: null, t: 0, seg: 0, segT: 0, done: false, rode: false, route: null,
  });
  const levelRef = useRef(displayLevel);
  levelRef.current = displayLevel;
  const finishRef = useRef(finishWalk);
  finishRef.current = finishWalk;
  const setLevelRef = useRef(setDisplayLevel);
  setLevelRef.current = setDisplayLevel;

  // Start / abort.
  useEffect(() => {
    const s = st.current;
    if (active && route && s.route !== route) {
      s.route = route;
      s.t = 0; s.seg = 0; s.segT = 0; s.done = false; s.rode = false;
      if (reduced) {
        // Reduced motion: a short fade; the store's short timer finishes the walk.
        s.plan = buildPlan(route, rt.player.pos, rt.guide, levelRef.current, lang);
        rt.fadeTarget = 1;
        rt.walkActive = true;
        rt.player.scripted = true;
        return;
      }
      s.plan = buildPlan(route, rt.player.pos, rt.guide, levelRef.current, lang);
      rt.walkActive = true;
      rt.player.scripted = true;
      rt.player.seated = false;
      rt.player.seat = null;
      rt.player.pos.x = s.plan.start.x;
      rt.player.pos.z = s.plan.start.z;
      rt.doors.target.fill(0);
    } else if (!active && s.plan) {
      // Skipped (or finished by the store): jump to the end state.
      snapToEnd(rt, s.plan, setLevelRef.current);
      s.plan = null;
      s.route = null;
    }
  }, [active, route, reduced, lang, rt]);

  useFrame((_, rawDt) => {
    const s = st.current;
    const plan = s.plan;
    if (!plan || s.done || reduced) return;
    const dt = Math.min(rawDt, 0.05);
    const seg = plan.segs[s.seg];
    if (!seg) {
      s.done = true;
      rt.guide.say = null;
      rt.guide.speed = 0;
      rt.player.speed = 0;
      finishRef.current();
      return;
    }
    s.segT += dt;
    const u = Math.min(1, s.segT / Math.max(0.01, seg.dur));
    const P = rt.player, G = rt.guide;
    const px = P.pos.x, pz = P.pos.z, gx = G.x, gz = G.z;

    switch (seg.kind) {
      case 'say': {
        G.say = seg.text;
        const e = ease(u);
        G.x = seg.gFrom.x + (seg.gTo.x - seg.gFrom.x) * e;
        G.z = seg.gFrom.z + (seg.gTo.z - seg.gFrom.z) * e;
        const face = Math.atan2(P.pos.x - G.x, P.pos.z - G.z);
        G.yaw += wrapAngle(face - G.yaw) * Math.min(1, dt * 6);
        P.yaw += wrapAngle(Math.atan2(G.x - P.pos.x, G.z - P.pos.z) - P.yaw) * Math.min(1, dt * 5);
        break;
      }
      case 'move': {
        if (u > 0.35) G.say = null;
        const e = ease(u);
        const a = along(seg.p, e);
        const b = along(seg.g, Math.min(1, ease(Math.min(1, u * 1.12))));
        P.pos.x = a.x; P.pos.z = a.z;
        G.x = b.x; G.z = b.z;
        if (a.dx || a.dz) P.yaw += wrapAngle(Math.atan2(a.dx, a.dz) - P.yaw) * Math.min(1, dt * 8);
        if (b.dx || b.dz) G.yaw += wrapAngle(Math.atan2(b.dx, b.dz) - G.yaw) * Math.min(1, dt * 8);
        if (u > 0.92 && seg.faceEnd !== undefined) P.yaw += wrapAngle(seg.faceEnd - P.yaw) * Math.min(1, dt * 8);
        if (u > 0.85 && seg.gFaceEnd !== undefined) G.yaw += wrapAngle(seg.gFaceEnd - G.yaw) * Math.min(1, dt * 6);
        break;
      }
      case 'ride': {
        G.say = floorWithYear(seg.to);
        const t = s.segT;
        rt.lift.doorsTarget = t < seg.dur - 0.6 ? 0 : 1;
        const k = Math.max(0, Math.min(1, (t - 0.6) / Math.max(0.1, seg.dur - 1.2)));
        rt.lift.indicator = seg.from + (seg.to - seg.from) * ease(k);
        if (k >= 1 && !s.rode) {
          s.rode = true;
          setLevelRef.current(seg.to);
        }
        P.yaw += wrapAngle(0 - P.yaw) * Math.min(1, dt * 4);
        G.yaw += wrapAngle(0 - G.yaw) * Math.min(1, dt * 4);
        break;
      }
      case 'door': {
        const i = seg.month - 1;
        if (seg.open) rt.doors.target[i] = 1;
        else if (s.segT < dt * 1.5) rt.doors.shake[i] = 0.7;
        break;
      }
      case 'hold':
        break;
      case 'sit': {
        P.seat = { x: seg.seat.x, z: seg.seat.z, yaw: seg.seat.yaw, height: SEAT_H };
        P.seated = true;
        P.pos.x += (seg.seat.x - P.pos.x) * Math.min(1, dt * 8);
        P.pos.z += (seg.seat.z - P.pos.z) * Math.min(1, dt * 8);
        P.yaw += wrapAngle(seg.seat.yaw - P.yaw) * Math.min(1, dt * 8);
        break;
      }
    }
    P.speed = seg.kind === 'move' ? Math.hypot(P.pos.x - px, P.pos.z - pz) / dt : 0;
    G.speed = Math.hypot(G.x - gx, G.z - gz) / dt;

    if (u >= 1) {
      s.seg++;
      s.segT = 0;
    }
  });

  return null;
}

/** Jump straight to the end of a walk (skip, safety timer or reduced motion). */
function snapToEnd(rt: WorldRuntime, plan: Plan, setLevel: (l: number) => void) {
  setLevel(plan.level);
  rt.lift.indicator = plan.level;
  rt.lift.doorsTarget = 1;
  const i = plan.month - 1;
  rt.doors.target.fill(0);
  if (plan.enter) {
    rt.doors.target[i] = 1;
    rt.doors.open[i] = 1;
  } else rt.doors.shake[i] = 0.7;
  rt.player.pos.x = plan.endPlayer.x;
  rt.player.pos.z = plan.endPlayer.z;
  rt.player.yaw = plan.endPlayer.yaw;
  rt.player.camYaw = plan.endPlayer.yaw + Math.PI;
  rt.player.speed = 0;
  rt.guide.x = plan.endGuide.x;
  rt.guide.z = plan.endGuide.z;
  rt.guide.yaw = plan.endGuide.yaw;
  rt.guide.speed = 0;
  rt.guide.say = null;
  rt.player.scripted = false;
  rt.walkActive = false;
  rt.fadeTarget = 0;
}

/** Natural end, after finishWalk(): hand control back. */
export function releaseWalk(rt: WorldRuntime) {
  rt.player.scripted = false;
  rt.walkActive = false;
}
