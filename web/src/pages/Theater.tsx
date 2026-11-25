import { useEffect, useRef } from 'react';
import { post } from '../api/client';
import { useWorld } from '../state/worldStore';
import { arbiter } from '../voice/speechArbiter';
import { useVoiceUi, voice } from '../voice/controller';
import { Orb, monthName } from '../ui/common';
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
      if (!guest && s.showcaseNarrated && s.showcaseIndex === 0) void voice.grandmaSpeak('tour');
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
    if (guest) return;
    const ms = ((item.duration_s && item.duration_s > 0 ? item.duration_s : item.kind === 'photo' ? 6 : 5) * 1000) / speed;
    const t = window.setTimeout(() => useWorld.getState().nextItem(), ms);
    return () => clearTimeout(t);
  }, [s.showcasePlaying, s.showcaseIndex, s.showcaseSpeed, s.skipVoiceNotes, item, guest]);

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

/** Full-display screen for 2D mode (the 3D world draws its own screen). */
export function ScreenView() {
  const { showcaseItems, showcaseIndex, screenMode, reducedMotion } = useWorld();
  const it = showcaseItems[showcaseIndex];
  if (!screenMode) return null;
  return (
    <div className="fullscreen-screen" aria-label="Showcase screen">
      {!it && <p className="display" style={{ fontSize: '2.6rem' }}>Nothing to show yet</p>}
      {it?.kind === 'photo' && it.url && <img key={showcaseIndex} className={reducedMotion ? '' : 'zoom'} src={it.url} alt={it.caption} />}
      {it?.kind === 'title' && <div style={{ maxWidth: 900, padding: 32, textAlign: 'center' }}><p className="display" style={{ fontSize: 'clamp(2.4rem,6vw,5rem)' }}>{it.caption}</p></div>}
      {it?.kind === 'voice' && <div style={{ maxWidth: 800, padding: 32, textAlign: 'center' }}><p className="display" style={{ fontSize: '2.6rem' }}>{it.caption}</p><p style={{ fontSize: 20, marginTop: 16 }}>{it.transcript ?? 'Voice note'}</p></div>}
    </div>
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
          <button className="btn btn-sm" onClick={() => s.prevItem()} aria-label="Previous (left arrow)" disabled={guest || total === 0}>Back</button>
          <button className="btn btn-sm btn-primary" onClick={() => { s.setShowcase({ showcasePlaying: !s.showcasePlaying }); if (s.showcasePlaying) voice.stopSpeech(); }} disabled={guest || total === 0} aria-label={s.showcasePlaying ? 'Pause (space)' : 'Play (space)'}>{s.showcasePlaying ? 'Pause' : 'Play'}</button>
          <button className="btn btn-sm" onClick={() => s.nextItem()} aria-label="Next (right arrow)" disabled={guest || total === 0}>Next</button>
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
        <div className="progress" aria-hidden="true"><i style={{ width: total ? `${((s.showcaseIndex + 1) / total) * 100}%` : 0 }} /></div>
        <p className="muted" style={{ fontSize: 13 }} aria-live="polite">{total === 0 ? 'No memories on the screen yet.' : `${s.showcaseIndex + 1} of ${total}: ${item?.caption ?? ''}`}</p>
        <RoomTools />
        <div className="row"><button className="btn btn-sm" onClick={() => s.setScreenMode(!s.screenMode)}>Fill the screen</button>{owner && <button className="btn btn-sm" onClick={() => s.leaveRoom()}>Leave room</button>}</div>
      </div>
      <p className="muted" style={{ fontSize: 12 }}>Say "pause", "next", "start over" or "step back". Keys: space, arrows, R, Esc.</p>
    </section>
  );
}
