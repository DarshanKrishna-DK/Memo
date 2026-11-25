/** Live voice via Agora Conversational AI (ported and trimmed from MedSim's voice/conversation.ts).
 *  POST /api/voice/start -> {appId, channel, uid, token, agentUid, agentId}; RTM carries transcripts + state;
 *  RTC carries the agent audio and our mic. A 503 means "not configured": the caller falls back to the browser path. */
import AgoraRTC, { type IAgoraRTCClient, type IMicrophoneAudioTrack, type IRemoteAudioTrack } from 'agora-rtc-sdk-ng';
import AgoraRTM, { type RTMClient } from 'agora-rtm';
import { ApiError, post } from '../api/client';
import type { VoiceSession } from '../api/types';

try { AgoraRTC.setLogLevel(2); } catch { /* noop */ }

export class VoiceUnavailable extends Error {}

export type AgentStateName = 'idle' | 'listening' | 'thinking' | 'speaking' | 'silent';
export interface AgoraListeners {
  onUser: (text: string, final: boolean, turn: string) => void;
  onAssistant: (text: string, done: boolean, turn: string) => void;
  onState: (s: AgentStateName) => void;
  onAction: (msg: Record<string, unknown>) => void;
  onLevel: (l: number) => void;
  onError: (m: string) => void;
}

function decode(raw: string | Uint8Array): Record<string, unknown> | null {
  try {
    const s = typeof raw === 'string' ? raw : new TextDecoder().decode(raw);
    return JSON.parse(s) as Record<string, unknown>;
  } catch { return null; }
}

export class AgoraVoice {
  private rtc: IAgoraRTCClient | null = null;
  private rtm: RTMClient | null = null;
  private mic: IMicrophoneAudioTrack | null = null;
  private remote: IRemoteAudioTrack | null = null;
  private session: VoiceSession | null = null;
  private poll: number | null = null;
  private closed = false;

  constructor(private l: AgoraListeners) {}

  get agentId() { return this.session?.agentId ?? null; }

  async start(body: Record<string, unknown>) {
    let s: VoiceSession;
    try {
      s = await post<VoiceSession>('/api/voice/start', body);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 503 || e.status === 501 || e.status === 404)) throw new VoiceUnavailable(e.message);
      throw e;
    }
    const raw = s as unknown as Record<string, unknown>;
    // tolerate snake_case
    const session: VoiceSession = {
      appId: (raw.appId ?? raw.app_id) as string, channel: raw.channel as string, uid: Number(raw.uid), token: raw.token as string,
      agentUid: Number(raw.agentUid ?? raw.agent_uid), agentId: String(raw.agentId ?? raw.agent_id ?? ''),
    };
    if (!session.appId || !session.channel || !session.token) throw new VoiceUnavailable('Voice is not configured on the server.');
    this.session = session;
    try {
      const rtm = new AgoraRTM.RTM(session.appId, String(session.uid));
      this.rtm = rtm;
      rtm.addEventListener('message', (ev) => {
        if (ev.channelName && ev.channelName !== session.channel) return;
        this.onRtm(ev.message);
      });
      rtm.addEventListener('presence', (ev) => {
        const st = ev.stateChanged as Record<string, unknown> | null | undefined;
        if (st && typeof st.state === 'string' && String(ev.publisher) !== String(session.uid)) this.l.onState(st.state as AgentStateName);
      });
      await rtm.login({ token: session.token });
      await rtm.subscribe(session.channel, { withMessage: true, withPresence: true });
    } catch { /* captions are optional; audio still works */ }

    const rtc = AgoraRTC.createClient({ mode: 'rtc', codec: 'vp8' });
    this.rtc = rtc;
    rtc.on('user-published', async (user, type) => {
      if (type !== 'audio') return;
      await rtc.subscribe(user, 'audio');
      this.remote = user.audioTrack ?? null;
      this.remote?.play();
    });
    rtc.on('user-left', (user) => { if (String(user.uid) === String(session.agentUid) && !this.closed) this.l.onError('The voice agent left. Tap the mic to reconnect.'); });
    await rtc.join(session.appId, session.channel, session.token, session.uid);
    this.mic = await AgoraRTC.createMicrophoneAudioTrack({ AEC: true, ANS: true, AGC: true });
    await rtc.publish([this.mic]);
    this.poll = window.setInterval(() => {
      this.l.onLevel(Math.min(1, (this.mic?.getVolumeLevel() ?? 0) * 3));
    }, 60);
  }

  private onRtm(raw: string | Uint8Array) {
    const m = decode(raw);
    if (!m) return;
    const turn = String(m.turn_id ?? '');
    switch (m.object) {
      case 'user.transcription': this.l.onUser(String(m.text ?? ''), !!m.final, turn); break;
      case 'assistant.transcription': this.l.onAssistant(String(m.text ?? ''), Number(m.turn_status) === 1 || Number(m.turn_status) === 2, turn); break;
      case 'message.interrupt': this.l.onState('listening'); break;
      default:
        // Action results from the server's tool loop ride the same channel (route, panel, import done ...).
        if (m.object) this.l.onAction(m);
    }
  }

  setMuted(muted: boolean) { this.mic?.setEnabled(!muted).catch(() => undefined); }
  /** Barge-in / "pause": silence the agent locally at once. */
  silenceAgent(on: boolean) { try { this.remote?.setVolume(on ? 0 : 100); } catch { /* noop */ } }

  async stop() {
    this.closed = true;
    if (this.poll != null) clearInterval(this.poll);
    try { this.mic?.stop(); this.mic?.close(); } catch { /* noop */ }
    try { await this.rtc?.leave(); } catch { /* noop */ }
    try { await this.rtm?.logout(); } catch { /* noop */ }
    if (this.session?.agentId) await post('/api/voice/stop', { agent_id: this.session.agentId }).catch(() => undefined);
    this.rtc = this.rtm = this.mic = this.remote = null;
  }
}
