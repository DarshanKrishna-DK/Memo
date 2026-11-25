/** Browsers need a click before audio plays. Called from the "Enter the museum" click. */
let ctx: AudioContext | null = null;
export async function unlockAudio(): Promise<void> {
  try {
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    ctx = ctx ?? new AC();
    await ctx.resume();
    const b = ctx.createBuffer(1, 1, 22050);
    const s = ctx.createBufferSource();
    s.buffer = b; s.connect(ctx.destination); s.start(0);
    const a = new Audio();
    a.muted = true;
    a.src = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=';
    await a.play().catch(() => undefined);
  } catch { /* audio unavailable: text and buttons still work */ }
}

/** Grandma / receptionist / guide speech is quiet next to other web audio. Route a speech <audio> element through
 *  gain 1.6 into a fast compressor (a soft limiter) so it is louder without clipping. Only once the AudioContext
 *  runs (after the Enter click): a media element wired into a suspended context would be silent. Same-origin media
 *  only (signed /media URLs are relative); cross-origin media would come out silent from WebAudio. */
const SPEECH_GAIN = 1.6;
const boosted = new WeakSet<HTMLMediaElement>();
export function boostSpeech(el: HTMLMediaElement, url: string): void {
  el.volume = 1;
  if (boosted.has(el) || !ctx) return;
  if (ctx.state !== 'running') { void ctx.resume().catch(() => undefined); return; }
  try { if (new URL(url, location.href).origin !== location.origin) return; } catch { return; }
  try {
    const src = ctx.createMediaElementSource(el);
    const gain = ctx.createGain();
    gain.gain.value = SPEECH_GAIN;
    const lim = ctx.createDynamicsCompressor();
    lim.threshold.value = -6; lim.knee.value = 4; lim.ratio.value = 12; lim.attack.value = 0.003; lim.release.value = 0.15;
    src.connect(gain).connect(lim).connect(ctx.destination);
    boosted.add(el);
  } catch { /* already wired or unsupported: plays at plain full volume */ }
}
/** Keep a boosted element audible: a context the browser suspended (tab switch, phone call) must be resumed. */
export function keepSpeechAlive(el: HTMLMediaElement): void {
  if (boosted.has(el) && ctx && ctx.state !== 'running') void ctx.resume().catch(() => undefined);
}
