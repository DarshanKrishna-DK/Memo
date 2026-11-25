import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type RefObject } from 'react';
import { useWorld } from '../../state/worldStore';
import { Modal, Orb } from '../../ui/common';
import { BrandMark } from '../../ui/Pixels';
import { CastPortrait, PixelGlyph, type CastId, type GlyphName } from '../../ui/pixel/Sprites';
import { ArrowIcon, Dither, HeroSky, OrnamentRule, goTo } from './Bits';
import { CALLOUT, FLOOR_Y, HeroMuseum } from './HeroMuseum';
import { SiteFooter } from './SiteFooter';
import { SignInHelp } from './SignInHelp';
import { QR, botUrl, useBot } from './bot';
import '../../styles/landing.css';

const NAV = [
  { id: 'how', label: 'How it works' },
  { id: 'voice', label: 'Languages' },
  { id: 'features', label: 'Features' },
  { id: 'cast', label: 'The cast' },
  { id: 'privacy', label: 'Privacy' },
  { id: 'faq', label: 'FAQ' },
];

const STEPS = [
  { title: 'Send it on Telegram', text: 'A text, a voice note or a photo to the Memo bot. Photos sent together count as one memory. If the date is unclear, the bot asks one tap-to-answer question, and the memory waits safely in the Attic until you answer.' },
  { title: 'The museum builds itself', text: 'Every year becomes a floor and every month a room, twelve doors to a floor. Nobody sorts or captions anything. A month with nothing in it keeps its door shut and puts up a cheeky board.' },
  { title: 'Walk in and listen', text: 'Take the lift to a year, sit down in a month’s theater, and Grandma tells its story in your language. Interrupt her any time to ask who, when or why.' },
];

const DESK_TOOLS = [
  { name: 'create_event', what: 'Adds an event such as Diwali 2026 and places it by its year and month.' },
  { name: 'query_gallery', what: 'Finds photos by date, size, camera or folder, and reads back the count.' },
  { name: 'import_gallery', what: 'Imports them after you say yes. Duplicates are skipped.' },
  { name: 'plan_route', what: 'Turns “last year’s Holi” into a floor and a door, then the guide robot walks you there.' },
  { name: 'change_setting', what: 'Language, captions, narration on or off.' },
];

interface Line { who: 'you' | 'desk'; text: string }
const LANG_TABS: { id: string; label: string; lang: string; lines: Line[] }[] = [
  {
    id: 'en', label: 'English', lang: 'en', lines: [
      { who: 'you', text: 'I want to add a new festival called Diwali.' },
      { who: 'desk', text: 'Which year and month was that?' },
      { who: 'you', text: 'November 2026. And add the ones with my dad in them.' },
      { who: 'desk', text: 'Diwali 2026 is added, in the November room. I can’t recognise faces, but I can choose photos by date, size, camera or folder.' },
    ],
  },
  {
    id: 'hinglish', label: 'Hinglish', lang: 'hi-Latn', lines: [
      { who: 'you', text: 'Kal ki saari photos Diwali 2026 mein daal do.' },
      { who: 'desk', text: '23 November ki 38 photos mili, 112 MB. Diwali 2026 mein add kar doon?' },
      { who: 'you', text: 'Haan, kar do.' },
      { who: 'desk', text: 'Ho gaya. 38 photos ab Diwali 2026 mein hain, November room mein.' },
    ],
  },
  {
    id: 'kanglish', label: 'Kanglish', lang: 'kn-Latn', lines: [
      { who: 'you', text: 'Last year Holi room ge karkond hogi.' },
      { who: 'desk', text: 'Sari! Holi 2025 March room alli ide. Guide robot nimmanna karkond hogatte.' },
      { who: 'you', text: 'Skip maadi.' },
      { who: 'desk', text: 'Sari, neevu March room alli kootkondiddeera.' },
    ],
  },
  {
    id: 'hi', label: 'हिन्दी', lang: 'hi', lines: [
      { who: 'you', text: 'मुझे मार्च 2025 का कमरा दिखाओ।' },
      { who: 'desk', text: 'चलिए, गाइड रोबोट आपको मार्च 2025 के कमरे तक ले जाएगा।' },
    ],
  },
  {
    id: 'kn', label: 'ಕನ್ನಡ', lang: 'kn', lines: [
      { who: 'you', text: 'ದೀಪಾವಳಿ 2026 ಕೋಣೆಗೆ ಕರೆದುಕೊಂಡು ಹೋಗಿ.' },
      { who: 'desk', text: 'ಸರಿ, ಗೈಡ್ ರೋಬೋಟ್ ನಿಮ್ಮನ್ನು ನವೆಂಬರ್ ಕೋಣೆಗೆ ಕರೆದುಕೊಂಡು ಹೋಗುತ್ತದೆ.' },
    ],
  },
];

const FEATURES: { glyph: GlyphName; title: string; text: string; tag: string }[] = [
  { glyph: 'bell', title: 'Robot receptionist', tag: 'Lobby', text: 'Ask at the desk: add an event, import photos from a date, take me to a room. Count and size are read back before anything is imported.' },
  { glyph: 'flag', title: 'Guide robot', tag: 'Lobby to room', text: '“Follow me.” It rides the lift with you and walks you to the door. Skip it with a tap, a key, or by saying “skip”.' },
  { glyph: 'screen', title: 'Grandma’s theater', tag: 'Every open room', text: 'Four seats face a big screen. Sit down and the month’s photos, notes and voice notes play while Grandma tells the story.' },
  { glyph: 'phone', title: 'Invite by a phone call', tag: 'Guests', text: '“Invite Priya to this room.” Grandma confirms aloud, a phone agent calls her, and if she says yes she takes the seat beside you, watching the same photo.' },
  { glyph: 'film', title: 'Reels of a month', tag: 'Video', text: 'Turn a month or an event into a video: photos with a slow zoom and captions, voice notes in their place, Grandma narrating if you like. Wide or vertical.' },
  { glyph: 'sparkle', title: 'Blurry photo cleanup', tag: 'Tidy up', text: 'Memo finds the shaky, out-of-focus shots in a month and lets you choose which to delete. Nothing goes without your say.' },
  { glyph: 'speech', title: 'Your languages', tag: 'Voice', text: 'Talk in English, Hindi or Kannada, or mix them the way you do at home. Subtitles show every line.' },
  { glyph: 'grid', title: '2D mode for any phone', tag: 'Light', text: 'Old phone or no 3D? The same floors and rooms as a simple grid, with every action as a button or a key.' },
];

const CAST: { id: CastId; name: string; where: string; says: string; knows: string }[] = [
  { id: 'receptionist', name: 'The receptionist', where: 'At the desk in the lobby', says: '“Hello! Add a memory, find photos, or go to a room?”', knows: 'Knows the museum’s floors, rooms, events and photo dates. Not what is inside your memories.' },
  { id: 'guide', name: 'The guide robot', where: 'From the lobby to your room', says: '“Follow me.”', knows: 'Knows the way and a few recorded lines. No AI, so it costs nothing to run.' },
  { id: 'grandma', name: 'Grandma', where: 'In the theater, in a saree', says: '“November 2025 has eleven memories, three of them voice notes. Shall I tell you?”', knows: 'Knows only what your family recorded. General festival facts are labelled as general. Ajji in Kannada, Dadi or Nani in Hindi.' },
];

const PRIVACY = [
  ['No public pages.', 'The museum opens only from a sign-in link the bot sends you. It works once and expires in 15 minutes.'],
  ['Signed links.', 'Photos and voice notes are served through short-lived signed links, never a public address.'],
  ['Yours to take.', 'Send /export for everything, any time. Deleting a family removes its records and media.'],
  ['No face recognition.', 'Photos of children stay inside the family.'],
  ['Microphone only while you talk.', 'A visible dot shows when it is listening.'],
  ['Guests hear little.', 'Until they join, a phone guest hears only the host’s name, the event and the month.'],
  ['Sarcasm on empty rooms only.', 'Any room can be closed with care, and the jokes can be switched off.'],
];

const FAQ: { q: string; a: string; signin?: boolean }[] = [
  { q: 'Do I need to install anything?', a: 'No. Memories go in through Telegram, which your family already uses. The museum opens in the browser on a phone or a laptop.' },
  { q: 'How do I sign in?', a: 'Send /museum to the Memo bot. It replies with a private button that opens your museum, already signed in.', signin: true },
  { q: 'What if the bot can’t tell when something happened?', a: 'It asks one question with tap buttons: which year, which month. Until you answer, the memory waits in the Attic. Nothing is dropped.' },
  { q: 'Can Grandma make things up about us?', a: 'No. Names, dates and counts come straight from what your family recorded, and she says so when something isn’t there. If you ask about a festival in general, she tells you that part isn’t from your memories.' },
  { q: 'Which languages work?', a: 'Grandma and the receptionist speak English, Hindi and Kannada. The receptionist also follows Hinglish and Kanglish, so you can talk the way you do at home.' },
  { q: 'Can relatives in another city watch with us?', a: 'Yes. Ask Grandma to invite them. A phone agent calls, and if they accept they get a link, no account needed, and sit in the theater beside you. Their screen follows yours.' },
  { q: 'My phone is old. Will it run?', a: 'Switch to 2D mode: the same floors and rooms as a grid, light enough for any phone. Everything also works with buttons and keys instead of voice.' },
];

function useNavState(scroller: RefObject<HTMLDivElement>) {
  const [solid, setSolid] = useState(false);
  const [hidden, setHidden] = useState(false);
  const last = useRef(0);
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const on = () => {
      const y = el.scrollTop;
      setSolid(y > 24);
      if (y < 160 || y < last.current - 4) setHidden(false);
      else if (y > last.current + 4) setHidden(true);
      last.current = y;
    };
    on();
    el.addEventListener('scroll', on, { passive: true });
    return () => el.removeEventListener('scroll', on);
  }, [scroller]);
  return { solid, hidden };
}

export function LandingPage() {
  const bot = useBot();
  const link = botUrl(bot);
  const authError = useWorld((s) => s.authError);
  const scroller = useRef<HTMLDivElement>(null);
  const { solid, hidden } = useNavState(scroller);
  const [signin, setSignin] = useState(!!authError);
  const [menu, setMenu] = useState(false);
  const [tab, setTab] = useState(0);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const openSignin = useCallback(() => { setMenu(false); setSignin(true); }, []);
  const closeSignin = useCallback(() => setSignin(false), []);
  const closeMenu = useCallback(() => setMenu(false), []);
  const jump = (id: string) => { setMenu(false); window.setTimeout(() => goTo(id), 0); };

  const onTabKey = (e: KeyboardEvent) => {
    const n = LANG_TABS.length;
    let next = -1;
    if (e.key === 'ArrowRight') next = (tab + 1) % n;
    else if (e.key === 'ArrowLeft') next = (tab - 1 + n) % n;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = n - 1;
    if (next < 0) return;
    e.preventDefault();
    setTab(next);
    tabRefs.current[next]?.focus();
  };
  const active = LANG_TABS[tab];

  return (
    <div className="lp" ref={scroller}>
      <a className="lp-skip" href="#lp-main">Skip to content</a>
      <header className={`lp-nav night${solid ? ' is-solid' : ''}${hidden ? ' is-hidden' : ''}`}>
        <div className="lp-nav-inner">
          <button type="button" className="brand lp-brand-btn" onClick={() => scroller.current?.scrollTo({ top: 0 })} aria-label="Memo, back to top">
            <BrandMark size={30} /><span className="brand-word">Memo</span>
          </button>
          <nav className="lp-nav-links" aria-label="Sections">
            {NAV.map((n) => <button key={n.id} type="button" className="lp-nav-link" onClick={() => jump(n.id)}>{n.label}</button>)}
          </nav>
          <div className="lp-nav-end">
            <button type="button" className="btn btn-ghost btn-sm lp-signin-btn" onClick={openSignin}>Sign in</button>
            <a className="btn btn-primary btn-sm lp-nav-cta" href={link} target="_blank" rel="noreferrer">Open the Telegram bot</a>
            <button type="button" className="btn btn-sm lp-menu-btn" onClick={() => setMenu(true)} aria-haspopup="dialog">Menu</button>
          </div>
        </div>
      </header>

      <main id="lp-main">
        {/* ── Hero ── */}
        <section className="lp-hero" aria-labelledby="lp-hero-title">
          <HeroSky />
          <div className="lp-hero-inner">
            <figure className="lp-hero-figure" role="img" aria-label="The Memo museum cut open: three floors for 2024, 2025 and 2026 with twelve month doors each, a lift moving between floors, a lobby with the reception desk, and February 2026's door shut with a board. A paper plane drops a new memory into a room and its door opens.">
              <div className="lp-hero-art">
                <HeroMuseum />
                <div className="lp-callout" style={{ left: `${CALLOUT.x * 100}%`, height: `${CALLOUT.y * 100}%` }} aria-hidden="true">
                  <span className="lp-callout-board"><b>February 2026</b> Nothing happened here. Or nobody told me.</span>
                </div>
                {['Lobby', '2024', '2025', '2026'].map((label, f) => (
                  <span key={label} className={'lp-floor-tag' + (f === 0 ? ' is-lobby' : '')} style={{ top: `${FLOOR_Y[f] * 100}%` }} aria-hidden="true">{label}</span>
                ))}
              </div>
            </figure>
            <div className="lp-hero-copy">
              <p className="lp-kicker lp-enter" style={{ ['--d' as string]: '0.05s' }}>The family memory museum</p>
              <h1 id="lp-hero-title" className="lp-wordmark lp-enter" style={{ ['--d' as string]: '0.15s' }}>
                <span className="lp-wordmark-text" data-text="Memo">Memo</span>
              </h1>
              <p className="lp-hero-tag lp-enter" style={{ ['--d' as string]: '0.25s' }}>Send it. Walk in. Listen.</p>
              <div className="lp-enter" style={{ ['--d' as string]: '0.32s' }}><OrnamentRule /></div>
              <p className="lp-hero-sub lp-enter" style={{ ['--d' as string]: '0.4s' }}>
                Your family sends photos, voice notes and stories to a Telegram bot. Memo hangs them in a 3D museum, a floor for every year and a room for every month, and Grandma tells you the story.
              </p>
              <div className="lp-hero-actions lp-enter" style={{ ['--d' as string]: '0.48s' }}>
                <a className="btn btn-primary btn-lg" href={link} target="_blank" rel="noreferrer">Open the Telegram bot</a>
                <button type="button" className="btn btn-lg lp-btn-secondary" onClick={openSignin}>Sign in to your museum</button>
              </div>
              <button type="button" className="lp-text-link lp-enter" style={{ ['--d' as string]: '0.56s' }} onClick={() => goTo('how')}>
                How it works <ArrowIcon size={12} />
              </button>
            </div>
          </div>
          <div className="lp-ground" aria-hidden="true" />
        </section>

        {/* ── How it works ── */}
        <section id="how" className="lp-band paper lp-dots" aria-labelledby="how-title">
          <div className="lp-wrap">
            <h2 id="how-title" className="lp-h2">A museum that <span className="lp-accent">fills itself.</span></h2>
            <div className="lp-about">
              <div className="lp-dialog">
                <div className="lp-dialog-head">
                  <span className="lp-portrait"><CastPortrait who="grandma" px={4} /></span>
                  <div>
                    <p className="lp-kicker">Ajji</p>
                    <p className="lp-dialog-sub">Your guide in the theater</p>
                  </div>
                </div>
                <p className="lp-dialog-body">
                  Send me anything: a photo from the puja, a voice note, two lines about who fell asleep during the film. I’ll hang it in the right month. When you come in and sit down, I’ll tell you the story, and only what your family told me.
                </p>
              </div>
              <figure className="lp-chat night" aria-label="Example Telegram chat with the Memo bot">
                <div className="lp-chat-head"><BrandMark size={22} /><span>@{bot}</span><span className="lp-chat-status">bot</span></div>
                <div className="lp-chat-body">
                  <div className="lp-msg lp-msg--me">
                    <span className="lp-photo" aria-hidden="true"><span /><span /><span /></span>
                    <span>Diwali at home. Dad finally gave Chinnu the bike.</span>
                  </div>
                  <div className="lp-msg lp-msg--me lp-msg--voice" aria-label="Voice note, 42 seconds">
                    <span className="lp-play" aria-hidden="true" />
                    <span className="lp-wave" aria-hidden="true">{Array.from({ length: 22 }, (_, i) => <i key={i} style={{ height: `${4 + ((i * 7) % 11) * 1.4}px` }} />)}</span>
                    <span className="lp-mono">0:42</span>
                  </div>
                  <div className="lp-msg lp-msg--bot">
                    <span>Saved. <strong>Diwali, Nov 2025: Dad’s bike</strong></span>
                    <span className="lp-msg-btns" aria-hidden="true"><span>Wrong date</span><span>Wrong festival</span><span>Delete</span></span>
                  </div>
                  <div className="lp-msg lp-msg--bot">
                    <span>Keep the voice, the words, or both?</span>
                    <span className="lp-msg-btns" aria-hidden="true"><span>Voice</span><span>Words</span><span>Both</span></span>
                  </div>
                </div>
              </figure>
            </div>

            <ol className="lp-steps">
              {STEPS.map((s, i) => (
                <li key={s.title} className="lp-step">
                  <span className="lp-step-n" aria-hidden="true">{i + 1}</span>
                  <h3 className="lp-step-title">{s.title}</h3>
                  <p>{s.text}</p>
                </li>
              ))}
            </ol>

            <dl className="lp-stats">
              <div className="lp-stat"><dt>Rooms on every floor</dt><dd>12</dd></div>
              <div className="lp-stat"><dt>Ways to send a memory</dt><dd>3</dd></div>
              <div className="lp-stat"><dt>Grandma’s languages</dt><dd>3</dd></div>
              <div className="lp-stat"><dt>Seats in each theater</dt><dd>4</dd></div>
              <div className="lp-stat"><dt>Albums to sort</dt><dd>0</dd></div>
            </dl>
          </div>
        </section>

        <Dither from="paper" to="night" />

        {/* ── Speak your way ── */}
        <section id="voice" className="lp-band night lp-sky-band" aria-labelledby="voice-title">
          <div className="lp-wrap lp-split">
            <div>
              <h2 id="voice-title" className="lp-h2">Speak your <span className="lp-accent">way.</span></h2>
              <p className="lp-lede">
                Walk up to the desk and say what you want, however you’d say it at home. The receptionist picks the right action, checks it, and tells you out loud what she did. If she can’t do something, she says so.
              </p>
              <ul className="lp-tools">
                {DESK_TOOLS.map((t) => <li key={t.name}><code className="lp-tool-chip">{t.name}</code><span>{t.what}</span></li>)}
              </ul>
            </div>
            <div className="lp-console">
              <div className="lp-console-head">
                <span className="lp-console-title">Reception desk</span>
                <span className="lp-kicker"><span className="lp-live" aria-hidden="true" />Listening</span>
              </div>
              <div className="lp-tabs" role="tablist" aria-label="Example language" onKeyDown={onTabKey}>
                {LANG_TABS.map((l, i) => (
                  <button key={l.id} ref={(el) => { tabRefs.current[i] = el; }} type="button" role="tab" id={`lp-tab-${l.id}`} aria-controls="lp-tabpanel"
                    aria-selected={tab === i} tabIndex={tab === i ? 0 : -1} onClick={() => setTab(i)}>{l.label}</button>
                ))}
              </div>
              <div id="lp-tabpanel" className="lp-convo" role="tabpanel" aria-labelledby={`lp-tab-${active.id}`} lang={active.lang} key={active.id}>
                {active.lines.map((l, i) => (
                  <div key={i} className={`lp-line lp-line--${l.who}`}>
                    {l.who === 'desk' && <span className="lp-line-orb" aria-hidden="true"><Orb state="composing" size={20} label="" /></span>}
                    <p><span className="lp-line-who" lang="en">{l.who === 'you' ? 'You' : 'Receptionist'}</span>{l.text}</p>
                  </div>
                ))}
              </div>
              <p className="lp-console-foot">English · हिन्दी · ಕನ್ನಡ · Hinglish · Kanglish</p>
            </div>
          </div>
        </section>

        <Dither from="night" to="paper" />

        {/* ── Features ── */}
        <section id="features" className="lp-band paper" aria-labelledby="features-title">
          <div className="lp-wrap">
            <h2 id="features-title" className="lp-h2">Everything in the <span className="lp-accent">building.</span></h2>
            <p className="lp-lede">Each part does one job, and every spoken request has a button that does the same thing.</p>
            <ul className="lp-features">
              {FEATURES.map((f) => (
                <li key={f.title} className="lp-feature">
                  <span className="lp-feature-art" aria-hidden="true"><PixelGlyph name={f.glyph} size={44} main="#a8e27c" hi="#f3f1e2" /></span>
                  <span className="lp-chip">{f.tag}</span>
                  <h3 className="lp-feature-title">{f.title}</h3>
                  <p>{f.text}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* ── Cast ── */}
        <section id="cast" className="lp-band paper lp-dots" aria-labelledby="cast-title">
          <div className="lp-wrap">
            <h2 id="cast-title" className="lp-h2">Meet the <span className="lp-accent">cast.</span></h2>
            <ul className="lp-cast">
              {CAST.map((c) => (
                <li key={c.id} className="lp-cast-card">
                  <span className={`lp-cast-stage lp-cast-stage--${c.id}`} aria-hidden="true"><CastPortrait who={c.id} px={8} /></span>
                  <div className="lp-cast-body">
                    <p className="lp-kicker">{c.where}</p>
                    <h3 className="lp-cast-name">{c.name}</h3>
                    <p className="lp-cast-says">{c.says}</p>
                    <p className="lp-cast-knows">{c.knows}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* ── Privacy ── */}
        <section id="privacy" className="lp-band paper" aria-labelledby="privacy-title">
          <div className="lp-wrap lp-split">
            <div>
              <h2 id="privacy-title" className="lp-h2">Private by <span className="lp-accent">default.</span></h2>
              <p className="lp-lede">These are family photos and the voices of elders. Nothing is public, and everything can leave with you.</p>
            </div>
            <ul className="lp-rules">
              {PRIVACY.map(([b, t]) => <li key={b}><strong>{b}</strong> {t}</li>)}
            </ul>
          </div>
        </section>

        <Dither from="paper" to="night" />

        {/* ── FAQ ── */}
        <section id="faq" className="lp-band night" aria-labelledby="faq-title">
          <div className="lp-wrap lp-split">
            <div>
              <h2 id="faq-title" className="lp-h2">Questions, <span className="lp-accent">answered.</span></h2>
              <p className="lp-lede">Anything else, ask the bot. It answers <kbd>/help</kbd>.</p>
            </div>
            <div className="lp-faq">
              {FAQ.map((f) => (
                <details key={f.q} className="lp-faq-item">
                  <summary><span>{f.q}</span><span className="lp-faq-sign" aria-hidden="true" /></summary>
                  <div className="lp-faq-a">
                    <p>{f.a}</p>
                    {f.signin && <button type="button" className="lp-text-link" onClick={openSignin}>Show me how <ArrowIcon size={12} /></button>}
                  </div>
                </details>
              ))}
            </div>
          </div>
        </section>

        {/* ── Final CTA ── */}
        <section className="lp-band night lp-cta-band" aria-labelledby="cta-title">
          <div className="lp-wrap">
            <div className="lp-cta">
              <div className="lp-cta-copy">
                <h2 id="cta-title" className="lp-h2">Send the first memory <span className="lp-accent">tonight.</span></h2>
                <p className="lp-lede">Open the bot, tap Start, and send one photo with a line about it. Its room opens on its own.</p>
                <div className="lp-hero-actions lp-cta-actions">
                  <a className="btn btn-primary btn-lg" href={link} target="_blank" rel="noreferrer">Open the Telegram bot</a>
                  <button type="button" className="btn btn-lg lp-btn-secondary" onClick={openSignin}>Sign in</button>
                </div>
              </div>
              <div className="lp-cta-qr">
                <QR text={link} size={148} />
                <span className="lp-kicker">Scan with your phone</span>
              </div>
            </div>
          </div>
        </section>
      </main>

      <SiteFooter bot={bot} onSignin={openSignin} onJump={jump} />

      {signin && <SignInHelp bot={bot} onClose={closeSignin} />}
      {menu && (
        <Modal title="Menu" onClose={closeMenu}>
          <nav className="lp-menu" aria-label="Sections">
            {NAV.map((n) => <button key={n.id} type="button" className="lp-menu-link" onClick={() => jump(n.id)}>{n.label}<ArrowIcon /></button>)}
          </nav>
          <div className="row">
            <a className="btn btn-primary" href={link} target="_blank" rel="noreferrer">Open the Telegram bot</a>
            <button type="button" className="btn" onClick={openSignin}>Sign in</button>
          </div>
        </Modal>
      )}
    </div>
  );
}
