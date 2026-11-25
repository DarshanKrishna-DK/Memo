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
