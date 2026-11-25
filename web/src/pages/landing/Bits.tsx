import { useEffect, useRef } from 'react';
import { disc, rect, rng } from '../../ui/pixel/draw';

export function reducedMotion(): boolean {
  if (typeof window === 'undefined') return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches || document.documentElement.dataset.reduced === '1';
}

/** Scroll the landing container to a section and move focus there for keyboard users. */
export function goTo(id: string) {
  const el = document.getElementById(id);
  if (!el) return;
  el.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' });
  const h = el.querySelector<HTMLElement>('h2, h1');
  if (h) { h.tabIndex = -1; h.focus({ preventScroll: true }); }
}

/* Checkerboard dither strip between a paper band and a night band (MedSim). */
const DITHER = (() => {
  const r = rng(42);
  const cols = 48;
  const rows = 4;
  const sq = 8;
  let rects = '';
  for (let y = 0; y < rows; y++) {
    const density = [0.85, 0.6, 0.35, 0.14][y];
    for (let x = 0; x < cols; x++) {
      const checker = (x + y) % 2 === 0;
      if (checker ? r() < density + 0.15 : r() < density - 0.25) rects += `<rect x="${x * sq}" y="${y * sq}" width="${sq}" height="${sq}"/>`;
    }
  }
  return { w: cols * sq, h: rows * sq, rects };
})();
const PAPER = '#f4f0e1';
const NIGHT = '#0b1f4b';
export function Dither({ from, to }: { from: 'paper' | 'night'; to: 'paper' | 'night' }) {
  const top = from === 'paper' ? PAPER : NIGHT;
  const bottom = to === 'paper' ? PAPER : NIGHT;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${DITHER.w}" height="${DITHER.h}" fill="${top}">${DITHER.rects}</svg>`;
  return <div className="lp-dither" aria-hidden="true" style={{ backgroundColor: bottom, backgroundImage: `url("data:image/svg+xml,${encodeURIComponent(svg)}")` }} />;
}

export function OrnamentRule() {
  return (
    <div className="lp-ornament" aria-hidden="true">
      <span className="lp-ornament-line" />
      <svg width="18" height="18" viewBox="0 0 9 9" shapeRendering="crispEdges">
        <rect x="3" y="0" width="3" height="3" fill="currentColor" />
        <rect x="0" y="3" width="3" height="3" fill="currentColor" />
        <rect x="6" y="3" width="3" height="3" fill="currentColor" />
        <rect x="3" y="6" width="3" height="3" fill="currentColor" />
        <rect x="3" y="3" width="3" height="3" fill="#a8e27c" />
      </svg>
      <span className="lp-ornament-line" />
    </div>
  );
}

export function ArrowIcon({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 7 7" shapeRendering="crispEdges" aria-hidden="true">
      <rect x="0" y="3" width="5" height="1" fill="currentColor" />
      <rect x="3" y="1" width="1" height="1" fill="currentColor" />
      <rect x="4" y="2" width="1" height="1" fill="currentColor" />
      <rect x="5" y="3" width="1" height="1" fill="currentColor" />
      <rect x="4" y="4" width="1" height="1" fill="currentColor" />
      <rect x="3" y="5" width="1" height="1" fill="currentColor" />
    </svg>
  );
}

/* Hero sky: a posterised night gradient, a pixel moon and a far skyline, drawn once at 384x216. */
const SW = 384;
const SH = 216;
function mix(a: string, b: string, t: number) {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return `rgb(${pa.map((v, i) => Math.round(v + (pb[i] - v) * t)).join(',')})`;
}
export function HeroSky() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const ctx = ref.current?.getContext('2d');
    if (!ctx) return;
    const stops = ['#0b1f4b', '#133d7e', '#1c61a1', '#2481aa'];
    const steps = 14;
    for (let i = 0; i < steps; i++) {
      const t = i / (steps - 1);
      const seg = Math.min(stops.length - 2, Math.floor(t * (stops.length - 1)));
      const local = t * (stops.length - 1) - seg;
      const y0 = Math.round((SH * i) / steps);
      const y1 = Math.round((SH * (i + 1)) / steps);
      rect(ctx, 0, y0, SW, y1 - y0, mix(stops[seg], stops[seg + 1], local));
    }
    const r = rng(5);
    for (let i = 0; i < 70; i++) { ctx.globalAlpha = 0.35 + r() * 0.6; rect(ctx, Math.floor(r() * SW), Math.floor(r() * 120), 1, 1, '#f3f1e2'); }
    // moon, upper right
    const mx = 148;
    const my = 46;
    ctx.globalAlpha = 0.08; disc(ctx, mx, my, 40, '#e9f5b8');
    ctx.globalAlpha = 0.12; disc(ctx, mx, my, 30, '#e9f5b8');
    ctx.globalAlpha = 1;
    disc(ctx, mx, my, 22, '#c9df92');
    disc(ctx, mx - 1, my - 1, 21, '#e4f2b0');
    disc(ctx, mx - 7, my - 8, 7, '#f6fbdc');
    // far city
    let x = 0;
    while (x < SW) {
      const w = 10 + Math.floor(r() * 18);
      const h = 10 + Math.floor(r() * 26);
      const top = SH - h;
      rect(ctx, x, top, w, h, r() > 0.5 ? '#16376f' : '#1f4a8a');
      for (let wy = top + 3; wy < SH - 2; wy += 4) for (let wx = x + 2; wx < x + w - 2; wx += 3) if (r() > 0.8) rect(ctx, wx, wy, 1, 1, r() > 0.8 ? '#ffd76a' : '#3f6fb3');
      x += w + (r() > 0.7 ? 2 : 0);
    }
    for (let tx = 0; tx < SW; tx += 3) { const th = 3 + Math.floor(r() * 5); rect(ctx, tx, SH - th, 3, th, '#24502f'); }
  }, []);
  return <canvas ref={ref} className="lp-sky" width={SW} height={SH} aria-hidden="true" />;
}
