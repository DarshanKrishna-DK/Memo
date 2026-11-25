import { useEffect, useState } from 'react';
import * as THREE from 'three';
import QRCode from 'qrcode';

/** Night-ward palette (web/src/styles/tokens.css) plus warm museum accents. */
export const PAL = {
  navy: '#0b1f4b',
  navyDeep: '#061431',
  surface: '#112a60',
  line: '#2b4c8a',
  cream: '#f3f1e2',
  lime: '#a8e27c',
  gold: '#d9a520',
  goldSoft: '#f0c24a',
  teal: '#6ad5e7',
  wood: '#8a5a3a',
  woodDark: '#5a3a26',
  wall: '#e9dfc9',
  wallWarm: '#d9c7a4',
  red: '#ff6568',
  plum: '#4a2c4f',
};

export const FONT_DISPLAY = '"Jersey 10", "VT323", ui-monospace, monospace';
export const FONT_SANS = '"Amarna", "Noto Sans Devanagari", "Noto Sans Kannada", system-ui, sans-serif';

export function canvasTex(w: number, h: number, draw: (g: CanvasRenderingContext2D) => void, srgb = true): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  draw(c.getContext('2d')!);
  const t = new THREE.CanvasTexture(c);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

/** Re-renders once the web fonts used on canvases are ready (so signs redraw in Jersey 10 / Amarna). */
export function useFontsReady(): number {
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    const fonts = (document as Document & { fonts?: FontFaceSet }).fonts;
    if (!fonts) return;
    Promise.all([
      fonts.load(`40px ${FONT_DISPLAY}`).catch(() => undefined),
      fonts.load(`600 20px ${FONT_SANS}`).catch(() => undefined),
    ]).then(() => fonts.ready).then(() => { if (live) setN((x) => x + 1); });
    return () => { live = false; };
  }, []);
  return n;
}

/** Word-wrap text into lines that fit `maxW` with the current font. */
export function wrap(g: CanvasRenderingContext2D, text: string, maxW: number, maxLines = 99): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let cur = '';
  for (const w of words) {
    const next = cur ? `${cur} ${w}` : w;
    if (g.measureText(next).width > maxW && cur) {
      lines.push(cur);
      cur = w;
      if (lines.length === maxLines) break;
    } else cur = next;
  }
  if (cur && lines.length < maxLines) lines.push(cur);
  if (lines.length === maxLines && words.join(' ').length > lines.join(' ').length) {
    let last = lines[maxLines - 1];
    while (last.length > 1 && g.measureText(last + '…').width > maxW) last = last.slice(0, -1);
    lines[maxLines - 1] = last + '…';
  }
  return lines;
}

/** Hard pixel bevel frame, like the UI cards. */
export function pixelFrame(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, line = PAL.line, shadow = PAL.navyDeep, px = 6) {
  g.fillStyle = shadow;
  g.fillRect(x + px, y + px, w, h);
  g.fillStyle = line;
  g.fillRect(x - px / 2, y - px / 2, w + px, h + px);
}

export function monthName(month: number, lang = 'en-IN', style: 'long' | 'short' = 'long'): string {
  try {
    return new Intl.DateTimeFormat(lang, { month: style, timeZone: 'UTC' }).format(new Date(Date.UTC(2020, month - 1, 1)));
  } catch {
    return ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'][month - 1];
  }
}

// ───────── atlas: many small signs share one GPU upload ─────────

/** A grid atlas. `cell(i)` returns a texture view (clone sharing the same Source = one upload). */
export class Atlas {
  readonly tex: THREE.CanvasTexture;
  private views: THREE.Texture[] = [];
  constructor(readonly cols: number, readonly rows: number, readonly cw: number, readonly ch: number, draw: (g: CanvasRenderingContext2D, i: number, w: number, h: number) => void) {
    this.tex = canvasTex(cols * cw, rows * ch, (g) => {
      for (let i = 0; i < cols * rows; i++) {
        g.save();
        g.translate((i % cols) * cw, Math.floor(i / cols) * ch);
        g.beginPath();
        g.rect(0, 0, cw, ch);
        g.clip();
        draw(g, i, cw, ch);
        g.restore();
      }
    });
  }
  cell(i: number): THREE.Texture {
    if (this.views[i]) return this.views[i];
    const t = this.tex.clone();
    t.repeat.set(1 / this.cols, 1 / this.rows);
    t.offset.set((i % this.cols) / this.cols, 1 - (Math.floor(i / this.cols) + 1) / this.rows);
    t.needsUpdate = true;
    this.views[i] = t;
    return t;
  }
  dispose() {
    this.views.forEach((v) => v.dispose());
    this.tex.dispose();
  }
}

// ───────── QR (t.me/<bot>) ─────────

export function qrTexture(text: string, caption: string): THREE.CanvasTexture {
  const qr = QRCode.create(text, { errorCorrectionLevel: 'M' });
  const n = qr.modules.size;
  const W = 512, H = 640;
  return canvasTex(W, H, (g) => {
    g.fillStyle = PAL.cream;
    g.fillRect(0, 0, W, H);
    const quiet = 4;
    const cell = Math.floor((W - 64) / (n + quiet * 2));
    const size = cell * (n + quiet * 2);
    const ox = (W - size) / 2, oy = 28;
    g.fillStyle = '#ffffff';
    g.fillRect(ox, oy, size, size);
    g.fillStyle = PAL.navy;
    for (let y = 0; y < n; y++)
      for (let x = 0; x < n; x++)
        if (qr.modules.get(x, y)) g.fillRect(ox + (x + quiet) * cell, oy + (y + quiet) * cell, cell, cell);
    g.textAlign = 'center';
    g.fillStyle = PAL.navy;
    g.font = `44px ${FONT_DISPLAY}`;
    g.fillText(caption, W / 2, oy + size + 52);
    g.font = `600 22px ${FONT_SANS}`;
    g.fillStyle = '#4a5878';
    g.fillText(text.replace(/^https?:\/\//, ''), W / 2, oy + size + 86);
  });
}

// ───────── photos (signed URLs), with a small budgeted cache ─────────

// Own LoadingManager: photo loads must not trip drei's useProgress (DefaultLoadingManager), which drives the
// full-screen "Opening the museum" overlay. Otherwise every room / showcase photo brought that overlay back.
const loader = new THREE.ImageBitmapLoader(new THREE.LoadingManager());
loader.setOptions({ imageOrientation: 'flipY' });

interface Entry { tex: THREE.Texture | null; refs: number; promise: Promise<THREE.Texture>; failed: boolean }
const photoCache = new Map<string, Entry>();
/** Max decoded photo textures kept alive (thumbs are ~512 px; the screen uses large). */
export const PHOTO_BUDGET = 24;

function keyOf(url: string) {
  // Signed URLs change their query string per request; the path names the object.
  try { return new URL(url, location.href).pathname; } catch { return url; }
}

export function acquirePhoto(url: string): Promise<THREE.Texture> {
  const k = keyOf(url);
  const hit = photoCache.get(k);
  if (hit) {
    hit.refs++;
    return hit.promise;
  }
  const entry: Entry = { tex: null, refs: 1, failed: false, promise: null as unknown as Promise<THREE.Texture> };
  entry.promise = new Promise<THREE.Texture>((resolve, reject) => {
    loader.load(
      url,
      (bmp) => {
        const t = new THREE.Texture(bmp as unknown as HTMLImageElement);
        t.colorSpace = THREE.SRGBColorSpace;
        t.flipY = false; // ImageBitmap already flipped
        t.anisotropy = 4;
        t.needsUpdate = true;
        entry.tex = t;
        resolve(t);
      },
      undefined,
      (err) => {
        entry.failed = true;
        photoCache.delete(k);
        reject(err);
      },
    );
  });
  photoCache.set(k, entry);
  trimPhotos();
  return entry.promise;
}

export function releasePhoto(url: string) {
  const e = photoCache.get(keyOf(url));
  if (!e) return;
  e.refs = Math.max(0, e.refs - 1);
  trimPhotos();
}

function trimPhotos() {
  if (photoCache.size <= PHOTO_BUDGET) return;
  for (const [k, e] of photoCache) {
    if (photoCache.size <= PHOTO_BUDGET) break;
    if (e.refs === 0 && e.tex) {
      e.tex.dispose();
      (e.tex.image as ImageBitmap | undefined)?.close?.();
      photoCache.delete(k);
    }
  }
}

/** Drop every unreferenced photo (called when leaving a floor). */
export function flushPhotos() {
  for (const [k, e] of photoCache) {
    if (e.refs === 0 && e.tex) {
      e.tex.dispose();
      (e.tex.image as ImageBitmap | undefined)?.close?.();
      photoCache.delete(k);
    }
  }
}

/** React hook: a photo texture for `url` (null while loading / on failure). */
export function usePhoto(url: string | null | undefined): THREE.Texture | null {
  const [tex, setTex] = useState<THREE.Texture | null>(null);
  useEffect(() => {
    if (!url) { setTex(null); return; }
    let live = true;
    acquirePhoto(url).then((t) => { if (live) setTex(t); }).catch(() => { if (live) setTex(null); });
    return () => {
      live = false;
      releasePhoto(url);
    };
  }, [url]);
  return tex;
}

/** Image aspect (w/h) of a loaded texture. */
export function aspectOf(t: THREE.Texture | null): number {
  const img = t?.image as { width?: number; height?: number } | undefined;
  return img?.width && img?.height ? img.width / img.height : 4 / 3;
}
