import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { get } from '../api/client';
import { useWorld } from '../state/worldStore';
import { LANGS, Modal, Spinner, monthName } from '../ui/common';
import { AvatarSprite } from '../ui/Pixels';
import { unlockAudio } from '../voice/audioUnlock';
import { LandingPage } from './landing/LandingPage';

export { QR } from './landing/bot';

/** Signed out (GET /api/museum said 401): the public landing page. "How to sign in" is a pop-up on it. */
export function SignIn() {
  return <LandingPage />;
}

interface Welcome { is_guest: boolean; host_name?: string; contact_name?: string | null; event_name?: string | null; year?: number; month?: number; family_name?: string }

/** Roving-focus radio group: arrows move the choice, Home/End jump. */
function useRadioKeys<T>(options: readonly T[], value: T, set: (v: T) => void) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    const n = options.length, i = Math.max(0, options.indexOf(value));
    let next = -1;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (i + 1) % n;
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (i - 1 + n) % n;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = n - 1;
    if (next < 0) return;
    e.preventDefault();
    set(options[next]);
    refs.current[next]?.focus();
  };
  return { refs, onKeyDown };
}

const AVATARS = [
  { id: 'woman', label: 'Saree', hint: 'Walks in a red saree' },
  { id: 'man', label: 'Shirt and trousers', hint: 'Walks in a blue shirt' },
] as const;

function AvatarPick({ autoFocus }: { autoFocus?: boolean }) {
  const avatar = useWorld((s) => s.avatar);
  const setAvatar = useWorld((s) => s.setAvatar);
  const ids = AVATARS.map((a) => a.id);
  const { refs, onKeyDown } = useRadioKeys(ids, avatar, setAvatar);
  return (
    <div className="entry-field">
      <span className="label" id="entry-who">Who walks in?</span>
      <div className="entry-avatars" role="radiogroup" aria-labelledby="entry-who" onKeyDown={onKeyDown}>
        {AVATARS.map((a, i) => {
          const on = avatar === a.id;
          return (
            <button key={a.id} ref={(el) => { refs.current[i] = el; }} type="button" className="entry-avatar" role="radio" aria-checked={on} tabIndex={on ? 0 : -1}
              data-autofocus={autoFocus && on ? '' : undefined} onClick={() => setAvatar(a.id)}>
              <span className="entry-avatar-stage"><AvatarSprite kind={a.id} px={6} /></span>
              <span className="entry-avatar-name">{a.label}</span>
              <span className="entry-avatar-hint">{a.hint}</span>
              <span className="entry-avatar-tick" aria-hidden="true" />
            </button>
          );
        })}
      </div>
    </div>
  );
}

function LanguagePick() {
  const language = useWorld((s) => s.language);
  const setLanguage = useWorld((s) => s.setLanguage);
  const ids = LANGS.map((l) => l.id);
  const { refs, onKeyDown } = useRadioKeys(ids, language as (typeof ids)[number], setLanguage);
  return (
    <div className="entry-field">
      <span className="label" id="entry-lang">Language</span>
      <div className="seg entry-seg" role="radiogroup" aria-labelledby="entry-lang" onKeyDown={onKeyDown}>
        {LANGS.map((l, i) => (
          <button key={l.id} ref={(el) => { refs.current[i] = el; }} type="button" role="radio" aria-checked={language === l.id} tabIndex={language === l.id ? 0 : -1} onClick={() => setLanguage(l.id)} lang={l.id}>{l.label}</button>
        ))}
      </div>
      <span className="entry-note">Grandma, the guide and the desk speak this. You can change it later in Settings.</span>
    </div>
  );
}

/** The "who walks in" pop-up shown over the landing page once a Telegram link signed the user in.
 *  Avatar and language are saved (localStorage, via the store) so the next visit starts on the last choice.
 *  Closing it (X, Esc, backdrop) just returns to the landing page; its "Enter" buttons open it again. */
function EntryModal({ onClose }: { onClose: () => void }) {
  const { museum, enter, displayName, setDisplayName } = useWorld();
  const [busy, setBusy] = useState(false);
  const [welcome, setWelcome] = useState<Welcome | null>(null);
  const [name, setName] = useState(displayName ?? '');
  const guest = !!museum?.me.is_guest;
  useEffect(() => {
    if (!guest) return;
    get<Welcome>('/api/guest/welcome').then((w) => { setWelcome(w); setName((n) => n || w.contact_name || ''); }).catch(() => undefined);
  }, [guest]);
  if (!museum) return null;
  const go = async () => {
    setBusy(true);
    if (guest) setDisplayName(name.trim().slice(0, 40) || welcome?.contact_name || null);
    await unlockAudio();   // the click that unlocks audio and, on the first mic tap, the microphone
    enter();
  };
  const inv = museum.me.invite_room;
  const where = welcome?.event_name
    ? `${welcome.event_name} (${monthName(welcome.month ?? inv?.month ?? 1)} ${welcome.year ?? inv?.year ?? ''})`
    : inv ? `${monthName(inv.month)} ${inv.year}` : 'one room';
  const host = welcome?.host_name ?? museum.family.name;
  const footer = (
    <>
      <p className="entry-sound"><SoundGlyph /> {guest ? 'Joining' : 'Entering'} turns on sound.</p>
      <button type="submit" form="entry-form" className="btn btn-primary btn-lg entry-go" disabled={busy}>{busy ? 'Opening the doors' : guest ? 'Take my seat' : 'Enter the museum'}</button>
    </>
  );
  return (
    <Modal title={guest ? `${host} invited you` : museum.family.name} kicker={guest ? `To ${where}` : 'Welcome to your museum'} size="md"
      onClose={onClose} busy={busy} footer={footer} className="entry-modal" layerClassName="entry-layer">
      <form id="entry-form" className="stack" onSubmit={(e) => { e.preventDefault(); void go(); }}>
        <p className="entry-lede">
          {guest
            ? `Take a seat in the theater and watch together. Your screen follows ${welcome?.host_name ?? 'the host'}'s showing, and everyone in the room sees you in your seat.`
            : `Every photo and voice note your family sent hangs in a museum you can walk through. ${museum.family.grandma_name} will show you around.`}
        </p>
        {guest && (
          <div className="field">
            <label htmlFor="guest-name">Your name</label>
            <input id="guest-name" className="input" value={name} maxLength={40} autoComplete="name" onChange={(e) => setName(e.target.value)} placeholder="Your name" />
          </div>
        )}
        <AvatarPick autoFocus={!guest} />
        {!guest && <LanguagePick />}
        <p className="entry-note">You can talk to the museum, or use only the buttons and keys.</p>
      </form>
    </Modal>
  );
}

function SoundGlyph() {
  return <svg width="14" height="14" viewBox="0 0 11 11" shapeRendering="crispEdges" fill="currentColor" aria-hidden="true"><rect x="1" y="4" width="2" height="3" /><rect x="3" y="3" width="1" height="5" /><rect x="4" y="2" width="1" height="7" /><rect x="5" y="1" width="1" height="9" /><rect x="7" y="4" width="1" height="3" /><rect x="9" y="2" width="1" height="7" /></svg>;
}

/** Signed in (phase "landing"): the landing page stays behind, the entry pop-up sits on top. */
export function Landing() {
  const museum = useWorld((s) => s.museum);
  const [open, setOpen] = useState(true);
  if (!museum) return <div className="loading-screen"><Spinner text="Opening the museum" /></div>;
  const label = museum.me.is_guest ? 'Take my seat' : 'Enter your museum';
  return (
    <>
      <div className="entry-behind" aria-hidden={open || undefined} {...(open ? { inert: '' } : {})}><LandingPage enter={{ label, onClick: () => setOpen(true) }} /></div>
      {open && <EntryModal onClose={() => setOpen(false)} />}
    </>
  );
}
