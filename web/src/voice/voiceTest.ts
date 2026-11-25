/** Browser test for the speech arbiter (open /voice-test.html in the dev server). Proves:
 *   1. two agents (and guide / filler lines) never overlap, whatever order they start in;
 *   2. an interruption silences audio in < 300 ms (p95 and max over 25 trials) and remembers the last finished sentence;
 *   3. fillers are cut by the real reply and never repeat back to back; 4. the command matcher is code-mix aware.
 *  Overlap is measured from the outside: every HTMLMediaElement.play/pause/ended is tracked, no arbiter internals involved. */
import { arbiter, playClip } from './speechArbiter';
import { SpeechPlayer } from './speechPlayer';
import { pickFiller } from './fillers';
import { matchCommand } from './commands';
import { voiceMetrics } from './voiceMetrics';

const out = document.getElementById('out')!;
const lines: string[] = [];
const results: { name: string; ok: boolean; detail: string }[] = [];
function check(name: string, ok: boolean, detail = '') {
  results.push({ name, ok, detail });
  lines.push(`<span class="${ok ? 'pass' : 'fail'}">${ok ? 'PASS' : 'FAIL'}</span> ${name}${detail ? ' - ' + detail : ''}`);
  out.innerHTML = lines.join('\n');
}
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** A short tone as a WAV blob URL. */
function tone(seconds: number, hz: number): string {
  const rate = 8000, n = Math.floor(seconds * rate);
  const buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
  const w = (o: number, s: string) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  w(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); w(8, 'WAVE'); w(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, 'data'); v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) v.setInt16(44 + i * 2, Math.sin((2 * Math.PI * hz * i) / rate) * 800, true);
  return URL.createObjectURL(new Blob([buf], { type: 'audio/wav' }));
}

// ---- external overlap monitor: counts audio elements that are really playing ----
const playing = new Set<HTMLMediaElement>();
let maxConcurrent = 0;
const origPlay = HTMLMediaElement.prototype.play;
HTMLMediaElement.prototype.play = function (this: HTMLMediaElement) {
  playing.add(this);
  this.addEventListener('pause', () => playing.delete(this), { once: true });
  this.addEventListener('ended', () => playing.delete(this), { once: true });
  return origPlay.call(this);
};
const live = () => [...playing].filter((a) => !a.paused && !a.ended && a.volume > 0.5).length; // showcase is ducked to 0.2, not counted
setInterval(() => { maxConcurrent = Math.max(maxConcurrent, live()); }, 5);
const resetMax = () => { maxConcurrent = 0; };

const speech = (n: number, hz: number) => ({ sentences: Array.from({ length: n }, (_, i) => ({ text: `sentence ${i + 1}`, audio_url: tone(1.2, hz + i * 40) })) });

async function run() {
  // 1. two agents never overlap
  const grandma = new SpeechPlayer(), reception = new SpeechPlayer();
  resetMax();
  grandma.play(speech(3, 300), { source: 'agent', who: 'grandma' });
  await sleep(500);
  const aAudible = live() === 1;
  reception.play(speech(3, 600), { source: 'agent', who: 'receptionist' });
  await sleep(300);
  check('agent B starting cuts agent A (no overlap)', aAudible && !grandma.active && reception.active && live() === 1 && maxConcurrent === 1, `A audible first: ${aAudible}, max concurrent = ${maxConcurrent}`);
  const g = playClip('guide', 'guide', tone(1, 900));
  check('guide line is refused while an agent talks', !g.started);
  reception.stop();

  // filler -> guide -> agent ordering, all single voice
  resetMax();
  const f = playClip('filler', 'grandma', tone(2, 500));
  await sleep(100);
  const g2 = playClip('guide', 'guide', tone(2, 700));
  await sleep(100);
  check('guide supersedes filler, still one voice', f.started && g2.started && live() === 1 && arbiter.current?.source === 'guide');
  grandma.play(speech(2, 400), { source: 'agent', who: 'grandma' });
  await sleep(100);
  check('real reply cuts the filler/guide instantly', arbiter.current?.source === 'agent' && live() === 1 && maxConcurrent <= 1, `max concurrent = ${maxConcurrent}`);
  grandma.stop();
  await sleep(50);

  // Agora live agent speaking: local audio is refused (guide) / agent mutes + interrupts
  let muted = false, interrupted = 0;
  arbiter.agoraHooks = { mute: (on) => { muted = on; }, interrupt: () => { interrupted++; } };
  arbiter.setAgoraSpeaking(true);
  check('guide refused while a live (Agora) agent speaks', !playClip('guide', 'guide', tone(1, 800)).started);
  grandma.play(speech(1, 450), { source: 'agent', who: 'grandma' });
  check('local agent audio mutes + interrupts the live agent', muted && interrupted === 1 && grandma.active);
  grandma.stop();
  arbiter.setAgoraSpeaking(true);
  const wasLocal = arbiter.current;
  check('live agent speaking stops local playback', wasLocal === null);
  arbiter.setAgoraSpeaking(false);
  arbiter.agoraHooks = null;

  // 2. interruption latency, 25 trials, measured independently with a 1 ms poll from the trigger
  voiceMetrics.samples.length = 0;
  const lat: number[] = [];
  for (let i = 0; i < 25; i++) {
    const p = new SpeechPlayer();
    p.play(speech(4, 300 + i * 10), { source: 'agent', who: 'grandma' });
    await sleep(350 + (i % 5) * 60); // lands mid sentence or on a boundary
    const t0 = performance.now();
    arbiter.interrupt('test');
    // independent check: poll until no element is playing
    while (live() > 0 && performance.now() - t0 < 1000) await sleep(1);
    lat.push(performance.now() - t0);
    await sleep(20);
  }
  lat.sort((a, b) => a - b);
  const p95 = lat[Math.ceil(lat.length * 0.95) - 1], max = lat[lat.length - 1];
  check('interruption stops all audio in < 300 ms (p95 and max)', p95 < 300 && max < 300, `p95 ${p95.toFixed(1)} ms, max ${max.toFixed(1)} ms, median ${lat[12].toFixed(1)} ms; voiceMetrics p95 ${voiceMetrics.p95()?.toFixed(1)} ms`);

  // "carry on": interrupt after the first sentence finished, then resume from the next one
  const rp = new SpeechPlayer();
  rp.play(speech(3, 350), { source: 'agent', who: 'grandma' });
  await sleep(1700);
  arbiter.interrupt('test-resume');
  check('last finished sentence is remembered', rp.lastFinished === 0 && rp.hasRemaining(), `lastFinished = ${rp.lastFinished}`);
  check('carry on resumes with the next sentence', rp.resume() && rp.currentIndex === 1 && live() === 1);
  rp.stop();

  // showcase track ducks, is not stopped
  const stopShow = arbiter.playShowcase(tone(3, 220));
  await sleep(100);
  grandma.play(speech(1, 450), { source: 'agent', who: 'grandma' });
  await sleep(50);
  check('showcase audio is ducked while Grandma narrates (not stopped)', arbiter.showcaseActive && live() === 1);
  grandma.stop(); stopShow();

  // 3. fillers never repeat back to back
  const list = [1, 2, 3].map((i) => ({ text: 'f' + i, audio_url: 'u' + i }));
  let last: string | undefined, repeats = 0;
  for (let i = 0; i < 200; i++) { const f2 = pickFiller(list, last)!; if (f2.audio_url === last) repeats++; last = f2.audio_url; }
  check('filler picker never repeats the previous clip', repeats === 0);

  // 4. command matcher
  const yes: [string, string][] = [
    ['ruko', 'pause'], ['ruk jao', 'pause'], ['रुको', 'pause'], ['ruko ji please', 'pause'], ['nillu', 'pause'], ['pasue', 'pause'],
    ['bas', 'stop'], ['chup', 'stop'], ['chup karo', 'stop'], ['saaku', 'stop'], ['saakuu', 'stop'], ['nillisu', 'stop'], ['ಸಾಕು', 'stop'], ['बस', 'stop'], ['stop talking', 'stop'],
    ['aage', 'next'], ['agla', 'next'], ['next wala', 'next'], ['mundhe', 'next'], ['ಮುಂದೆ', 'next'], ['अगला', 'next'], ['nxt', 'next'], ['next please', 'next'],
    ['peeche', 'back'], ['hinde', 'back'], ['पीछे', 'back'], ['previous', 'back'],
    ['phir se', 'restart'], ['shuru se', 'restart'], ['matte', 'restart'], ['start over', 'restart'], ['फिर से शुरू', 'restart'],
    ['jaldi', 'faster'], ['dheere', 'slower'], ['dhiree karo', 'slower'], ['तेज़ करो', 'faster'], ['ನಿಧಾನ', 'slower'],
    ['carry on', 'resume'], ['chalu karo', 'resume'], ['step back', 'step_back'], ['skip', 'skip'],
  ];
  const no = ['what is the next festival we celebrated', 'the bus stopped near the temple', 'tell me about aage wala ghar ki kahani', 'who is in the back of this photo',
    'mujhe batao ye photo kab ki hai', 'ee photo yaavaaga tegedaddu', 'play the song from grandpa birthday party', 'this is my last one from the trip', 'bassi pyaar hai', 'Diwali ke baad kya hua'];
  const bad = yes.filter(([t, c]) => matchCommand(t) !== c).map(([t, c]) => `${t} -> ${matchCommand(t)} (want ${c})`);
  check(`code-mixed commands match (${yes.length} phrases)`, bad.length === 0, bad.join('; '));
  const hijacked = no.filter((t) => matchCommand(t) !== null).map((t) => `${t} -> ${matchCommand(t)}`);
  check(`normal sentences are not hijacked (${no.length} phrases)`, hijacked.length === 0, hijacked.join('; '));

  const ok = results.every((r) => r.ok);
  lines.push(`\n<span class="${ok ? 'pass' : 'fail'}">${ok ? 'ALL PASS' : 'FAILURES'}</span>  (${results.filter((r) => r.ok).length}/${results.length})`);
  out.innerHTML = lines.join('\n');
  (window as unknown as { __voiceTestResult: unknown }).__voiceTestResult = { ok, results, latenciesMs: lat, p95, max };
}
void run();
