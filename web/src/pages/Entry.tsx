import { useEffect, useState } from 'react';
import { get } from '../api/client';
import { useWorld } from '../state/worldStore';
import { Brand, LANGS, Spinner, monthName } from '../ui/common';
import { AvatarSprite, Facade } from '../ui/Pixels';
import { unlockAudio } from '../voice/audioUnlock';
import { LandingPage } from './landing/LandingPage';

export { QR } from './landing/bot';

/** Signed out (GET /api/museum said 401): the public landing page. "How to sign in" is a pop-up on it. */
export function SignIn() {
  return <LandingPage />;
}

interface Welcome { is_guest: boolean; host_name?: string; contact_name?: string | null; event_name?: string | null; year?: number; month?: number; family_name?: string }

function AvatarPick() {
  const avatar = useWorld((s) => s.avatar);
  const setAvatar = useWorld((s) => s.setAvatar);
  return (
    <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
      <legend className="label" style={{ marginBottom: 8 }}>Who walks in?</legend>
      <div className="pick-row" role="radiogroup" aria-label="Your character">
        {(['woman', 'man'] as const).map((k) => (
          <button key={k} type="button" className="pick" role="radio" aria-checked={avatar === k} onClick={() => setAvatar(k)}>
            <AvatarSprite kind={k} /><span>{k === 'woman' ? 'Saree' : 'Shirt and trousers'}</span>
          </button>
        ))}
      </div>
    </fieldset>
  );
}

export function Landing() {
  const { museum, language, setLanguage, enter, displayName, setDisplayName } = useWorld();
  const [busy, setBusy] = useState(false);
  const [welcome, setWelcome] = useState<Welcome | null>(null);
  const [name, setName] = useState(displayName ?? '');
  const guest = !!museum?.me.is_guest;
  useEffect(() => {
    if (!guest) return;
    get<Welcome>('/api/guest/welcome').then((w) => { setWelcome(w); setName((n) => n || w.contact_name || ''); }).catch(() => undefined);
  }, [guest]);
  if (!museum) return <div className="loading-screen"><Spinner text="Opening the museum" /></div>;
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
  if (guest) {
    return (
      <main className="landing night">
        <section className="landing-left fade-in">
          <Brand />
          <h1 className="display landing-title">{welcome?.host_name ?? museum.family.name} invited you to {where}</h1>
          <p className="landing-lede">Take a seat in the theater and watch together. Your screen follows {welcome?.host_name ?? 'the host'}'s showing, and everyone in the room sees you in your seat.</p>
          <form className="guest-welcome" onSubmit={(e) => { e.preventDefault(); void go(); }}>
            <div className="field">
              <label htmlFor="guest-name">Your name</label>
              <input id="guest-name" className="input" value={name} maxLength={40} autoComplete="name" onChange={(e) => setName(e.target.value)} placeholder="Your name" />
            </div>
            <AvatarPick />
            <div className="row">
              <button type="submit" className="btn btn-primary btn-lg" disabled={busy}>Take my seat</button>
            </div>
          </form>
          <p className="muted" style={{ fontSize: 13 }}>Joining turns on sound.</p>
        </section>
        <section className="landing-right" aria-hidden="true"><Facade /></section>
      </main>
    );
  }
  return (
    <main className="landing night">
      <section className="landing-left fade-in">
        <Brand />
        <h1 className="display landing-title">{museum.family.name}</h1>
        <p className="landing-lede">
          {guest
            ? `You are invited to sit in on one room. Your screen will follow ${museum.family.grandma_name}'s showing.`
            : `Every photo and voice note your family sent is hung in a museum you can walk through. ${museum.family.grandma_name} will show you around.`}
        </p>
        {!guest && (
          <>
            <AvatarPick />
            <div className="field">
              <span className="label" id="lang-l">Language</span>
              <div className="seg" role="radiogroup" aria-labelledby="lang-l">
                {LANGS.map((l) => <button key={l.id} role="radio" aria-checked={language === l.id} onClick={() => setLanguage(l.id)}>{l.label}</button>)}
              </div>
            </div>
          </>
        )}
        <div className="row">
          <button className="btn btn-primary btn-lg" onClick={go} disabled={busy}>{guest ? 'Join the room' : 'Enter the museum'}</button>
        </div>
        <p className="muted" style={{ fontSize: 13 }}>Entering turns on sound. You can talk to the museum or use only the buttons and keys.</p>
      </section>
      <section className="landing-right" aria-hidden="true"><Facade /></section>
    </main>
  );
}
