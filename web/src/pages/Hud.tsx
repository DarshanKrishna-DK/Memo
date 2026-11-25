import { useEffect, useRef, useState } from 'react';
import type { Interactable } from '../contract';
import { useWorld } from '../state/worldStore';
import { useVoiceUi, voice } from '../voice/controller';
import { Brand, Orb, monthName } from '../ui/common';
import { floorWithYear } from '../lib/floors';

function promptFor(i: Interactable, s: ReturnType<typeof useWorld.getState>): string {
  switch (i.kind) {
    case 'desk': return 'Talk to the receptionist';
    case 'lift_panel': return 'Use the lift';
    case 'door': return `Go to ${monthName(i.month)} ${i.year}`;
    case 'seat': return 'Sit down';
    case 'frame': return 'Look closer';
    case 'plaque': return 'Read the plaque';
    case 'jukebox': return 'Play the voice note';
    case 'attic': return 'Open the Attic';
    case 'directory': return 'Open the room directory';
  }
  void s;
  return '';
}

export function Hud() {
  const s = useWorld();
  const ui = useVoiceUi();
  const [text, setText] = useState('');
  // Screen mode: subtitles are a compact, scrollable strip that can be hidden; keep the newest line in view.
  const [capsHidden, setCapsHidden] = useState(false);
  const capsRef = useRef<HTMLDivElement>(null);
  useEffect(() => { const el = capsRef.current; if (el) el.scrollTop = el.scrollHeight; }, [s.captions, s.liveTranscript]);
  const target = s.seat ? 'grandma' : 'receptionist';
  const grandma = s.museum?.family.grandma_name ?? 'Grandma';
  const guest = !!s.museum?.me.is_guest;
  const place = s.seat ? `${monthName(s.seat.month)} ${s.seat.year}` : s.mode === 'lobby' ? 'Lobby' : s.mode === 'walking' ? 'On the way' : s.mode === 'riding' ? 'In the lift' : floorWithYear(s.currentLevel);

  // Keys. E interacts with what the world says is nearby; the rest mirror the buttons.
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      // A pop-up owns the keyboard: no world shortcuts while one is open.
      if (document.querySelector('[aria-modal="true"]')) return;
      const el = e.target as HTMLElement | null;
      // Esc (even from the text box) or space (outside it) while an agent talks stops them; the key is used up.
      const inField = !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable);
      if ((e.key === 'Escape' || (e.key === ' ' && !inField)) && voice.interruptByKey(e.key === ' ' ? 'space' : 'Esc')) { e.preventDefault(); return; }
      // Arrows on the video (or its seek bar) still step through the show, in and out of full screen.
      const mediaEl = !!el && (el.tagName === 'VIDEO' || (el.tagName === 'INPUT' && (el as HTMLInputElement).type === 'range' && !!el.closest('.media-bar')));
      if (mediaEl && (e.key === 'ArrowRight' || e.key === 'ArrowLeft') && useWorld.getState().seat) {
        e.preventDefault();
        if (!useWorld.getState().museum?.me.is_guest) { if (e.key === 'ArrowRight') useWorld.getState().nextItem(); else useWorld.getState().prevItem(); }
        return;
      }
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)) return;
      if (e.key === ' ' && el?.tagName === 'BUTTON') return;   // a focused button handles space itself (no double toggle)
      const w = useWorld.getState();
      if (e.key === 'Escape') {
        if (w.screenMode) { w.setScreenMode(false); w.setShowcase({ showcasePlaying: false }); }
        else if (w.panel) w.openPanel(null);
        return;
      }
      if (w.panel) return;
      if ((e.key === 'e' || e.key === 'E') && w.nearby) { e.preventDefault(); w.interact(w.nearby); }
      else if (e.key === 's' || e.key === 'S') { if (w.mode === 'walking') w.skipWalk(); }
      else if (e.key === 'm' || e.key === 'M') void voice.setMic(!w.micOn);
      else if (w.seat) {
        if (e.key === ' ') { e.preventDefault(); w.setShowcase({ showcasePlaying: !w.showcasePlaying }); if (!w.showcasePlaying) voice.stopSpeech(); }
        else if (e.key === 'ArrowRight') w.nextItem();
        else if (e.key === 'ArrowLeft') w.prevItem();
        else if (e.key === 'r' || e.key === 'R') w.restartShowcase();
      }
    };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, []);

  useEffect(() => { void voice.retarget(); void voice.pushContext(); }, [s.seat?.year, s.seat?.month]); // eslint-disable-line react-hooks/exhaustive-deps

  const send = (e: React.FormEvent) => { e.preventDefault(); const t = text; setText(''); void voice.sendText(t); };
  const orb = s.agentState === 'thinking' ? 'working' : s.agentState === 'speaking' ? 'composing' : 'listening';

  return (
    <div className={'hud' + (s.screenMode ? ' screenmode' : '')}>
      <header className="hud-top">
        <Brand small />
        <span className="hud-place" aria-live="polite">{place}</span>
        {!guest && s.mode !== 'walking' && (
          <>
            <button className="btn btn-sm" onClick={() => s.openPanel('reception')}>Reception</button>
            <button className="btn btn-sm" onClick={() => s.openPanel('lift')}>Lift</button>
            <button className="btn btn-sm" onClick={() => s.openPanel('directory')}>Rooms</button>
            <button className="btn btn-sm" onClick={() => s.openPanel('attic')}>Attic{s.museum && s.museum.attic_count > 0 ? ` (${s.museum.attic_count})` : ''}</button>
            <button className="btn btn-sm" onClick={() => s.openPanel('settings')}>Settings</button>
          </>
        )}
        <span className="grow" />
        {s.mode === 'walking' && <button className="btn btn-brass btn-sm hud-hit" onClick={() => s.skipWalk()}>Skip walk <kbd>S</kbd></button>}
        {s.seat && !guest && <button className="btn btn-sm" onClick={() => s.standUp()}>Step back</button>}
        {guest && s.seat && <span className="chip chip--teal">Watching with {grandma}</span>}
        <button className="btn btn-sm" aria-pressed={s.reducedMotion} onClick={() => s.setReducedMotion(!s.reducedMotion)} title="Fade instead of walking scenes">Reduced motion</button>
      </header>

      <div className="hud-mid">
        {s.nearby && !s.panel && s.mode !== 'walking' && (
          <div className="prompt" role="status"><kbd>E</kbd><span>{promptFor(s.nearby, s)}</span>
            <button className="btn btn-sm" onClick={() => s.interact(s.nearby!)}>Do it</button></div>
        )}
      </div>

      <div className="hud-bottom">
        {s.screenMode && <button type="button" className="btn btn-sm cap-toggle" aria-pressed={!capsHidden} aria-controls="hud-captions" onClick={() => setCapsHidden(!capsHidden)} title={capsHidden ? 'Show subtitles' : 'Hide subtitles'}>{capsHidden ? 'CC' : 'CC on'}</button>}
        <div id="hud-captions" ref={capsRef} className={'captions' + (s.screenMode && capsHidden ? ' is-collapsed' : '')} aria-live="polite" aria-label="Captions">
          {s.captions.slice(-3).map((c) => <p key={c.id} className={`cap cap--${c.who}` + (c.final ? '' : ' cap--live')}>{c.text || '...'}</p>)}
          {s.liveTranscript && <p className="cap cap--you cap--live">{s.liveTranscript}</p>}
          {ui.error && <p className="cap cap--system" role="alert">{ui.error}</p>}
        </div>
        {!guest && (
          <form className="inputbar" onSubmit={send}>
            {(s.agentState === 'thinking' || s.agentState === 'speaking') && <Orb state={orb} size={32} label={s.agentState === 'thinking' ? 'Thinking' : 'Speaking'} />}
            <input className="input" value={text} onChange={(e) => { setText(e.target.value); voice.userTyping(); }} aria-label={target === 'grandma' ? `Ask ${grandma}` : 'Ask the receptionist'} placeholder={target === 'grandma' ? `Ask ${grandma}, or say pause, next, step back` : 'Ask the receptionist: add an event, import photos, go to a room'} />
            <button className="btn btn-primary" type="submit" disabled={!text.trim() || ui.busy}>Send</button>
            {ui.transport === 'browser' && s.micOn && (
              <button type="button" className="btn" onPointerDown={() => voice.pushToTalk(true)} onPointerUp={() => voice.pushToTalk(false)} onPointerLeave={() => voice.pushToTalk(false)}>Hold to talk</button>
            )}
            <button type="button" className="mic" aria-pressed={s.micOn} aria-label={s.micOn ? 'Microphone is on. Turn it off' : 'Turn the microphone on'} title="Microphone (M)" onClick={() => void voice.setMic(!s.micOn)}>
              <svg width="22" height="22" viewBox="0 0 11 11" shapeRendering="crispEdges" fill="currentColor" aria-hidden="true"><rect x="4" y="0" width="3" height="6" /><rect x="2" y="4" width="1" height="2" /><rect x="8" y="4" width="1" height="2" /><rect x="3" y="6" width="5" height="1" /><rect x="5" y="7" width="1" height="2" /><rect x="3" y="9" width="5" height="1" /></svg>
              <span className="live" aria-hidden="true" />
            </button>
          </form>
        )}
        {s.micOn && <div className="meter" style={{ maxWidth: 760 }} aria-hidden="true"><i style={{ width: `${Math.round(s.micLevel * 100)}%` }} /></div>}
      </div>
      <div className={'micdot' + (s.micOn ? ' on' : '')} aria-hidden="true" />
    </div>
  );
}
