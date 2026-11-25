/** One voice controller for both characters. Voice has no private powers: every outcome ends in the same store
 *  actions the buttons call. Transport: Agora when /api/voice/start succeeds, else the browser path. */
import { create } from 'zustand';
import type { Lang, MuseumRoute, Speech } from '../contract';
import { ApiError, post, upload } from '../api/client';
import type { ReceptionReply } from '../api/types';
import { useWorld } from '../state/worldStore';
import { AgoraVoice, VoiceUnavailable } from './agora';
import { BrowserVoice } from './browserVoice';
import { SpeechPlayer } from './speechPlayer';
import { matchCommand, runCommand, ANYWHERE, type Cmd } from './commands';
import { arbiter, playClip } from './speechArbiter';
import { armFiller, prefetchFillers, type FillerWatch } from './fillers';

export type Target = 'receptionist' | 'grandma';
export interface Turn { who: 'you' | 'agent'; text: string; label?: string }

interface VoiceUi {
  transport: 'none' | 'agora' | 'browser';
  busy: boolean;
  error: string | null;
  thread: Turn[];
  pending: string | null;
  toolSteps: string[];
  grandmaSpeech: Speech | null;
  hold: boolean;
  set(p: Partial<Omit<VoiceUi, 'set'>>): void;
}
export const useVoiceUi = create<VoiceUi>((set) => ({
  transport: 'none', busy: false, error: null, thread: [], pending: null, toolSteps: [], grandmaSpeech: null, hold: false,
  set: (p) => set(p),
}));
const ui = () => useVoiceUi.getState();
const W = () => useWorld.getState();

const sessionId = (crypto as Crypto & { randomUUID?: () => string }).randomUUID?.() ?? String(Date.now());

class VoiceController {
  player = new SpeechPlayer();
  private agora: AgoraVoice | null = null;
  private browser: BrowserVoice | null = null;
  private abort: AbortController | null = null;
  private liveTarget: Target | null = null;
  private lastCmdAt = 0;
  private filler: FillerWatch | null = null;
  private noInterruptApi = false;

  constructor() {
    arbiter.agoraHooks = {
      mute: (on) => this.agora?.silenceAgent(on),
      // Best effort server-side interrupt of the live agent (the track is already muted locally).
      interrupt: () => {
        const id = this.agora?.agentId;
        if (!id || this.noInterruptApi) return;
        post('/api/voice/interrupt', { agent_id: id, agentId: id }).catch((e) => { if (e instanceof ApiError && e.status === 404) this.noInterruptApi = true; });
      },
    };
  }

  /** Is the user talking right now (VAD)? Used to skip fillers. */
  userSpeaking() { return !!this.browser?.userSpeaking; }

  /** Typed-text / transcript matcher shared by every entry point. The receptionist only honours stop/pause. */
  private tryCommand(text: string, target: Target): boolean {
    const c: Cmd | null = matchCommand(text);
    if (!c) return false;
    if (target !== 'grandma' && W().mode !== 'walking' && !ANYWHERE.includes(c)) return false;
    runCommand(c, { stopSpeech: () => this.stopSpeech(), resumeSpeech: () => this.resumeGrandma() });
    return true;
  }

  target(): Target { return W().seat ? 'grandma' : 'receptionist'; }

  private scope() {
    const r = W().room ?? (W().seat ? { year: W().seat!.year, month: W().seat!.month, eventId: null } : null);
    return r ? { year: r.year, month: r.month, event_id: r.eventId } : {};
  }

  // ---------- playback ----------
  /** Stop whoever is talking right now (arbiter: agent, guide, filler, Agora). The last finished sentence is kept for "carry on". */
  stopSpeech(reason = 'stop') {
    this.filler?.cancel(); this.filler = null;
    arbiter.interrupt(reason);
    this.player.stop(); // no-op when the arbiter already stopped it
    this.browser?.setPlaying(false);
    if (W().agentState === 'speaking') W().setVoice({ agentState: 'idle' });
  }

  /** Barge-in from anywhere (voice, typing, mic button, key): stop audio, drop queued sentences, abort the in-flight request. */
  interrupt(reason = 'interrupt') {
    this.abort?.abort();
    this.abort = null;
    this.stopSpeech(reason);
    ui().set({ busy: false });
    if (W().agentState !== 'idle') W().setVoice({ agentState: 'idle' });
  }

  /** Called on every keystroke in the text box. */
  userTyping() { if (arbiter.speaking || ui().busy) this.interrupt('typing'); }

  /** Esc / space while an agent talks. Returns true when it stopped someone (the caller then skips its own use of the key). */
  interruptByKey(key: string): boolean {
    if (!arbiter.speaking && !ui().busy) return false;
    this.interrupt('key:' + key);
    return true;
  }

  /** Read a card / phone message aloud with the guide voice (dropped if someone is already talking). */
  async readAloud(text: string) {
    const t = text.trim();
    if (!t || arbiter.speaking) return;
    try {
      const r = await post<{ url?: string }>('/api/tts', { text: t, language: W().language, voice: 'guide' });
      if (r.url && !arbiter.speaking) playClip('guide', 'guide', r.url);
    } catch { /* the card already shows the text */ }
  }

  speak(speech: Parameters<SpeechPlayer['play']>[0], who: 'receptionist' | 'grandma', startAt = 0, label?: string) {
    const w = W();
    this.filler?.cancel(); this.filler = null;
    const capId = w.pushCaption({ who, text: '', final: false });
    w.setVoice({ agentState: 'speaking' });
    this.browser?.setPlaying(true);
    this.player.setRate(1);
    this.player.play(speech, {
      source: 'agent', who,
      startAt,
      onSegment: (_i, seg) => W().pushCaption({ id: capId, who, text: (label ? label + ' ' : '') + seg.text, final: false }),
      onHighlight: (id) => {
        const s = W();
        const idx = s.showcaseItems.findIndex((it) => it.memory_id === id);
        if (idx >= 0 && s.showcaseNarrated) s.setShowcase({ showcaseIndex: idx });
      },
      onEnd: () => {
        this.browser?.setPlaying(false);
        const s = W();
        s.pushCaption({ id: capId, who, text: s.captions.find((c) => c.id === capId)?.text ?? '', final: true });
        if (s.agentState === 'speaking') s.setVoice({ agentState: 'idle' });
      },
    });
  }

  // ---------- mic ----------
  async setMic(on: boolean) {
    const w = W();
    if (!on) { await this.shutdown(); return; }
    if (arbiter.speaking) this.interrupt('mic');
    if (w.micOn) return;
    w.setVoice({ micOn: true, agentState: 'listening' });
    ui().set({ error: null });
    const target = this.target();
    this.liveTarget = target;
    // Prefer Agora live voice; a 503 (or any start failure) drops to the browser path.
    if (w.museum?.flags?.voice_enabled !== false) {
      try {
        const ag = new AgoraVoice({
          onUser: (text, fin) => this.onLiveUser(text, fin),
          onAssistant: (text, done, turn) => { W().pushCaption({ id: 5000 + (parseInt(turn, 10) || 0), who: target, text, final: done }); W().setVoice({ agentState: done ? 'listening' : 'speaking' }); arbiter.setAgoraSpeaking(!done); },
          onState: (s) => { const m = s === 'silent' ? 'idle' : s; W().setVoice({ agentState: m }); arbiter.setAgoraSpeaking(s === 'speaking'); },
          onAction: (m) => this.onAgoraAction(m),
          onLevel: (l) => W().setVoice({ micLevel: l }),
          onError: (m) => ui().set({ error: m }),
        });
        await ag.start({ agent: target, language: w.language, scope: this.scope(), session_id: sessionId });
        this.agora = ag;
        ui().set({ transport: 'agora' });
        return;
      } catch (e) {
        if (!(e instanceof VoiceUnavailable) && !(e instanceof ApiError)) {
          ui().set({ error: (e as Error)?.message || 'Live voice failed. Using the browser microphone.' });
        }
        this.agora = null;
      }
    }
    if (!BrowserVoice.supported()) { ui().set({ error: 'This browser cannot record. Type instead.', transport: 'none' }); W().setVoice({ micOn: false, agentState: 'idle' }); return; }
    const bv = new BrowserVoice({
      language: w.language,
      onLevel: (l) => W().setVoice({ micLevel: l }),
      onSpeechStart: () => { if (arbiter.speaking || ui().busy || this.filler) this.interrupt('vad'); W().setVoice({ agentState: 'listening' }); },
      onUtterance: (b) => void this.sendAudio(b),
      onInterim: (t) => this.onLiveUser(t, false),
      onError: (m) => ui().set({ error: m }),
    });
    try {
      await bv.start();
      this.browser = bv;
      ui().set({ transport: 'browser' });
    } catch (e) {
      ui().set({ error: (e as Error).message, transport: 'none' });
      W().setVoice({ micOn: false, agentState: 'idle', micLevel: 0 });
    }
  }

  async shutdown() {
    this.interrupt('shutdown');
    this.browser?.stop(); this.browser = null;
    const a = this.agora; this.agora = null;
    await a?.stop();
    this.liveTarget = null;
    ui().set({ transport: 'none' });
    W().setVoice({ micOn: false, agentState: 'idle', micLevel: 0, liveTranscript: '' });
  }

  /** Keep the voice session matched to where the user is (desk vs theater). */
  async retarget() {
    if (!W().micOn || this.liveTarget === this.target()) return;
    await this.shutdown();
    await this.setMic(true);
  }

  async pushContext() {
    if (this.agora) await post('/api/voice/context', { agent_id: this.agora.agentId, scope: this.scope(), language: W().language }).catch(() => undefined);
  }

  pushToTalk(down: boolean) {
    if (!this.browser) return;
    if (down) { this.interrupt('push-to-talk'); this.browser.pushStart(); W().setVoice({ agentState: 'listening' }); } else this.browser.pushEnd();
  }

  // ---------- transcripts ----------
  private onLiveUser(text: string, final: boolean) {
    const w = W();
    w.setVoice({ liveTranscript: final ? '' : text });
    if (!text.trim()) return;
    // The user's voice always wins: the first words of a transcript silence whoever is talking.
    if (arbiter.speaking) this.stopSpeech('user-transcript');
    // Commands act on the partial transcript instantly (V6), before any model call.
    if (Date.now() - this.lastCmdAt > 1200 && this.tryCommand(text, this.target())) {
      this.lastCmdAt = Date.now();
      w.setVoice({ liveTranscript: '' });
      return;
    }
    if (final) w.pushCaption({ who: 'you', text, final: true });
  }

  private onAgoraAction(m: Record<string, unknown>) {
    const act = (m.action ?? m) as { type?: string; data?: Record<string, unknown> };
    if (act.type && act.data) this.applyAction({ type: act.type, data: act.data });
    const steps = m.tool || m.name;
    if (typeof steps === 'string') ui().set({ toolSteps: [...ui().toolSteps.slice(-3), steps] });
  }

  // ---------- requests ----------
  private payloadBase() {
    return { language: W().language, scope: this.scope(), session_id: sessionId, history: ui().thread.slice(-8).map((t) => ({ role: t.who === 'you' ? 'user' : 'assistant', text: t.text })) };
  }

  /** Typed text or a transcript. In the theater, short command phrases run locally; everything else goes to Grandma. */
  async sendText(text: string) {
    const t = text.trim();
    if (!t) return;
    const target = this.target();
    const w = W();
    w.pushCaption({ who: 'you', text: t, final: true });
    ui().set({ thread: [...ui().thread, { who: 'you', text: t }] });
    if (this.tryCommand(t, target)) return;
    this.interrupt('send');
    await this.request(target, async (signal) => {
      const base = this.payloadBase();
      if (target === 'grandma') return post<Record<string, unknown>>('/api/grandma/talk', { text: t, language: base.language, scope: base.scope }, { signal });
      return post<Record<string, unknown>>('/api/reception/act', { text: t, language: base.language, room: base.scope.year ? base.scope : undefined }, { signal });
    });
  }

  private async sendAudio(blob: Blob) {
    const target = this.target();
    this.interrupt('utterance');
    const fd = new FormData();
    const base = this.payloadBase();
    fd.append('audio', blob, blob.type.includes('mp4') ? 'speech.m4a' : 'speech.webm');
    fd.append('language', base.language);
    fd.append('scope', JSON.stringify(base.scope));
    W().setVoice({ agentState: 'thinking' });
    await this.request(target, (signal) => upload(target === 'grandma' ? '/api/grandma/talk' : '/api/reception/act', fd, signal), true);
  }

  private async request(target: Target, run: (signal: AbortSignal) => Promise<unknown>, fromAudio = false) {
    const ctl = new AbortController();
    this.abort = ctl;
    ui().set({ busy: true, error: null });
    W().setVoice({ agentState: 'thinking' });
    this.filler?.cancel();
    this.filler = this.agora ? null : armFiller(target, W().language, () => this.userSpeaking());
    try {
      const raw = (await run(ctl.signal)) as Record<string, unknown>;
      if (ctl.signal.aborted) return;
      const said = raw.transcript as string | undefined;
      if (fromAudio && said) {
        W().pushCaption({ who: 'you', text: said, final: true });
        ui().set({ thread: [...ui().thread, { who: 'you', text: said }] });
        if (this.tryCommand(said, target)) { this.filler?.cancel(); this.filler = null; W().setVoice({ agentState: 'idle' }); ui().set({ busy: false }); return; }
      }
      if (target === 'receptionist') {
        const r = raw as unknown as ReceptionReply;
        const text = r.reply ?? '';
        ui().set({
          thread: [...ui().thread, { who: 'agent', text }],
          pending: r.pending ?? null,
          toolSteps: (r.steps ?? []).map((x) => x.tool),
        });
        this.applyAction(r.action ?? null);
        const sp = r.speech ?? { text };
        if (text) this.speak(sp as Parameters<SpeechPlayer['play']>[0], 'receptionist');
        else W().setVoice({ agentState: 'idle' });
      } else {
        const sp = (raw.speech ?? raw) as Parameters<SpeechPlayer['play']>[0] & { text?: string };
        const label = raw.source === 'general' ? "(Not from your family's memories.)" : undefined;
        const text = sp.text ?? '';
        ui().set({ thread: [...ui().thread, { who: 'agent', text, label }], grandmaSpeech: sp as unknown as Speech });
        if (raw.error) ui().set({ error: String(raw.error) });
        if (text) this.speak(sp, 'grandma', 0, label);
        else W().setVoice({ agentState: 'idle' });
      }
    } catch (e) {
      if ((e as Error).name === 'AbortError') return;
      const msg = e instanceof Error ? e.message : 'Something went wrong.';
      ui().set({ error: msg });
      W().pushCaption({ who: 'system', text: msg, final: true });
      W().setVoice({ agentState: 'idle' });
    } finally {
      if (this.abort === ctl) { this.abort = null; ui().set({ busy: false }); }
      if (!this.abort) { this.filler?.cancel(); this.filler = null; }
    }
  }

  /** What the receptionist did on the server. Same effects the buttons have. */
  private applyAction(a: { type: string; data: Record<string, unknown> } | null) {
    if (!a) return;
    const w = W();
    switch (a.type) {
      case 'route': w.startGuidedWalk(a.data as unknown as MuseumRoute); break;
      case 'event_created': case 'import_started': case 'setting_changed': {
        void w.refreshMuseum();
        const ev = a.data.event as { year?: number } | undefined;
        if (ev?.year) void w.loadFloor(ev.year, true).catch(() => undefined);
        if (a.type === 'setting_changed' && a.data.key === 'language' && typeof a.data.value === 'string') w.setLanguage(a.data.value as Lang);
        break;
      }
      case 'invite_called': w.bumpInvites(); break;
    }
  }

  // ---------- Grandma ----------
  async grandmaSpeak(mode: 'greet' | 'tour') {
    const r = W().room ?? (W().seat ? { year: W().seat!.year, month: W().seat!.month, eventId: null } : null);
    if (!r) return;
    this.interrupt('grandma-start');
    await this.request('grandma', (signal) => post<Speech>(mode === 'greet' ? '/api/grandma/greet' : '/api/grandma/tour', { year: r.year, month: r.month, event_id: r.eventId, language: W().language }, { signal }));
  }
  resumeGrandma() {
    if (this.player.hasRemaining()) { W().setVoice({ agentState: 'speaking' }); this.player.resume(); return true; }
    return false;
  }
  canResume() { return this.player.hasRemaining(); }

}
export const voice = new VoiceController();

// Phone / guest cards ("Aunt says ...", call outcomes) are read aloud with the guide voice, through the arbiter.
let seenCard = 0;
useWorld.subscribe((s) => {
  const c = s.cards[s.cards.length - 1];
  if (!c || c.id <= seenCard) return;
  seenCard = c.id;
  if (c.kind === 'message' || c.kind === 'outcome') void voice.readAloud(c.text);
});
// Warm fillers for the characters the user can talk to, per language.
let fillLang = '';
useWorld.subscribe((s) => {
  if (s.language === fillLang) return;
  fillLang = s.language;
  prefetchFillers('receptionist', s.language);
  prefetchFillers('grandma', s.language);
});
export { VoiceUnavailable };
if (import.meta.env.DEV) (window as unknown as { __memoVoice: unknown }).__memoVoice = voice;
