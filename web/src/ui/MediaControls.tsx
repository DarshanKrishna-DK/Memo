import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { fmtTime } from '../pages/theaterVideo';
import { arbiter } from '../voice/speechArbiter';
import { voice } from '../voice/controller';

/** Pixel icons (11x11 grid) for the media bar. */
export function MediaIcon({ name, size = 16 }: { name: 'play' | 'pause' | 'prev' | 'next' | 'sound' | 'mute' | 'full' | 'exitfull'; size?: number }) {
  const r: [number, number, number, number][] = {
    play: [[2, 1, 2, 9], [4, 2, 2, 7], [6, 3, 2, 5], [8, 4, 1, 3]],
    pause: [[2, 1, 3, 9], [6, 1, 3, 9]],
    prev: [[1, 1, 2, 9], [7, 1, 2, 9], [5, 3, 2, 5], [3, 4, 2, 3]],
    next: [[8, 1, 2, 9], [2, 1, 2, 9], [4, 3, 2, 5], [6, 4, 2, 3]],
    sound: [[1, 4, 2, 3], [3, 3, 1, 5], [4, 2, 1, 7], [5, 1, 1, 9], [7, 4, 1, 3], [9, 2, 1, 7]],
    mute: [[1, 4, 2, 3], [3, 3, 1, 5], [4, 2, 1, 7], [5, 1, 1, 9], [7, 3, 1, 1], [9, 3, 1, 1], [8, 4, 1, 3], [7, 7, 1, 1], [9, 7, 1, 1]],
    full: [[1, 1, 3, 1], [1, 1, 1, 3], [7, 1, 3, 1], [9, 1, 1, 3], [1, 9, 3, 1], [1, 7, 1, 3], [7, 9, 3, 1], [9, 7, 1, 3]],
    exitfull: [[1, 3, 3, 1], [3, 1, 1, 3], [7, 3, 3, 1], [7, 1, 1, 3], [1, 7, 3, 1], [3, 7, 1, 3], [7, 7, 3, 1], [7, 7, 1, 3]],
  }[name] as [number, number, number, number][];
  return <svg width={size} height={size} viewBox="0 0 11 11" shapeRendering="crispEdges" fill="currentColor" aria-hidden="true">{r.map(([x, y, w, h], i) => <rect key={i} x={x} y={y} width={w} height={h} />)}</svg>;
}

/** Play/pause, seek bar, time, mute and (optionally) full screen. Shared by the theater and the Reels player. */
export function MediaControls({ playing, current, duration, muted, disabled, buffering, onToggle, onSeek, onMute, fullscreen, onFullscreen, label = 'Video' }: {
  playing: boolean; current: number; duration: number; muted: boolean; disabled?: boolean; buffering?: boolean;
  onToggle: () => void; onSeek: (t: number) => void; onMute: (m: boolean) => void; fullscreen?: boolean; onFullscreen?: () => void; label?: string;
}) {
  const max = duration > 0 ? duration : 0;
  return (
    <div className="media-bar" role="group" aria-label={`${label} controls`}>
      <button type="button" className="btn btn-sm icon-btn" onClick={onToggle} disabled={disabled} aria-label={playing ? `Pause ${label.toLowerCase()}` : `Play ${label.toLowerCase()}`}><MediaIcon name={playing ? 'pause' : 'play'} /></button>
      <input className="media-seek" type="range" min={0} max={max || 1} step={0.1} value={Math.min(current, max || 1)} disabled={disabled || !max}
        onChange={(e) => onSeek(+e.target.value)} aria-label={`Seek ${label.toLowerCase()}`} aria-valuetext={`${fmtTime(current)} of ${fmtTime(max)}`}
        style={{ ['--pct' as string]: max ? `${(current / max) * 100}%` : '0%' }} />
      <span className="media-time" aria-hidden="true">{buffering ? '...' : fmtTime(current)} / {fmtTime(max)}</span>
      <button type="button" className="btn btn-sm icon-btn" onClick={() => onMute(!muted)} disabled={disabled} aria-pressed={muted} aria-label={muted ? 'Turn sound on' : 'Mute'}><MediaIcon name={muted ? 'mute' : 'sound'} /></button>
      {onFullscreen && <button type="button" className="btn btn-sm icon-btn" onClick={onFullscreen} disabled={disabled} aria-pressed={!!fullscreen} aria-label={fullscreen ? 'Leave full screen' : 'Full screen'}><MediaIcon name={fullscreen ? 'exitfull' : 'full'} /></button>}
    </div>
  );
}

/** A self-contained video with the same pixel controls (Reels). Sound goes through the arbiter like theater videos. */
export function VideoPlayer({ src, poster, autoPlay, label = 'Video' }: { src: string; poster?: string | null; autoPlay?: boolean; label?: string }) {
  const wrap = useRef<HTMLDivElement>(null);
  const ref = useRef<HTMLVideoElement>(null);
  const [st, setSt] = useState({ playing: false, current: 0, duration: 0, muted: false, buffering: false });
  const [full, setFull] = useState(false);
  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    let detach: (() => void) | null = null;
    const sound = () => {
      if (!v.paused && !v.muted) { if (!detach) { if (arbiter.speaking) voice.stopSpeech('reel'); detach = arbiter.attachShowcaseMedia(v); } }
      else { detach?.(); detach = null; }
    };
    const up = () => setSt({ playing: !v.paused, current: v.currentTime, duration: Number.isFinite(v.duration) ? v.duration : 0, muted: v.muted, buffering: v.readyState < 3 && !v.paused });
    const evs = ['play', 'pause', 'timeupdate', 'loadedmetadata', 'volumechange', 'waiting', 'playing', 'ended', 'seeked'];
    const on = () => { up(); sound(); };
    evs.forEach((e) => v.addEventListener(e, on));
    const fs = () => setFull(document.fullscreenElement === wrap.current);
    document.addEventListener('fullscreenchange', fs);
    if (autoPlay) void v.play().catch(() => undefined);
    return () => { evs.forEach((e) => v.removeEventListener(e, on)); document.removeEventListener('fullscreenchange', fs); detach?.(); v.pause(); };
  }, [src, autoPlay]);
  const toggle = () => { const v = ref.current; if (!v) return; if (v.paused) void v.play().catch(() => undefined); else v.pause(); };
  const seek = (t: number) => { const v = ref.current; if (v) v.currentTime = t; };
  const onKey = (e: KeyboardEvent) => {
    if ((e.key === ' ' && (e.target as HTMLElement).tagName !== 'BUTTON') || e.key === 'k') { e.preventDefault(); toggle(); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); seek(Math.min(st.duration, st.current + 5)); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); seek(Math.max(0, st.current - 5)); }
    else if (e.key === 'm') { const v = ref.current; if (v) v.muted = !v.muted; }
  };
  const fullscreen = () => {
    const w = wrap.current;
    if (!w) return;
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
    else if (w.requestFullscreen) void w.requestFullscreen().catch(() => undefined);
    else (ref.current as HTMLVideoElement & { webkitEnterFullscreen?: () => void })?.webkitEnterFullscreen?.();   // iPhone Safari
  };
  return (
    <div className={'video-player' + (full ? ' is-full' : '')} ref={wrap} onKeyDown={onKey}>
      <video ref={ref} src={src} poster={poster ?? undefined} playsInline preload="metadata" onClick={toggle} aria-label={label} />
      <MediaControls label={label} {...st} onToggle={toggle} onSeek={seek} onMute={(m) => { if (ref.current) ref.current.muted = m; }} fullscreen={full} onFullscreen={fullscreen} />
    </div>
  );
}
