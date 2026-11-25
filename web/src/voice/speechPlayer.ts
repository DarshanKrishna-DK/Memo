/** Plays a Speech (or reception reply) one sentence at a time, so an interruption lands cleanly and the
 *  last finished sentence is remembered (PRD "Grandma in the theater"). stop() pauses synchronously. */
import type { Speech } from '../contract';
import { arbiter, type Source, type Ticket } from './speechArbiter';
import { boostSpeech, keepSpeechAlive } from './audioUnlock';

export interface Segment { text: string; url: string | null; from?: number; to?: number; start_s: number }

export function toSegments(sp: { text?: string; audio_url?: string | null; subtitles?: { text: string; start_s: number; end_s: number }[]; sentences?: { text: string; audio_url: string | null }[] }): Segment[] {
  if (sp.sentences?.length) {
    let t = 0;
    return sp.sentences.map((s) => { const seg = { text: s.text, url: s.audio_url, start_s: t }; t += Math.max(1, s.text.length * 0.06); return seg; });
  }
  const subs = sp.subtitles ?? [];
  if (subs.length && sp.audio_url) return subs.map((s) => ({ text: s.text, url: sp.audio_url!, from: s.start_s, to: s.end_s, start_s: s.start_s }));
  if (subs.length) return subs.map((s) => ({ text: s.text, url: null, start_s: s.start_s }));
  if (sp.text) return sp.text.split(/(?<=[.!?।])\s+/).filter(Boolean).map((t, i) => ({ text: t, url: sp.audio_url && i === 0 ? sp.audio_url : null, start_s: i }));
  return [];
}

export interface PlayOpts {
  startAt?: number;
  onSegment?: (i: number, seg: Segment) => void;
  onHighlight?: (memoryId: string) => void;
  onEnd?: (completed: boolean) => void;
  /** Which arbiter channel this speech uses (default agent) and who is talking. */
  source?: Source;
  who?: string;
}

export class SpeechPlayer {
  private audio = new Audio();
  private segs: Segment[] = [];
  private idx = -1;
  private opts: PlayOpts = {};
  private timer: number | null = null;
  private fired = new Set<string>();
  private highlights: { memory_id: string; at_s: number }[] = [];
  private token = 0;
  private ticket: Ticket | null = null;
  /** index of the last sentence that fully finished (-1 none) */
  lastFinished = -1;
  active = false;

  constructor() { this.audio.preload = 'auto'; this.audio.volume = 1; }

  setRate(r: number) { this.audio.playbackRate = r; }

  get segments() { return this.segs; }

  play(speech: { highlights?: Speech['highlights'] } & Parameters<typeof toSegments>[0], opts: PlayOpts = {}) {
    this.stop();
    this.segs = toSegments(speech);
    this.highlights = speech.highlights ?? [];
    this.fired.clear();
    this.opts = opts;
    this.lastFinished = -1;
    this.token++;
    this.active = this.segs.length > 0;
    if (!this.active) { opts.onEnd?.(true); return; }
    if (!this.claim()) { this.active = false; opts.onEnd?.(false); return; }
    this.run(opts.startAt ?? 0, this.token);
  }

  /** Continue from the sentence that was cut off. */
  resume() {
    if (!this.segs.length) return false;
    const from = Math.min(this.segs.length - 1, this.lastFinished + 1);
    if (this.lastFinished >= this.segs.length - 1) return false;
    this.token++;
    if (!this.claim()) return false;
    this.active = true;
    this.run(from, this.token);
    return true;
  }

  private claim(): boolean {
    this.ticket = arbiter.begin(this.opts.source ?? 'agent', this.opts.who ?? 'agent', { stop: () => this.stop() });
    return !!this.ticket;
  }

  hasRemaining() { return this.segs.length > 0 && this.lastFinished < this.segs.length - 1; }

  /** Synchronous: audio is paused before this returns (well inside the 300 ms barge-in budget). */
  stop(): Promise<void> | void {
    this.token++;
    if (this.timer != null) { clearTimeout(this.timer); this.timer = null; }
    const a = this.audio;
    const playing = !a.paused;
    let confirmed: Promise<void> | void = undefined;
    if (playing) confirmed = new Promise<void>((res) => a.addEventListener('pause', () => res(), { once: true }));
    try { a.pause(); } catch { /* ignore */ }
    a.onended = null; a.ontimeupdate = null; a.onerror = null; a.onloadedmetadata = null;
    const was = this.active;
    this.active = false;
    arbiter.end(this.ticket); this.ticket = null;
    if (was) this.opts.onEnd?.(false);
    return confirmed;
  }

  private run(i: number, tok: number) {
    if (tok !== this.token) return;
    if (i >= this.segs.length) { this.active = false; arbiter.end(this.ticket); this.ticket = null; this.opts.onEnd?.(true); return; }
    const seg = this.segs[i];
    this.idx = i;
    this.opts.onSegment?.(i, seg);
    for (const h of this.highlights) {
      if (!this.fired.has(h.memory_id + h.at_s) && seg.start_s >= h.at_s - 0.05) { this.fired.add(h.memory_id + h.at_s); this.opts.onHighlight?.(h.memory_id); }
    }
    const done = () => { if (tok !== this.token) return; this.lastFinished = i; this.run(i + 1, tok); };
    if (!seg.url) { this.timer = window.setTimeout(done, Math.max(900, seg.text.length * 55)); return; }
    const a = this.audio;
    boostSpeech(a, seg.url);   // full volume, plus gain + limiter through WebAudio when possible
    keepSpeechAlive(a);
    const needLoad = a.getAttribute('data-url') !== seg.url;
    const seekTo = seg.from ?? 0;
    const start = () => {
      if (tok !== this.token) return;
      if (seg.from != null && Math.abs(a.currentTime - seekTo) > 0.35) a.currentTime = seekTo;
      a.ontimeupdate = seg.to != null ? () => { if (a.currentTime >= seg.to! - 0.03) { a.ontimeupdate = null; done(); } } : null;
      a.onended = () => done();
      a.onerror = () => { this.timer = window.setTimeout(done, Math.max(900, seg.text.length * 55)); };
      a.play().catch(() => { this.timer = window.setTimeout(done, Math.max(900, seg.text.length * 55)); });
    };
    if (needLoad) {
      a.setAttribute('data-url', seg.url);
      a.src = seg.url;
      a.onloadedmetadata = () => { a.onloadedmetadata = null; start(); };
      a.load();
    } else start();
  }

  get currentIndex() { return this.idx; }
}
