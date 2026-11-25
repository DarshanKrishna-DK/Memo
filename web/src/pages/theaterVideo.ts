/** The one <video> element the theater plays from. The 3D screen draws it as a VideoTexture, the 2D / full screen view
 *  mounts the element itself, and every control (buttons, space, voice, swipe) goes through this object, so there is
 *  never a second copy making sound. Sound goes through the speech arbiter: while it plays unmuted Grandma stops, and if
 *  she is asked something mid-video the video is ducked under her (same rule as voice notes). */
import { useSyncExternalStore } from 'react';
import { arbiter } from '../voice/speechArbiter';

export interface VideoState { url: string | null; poster: string | null; playing: boolean; started: boolean; current: number; duration: number; muted: boolean; buffering: boolean; error: boolean; aspect: number }
const MUTE_KEY = 'memo.video.muted';
const readMuted = () => { try { return localStorage.getItem(MUTE_KEY) === '1'; } catch { return false; } };

class TheaterVideo {
  el: HTMLVideoElement | null = null;
  private state: VideoState = { url: null, poster: null, playing: false, started: false, current: 0, duration: 0, muted: readMuted(), buffering: false, error: false, aspect: 16 / 9 };
  private subs = new Set<() => void>();
  private detach: (() => void) | null = null;
  private onEnded: (() => void) | null = null;
  /** Called when sound is about to start (unmuted play): the engine stops Grandma here. */
  onSound: (() => void) | null = null;
  private raf = 0;

  get snapshot() { return this.state; }
  subscribe = (fn: () => void) => { this.subs.add(fn); return () => { this.subs.delete(fn); }; };
  private set(p: Partial<VideoState>) {
    const n = { ...this.state, ...p };
    if ((Object.keys(p) as (keyof VideoState)[]).every((k) => n[k] === this.state[k])) return;
    this.state = n;
    this.subs.forEach((f) => f());
  }

  load(url: string, poster: string | null, onEnded: () => void) {
    this.onEnded = onEnded;
    if (this.el && this.state.url === url) return;
    this.unload();
    const v = document.createElement('video');
    v.crossOrigin = 'anonymous';   // VideoTexture needs CORS-clean frames; signed media URLs send CORS headers
    v.playsInline = true;
    v.preload = 'metadata';
    v.muted = this.state.muted;
    if (poster) v.poster = poster;
    v.className = 'theater-video';
    v.src = url;
    v.addEventListener('loadedmetadata', () => this.set({ duration: Number.isFinite(v.duration) ? v.duration : 0, aspect: v.videoWidth && v.videoHeight ? v.videoWidth / v.videoHeight : 16 / 9 }));
    v.addEventListener('play', () => { this.set({ playing: true, started: true, error: false }); this.sound(); this.tick(); });
    v.addEventListener('pause', () => this.set({ playing: false, current: v.currentTime }));
    v.addEventListener('waiting', () => this.set({ buffering: true }));
    v.addEventListener('playing', () => this.set({ buffering: false }));
    v.addEventListener('seeked', () => this.set({ current: v.currentTime }));
    v.addEventListener('volumechange', () => { this.set({ muted: v.muted }); this.sound(); });
    v.addEventListener('error', () => this.set({ error: true, playing: false, buffering: false }));
    v.addEventListener('ended', () => { this.set({ playing: false, current: v.duration || this.state.current }); this.release(); this.onEnded?.(); });
    this.el = v;
    this.set({ url, poster, playing: false, started: false, current: 0, duration: 0, buffering: false, error: false });
  }

  unload() {
    cancelAnimationFrame(this.raf);
    this.release();
    const v = this.el;
    this.el = null;
    if (v) { try { v.pause(); v.removeAttribute('src'); v.load(); v.remove(); } catch { /* ignore */ } }
    if (this.state.url) this.set({ url: null, poster: null, playing: false, started: false, current: 0, duration: 0, buffering: false, error: false });
  }

  private sound() {
    const v = this.el;
    if (!v) return;
    if (!v.paused && !v.muted) {
      if (!this.detach) { this.onSound?.(); this.detach = arbiter.attachShowcaseMedia(v); }
    } else if (v.muted) this.release();
  }
  private release() { this.detach?.(); this.detach = null; }

  private tick = () => {
    cancelAnimationFrame(this.raf);
    const v = this.el;
    if (!v || v.paused) return;
    this.set({ current: Math.floor(v.currentTime * 4) / 4 });
    this.raf = requestAnimationFrame(this.tick);
  };

  play() { const v = this.el; if (v) void v.play().catch(() => { if (!v.muted) { v.muted = true; void v.play().catch(() => undefined); } }); }
  pause() { this.el?.pause(); }
  seek(t: number) { const v = this.el; if (v && Number.isFinite(t)) { v.currentTime = Math.max(0, Math.min(t, v.duration || t)); this.set({ current: v.currentTime }); } }
  setMuted(m: boolean) { if (this.el) this.el.muted = m; this.set({ muted: m }); try { localStorage.setItem(MUTE_KEY, m ? '1' : '0'); } catch { /* storage blocked */ } }
  setRate(r: number) { if (this.el) this.el.playbackRate = r; }
}

export const theaterVideo = new TheaterVideo();
export function useTheaterVideo(): VideoState { return useSyncExternalStore(theaterVideo.subscribe, () => theaterVideo.snapshot); }

export function fmtTime(s: number): string {
  if (!Number.isFinite(s) || s < 0) s = 0;
  const m = Math.floor(s / 60), r = Math.floor(s % 60);
  return `${m}:${r.toString().padStart(2, '0')}`;
}
