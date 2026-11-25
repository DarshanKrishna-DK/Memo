/** Client-side showcase command matcher (PRD "Playback by voice"): no model call, runs on the live transcript.
 *  Word lists are the union across en / hi / kn, in native script AND Roman-script (Hinglish / Kanglish) spellings with
 *  common typos, so a code-mixed sentence or a spoken switch of language still works. */
import { useWorld } from '../state/worldStore';

export type Cmd = 'pause' | 'resume' | 'next' | 'back' | 'restart' | 'skip_voice' | 'faster' | 'slower' | 'narrated' | 'silent' | 'step_back' | 'stop' | 'skip';

const WORDS: Record<Cmd, string[]> = {
  pause: ['pause', 'pause it', 'puase', 'pasue', 'hold on', 'hold it', 'wait', 'ruko', 'ruk jao', 'ruk ja', 'ruk jaiye', 'rukiye', 'thehro', 'ek minute', 'nillu', 'konchem nillu', 'रुको', 'रुकिए', 'रुक जाओ', 'रुक जा', 'ठहरो', 'पॉज़', 'पॉज', 'ವಿರಾಮ', 'ನಿಲ್ಲು', 'ಸ್ವಲ್ಪ ನಿಲ್ಲು'],
  resume: ['resume', 'continue', 'play', 'go on', 'carry on', 'keep going', 'start playing', 'play it', 'chalao', 'chalu', 'chalu karo', 'chala', 'jaari rakho', 'aage badho', 'munduvarisu', 'hakku', 'play maadu', 'चलाओ', 'चालू करो', 'चालू', 'जारी रखो', 'आगे बढ़ो', 'शुरू करो', 'ಮುಂದುವರಿಸು', 'ಪ್ಲೇ', 'ಹಾಕು'],
  next: ['next', 'nxt', 'next one', 'next photo', 'next wala', 'next wali', 'agla', 'agla wala', 'agli', 'aage', 'aage wala', 'forward', 'mundhe', 'munde', 'mundina', 'ಮುಂದಿನ', 'ಮುಂದೆ', 'अगला', 'अगली', 'आगे', 'अगला वाला'],
  back: ['back', 'previous', 'prev', 'previous photo', 'go back', 'last one', 'pichla', 'pichhla', 'pichli', 'pichla wala', 'peeche', 'piche', 'hinde', 'hindina', 'hindhe', 'ಹಿಂದಿನ', 'ಹಿಂದೆ', 'पिछला', 'पिछली', 'पीछे', 'पिछला वाला'],
  restart: ['start over', 'restart', 'from the beginning', 'from start', 'play again', 'phir se', 'phir se shuru', 'fir se', 'fir se shuru', 'dobara', 'dobara shuru', 'shuru se', 'shuruwat se', 'matte', 'matte modalinda', 'matte shuru', 'modalinda', 'फिर से', 'फिर से शुरू', 'दोबारा', 'दोबारा शुरू', 'शुरू से', 'शुरुआत से', 'ಮತ್ತೆ', 'ಮತ್ತೆ ಶುರು', 'ಮೊದಲಿನಿಂದ'],
  skip_voice: ['skip voice notes', 'skip the voice notes', 'skip voice', 'voice notes skip', 'voice note chhodo', 'voice note skip karo', 'वॉइस नोट छोड़ो', 'आवाज़ वाले नोट छोड़ो', 'ಧ್ವನಿ ಟಿಪ್ಪಣಿ ಬಿಡು'],
  faster: ['faster', 'fast', 'speed up', 'go faster', 'jaldi', 'jaldi karo', 'jaldi chalao', 'tez', 'tez karo', 'tej', 'bega', 'bega maadu', 'जल्दी', 'जल्दी करो', 'तेज़', 'तेज', 'तेज़ करो', 'ವೇಗ', 'ಬೇಗ', 'ಬೇಗ ಮಾಡು'],
  slower: ['slower', 'slow', 'slow down', 'dheere', 'dheere karo', 'dhire', 'nidhana', 'nidhana maadu', 'धीरे', 'धीरे करो', 'धीमा', 'ನಿಧಾನ', 'ನಿಧಾನವಾಗಿ'],
  narrated: ['narrate', 'with narration', 'narrated', 'tell the story', 'kahani sunao', 'कहानी सुनाओ', 'ಕಥೆ ಹೇಳು'],
  silent: ['silent', 'no narration', 'without narration', 'mute grandma', 'bina awaaz', 'बिना आवाज़', 'ಮೌನ'],
  step_back: ['step back', 'exit', 'close the screen', 'leave the screen', 'peeche hato', 'piche hato', 'bahar aao', 'hinde sari', 'पीछे हटो', 'बाहर आओ', 'ಹಿಂದೆ ಸರಿ'],
  stop: ['stop', 'stp', 'stop talking', 'stop it', 'be quiet', 'quiet', 'shush', 'shh', 'chup', 'chup raho', 'chup kar', 'chup karo', 'bas', 'bas karo', 'bas kijiye', 'band karo', 'saaku', 'saaku maadu', 'summane iru', 'summaniru', 'nillisu', 'nillisi', 'चुप', 'चुप रहो', 'चुप करो', 'बस', 'बस करो', 'बंद करो', 'ಸಾಕು', 'ಸುಮ್ಮನಿರು', 'ನಿಲ್ಲಿಸು', 'ನಿಲ್ಲಿಸಿ'],
  skip: ['skip', 'skip it', 'skip this', 'chhodo', 'chodo', 'chhod do', 'bidu', 'छोड़ो', 'छोड़ दो', 'ಬಿಡು'],
};

/** Polite / address words that do not change the meaning ("next please", "ok bas ji", "grandma, next wala"). */
const FILLER_TOKENS = new Set(['please', 'plz', 'pls', 'ok', 'okay', 'now', 'the', 'it', 'a', 'ji', 'na', 'yaar', 'zara', 'thoda', 'kripya', 'ab', 'to', 'toh', 'grandma', 'granny', 'ammaji', 'dadi', 'nani', 'ajji', 'amma', 'hey', 'hi', 'bhi', 'hai', 'photo', 'wala', 'wali', 'sir', 'madam', 'दादी', 'नानी', 'अम्मा', 'जी', 'ज़रा', 'ಅಜ್ಜಿ', 'ಅಮ್ಮ']);

/** Lowercase, NFC, drop zero-width joiners and the Devanagari nukta (so ज़/ज and ड़/ड match), strip punctuation, split to tokens. */
export function tokens(s: string): string[] {
  return s.normalize('NFC').toLowerCase()
    .replace(/[​-‍⁠﻿़]/g, '')
    .replace(/[^\p{L}\p{M}\p{N}]+/gu, ' ')
    .trim().split(' ').filter(Boolean).map(squash);
}
/** Roman spellings stretch ("ruukooo", "aage", "saaku"): squash runs of the same letter so they compare equal. */
function squash(t: string): string { return /^[a-z]+$/.test(t) ? t.replace(/(.)\1+/g, '$1') : t; }

function lev1(a: string, b: string): boolean {
  if (a === b) return true;
  const la = a.length, lb = b.length;
  if (Math.abs(la - lb) > 1) return false;
  let i = 0;
  while (i < la && i < lb && a[i] === b[i]) i++;
  if (la === lb) return a.slice(i + 1) === b.slice(i + 1) || (a[i] === b[i + 1] && a[i + 1] === b[i] && a.slice(i + 2) === b.slice(i + 2));
  return la > lb ? a.slice(i + 1) === b.slice(i) : b.slice(i + 1) === a.slice(i);
}
/** Exact for short or non-Latin words (so "bus" never becomes "bas"); one typo allowed from 5 letters up. */
function same(a: string, b: string): boolean {
  if (a === b) return true;
  return a.length >= 5 && b.length >= 5 && /^[a-z]+$/.test(a) && /^[a-z]+$/.test(b) && a[0] === b[0] && lev1(a, b);
}

const COMPILED = (Object.entries(WORDS) as [Cmd, string[]][])
  .flatMap(([cmd, list]) => list.map((w) => ({ cmd, toks: tokens(w) })))
  .filter((p) => p.toks.length);

const MAX_TOKENS = 6;

/** Returns the command when the (short) utterance is a command phrase, else null so it goes to Grandma / the receptionist.
 *  Whole-word matching only, and the phrase must make up most of what was said, so "what is the next festival"
 *  or "the bus stopped" stay normal sentences. */
export function matchCommand(text: string): Cmd | null {
  const all = tokens(text);
  if (!all.length || all.length > MAX_TOKENS) return null;
  const content = all.filter((t) => !FILLER_TOKENS.has(t));
  if (!content.length) return null;
  let best: { cmd: Cmd; n: number } | null = null;
  for (const p of COMPILED) {
    const n = p.toks.length;
    if (n > all.length || (best && n <= best.n)) continue;
    for (let i = 0; i + n <= all.length; i++) {
      let ok = true;
      for (let j = 0; j < n; j++) if (!same(all[i + j], p.toks[j])) { ok = false; break; }
      if (ok) { best = { cmd: p.cmd, n }; break; }
    }
  }
  if (!best) return null;
  return best.n / content.length >= 0.6 ? best.cmd : null;
}

/** Commands that also make sense at the reception desk (there is no showcase there). */
export const ANYWHERE: Cmd[] = ['stop', 'pause'];

/** Runs a matched command on the shared store. Returns true if it did something. Voice has no private powers:
 *  every branch is a store action the buttons call too. */
export function runCommand(cmd: Cmd, hooks: { stopSpeech: () => void; resumeSpeech: () => void }): boolean {
  const s = useWorld.getState();
  switch (cmd) {
    case 'pause': s.setShowcase({ showcasePlaying: false }); hooks.stopSpeech(); return true;
    case 'resume': hooks.resumeSpeech(); s.setShowcase({ showcasePlaying: true }); return true;
    case 'next': s.nextItem(); return true;
    case 'back': s.prevItem(); return true;
    case 'restart': s.restartShowcase(); return true;
    case 'skip_voice': s.setShowcase({ skipVoiceNotes: true }); return true;
    case 'faster': s.setShowcase({ showcaseSpeed: Math.min(3, +(s.showcaseSpeed + 0.5).toFixed(1)) }); return true;
    case 'slower': s.setShowcase({ showcaseSpeed: Math.max(0.5, +(s.showcaseSpeed - 0.5).toFixed(1)) }); return true;
    case 'narrated': s.setShowcase({ showcaseNarrated: true }); return true;
    case 'silent': s.setShowcase({ showcaseNarrated: false }); hooks.stopSpeech(); return true;
    case 'stop': hooks.stopSpeech(); return true;
    case 'step_back':
      if (s.screenMode) s.setScreenMode(false); else if (s.seat) s.standUp();
      return true;
    case 'skip':
      if (s.mode === 'walking') { s.skipWalk(); return true; }
      s.nextItem(); return true;
  }
}
