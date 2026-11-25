import { useEffect, useRef } from 'react';
import { rect, sprite, type Ctx } from '../../ui/pixel/draw';
import { reducedMotion } from './Bits';

/* The hero: the Memo museum cut open like a doll's house, drawn at 198x176 art pixels and upscaled with
 * image-rendering: pixelated. Floors are years, the 12 doors on each floor are months, the lift rides between
 * floors. A Telegram paper plane crosses the sky and drops a memory (lime spark) into a shut room, which opens.
 * February 2026 stays shut with its board, the way an empty month does in the real museum. */

export const ART_W = 198;
export const ART_H = 176;
const FH = 28;                 // floor height incl. slab
const SLAB = 3;
const ROOMS_X = 25;
const ROOM_W = 14;
const FLOORS = 4;              // lobby + 3 years
const FPS = 15;

const C = {
  stone: '#d6cfb4', stoneHi: '#f3f1e2', stoneLo: '#a89a74', stoneDeep: '#8b7d58',
  gold: '#d9a520', goldHi: '#f0c24a',
  roomOpen: '#1d3f82', roomLit: '#ffd76a', roomShut: '#0e2457', roomFuture: '#0a1a40',
  part: '#061431', doorway: '#ffeaa8', doorwayLo: '#f0b13a',
  wood: '#8b5a2b', woodLo: '#6b4423', board: '#f3f1e2', boardInk: '#0b1f4b',
  shaft: '#061431', cable: '#2b4c8a', car: '#f3f1e2', carLo: '#a89a74',
  lime: '#a8e27c', limeHi: '#f4ffe6', cyan: '#6ad5e7', cyanLo: '#2481aa', white: '#f3f1e2',
  lobbyFloor: '#173571', lobbyWall: '#112a60', tile: '#2b4c8a', plant: '#3a7a3e', plantLo: '#24502f',
  frames: ['#2481aa', '#d6455d', '#a8e27c', '#1c61a1', '#f0b13a', '#6ad5e7'],
};

type RoomState = 'open' | 'shut' | 'future' | 'current';
/* index 0 = 2024 (floor 1) … 2 = 2026 (floor 3). 'o' open, 's' shut, 'c' current month empty, 'f' future. */
const START: string[] = [
  'osoossosoooo',   // 2024
  'osoossooosoo',   // 2025
  'osssooosoocf',   // 2026 (Feb shut: the board in the callout; Nov is this month; Dec not yet)
];
const CODE: Record<string, RoomState> = { o: 'open', s: 'shut', c: 'current', f: 'future' };
/** Rooms that receive a memory, in order. Then the loop resets. [floorIdx 0..2, month 0..11] */
const TARGETS: [number, number][] = [[2, 10], [1, 4], [0, 6], [2, 2], [1, 7], [0, 1]];
const PLANE_S = 4.2;           // one delivery cycle
const CYCLE = PLANE_S * TARGETS.length + 2.4;

export const CALLOUT = { x: (ROOMS_X + 1 * ROOM_W + 7) / ART_W, y: 0 };
const floorTop = (f: number) => ART_H - (f + 1) * FH;   // f: 0 lobby … 3 top
CALLOUT.y = (floorTop(3) + SLAB + 6) / ART_H;
/** Vertical centre of each floor as a fraction, for the HTML year labels. */
export const FLOOR_Y = [0, 1, 2, 3].map((f) => (floorTop(f) + FH / 2 + 1) / ART_H);

const PLANE = ['.....ww', '...wwcw', '.wwwcw.', 'wwwww..', '..ww...', '..w....'];
const ROBOT = ['.l.', 'ooo', 'oeo', 'www', 'wbw', 'k.k'];
const ROBOT_B = ['.l.', 'ooo', 'oeo', 'www', 'wbw', '.k.'];
const DESK_BOT = ['.g.', 'www', 'wew', 'www'];
const VISITOR = ['.h.', 'hfh', 'rrr', 'rgr', 'rrr', 'f.f'];
const SPR = { o: '#f3f1e2', e: '#6ad5e7', w: '#f3f1e2', b: '#2b4c8a', k: '#3d63a8', l: '#a8e27c', g: '#d9a520', h: '#1a1010', f: '#c98d5e', r: '#d6455d' };

const GLYPH: Record<string, string[]> = {
  M: ['x...x', 'xx.xx', 'x.x.x', 'x...x', 'x...x'],
  E: ['xxx', 'x..', 'xx.', 'x..', 'xxx'],
  O: ['xxx', 'x.x', 'x.x', 'x.x', 'xxx'],
};

function drawRoof(ctx: Ctx) {
  const top = floorTop(3);
  // cornice
  rect(ctx, 0, top - 4, ART_W, 4, C.stoneLo);
  rect(ctx, 0, top - 4, ART_W, 1, C.stoneHi);
  rect(ctx, 0, top - 1, ART_W, 1, C.stoneDeep);
  // stepped pediment
  const steps = 7;
  for (let i = 0; i < steps; i++) {
    const inset = 8 + i * 12;
    const y = top - 4 - (i + 1) * 4;
    rect(ctx, inset, y, ART_W - inset * 2, 4, i % 2 ? C.stone : C.stoneHi);
    rect(ctx, inset, y, 4, 1, C.goldHi);
    rect(ctx, ART_W - inset - 4, y, 4, 1, C.goldHi);
  }
  // gold tympanum band and the sign
  const signY = top - 4 - 3 * 4 + 1;
  rect(ctx, 58, signY - 2, ART_W - 116, 9, C.part);
  let cx = Math.round(ART_W / 2 - 9);
  for (const ch of 'MEMO') {
    const g = GLYPH[ch];
    sprite(ctx, g, { x: C.lime }, cx, signY);
    cx += g[0].length + 1;
  }
  rect(ctx, ART_W / 2 - 3, top - 4 - steps * 4 - 2, 6, 2, C.gold);
}

function drawShell(ctx: Ctx) {
  const roofBase = floorTop(3);
  // outer walls
  rect(ctx, 2, roofBase, 3, ART_H - roofBase, C.stone);
  rect(ctx, 2, roofBase, 1, ART_H - roofBase, C.stoneHi);
  rect(ctx, ART_W - 5, roofBase, 3, ART_H - roofBase, C.stoneLo);
  // lift shaft
  rect(ctx, 5, roofBase, 18, ART_H - roofBase, C.shaft);
  rect(ctx, 9, roofBase, 1, ART_H - roofBase, C.cable);
  rect(ctx, 18, roofBase, 1, ART_H - roofBase, C.cable);
  rect(ctx, 23, roofBase, 2, ART_H - roofBase, C.stoneLo);
  // slabs
  for (let f = 0; f < FLOORS; f++) {
    const y = floorTop(f);
    rect(ctx, 5, y, ART_W - 10, SLAB, C.stoneLo);
    rect(ctx, 5, y, ART_W - 10, 1, C.stone);
  }
  // plinth
  rect(ctx, 0, ART_H - 2, ART_W, 2, C.stoneDeep);
}

function drawRoom(ctx: Ctx, f: number, m: number, state: RoomState, flash: number, t: number) {
  const x = ROOMS_X + m * ROOM_W;
  const y = floorTop(f) + SLAB;
  const h = FH - SLAB;
  const bottom = y + h;
  const bg = state === 'open' ? C.roomOpen : state === 'future' ? C.roomFuture : C.roomShut;
  rect(ctx, x, y, ROOM_W, h, bg);
  rect(ctx, x, y, 1, h, C.part);
  const dx = x + 3;
  const dy = bottom - 14;
  if (state === 'open') {
    // ceiling lamp, a framed photo, the doorway glowing from the theater
    rect(ctx, x + 6, y, 2, 1, C.roomLit);
    ctx.globalAlpha = 0.25;
    rect(ctx, x + 3, y + 1, 8, 1, C.roomLit);
    ctx.globalAlpha = 1;
    rect(ctx, x + 4, y + 3, 6, 5, C.gold);
    rect(ctx, x + 5, y + 4, 4, 3, C.frames[(f * 5 + m) % C.frames.length]);
    rect(ctx, dx, dy, 8, 14, C.doorwayLo);
    rect(ctx, dx + 1, dy + 1, 6, 13, C.doorway);
    rect(ctx, dx + 6, dy, 2, 14, C.wood);   // door swung open
    // seats inside the doorway
    rect(ctx, dx + 1, bottom - 3, 2, 2, C.roomOpen);
    rect(ctx, dx + 4, bottom - 3, 2, 2, C.roomOpen);
    ctx.globalAlpha = 0.35;
    rect(ctx, dx - 1, bottom, 10, 1, C.doorway);
    ctx.globalAlpha = 1;
  } else {
    // nail where a frame would hang
    rect(ctx, x + 7, y + 5, 1, 1, C.stoneLo);
    const door = state === 'future' ? '#173571' : C.wood;
    const doorLo = state === 'future' ? '#0e2457' : C.woodLo;
    rect(ctx, dx, dy, 8, 14, doorLo);
    rect(ctx, dx + 1, dy + 1, 6, 13, door);
    rect(ctx, dx + 5, dy + 8, 1, 1, C.gold);
    // the board hung on the shut door
    const bc = state === 'current' ? C.goldHi : state === 'future' ? '#a7b6d6' : C.board;
    rect(ctx, dx - 1, dy + 3, 10, 5, bc);
    rect(ctx, dx, dy + 4, 6, 1, C.boardInk);
    rect(ctx, dx, dy + 6, 4, 1, C.boardInk);
    if (state === 'current' && Math.floor(t * 2) % 2 === 0) rect(ctx, dx + 6, dy + 6, 2, 1, C.boardInk);
  }
  if (flash > 0) {
    ctx.globalAlpha = flash * 0.8;
    rect(ctx, x + 1, y, ROOM_W - 1, h, C.lime);
    ctx.globalAlpha = 1;
  }
}

function drawLobby(ctx: Ctx, t: number, still: boolean) {
  const y = floorTop(0) + SLAB;
  const h = FH - SLAB;
  const bottom = y + h - 2;
  rect(ctx, ROOMS_X, y, ART_W - 5 - ROOMS_X, h, C.lobbyWall);
  rect(ctx, ROOMS_X, bottom - 3, ART_W - 5 - ROOMS_X, 3, C.lobbyFloor);
  for (let x = ROOMS_X + 1; x < ART_W - 6; x += 4) rect(ctx, x, bottom - 3, 2, 1, C.tile);
  // directory board: three years with open-room bars
  const bx = 70;
  rect(ctx, bx, y + 3, 22, 12, C.gold);
  rect(ctx, bx + 1, y + 4, 20, 10, C.part);
  [9, 10, 6].forEach((n, i) => {
    rect(ctx, bx + 3, y + 6 + i * 3, 3, 1, C.white);
    rect(ctx, bx + 8, y + 6 + i * 3, n, 1, C.lime);
  });
  // reception desk with the receptionist
  sprite(ctx, DESK_BOT, SPR, 41, bottom - 13);
  rect(ctx, 34, bottom - 9, 18, 6, C.stone);
  rect(ctx, 34, bottom - 9, 18, 1, C.goldHi);
  rect(ctx, 34, bottom - 4, 18, 1, C.stoneLo);
  // entrance doors
  const ex = 150;
  rect(ctx, ex, y + 4, 20, h - 6, C.gold);
  rect(ctx, ex + 1, y + 5, 18, h - 7, C.cyanLo);
  rect(ctx, ex + 1, y + 5, 18, 1, C.cyan);
  rect(ctx, ex + 10, y + 5, 1, h - 7, C.gold);
  // plants
  for (const px of [104, 140, 180]) {
    rect(ctx, px, bottom - 6, 4, 3, C.plant);
    rect(ctx, px + 1, bottom - 7, 2, 1, C.plant);
    rect(ctx, px + 1, bottom - 3, 2, 0, C.plantLo);
  }
  // the guide robot pacing between the desk and the lift
  const span = 40;
  const p = still ? 0.5 : (Math.sin(t * 0.7) + 1) / 2;
  const gx = Math.round(56 + p * span);
  const frame = !still && Math.floor(t * 6) % 2 === 0;
  sprite(ctx, frame ? ROBOT : ROBOT_B, SPR, gx, bottom - 9);
}

/** Lift car position (floor as a float) at time t: 2.2 s parked, 1.2 s riding, through 0→1→2→3→2→1. */
function liftFloor(t: number): number {
  const seq = [0, 1, 2, 3, 2, 1];
  const leg = 3.4;
  const i = Math.floor(t / leg) % seq.length;
  const from = seq[i];
  const to = seq[(i + 1) % seq.length];
  const local = (t % leg) - 2.2;
  if (local <= 0) return from;
  const k = Math.min(1, local / 1.2);
  const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
  return from + (to - from) * e;
}

function drawLift(ctx: Ctx, t: number, still: boolean) {
  const lf = still ? 2 : liftFloor(t);
  const cy = Math.round(ART_H - (lf + 1) * FH + SLAB + 2);
  rect(ctx, 13, floorTop(3), 2, cy - floorTop(3), C.cable);
  rect(ctx, 7, cy, 14, FH - SLAB - 2, C.carLo);
  rect(ctx, 8, cy + 1, 12, FH - SLAB - 4, C.car);
  rect(ctx, 7, cy, 14, 1, C.goldHi);
  sprite(ctx, VISITOR, SPR, 12, cy + FH - SLAB - 11);
  // call lights: the floor the car is at glows
  for (let f = 0; f < FLOORS; f++) {
    const at = Math.abs(lf - f) < 0.08;
    rect(ctx, 23, floorTop(f) + SLAB + 4, 2, 2, at ? C.lime : C.cable);
  }
}

interface Frame { states: RoomState[][]; flash: number[][]; plane: { x: number; y: number } | null; spark: { x: number; y: number } | null }

function frameAt(t: number, still: boolean): Frame {
  const states = START.map((row) => [...row].map((c) => CODE[c]));
  const flash = states.map((row) => row.map(() => 0));
  if (still) return { states, flash, plane: null, spark: null };
  const local = t % CYCLE;
  const done = Math.floor(local / PLANE_S);
  for (let i = 0; i < Math.min(done, TARGETS.length); i++) {
    const [f, m] = TARGETS[i];
    states[f][m] = 'open';
  }
  let plane: Frame['plane'] = null;
  let spark: Frame['spark'] = null;
  if (done < TARGETS.length) {
    const [f, m] = TARGETS[done];
    const p = (local % PLANE_S) / PLANE_S;      // 0..1 within this delivery
    const tx = ROOMS_X + m * ROOM_W + 7;
    const x = ART_W + 10 - p * (ART_W + 30);
    plane = { x, y: 6 + Math.round(Math.sin(p * 9) * 1.5) };
    const dropAt = (ART_W + 10 - tx) / (ART_W + 30);
    if (p > dropAt) {
      const fall = (p - dropAt) * PLANE_S;          // seconds since release
      const landY = floorTop(f + 1) + SLAB + 10;
      const sy = 12 + fall * fall * 90;
      if (sy < landY) spark = { x: tx, y: sy };
      else {
        states[f][m] = 'open';
        flash[f][m] = Math.max(0, 1 - (sy - landY) / 60);
      }
    }
  }
  return { states, flash, plane, spark };
}

function draw(ctx: Ctx, t: number, still: boolean) {
  ctx.clearRect(0, 0, ART_W, ART_H);
  const fr = frameAt(t, still);
  drawRoof(ctx);
  drawShell(ctx);
  for (let i = 0; i < 3; i++) for (let m = 0; m < 12; m++) drawRoom(ctx, i + 1, m, fr.states[i][m], fr.flash[i][m], t);
  drawLobby(ctx, t, still);
  drawLift(ctx, t, still);
  if (fr.spark) {
    ctx.globalAlpha = 0.35;
    rect(ctx, fr.spark.x - 1, fr.spark.y - 4, 3, 4, C.lime);
    ctx.globalAlpha = 1;
    rect(ctx, fr.spark.x - 1, fr.spark.y, 3, 3, C.lime);
    rect(ctx, fr.spark.x, fr.spark.y + 1, 1, 1, C.limeHi);
  }
  if (fr.plane) {
    // dotted trail behind the plane
    for (let i = 1; i < 9; i++) {
      ctx.globalAlpha = 0.5 - i * 0.05;
      rect(ctx, fr.plane.x + 7 + i * 3, fr.plane.y + 3, 1, 1, C.cyan);
    }
    ctx.globalAlpha = 1;
    sprite(ctx, PLANE, { w: C.white, c: C.cyan }, Math.round(fr.plane.x), fr.plane.y);
  }
}

export function HeroMuseum() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;
    let still = reducedMotion();
    let raf = 0;
    let last = 0;
    let visible = true;
    const t0 = performance.now() - 1500;
    const paint = (now: number) => draw(ctx, (now - t0) / 1000, still);
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      if (now - last < 1000 / FPS) return;
      last = now;
      paint(now);
    };
    const start = () => { if (!raf && !still && visible) raf = requestAnimationFrame(tick); };
    const stop = () => { cancelAnimationFrame(raf); raf = 0; };
    paint(performance.now());
    start();
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible) start(); else stop(); });
    io.observe(canvas);
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onMq = () => { still = mq.matches; stop(); paint(performance.now()); start(); };
    mq.addEventListener('change', onMq);
    return () => { stop(); io.disconnect(); mq.removeEventListener('change', onMq); };
  }, []);
  return <canvas ref={ref} className="hm-canvas" width={ART_W} height={ART_H} aria-hidden="true" />;
}
