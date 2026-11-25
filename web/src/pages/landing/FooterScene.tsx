import { useEffect, useRef } from 'react';
import { makeCanvas, rect, rng, sprite, type Ctx } from '../../ui/pixel/draw';
import { reducedMotion } from './Bits';

/* Footer signature, after MedSim's night street: drawn 84 art pixels tall and upscaled 2x/3x/4x.
 * Left to right: a sleeping city under stars, a Telegram paper plane flying a dotted route across the sky
 * into the Memo museum (a window lights each time it lands), Ajji and the guide robot at the door, and the
 * route turning into a voice-note waveform at the far end. An auto-rickshaw drives the road.
 * ~20 fps, paused off-screen, one still frame under reduced motion. */

const H = 84;
const GROUND = 68;
const ROAD = 72;
const ROUTE_Y = 24;
const FPS = 20;

const C = {
  far0: '#0e2457', far1: '#112a60', farEdge: '#173571', farLit: '#3d63a8',
  warm: '#ffd76a', warm2: '#ffeaa8',
  stone: '#d6cfb4', stoneHi: '#f3f1e2', stoneLo: '#a89a74', stoneDeep: '#8b7d58',
  gold: '#d9a520', goldHi: '#f0c24a', hall: '#0e2457',
  white: '#f3f1e2', walk: '#173571', walkHi: '#2b4c8a', road: '#061431', lane: '#2b4c8a',
  lime: '#a8e27c', limeDim: '#41713f', cyan: '#6ad5e7', cyanDim: '#2b6f84',
  post: '#2b4c8a', bush: '#24502f', bushHi: '#3a7a3e', lampGlow: '#8a7b45', lampPool: '#45507a', lampPoolHi: '#6f6f6a',
  frames: ['#2481aa', '#d6455d', '#a8e27c', '#1c61a1', '#f0b13a'],
};

const RICKSHAW = [
  '....gggggggggg.....',
  '...gggggggggggg....',
  '..gg.cccc.g...gg...',
  '..g..cccc.g....g...',
  '.gg.......g....gyy.',
  '.ggkkkkkkkgkkkkggg.',
  'ggggggggggggggggggg',
  '...kk.........kk...',
];
const RICK_PAL = { g: '#a8e27c', k: '#3f7a17', c: '#6ad5e7', y: '#ffd76a' };

const GRANDMA = ['.HH..', 'HffH.', '.ff..', 'rrgr.', 'rrrgr', 'frrrf', '.rrr.', '.rgr.', '.rrr.', '.f.f.'];
const GRANDMA_PAL = { H: '#d8d4c8', f: '#b77a4e', r: '#d6455d', g: '#f0b13a' };
const ROBOT = ['..l..', '.www.', 'weeew', '.www.', 'wbbbw', '.www.', '.www.', 'k...k'];
const ROBOT_WAVE = ['..l..', '.www.', 'weeew', '.www.w', 'wbbbw.', '.www.', '.www.', 'k...k'];
const ROBOT_PAL = { w: '#f3f1e2', e: '#6ad5e7', b: '#2b4c8a', l: '#a8e27c', k: '#3d63a8' };
const PLANE = ['.....ww', '...wwcw', '.wwwcw.', 'wwwww..', '..ww...', '..w....'];

const GLYPHS: Record<string, string[]> = {
  M: ['x...x', 'xx.xx', 'x.x.x', 'x...x', 'x...x'],
  E: ['xxx', 'x..', 'xx.', 'x..', 'xxx'],
  O: ['xxx', 'x.x', 'x.x', 'x.x', 'xxx'],
};

function layout(W: number) {
  const mx = W < 260 ? Math.round(W * 0.5) : Math.round(W * 0.6);
  return { mx, voiceX: Math.max(mx + 58, Math.round(W * 0.82)) };
}

/** Museum: stepped pediment, 'MEMO' sign, colonnade with framed photos between the columns, lit door. */
function drawMuseum(ctx: Ctx, mx: number) {
  const left = mx - 50;
  const w = 100;
  const top = 40;
  // wings
  for (const [x, ww] of [[mx - 72, 22], [mx + 50, 22]] as const) {
    rect(ctx, x, 50, ww, GROUND - 50, C.stoneLo);
    rect(ctx, x, 50, ww, 1, C.stoneHi);
    for (let wx = x + 3; wx + 4 <= x + ww - 2; wx += 6) {
      rect(ctx, wx, 55, 4, 5, C.gold);
      rect(ctx, wx + 1, 56, 2, 3, C.warm);
    }
  }
  // hall
  rect(ctx, left, top, w, GROUND - top, C.hall);
  // cornice + pediment
  rect(ctx, left - 3, top - 3, w + 6, 3, C.stoneLo);
  rect(ctx, left - 3, top - 3, w + 6, 1, C.stoneHi);
  for (let i = 0; i < 5; i++) {
    const inset = 2 + i * 10;
    rect(ctx, left + inset - 3, top - 3 - (i + 1) * 3, w + 6 - inset * 2, 3, i % 2 ? C.stone : C.stoneHi);
  }
  rect(ctx, mx - 2, top - 20, 4, 2, C.gold);
  // sign on the pediment
  let cx = mx - 9;
  ctx.globalAlpha = 0.2;
  rect(ctx, cx - 2, top - 11, 22, 7, C.lime);
  ctx.globalAlpha = 1;
  for (const ch of 'MEMO') {
    const g = GLYPHS[ch];
    sprite(ctx, g, { x: C.lime }, cx, top - 10);
    cx += g[0].length + 1;
  }
  // colonnade with photo frames between the columns
  const cols = 7;
  for (let i = 0; i < cols; i++) {
    if (i === 3) continue;   // the door bay
    const x = left + 4 + i * 15;
    rect(ctx, x, top + 1, 4, GROUND - top - 3, C.stone);
    rect(ctx, x, top + 1, 1, GROUND - top - 3, C.stoneHi);
    rect(ctx, x - 1, top, 6, 2, C.stoneHi);
    rect(ctx, x - 1, GROUND - 3, 6, 2, C.stoneLo);
  }
  for (let i = 0; i < cols - 1; i++) {
    const x = left + 10 + i * 15;
    rect(ctx, x, 47, 7, 6, C.gold);
    rect(ctx, x + 1, 48, 5, 4, C.frames[i % C.frames.length]);
  }
  // lit door in the middle bay
  rect(ctx, mx - 5, 56, 10, GROUND - 56, C.gold);
  rect(ctx, mx - 4, 57, 8, GROUND - 57, C.warm2);
  rect(ctx, mx, 57, 1, GROUND - 57, C.warm);
  ctx.globalAlpha = 0.35;
  rect(ctx, mx - 8, GROUND, 16, 2, C.warm);
  ctx.globalAlpha = 0.18;
  rect(ctx, mx - 12, GROUND + 2, 24, 2, C.warm);
  ctx.globalAlpha = 1;
  // steps and bushes
  rect(ctx, left - 4, GROUND - 1, w + 8, 1, C.stoneDeep);
  for (const bx of [mx - 66, mx - 58, mx + 54, mx + 62]) {
    rect(ctx, bx, GROUND - 3, 6, 3, C.bush);
    rect(ctx, bx + 1, GROUND - 4, 4, 1, C.bushHi);
  }
}

function drawStatic(ctx: Ctx, W: number) {
  const { mx } = layout(W);
  const r = rng(11);
  let x = -4;
  while (x < W) {
    const w = 8 + Math.floor(r() * 16);
    const top = 40 + Math.floor(r() * 18);
    rect(ctx, x, top, w, GROUND - top, r() > 0.5 ? C.far0 : C.far1);
    rect(ctx, x, top, w, 1, C.farEdge);
    if (r() > 0.7) rect(ctx, x + Math.floor(w / 2), top - 4, 1, 4, C.farEdge);
    for (let wy = top + 3; wy < GROUND - 3; wy += 4) {
      for (let wx = x + 2; wx < x + w - 2; wx += 3) {
        const q = r();
        if (q > 0.94) rect(ctx, wx, wy, 1, 2, C.warm);
        else if (q > 0.76) rect(ctx, wx, wy, 1, 2, C.farLit);
      }
    }
    x += w;
  }
  rect(ctx, 0, GROUND, W, ROAD - GROUND, C.walk);
  rect(ctx, 0, GROUND, W, 1, C.walkHi);
  rect(ctx, 0, ROAD, W, H - ROAD, C.road);
  for (let lx = 2; lx < W; lx += 10) rect(ctx, lx, 78, 5, 1, C.lane);
  for (let lx = 20; lx < W - 4; lx += 56) {
    if (Math.abs(lx - mx) < 80) continue;
    rect(ctx, lx, 50, 1, GROUND - 50, C.post);
    rect(ctx, lx, 49, 4, 1, C.post);
    rect(ctx, lx + 2, 50, 2, 1, C.warm2);
    rect(ctx, lx + 1, 51, 4, 1, C.lampGlow);
    rect(ctx, lx - 1, GROUND, 9, 1, C.lampPool);
    rect(ctx, lx + 1, GROUND, 5, 1, C.lampPoolHi);
  }
  drawMuseum(ctx, mx);
}

const STARS = (() => {
  const r = rng(99);
  return Array.from({ length: 110 }, () => ({ x: r(), y: 2 + Math.floor(r() * 32), big: r() > 0.9, phase: r() * 6.28, speed: 0.5 + r() * 1.5 }));
})();

/** The dotted route: a gentle swell, so it reads as a flight path, not a rule. */
const routeY = (x: number) => ROUTE_Y + Math.round(Math.sin(x / 23) * 3);

function drawFrame(ctx: Ctx, W: number, t: number, base: HTMLCanvasElement, still: boolean) {
  const { mx, voiceX } = layout(W);
  ctx.clearRect(0, 0, W, H);
  for (const s of STARS) {
    const x = Math.floor(s.x * W);
    const tw = still ? 0.8 : 0.5 + 0.5 * Math.sin(t * s.speed + s.phase);
    if (tw < 0.12) continue;
    ctx.globalAlpha = 0.3 + 0.7 * tw;
    rect(ctx, x, s.y, 1, 1, C.white);
    if (s.big && tw > 0.7) {
      ctx.globalAlpha = 0.45 * tw;
      rect(ctx, x - 1, s.y, 3, 1, C.white);
      rect(ctx, x, s.y - 1, 1, 3, C.white);
    }
  }
  ctx.globalAlpha = 1;

  // route: dim dots everywhere, bright trail behind the plane
  const span = voiceX + 30;
  const head = still ? mx - 30 : (t * 40) % span;
  for (let x = 0; x < voiceX; x += 3) {
    const behind = head - x;
    const hot = behind >= 0 && behind < 70;
    ctx.globalAlpha = hot ? Math.max(0.4, 1 - behind / 80) : 1;
    rect(ctx, x, routeY(x), 2, 1, hot ? C.cyan : C.cyanDim);
  }
  ctx.globalAlpha = 1;

  // voice-note waveform at the end of the route
  for (let x = voiceX + 1; x < W; x += 2) {
    const i = (x - voiceX) / 2;
    const env = Math.min(1, i / 6) * Math.min(1, (W - x) / 24 + 0.3);
    const ph = still ? 0 : t;
    const n = 0.5 + 0.5 * Math.sin(i * 1.7 + ph * 8) * Math.sin(i * 0.31 - ph * 2.7);
    const h = Math.max(1, Math.round(env * n * 9));
    rect(ctx, x, ROUTE_Y - h, 1, h * 2 + 1, C.lime);
  }

  ctx.drawImage(base, 0, 0);

  // a memory lands: each time the plane passes the museum, one frame flashes lime
  const since = head - mx;
  if (!still && since > 0 && since < 40) {
    const i = Math.floor(t / (span / 40)) % 6;
    const x = mx - 40 + i * 15;
    ctx.globalAlpha = 1 - since / 40;
    rect(ctx, x, 47, 7, 6, C.lime);
    ctx.globalAlpha = 1;
  }
  if (head < voiceX) sprite(ctx, PLANE, { w: C.white, c: C.cyan }, Math.floor(head) - 3, routeY(Math.floor(head)) - 4);

  // Ajji and the guide robot by the door; the robot waves now and then
  const waving = !still && t % 6 < 1.4 && Math.floor(t * 5) % 2 === 0;
  sprite(ctx, GRANDMA, GRANDMA_PAL, mx + 9, GROUND - 10);
  sprite(ctx, waving ? ROBOT_WAVE : ROBOT, ROBOT_PAL, mx + 16, GROUND - 8);

  // auto-rickshaw on the road
  const ax = still ? mx - 44 : Math.floor((t * 20) % (W + 80)) - 40;
  sprite(ctx, RICKSHAW, RICK_PAL, ax, ROAD + 2);
  if (still || Math.floor(t * 4) % 2 === 0) {
    ctx.globalAlpha = 0.5;
    for (let i = 1; i < 8; i++) rect(ctx, ax + 18 + i, ROAD + 6 + ((i % 3) - 1) * Math.floor(i / 3), 1, 1, C.warm);
    ctx.globalAlpha = 1;
  }
}

function pickScale(cssW: number) {
  if (cssW >= 1100) return 4;
  if (cssW >= 560) return 3;
  return 2;
}

export function FooterScene() {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!wrap || !canvas || !ctx) return;
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let still = reducedMotion();
    let W = 0;
    let base: HTMLCanvasElement | null = null;
    let raf = 0;
    let visible = false;
    let last = 0;
    let t = 3.2;
    let prevNow = 0;
    const paint = () => { if (base) drawFrame(ctx, W, t, base, still); };
    const size = () => {
      const cssW = wrap.clientWidth;
      if (!cssW) return;
      const scale = pickScale(cssW);
      const next = Math.ceil(cssW / scale);
      canvas.style.width = `${next * scale}px`;
      canvas.style.height = `${H * scale}px`;
      if (next === W && base) return;
      W = next;
      canvas.width = W;
      canvas.height = H;
      base = makeCanvas(W, H);
      const bctx = base.getContext('2d');
      if (bctx) drawStatic(bctx, W);
      paint();
    };
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      if (now - last < 1000 / FPS) return;
      t += Math.min(0.1, prevNow ? (now - prevNow) / 1000 : 0);
      prevNow = now;
      last = now;
      paint();
    };
    const start = () => { if (raf || still || !visible) return; prevNow = 0; raf = requestAnimationFrame(tick); };
    const stop = () => { cancelAnimationFrame(raf); raf = 0; };
    const onMotion = () => { still = motion.matches; if (still) stop(); paint(); start(); };
    size();
    const ro = new ResizeObserver(size);
    ro.observe(wrap);
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible) start(); else stop(); }, { rootMargin: '80px 0px' });
    io.observe(wrap);
    motion.addEventListener('change', onMotion);
    return () => { stop(); ro.disconnect(); io.disconnect(); motion.removeEventListener('change', onMotion); };
  }, []);
  return (
    <div ref={wrapRef} className="footer-scene" aria-hidden="true">
      <canvas ref={canvasRef} className="footer-scene-canvas" />
    </div>
  );
}
