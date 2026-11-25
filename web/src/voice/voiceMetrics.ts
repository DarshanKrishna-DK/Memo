/** Interruption latency log (PRD V7: whoever talks stops within 300 ms at p95). Readable at window.__voiceMetrics. */
export interface StopSample {
  reason: string;
  /** trigger -> every audio element paused (synchronous part), ms */
  syncMs: number;
  /** trigger -> the browser confirmed the pause event, ms (null if nothing needed confirming) */
  confirmedMs: number | null;
  stopped: string[];
  at: number;
}

const samples: StopSample[] = [];
const BUDGET_MS = 300;

export const voiceMetrics = {
  budgetMs: BUDGET_MS,
  samples,
  record(s: StopSample) {
    samples.push(s);
    if (samples.length > 200) samples.shift();
    const worst = s.confirmedMs ?? s.syncMs;
    const msg = `[voice] stop (${s.reason}) sync ${s.syncMs.toFixed(1)} ms, confirmed ${s.confirmedMs == null ? 'n/a' : s.confirmedMs.toFixed(1) + ' ms'}, stopped: ${s.stopped.join(',') || 'none'}`;
    if (worst > BUDGET_MS) console.warn(msg + ' OVER BUDGET'); else console.info(msg);
  },
  p95(): number | null {
    const v = samples.map((s) => s.confirmedMs ?? s.syncMs).sort((a, b) => a - b);
    if (!v.length) return null;
    return v[Math.min(v.length - 1, Math.ceil(v.length * 0.95) - 1)];
  },
  max(): number | null { return samples.length ? Math.max(...samples.map((s) => s.confirmedMs ?? s.syncMs)) : null; },
};
if (typeof window !== 'undefined') (window as unknown as { __voiceMetrics: unknown }).__voiceMetrics = voiceMetrics;
