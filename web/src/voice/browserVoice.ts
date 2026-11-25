/** Browser-only voice path (used when /api/voice/start returns 503): MediaRecorder push-to-talk or hands-free,
 *  with VAD barge-in from an AnalyserNode. Speech detected -> onSpeechStart fires within ~60-90 ms so the caller
 *  can stop playback long before the 300 ms budget. */

export interface BrowserVoiceOpts {
  language: string;
  onLevel: (l: number) => void;
  onSpeechStart: () => void;
  onUtterance: (blob: Blob) => void;
  onInterim: (text: string) => void;
  onError: (msg: string) => void;
}

type SRCtor = new () => {
  lang: string; continuous: boolean; interimResults: boolean; onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onend: (() => void) | null; onerror: (() => void) | null; start(): void; stop(): void; abort(): void;
};

export class BrowserVoice {
  private stream: MediaStream | null = null;
  private ctx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private rec: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private loop: number | null = null;
  private floor = 0.008;
  private loudFrames = 0;
  private lastLoud = 0;
  private recStart = 0;
  private forced = false;
  private playing = false;
  private sr: InstanceType<SRCtor> | null = null;
  private srOn = false;
  live = false;

  /** True while the user is talking (recording and loud within the last 400 ms), or holding push-to-talk. */
  get userSpeaking() { return this.forced || (!!this.rec && performance.now() - this.lastLoud < 400); }

  constructor(private o: BrowserVoiceOpts) {}

  static supported() { return !!navigator.mediaDevices && typeof MediaRecorder !== 'undefined'; }

  async start() {
    if (this.live) return;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch (e) {
      const name = (e as { name?: string })?.name;
      throw new Error(name === 'NotAllowedError' ? 'Microphone is blocked. Allow it in the address bar, or type instead.' : 'No microphone found. You can type instead.');
    }
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    this.ctx = new AC();
    void this.ctx.resume();
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 1024;
    this.ctx.createMediaStreamSource(this.stream).connect(this.analyser);
    this.live = true;
    this.loop = window.setInterval(() => this.tick(), 30);
    this.startRecognition();
  }

  stop() {
    this.live = false;
    if (this.loop != null) clearInterval(this.loop);
    this.loop = null;
    this.stopRecognition();
    if (this.rec && this.rec.state !== 'inactive') { this.chunks = []; this.rec.onstop = null; this.rec.stop(); }
    this.rec = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    void this.ctx?.close().catch(() => undefined);
    this.ctx = null; this.analyser = null;
    this.o.onLevel(0);
  }

  /** While our own audio plays on laptop speakers, demand a louder voice to count as a barge-in. */
  setPlaying(p: boolean) { this.playing = p; }

  pushStart() { this.forced = true; if (!this.rec) this.beginRecording(); }
  pushEnd() { this.forced = false; this.endRecording(); }

  private rms(): number {
    if (!this.analyser) return 0;
    const buf = new Float32Array(this.analyser.fftSize);
    this.analyser.getFloatTimeDomainData(buf);
    let s = 0;
    for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i];
    return Math.sqrt(s / buf.length);
  }

  private tick() {
    const lvl = this.rms();
    this.o.onLevel(Math.min(1, lvl * 8));
    const thr = Math.max(0.02, this.floor * 3) * (this.playing ? 2.2 : 1);
    const now = performance.now();
    if (lvl > thr) {
      this.loudFrames++;
      this.lastLoud = now;
      if (!this.rec && this.loudFrames >= 2) { this.o.onSpeechStart(); this.beginRecording(); }
    } else {
      this.loudFrames = 0;
      if (!this.rec) this.floor = this.floor * 0.97 + lvl * 0.03; // learn the room's noise floor while idle
      else if (!this.forced && now - this.lastLoud > 800) this.endRecording();
    }
  }

  private beginRecording() {
    if (!this.stream || this.rec) return;
    const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg'].find((m) => MediaRecorder.isTypeSupported(m));
    try { this.rec = new MediaRecorder(this.stream, mime ? { mimeType: mime } : undefined); } catch { this.o.onError('This browser cannot record audio.'); return; }
    this.chunks = [];
    this.recStart = performance.now();
    this.lastLoud = this.recStart;
    this.rec.ondataavailable = (e) => { if (e.data.size) this.chunks.push(e.data); };
    this.rec.onstop = () => {
      const dur = performance.now() - this.recStart;
      const blob = new Blob(this.chunks, { type: this.rec?.mimeType || 'audio/webm' });
      this.rec = null; this.chunks = [];
      if (dur > 450 && blob.size > 800) this.o.onUtterance(blob);
    };
    this.rec.start(250);
  }

  private endRecording() {
    if (this.rec && this.rec.state === 'recording') this.rec.stop();
  }

  // Optional live captions + instant command matching in Chromium (no model call).
  private startRecognition() {
    const Ctor = ((window as unknown as { SpeechRecognition?: SRCtor; webkitSpeechRecognition?: SRCtor }).SpeechRecognition
      ?? (window as unknown as { webkitSpeechRecognition?: SRCtor }).webkitSpeechRecognition);
    if (!Ctor) return;
    try {
      const sr = new Ctor();
      sr.lang = this.o.language; sr.continuous = true; sr.interimResults = true;
      sr.onresult = (e) => {
        const r = e.results[e.results.length - 1];
        this.o.onInterim(r[0].transcript);
      };
      sr.onend = () => { if (this.live && this.srOn) { try { sr.start(); } catch { /* already started */ } } };
      sr.onerror = () => undefined;
      sr.start();
      this.sr = sr; this.srOn = true;
    } catch { /* not available */ }
  }
  private stopRecognition() {
    this.srOn = false;
    try { this.sr?.abort(); } catch { /* ignore */ }
    this.sr = null;
  }
}
