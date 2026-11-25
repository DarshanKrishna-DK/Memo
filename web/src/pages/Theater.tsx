import { useEffect, useRef, useState, type PointerEvent as RPointerEvent } from 'react';
import { post } from '../api/client';
import { useWorld } from '../state/worldStore';
import { arbiter } from '../voice/speechArbiter';
import { useVoiceUi, voice } from '../voice/controller';
import { Orb, monthName } from '../ui/common';
import { MediaControls, MediaIcon } from '../ui/MediaControls';
import { theaterVideo, useTheaterVideo } from './theaterVideo';
import { RoomTools } from './RoomUi';
import { watchingWith } from './presence';

/** Drives the showcase playlist: photos ~6 s, title cards ~5 s, voice notes play their audio. Guests only follow. */
export function useShowcaseEngine() {
  const s = useWorld();
  const guest = !!s.museum?.me.is_guest;
  const wasPlaying = useRef(false);
  const item = s.showcaseItems[s.showcaseIndex];

  // Start: camera moves into the screen (PRD V5) and Grandma narrates if chosen.
  useEffect(() => {
    if (s.showcasePlaying && !wasPlaying.current) {
      if (!s.screenMode) s.setScreenMode(true);
      if (!guest && s.showcaseNarrated && s.showcaseIndex === 0 && item?.kind !== 'video') void voice.grandmaSpeak('tour');
    }
    if (!s.showcasePlaying && wasPlaying.current && s.screenMode && s.showcaseIndex >= s.showcaseItems.length - 1) s.setScreenMode(false);
    wasPlaying.current = s.showcasePlaying;
  }, [s.showcasePlaying]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!s.showcasePlaying || !item) return;
    const speed = s.showcaseSpeed;
    if (item.kind === 'voice') {
      if (s.skipVoiceNotes) { const t = window.setTimeout(() => useWorld.getState().nextItem(), 80); return () => clearTimeout(t); }
      if (!item.audio_url) { const t = window.setTimeout(() => !guest && useWorld.getState().nextItem(), Math.max(4000, (item.transcript?.length ?? 40) * 60) / speed); return () => clearTimeout(t); }
      voice.stopSpeech('voice-note');   // the voice note is the star: Grandma waits, and if she speaks later the note is ducked, never overlapped
      return arbiter.playShowcase(item.audio_url, { rate: speed, onEnded: () => { if (!guest) useWorld.getState().nextItem(); } });
    }
    if (item.kind === 'video') {
      // The video's own "ended" moves on (see below). No playable file: show the poster for a few seconds instead.
      if (item.url || guest) return;
      const t = window.setTimeout(() => useWorld.getState().nextItem(), 5000 / speed);
      return () => clearTimeout(t);
    }
    if (guest) return;
    const ms = ((item.duration_s && item.duration_s > 0 ? item.duration_s : item.kind === 'photo' ? 6 : 5) * 1000) / speed;
    const t = window.setTimeout(() => useWorld.getState().nextItem(), ms);
    return () => clearTimeout(t);
  }, [s.showcasePlaying, s.showcaseIndex, s.showcaseSpeed, s.skipVoiceNotes, item, guest]);

  // Video items: one shared <video> (theaterVideo). Poster first, plays while the show plays, next item when it ends.
  // While it plays with sound Grandma is stopped (speech arbiter: one voice at a time) and carries on when it ends.
  const videoUrl = s.seat && item?.kind === 'video' ? item.url : null;
  const stoppedGrandma = useRef(false);
  useEffect(() => {
    theaterVideo.onSound = () => { if (arbiter.speaking) { stoppedGrandma.current = true; voice.stopSpeech('video'); } };
    return () => { theaterVideo.onSound = null; theaterVideo.unload(); };
  }, []);
  useEffect(() => {
    if (!videoUrl || !item) { theaterVideo.unload(); return; }
    theaterVideo.load(videoUrl, item.poster_url ?? item.thumb_url, () => {
      const w = useWorld.getState();
      if (stoppedGrandma.current && voice.canResume() && w.showcaseNarrated) { stoppedGrandma.current = false; voice.resumeGrandma(); }
      if (!guest) w.nextItem();
    });
  }, [videoUrl]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!videoUrl) return;
    if (s.showcasePlaying) theaterVideo.play(); else theaterVideo.pause();
  }, [videoUrl, s.showcasePlaying]);
  const vErr = useTheaterVideo().error;
  useEffect(() => {
    if (!vErr || !videoUrl || guest || !useWorld.getState().showcasePlaying) return;
    const t = window.setTimeout(() => useWorld.getState().nextItem(), 2500);   // a broken file never stalls the show
    return () => clearTimeout(t);
  }, [vErr, videoUrl, guest]);

  // Host publishes its position; guests follow it.
  const room = s.seat;
  useEffect(() => {
    if (guest || !room) return;
    const t = window.setTimeout(() => { void post('/api/sync', { year: room.year, month: room.month, index: s.showcaseIndex, playing: s.showcasePlaying }).catch(() => undefined); }, 150);
    return () => clearTimeout(t);
  }, [guest, room?.year, room?.month, s.showcaseIndex, s.showcasePlaying]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!guest || !s.guestSync) return;
    s.setShowcase({ showcaseIndex: s.guestSync.index, showcasePlaying: s.guestSync.playing });
  }, [guest, s.guestSync]); // eslint-disable-line react-hooks/exhaustive-deps

  // Someone new sat down: send them where we are (they follow from the next sync on).
  const people = (s.presence?.seats.length ?? 0) + (s.presence?.watchers.length ?? 0);
  useEffect(() => {
    if (guest || !room || people < 2) return;
    const t = window.setTimeout(() => { const w = useWorld.getState(); void post('/api/sync', { year: room.year, month: room.month, index: w.showcaseIndex, playing: w.showcasePlaying }).catch(() => undefined); }, 600);
    return () => clearTimeout(t);
  }, [people]); // eslint-disable-line react-hooks/exhaustive-deps

  // Greet on sitting down (host only), after any join/leave card. She waits for the user after that.
  useEffect(() => {
    if (!room || guest) return;
    const wait = Math.max(0, useWorld.getState().presenceCardUntil - Date.now());
    const t = window.setTimeout(() => { void voice.grandmaSpeak('greet'); }, wait);
    return () => { clearTimeout(t); voice.interrupt(); };
  }, [room?.year, room?.month]); // eslint-disable-line react-hooks/exhaustive-deps

  // A join/leave card is up: Grandma does not talk over it. She pauses and carries on when it is read.
  useEffect(() => {
    if (!room || !s.presenceCardUntil) return;
    const wait = s.presenceCardUntil - Date.now();
    if (wait <= 0 || useWorld.getState().agentState !== 'speaking') return;
    voice.stopSpeech('presence-card');
    const t = window.setTimeout(() => { if (useWorld.getState().seat && voice.canResume()) voice.resumeGrandma(); }, wait);
    return () => clearTimeout(t);
  }, [s.presenceCardUntil]); // eslint-disable-line react-hooks/exhaustive-deps
}

/** "Watching with: Priya, Ravi" under the theater header. */
export function WatchingWith() {
  const presence = useWorld((s) => s.presence);
  const names = watchingWith(presence);
  if (!names.length) return null;
  return <p className="watching-with" aria-live="polite"><span className="label">Watching with:</span> {names.join(', ')}</p>;
}

/** Mounts the shared theater <video> element into the page (2D screen). The 3D screen draws it as a texture instead. */
function VideoMount() {
  const host = useRef<HTMLDivElement>(null);
  const v = useTheaterVideo();
  useEffect(() => {
    const el = theaterVideo.el, h = host.current;
    if (!el || !h) return;
    h.appendChild(el);
    return () => { if (el.parentNode === h) h.removeChild(el); };
  }, [v.url]);
  return (
    <div className="video-mount" ref={host}>
      {!v.started && v.poster && <img className="video-poster" src={v.poster} alt="" />}
      {!v.playing && !v.error && <span className="video-badge" aria-hidden="true"><MediaIcon name="play" size={28} /></span>}
      {v.error && <p className="video-error" role="status">This video could not be played.</p>}
    </div>
  );
}

/** Full-display screen for 2D mode (the 3D world draws its own screen). */
export function ScreenView() {
  const { showcaseItems, showcaseIndex, screenMode, reducedMotion } = useWorld();
  const it = showcaseItems[showcaseIndex];
  if (!screenMode) return null;
  return (
    <div className="fullscreen-screen" aria-label="Showcase screen">
      {!it && <p className="display" style={{ fontSize: '2.6rem' }}>Nothing to show yet</p>}
      {it?.kind === 'photo' && it.url && <img key={showcaseIndex} className={reducedMotion ? '' : 'zoom'} src={it.url} alt={it.caption} />}
      {it?.kind === 'video' && <VideoMount key={showcaseIndex} />}
      {it?.kind === 'title' && <div style={{ maxWidth: 900, padding: 32, textAlign: 'center' }}><p className="display" style={{ fontSize: 'clamp(2.4rem,6vw,5rem)' }}>{it.caption}</p></div>}
      {it?.kind === 'voice' && <div style={{ maxWidth: 800, padding: 32, textAlign: 'center' }}><p className="display" style={{ fontSize: '2.6rem' }}>{it.caption}</p><p style={{ fontSize: 20, marginTop: 16 }}>{it.transcript ?? 'Voice note'}</p></div>}
    </div>
  );
}

/** Horizontal swipe = previous / next. A short tap calls onTap. Pointer events cover touch, pen and mouse. */
export function useSwipe(onTap?: () => void) {
  const start = useRef<{ x: number; y: number; t: number; id: number } | null>(null);
  return {
    onPointerDown: (e: RPointerEvent) => { start.current = { x: e.clientX, y: e.clientY, t: performance.now(), id: e.pointerId }; },
    onPointerCancel: () => { start.current = null; },
    onPointerUp: (e: RPointerEvent) => {
      const s0 = start.current; start.current = null;
      if (!s0 || s0.id !== e.pointerId) return;
      const dx = e.clientX - s0.x, dy = e.clientY - s0.y, dt = performance.now() - s0.t;
      const w = useWorld.getState();
      if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.4 && dt < 800) {
        if (w.museum?.me.is_guest) return;
        if (dx < 0) w.nextItem(); else w.prevItem();
      } else if (Math.abs(dx) < 10 && Math.abs(dy) < 10) onTap?.();
    },
  };
}

function playToggle() {
  const w = useWorld.getState();
  w.setShowcase({ showcasePlaying: !w.showcasePlaying });
  if (w.showcasePlaying) voice.stopSpeech();
}

/** Video controls bound to the theater's shared video. Play/pause is the show's play/pause, so space, voice and buttons agree.
 *  Guests follow the host's show, but may still pause, seek and mute their own copy. */
export function TheaterVideoControls({ onFullscreen, fullscreen }: { onFullscreen?: () => void; fullscreen?: boolean }) {
  const v = useTheaterVideo();
  const guest = useWorld((s) => !!s.museum?.me.is_guest);
  if (!v.url) return null;
  return (
    <MediaControls label="Video" playing={v.playing} current={v.current} duration={v.duration} muted={v.muted} buffering={v.buffering}
      onToggle={() => (guest ? (v.playing ? theaterVideo.pause() : theaterVideo.play()) : playToggle())}
      onSeek={(t) => theaterVideo.seek(t)} onMute={(m) => theaterVideo.setMuted(m)} onFullscreen={onFullscreen} fullscreen={fullscreen} />
  );
}

/** "3 / 12" plus a thin progress line. */
function SlideCounter({ index, total }: { index: number; total: number }) {
  return (
    <div className="slide-count">
      <span className="slide-num" aria-hidden="true">{total ? index + 1 : 0}<i>/</i>{total}</span>
      <div className="progress progress--thin" aria-hidden="true"><i style={{ width: total ? `${((index + 1) / total) * 100}%` : 0 }} /></div>
    </div>
  );
}

/** Controls over the screen when "Fill the screen" is on (2D and 3D): swipe, tap to show/hide, prev / play / next,
 *  counter, progress, video bar. Hides itself after a few seconds of playing; any key, mouse move or tap brings it back. */
export function ScreenOverlay() {
  const s = useWorld();
  const guest = !!s.museum?.me.is_guest;
  const total = s.showcaseItems.length;
  const item = s.showcaseItems[s.showcaseIndex];
  const [shown, setShown] = useState(true);
  const [docFull, setDocFull] = useState(false);
  const hideT = useRef(0);
  const bar = useRef<HTMLDivElement>(null);
  const poke = () => {
    setShown(true);
    clearTimeout(hideT.current);
    hideT.current = window.setTimeout(() => { if (useWorld.getState().showcasePlaying && !bar.current?.contains(document.activeElement)) setShown(false); }, 4000);
  };
  useEffect(() => { poke(); return () => clearTimeout(hideT.current); }, [s.showcaseIndex, s.showcasePlaying, s.screenMode]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const k = () => poke();
    const fs = () => setDocFull(!!document.fullscreenElement);
    window.addEventListener('keydown', k);
    document.addEventListener('fullscreenchange', fs);
    return () => { window.removeEventListener('keydown', k); document.removeEventListener('fullscreenchange', fs); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const swipe = useSwipe(() => (shown ? setShown(false) : poke()));
  if (!s.seat || !s.screenMode) return null;
  const exit = () => { if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined); s.setScreenMode(false); };
  const docFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
    else void document.documentElement.requestFullscreen?.().catch(() => undefined);
  };
  return (
    <>
      <div className="screen-gesture" {...swipe} onPointerMove={(e) => { if (e.pointerType === 'mouse') poke(); }} aria-hidden="true" />
      <div ref={bar} className={'screen-bar hud-hit' + (shown ? '' : ' is-hidden')} role="group" aria-label="Screen controls" onFocus={poke}>
        <div className="screen-bar-row">
          <button className="btn btn-sm icon-btn" onClick={() => s.prevItem()} disabled={guest || total === 0 || s.showcaseIndex === 0} aria-label="Previous (left arrow)" aria-keyshortcuts="ArrowLeft"><MediaIcon name="prev" /></button>
          <button className="btn btn-sm btn-primary icon-btn" onClick={playToggle} disabled={guest || total === 0} aria-label={s.showcasePlaying ? 'Pause (space)' : 'Play (space)'} aria-keyshortcuts="Space"><MediaIcon name={s.showcasePlaying ? 'pause' : 'play'} /></button>
          <button className="btn btn-sm icon-btn" onClick={() => s.nextItem()} disabled={guest || total === 0 || s.showcaseIndex >= total - 1} aria-label="Next (right arrow)" aria-keyshortcuts="ArrowRight"><MediaIcon name="next" /></button>
          <SlideCounter index={s.showcaseIndex} total={total} />
          <p className="screen-caption" aria-live="polite">{item?.caption ?? ''}</p>
          <button className="btn btn-sm" onClick={exit} aria-keyshortcuts="Escape">Back to seat</button>
        </div>
        {item?.kind === 'video' && <TheaterVideoControls onFullscreen={docFullscreen} fullscreen={docFull} />}
      </div>
    </>
  );
}

export function TheaterPanel() {
  const s = useWorld();
  const ui = useVoiceUi();
  const grandma = s.museum?.family.grandma_name ?? 'Grandma';
  const guest = !!s.museum?.me.is_guest;
  const item = s.showcaseItems[s.showcaseIndex];
  const total = s.showcaseItems.length;
  const owner = s.museum?.me.role !== 'viewer' && !guest;
  const state = s.agentState;
  if (!s.seat) return null;
  return (
    <section className="theater panel panel--brass hud-hit fade-in" aria-label="Theater controls">
      <div className="grandma-head">
        <div className="orb-slot">{state === 'thinking' || state === 'speaking' ? <Orb state={state === 'thinking' ? 'working' : 'composing'} size={64} label={`${grandma} is ${state === 'thinking' ? 'thinking' : 'speaking'}`} /> : <Orb state="breathing" size={64} label={`${grandma} is listening`} />}</div>
        <div><h2>{grandma}</h2><p className="muted" style={{ fontSize: 13 }}>{monthName(s.seat.month)} {s.seat.year}{s.room?.eventId ? ', one event' : ''}</p></div>
      </div>
      <WatchingWith />
      {!guest && (
        <div className="btn-row" role="group" aria-label={`Talk to ${grandma}`}>
          <button className="btn btn-sm btn-brass" onClick={() => void voice.grandmaSpeak('tour')} disabled={ui.busy}>Tell the story</button>
          <button className="btn btn-sm" onClick={() => voice.stopSpeech()} disabled={state !== 'speaking'}>Stop</button>
          <button className="btn btn-sm" onClick={() => voice.resumeGrandma()} disabled={state === 'speaking' || !voice.canResume()}>Carry on</button>
          <button className="btn btn-sm" onClick={() => s.openPanel('reception')} title="Invite someone into this room">Invite</button>
        </div>
      )}
      <div className="showcase-bar" role="group" aria-label="Showcase">
        <div className="row" style={{ gap: 6 }}>
          <button className="btn btn-sm" onClick={() => s.prevItem()} aria-label="Previous (left arrow)" aria-keyshortcuts="ArrowLeft" disabled={guest || total === 0 || s.showcaseIndex === 0}>Back</button>
          <button className="btn btn-sm btn-primary" onClick={playToggle} disabled={guest || total === 0} aria-label={s.showcasePlaying ? 'Pause (space)' : 'Play (space)'} aria-keyshortcuts="Space">{s.showcasePlaying ? 'Pause' : 'Play'}</button>
          <button className="btn btn-sm" onClick={() => s.nextItem()} aria-label="Next (right arrow)" aria-keyshortcuts="ArrowRight" disabled={guest || total === 0 || s.showcaseIndex >= total - 1}>Next</button>
          <button className="btn btn-sm" onClick={() => s.restartShowcase()} disabled={guest || total === 0} aria-label="Start over (R)">Start over</button>
        </div>
        {!guest && (
          <div className="row" style={{ gap: 6 }}>
            <button className="btn btn-sm" aria-pressed={s.skipVoiceNotes} onClick={() => s.setShowcase({ skipVoiceNotes: !s.skipVoiceNotes })}>Skip voice notes</button>
            <button className="btn btn-sm" aria-pressed={s.showcaseNarrated} onClick={() => s.setShowcase({ showcaseNarrated: !s.showcaseNarrated })}>{s.showcaseNarrated ? 'Narrated' : 'Silent'}</button>
            <button className="btn btn-sm" onClick={() => s.setShowcase({ showcaseSpeed: Math.max(0.5, +(s.showcaseSpeed - 0.5).toFixed(1)) })} aria-label="Slower">-</button>
            <span className="chip" style={{ textTransform: 'none' }} aria-label={`Speed ${s.showcaseSpeed} times`}>{s.showcaseSpeed.toFixed(1)}x</span>
            <button className="btn btn-sm" onClick={() => s.setShowcase({ showcaseSpeed: Math.min(3, +(s.showcaseSpeed + 0.5).toFixed(1)) })} aria-label="Faster">+</button>
          </div>
        )}
        {item?.kind === 'video' && <TheaterVideoControls onFullscreen={() => s.setScreenMode(true)} />}
        <SlideCounter index={s.showcaseIndex} total={total} />
        <p className="muted" style={{ fontSize: 13 }} aria-live="polite">{total === 0 ? 'No memories on the screen yet.' : `${s.showcaseIndex + 1} of ${total}${item?.kind === 'video' ? ', video' : ''}: ${item?.caption ?? ''}`}</p>
        <RoomTools />
        <div className="row"><button className="btn btn-sm" onClick={() => s.setScreenMode(!s.screenMode)}>Fill the screen</button>{owner && <button className="btn btn-sm" onClick={() => s.leaveRoom()}>Leave room</button>}</div>
      </div>
      <p className="muted" style={{ fontSize: 12 }}>Say "pause", "next", "start over" or "step back". Keys: space, arrows, R, Esc. On a phone, swipe the screen.</p>
    </section>
  );
}
