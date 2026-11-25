/**
 * The guide robot's pre-recorded lines (PRD: recorded once per language, played from storage, no model).
 * GET /api/guide/lines?lang= -> {lines: {follow_me, to_lift, here_we_are, locked_door, enjoy: {text, audio_url}}}
 * Audio goes through the speech arbiter (rank guide): it never talks over an agent and any user barge-in cuts it.
 */
import { get } from '../api/client';
import { playClip } from './speechArbiter';

export type GuideLineKey = 'follow_me' | 'to_lift' | 'here_we_are' | 'locked_door' | 'enjoy';
interface Line { text: string; audio_url: string | null; duration_s?: number }

const cache = new Map<string, Promise<Record<string, Line>>>();

function linesFor(lang: string): Promise<Record<string, Line>> {
  let p = cache.get(lang);
  if (!p) {
    p = get<{ lines: Record<string, Line> }>(`/api/guide/lines?lang=${encodeURIComponent(lang)}`)
      .then((r) => r.lines || {})
      .catch(() => { cache.delete(lang); return {}; });
    cache.set(lang, p);
  }
  return p;
}

/** Plays one guide line; resolves with its text (or null). Never throws: the walk must not depend on audio. */
export async function playGuideLine(key: GuideLineKey, lang: string): Promise<string | null> {
  const line = (await linesFor(lang))[key];
  if (!line) return null;
  if (line.audio_url) playClip('guide', 'guide', line.audio_url); // refused (dropped) while an agent talks
  return line.text;
}

/** Cut the guide line if it is the one talking. */
export function stopGuideLine() {
  void import('./speechArbiter').then(({ arbiter }) => { if (arbiter.current?.source === 'guide') arbiter.interrupt('guide-stop'); });
}

export function prefetchGuideLines(lang: string) { void linesFor(lang); }
