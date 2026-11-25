// Tiny pixel-art toolkit: everything is drawn at low resolution onto a
// canvas and upscaled by CSS with `image-rendering: pixelated`.

export type Ctx = CanvasRenderingContext2D;

/** Deterministic PRNG so the scene is identical on every load. */
export function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function rect(ctx: Ctx, x: number, y: number, w: number, h: number, c: string) {
  ctx.fillStyle = c;
  ctx.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
}

/** Draw a sprite from string rows; '.' or ' ' is transparent. */
export function sprite(
  ctx: Ctx,
  rows: readonly string[],
  palette: Record<string, string>,
  x: number,
  y: number,
  scale = 1,
) {
  rows.forEach((row, ry) => {
    for (let rx = 0; rx < row.length; rx++) {
      const ch = row[rx];
      const col = palette[ch];
      if (!col) continue;
      rect(ctx, x + rx * scale, y + ry * scale, scale, scale, col);
    }
  });
}

/** Filled pixel disc (midpoint test per pixel). */
export function disc(ctx: Ctx, cx: number, cy: number, r: number, c: string) {
  ctx.fillStyle = c;
  for (let y = -r; y <= r; y++) {
    const w = Math.floor(Math.sqrt(r * r - y * y));
    ctx.fillRect(cx - w, cy + y, w * 2 + 1, 1);
  }
}

/** Ordered 2x2 dither between two colours across a horizontal band. */
export function ditherBand(ctx: Ctx, y: number, h: number, w: number, a: string, b: string) {
  for (let yy = 0; yy < h; yy++) {
    const t = (yy + 0.5) / h; // 0 → a, 1 → b
    for (let x = 0; x < w; x++) {
      const threshold = ((x % 2) * 2 + (yy % 2)) / 4 + 0.125;
      rect(ctx, x, y + yy, 1, 1, t > threshold ? b : a);
    }
  }
}

export function makeCanvas(w: number, h: number): HTMLCanvasElement {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  return c;
}
