/** The one place every audio source asks before it makes a sound (PRD: interruption always wins; one speaker at a time).
 *
 *  Speakers (a "ticket" is one claim on the speakers' channel):
 *    agent   receptionist replies, Grandma sentences, Agora live agents   (rank 3: the agent the user is addressing)
 *    guide   guide robot lines, phone / guest cards read aloud            (rank 2)
 *    filler  short "hmm..." clips while a reply is pending                (rank 1: cut the instant anything real starts)
 *  Showcase audio (voice notes) is a separate track: an agent never stops it, only ducks it.
 *  A claim of equal or higher rank stops the current speaker first; a lower rank claim is refused (dropped), so
 *  there is never overlap. `interrupt()` is the user's barge-in: it stops every speaker synchronously and logs latency.
 */
import { useWorld } from '../state/worldStore';
import { voiceMetrics } from './voiceMetrics';

export type Source = 'agent' | 'guide' | 'filler';
const RANK: Record<Source, number> = { agent: 3, guide: 2, filler: 1 };
const DUCK = 0.2;

export interface Handle {
  /** Must silence the audio synchronously. May return a promise that resolves once the browser confirmed it. */
  stop(): void | Promise<void>;
}
export interface Ticket { id: number; source: Source; who: string; handle: Handle }

class Arbiter {
  private seq = 0;
  private cur: Ticket | null = null;
  private agoraSpeaking = false;
  private show: { audio: HTMLAudioElement; onEnded?: () => void } | null = null;
  /** Set by the controller: silence / restore the Agora agent track and ask the server to stop it. */
  agoraHooks: { mute(on: boolean): void; interrupt(): void } | null = null;
  lastInterrupt: { reason: string; at: number } | null = null;

  get current(): Ticket | null { return this.cur; }
  get speaking(): boolean { return !!this.cur || this.agoraSpeaking; }

  private publish() {
    const t = this.cur;
    const next = t ? { source: t.source, who: t.who } : this.agoraSpeaking ? { source: 'agent' as const, who: 'agent' } : null;
    const w = useWorld.getState();
    const a = w.speaking;
    const same = a && next && a.source === next.source && a.who === next.who;
    if (!same && (a || next)) w.setSpeaking(next);
    this.applyDuck();
  }

  private applyDuck() {
    if (this.show) this.show.audio.volume = this.cur || this.agoraSpeaking ? DUCK : 1;
  }

  /** Ask to speak. Returns null when something of higher rank holds the floor. Stops the previous speaker otherwise. */
  begin(source: Source, who: string, handle: Handle): Ticket | null {
    if (this.agoraSpeaking) {
      if (source !== 'agent') return null;
      this.agoraHooks?.mute(true); // local agent audio wins over the live agent: silence its track, stop it server side
      this.agoraHooks?.interrupt();
      this.agoraSpeaking = false;
    }
    if (this.cur) {
      if (RANK[source] < RANK[this.cur.source]) return null;
      this.stopTicket(this.cur);
    }
    const t: Ticket = { id: ++this.seq, source, who, handle };
    this.cur = t;
    this.publish();
    return t;
  }

  isCurrent(t: Ticket | null): boolean { return !!t && this.cur?.id === t.id; }

  /** The speaker finished (or was stopped). Idempotent. */
  end(t: Ticket | null) {
    if (t && this.cur?.id === t.id) { this.cur = null; this.publish(); }
  }

  private stopTicket(t: Ticket): Promise<void> | void {
    if (this.cur?.id === t.id) this.cur = null;
    let p: Promise<void> | void = undefined;
    try { p = t.handle.stop(); } catch { /* ignore */ }
    this.publish();
    return p;
  }

  /** The Agora agent started / stopped talking (from RTM state). Local playback stops the moment it starts. */
  setAgoraSpeaking(on: boolean) {
    if (on === this.agoraSpeaking) return;
    this.agoraSpeaking = on;
    if (on && this.cur) this.stopTicket(this.cur);
    this.publish();
  }

  /** User barge-in: stop everyone now. The synchronous part is returned; the browser-confirmed latency is logged. */
  interrupt(reason: string): { syncMs: number; stopped: number } {
    const t0 = performance.now();
    const stopped: string[] = [];
    const waits: Promise<void>[] = [];
    if (this.cur) {
      stopped.push(`${this.cur.source}:${this.cur.who}`);
      const p = this.stopTicket(this.cur);
      if (p) waits.push(p);
    }
    if (this.agoraSpeaking) {
      stopped.push('agora');
      this.agoraHooks?.mute(true);
      this.agoraHooks?.interrupt();
      setTimeout(() => this.agoraHooks?.mute(false), 600);
      this.agoraSpeaking = false;
    }
    if (this.show) this.show.audio.volume = DUCK;
    this.publish();
    const syncMs = performance.now() - t0;
    this.lastInterrupt = { reason, at: Date.now() };
    if (stopped.length) {
      if (waits.length) void Promise.all(waits).then(() => voiceMetrics.record({ reason, syncMs, confirmedMs: performance.now() - t0, stopped, at: Date.now() }));
      else voiceMetrics.record({ reason, syncMs, confirmedMs: null, stopped, at: Date.now() });
    }
    setTimeout(() => this.applyDuck(), 1200); // un-duck the showcase track once the user went quiet
    return { syncMs, stopped: stopped.length };
  }

  /** Showcase voice-note playback: its own track, ducked while any speaker talks. Returns a stop function. */
  playShowcase(url: string, opts: { rate?: number; onEnded?: () => void } = {}): () => void {
    this.stopShowcase();
    const audio = new Audio(url);
    audio.playbackRate = opts.rate ?? 1;
    audio.volume = this.cur || this.agoraSpeaking ? DUCK : 1;
    const rec = { audio, onEnded: opts.onEnded };
    this.show = rec;
    audio.onended = () => { if (this.show === rec) { this.show = null; rec.onEnded?.(); } };
    void audio.play().catch(() => undefined);
    return () => { if (this.show === rec) this.stopShowcase(); };
  }
  stopShowcase() {
    const s = this.show;
    this.show = null;
    if (s) { s.audio.onended = null; try { s.audio.pause(); } catch { /* ignore */ } }
  }
  get showcaseActive() { return !!this.show; }
}

export const arbiter = new Arbiter();
if (typeof window !== 'undefined') (window as unknown as { __arbiter: unknown }).__arbiter = arbiter;

/** Plays one URL as a single clip through the arbiter (guide lines, fillers, cards). `done` resolves true when it
 *  played to the end, false when it was cut or refused. */
export function playClip(source: Source, who: string, url: string): { started: boolean; done: Promise<boolean> } {
  const audio = new Audio(url);
  let resolve!: (v: boolean) => void;
  const done = new Promise<boolean>((r) => { resolve = r; });
  const ticket = arbiter.begin(source, who, {
    stop: () => new Promise<void>((res) => {
      audio.onended = null; audio.onerror = null;
      const was = !audio.paused;
      if (was) audio.addEventListener('pause', () => res(), { once: true });
      audio.pause();
      if (!was) res();
      resolve(false);
    }),
  });
  if (!ticket) return { started: false, done: Promise.resolve(false) };
  audio.onended = () => { arbiter.end(ticket); resolve(true); };
  audio.onerror = () => { arbiter.end(ticket); resolve(false); };
  audio.play().catch(() => { arbiter.end(ticket); resolve(false); });
  return { started: true, done };
}
