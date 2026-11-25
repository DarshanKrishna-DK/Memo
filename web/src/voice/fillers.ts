/** Filler clips ("hmm...", "one moment...") for slow replies. GET /api/voice/fillers?character=&lang= -> list of {text, audio_url}
 *  (a bare array or {fillers:[...]} are both accepted). Prefetched per character+language; never the same clip twice in
 *  a row; skipped while the user speaks. Played through the arbiter as `filler`, so the real reply cuts it instantly. */
import { get } from '../api/client';
import { arbiter, playClip } from './speechArbiter';

export interface Filler { text: string; audio_url: string }
export const FILLER_DELAY_MS = 700;

const cache = new Map<string, Promise<Filler[]>>();
const last = new Map<string, string>();

function load(character: string, lang: string): Promise<Filler[]> {
  const key = `${character}|${lang}`;
  let p = cache.get(key);
  if (!p) {
    p = get<unknown>(`/api/voice/fillers?character=${encodeURIComponent(character)}&lang=${encodeURIComponent(lang)}`)
      .then((r) => {
        const raw = Array.isArray(r) ? r : ((r as { fillers?: unknown[]; items?: unknown[] })?.fillers ?? (r as { items?: unknown[] })?.items ?? []);
        const list = (raw as Partial<Filler>[]).filter((f): f is Filler => !!f && typeof f.audio_url === 'string' && !!f.audio_url);
        for (const f of list) { const a = new Audio(); a.preload = 'auto'; a.src = f.audio_url; } // warm the cache
        return list;
      })
      .catch(() => { cache.delete(key); return [] as Filler[]; });
    cache.set(key, p);
  }
  return p;
}

export function prefetchFillers(character: string, lang: string) { void load(character, lang); }

/** Pick the next clip: random, but never the one used last for this character. Pure, exported for the test page. */
export function pickFiller(list: Filler[], lastUrl: string | undefined, rnd: () => number = Math.random): Filler | null {
  if (!list.length) return null;
  const pool = list.length > 1 ? list.filter((f) => f.audio_url !== lastUrl) : list;
  return pool[Math.floor(rnd() * pool.length)] ?? null;
}

export interface FillerWatch { cancel(): void }

/** Start watching a pending reply. If it is still pending after 700 ms and nobody speaks, play one filler. */
export function armFiller(character: string, lang: string, userSpeaking: () => boolean, delay = FILLER_DELAY_MS): FillerWatch {
  const pre = load(character, lang); // make sure it is in flight even if prefetch was never called
  let cancelled = false;
  const timer = window.setTimeout(async () => {
    if (cancelled || userSpeaking() || arbiter.speaking) return;
    const f = pickFiller(await pre, last.get(character));
    if (!f || cancelled || userSpeaking() || arbiter.speaking) return;
    last.set(character, f.audio_url);
    playClip('filler', character, f.audio_url);
  }, delay);
  return {
    cancel() {
      cancelled = true;
      clearTimeout(timer);
      if (arbiter.current?.source === 'filler') arbiter.interrupt('filler-cut');
    },
  };
}
