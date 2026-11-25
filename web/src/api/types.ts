import type { Lang } from '../contract';

export interface EventRec { id: string; name: string; kind: string; year: number; month: number; level?: number }
export interface Member { id: string; nickname: string | null; role: 'owner' | 'editor' | 'viewer'; language?: Lang | null; joined_at?: string }
export interface Contact { id: string; name: string; relation: string | null; phone_last4?: string | null; phone_e164?: string | null; consent_to_calls: boolean; do_not_call: boolean; timezone?: string | null }
export interface Invite {
  id: string; contact_id: string; contact_name?: string; year: number; month: number; event_id?: string | null;
  status: string; call?: { status: string | null; summary: string | null; message: string | null } | null; expires_at?: string | null; link?: string | null;
}
export interface GalleryQueryResult {
  count: number; total_bytes: number; preview_token: string; over_limit: boolean; limit: number;
  sample?: { id?: string; name?: string; taken_at?: string; thumb_url?: string | null }[];
}
export interface GalleryFilter { date_from?: string; date_to?: string; type?: string; min_size?: number; max_size?: number; camera?: string; folder?: string; all?: boolean; latest_n?: number }
export interface Reel { id: string; year: number; month: number; status: 'queued' | 'running' | 'ready' | 'failed' | string; progress?: number | null; narrated: boolean; url?: string | null; error?: string | null }
export interface BlurryItem { key: string; media_id?: string; gallery_item_id?: string; memory_id?: string; thumb_url: string | null; score?: number | null; name?: string; room?: { year: number; month: number } | null }
export interface JobRec { id: string; type: string; status: string; attempts: number; last_error: string | null; run_at?: string }
export interface FamilySettings { name: string; language: Lang; grandma_name: string; settings: { sarcasm_on: boolean; keep_location: boolean; [k: string]: unknown } }
/** POST /api/reception/act: {reply, speech, action:{type,data}, steps:[{tool,spoken}], pending: kind|null} (+ transcript when audio was sent) */
export interface ReceptionReply {
  reply: string;
  speech?: import('../contract').Speech & { sentences?: { text: string; audio_url: string | null }[] };
  action?: { type: string; data: Record<string, unknown> } | null;
  steps?: { tool: string; spoken?: string; ok?: boolean }[];
  pending?: string | null;
  transcript?: string;
  language?: string;
}
export interface VoiceSession { appId: string; channel: string; uid: number; token: string; agentUid: number; agentId: string }
export interface StreamEvent { type: string; [k: string]: unknown }
