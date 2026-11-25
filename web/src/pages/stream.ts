import { useEffect } from 'react';
import type { StreamEvent } from '../api/types';
import { useWorld } from '../state/worldStore';
import { onPresenceEvent } from './presence';

const CALL: Record<string, string> = { queued: 'is lined up', dialling: 'is being dialled', ringing: 'is ringing', talking: 'is talking to the assistant', accepted: 'said yes', declined: 'said no', no_answer: 'did not pick up', message_left: 'left a message', failed: 'could not be reached' };

/** GET /api/stream: call progress, outcomes, guest messages, import/reel completions and host playback sync. */
export function useLiveStream() {
  useEffect(() => {
    if (typeof EventSource === 'undefined') return;
    let es: EventSource | null = new EventSource('/api/stream', { withCredentials: true });
    const handle = (raw: string, name?: string) => {
      let ev: StreamEvent;
      try { ev = JSON.parse(raw) as StreamEvent; } catch { return; }
      const type = (ev.type as string) || name || '';
      const w = useWorld.getState();
      const who = (ev.contact_name as string) || 'Your guest';
      switch (type) {
        case 'call_progress':
          w.bumpInvites();
          w.addCard({ kind: 'call', title: 'Calling', text: `${who} ${CALL[String(ev.status)] ?? String(ev.status)}.` });
          break;
        case 'call_outcome':
          w.bumpInvites();
          w.addCard({ kind: 'outcome', title: 'Call finished', text: `${who} ${CALL[String(ev.status)] ?? String(ev.status)}.${ev.summary ? ' ' + String(ev.summary) : ''}` });
          break;
        case 'guest_message':
          w.bumpInvites();
          w.addCard({ kind: 'message', title: `${who} says`, text: String(ev.text ?? '') });
          break;
        case 'import_done':
          w.addCard({ kind: 'info', title: 'Photos are on the wall', text: `${String(ev.count ?? '')} photos in ${String(ev.event_name ?? 'your event')}.` });
          void w.refreshMuseum();
          if (typeof ev.year === 'number') void w.loadFloor(ev.year, true).catch(() => undefined);
          if (w.room && w.room.year === ev.year && w.room.month === ev.month) void w.loadRoom(w.room.year, w.room.month, w.room.eventId).then(() => w.loadShowcase({ keep: true })).catch(() => undefined);
          break;
        case 'memory_saved':
          void w.refreshMuseum();
          if (typeof ev.year === 'number') void w.loadFloor(ev.year, true).catch(() => undefined);
          if (w.room && w.room.year === ev.year && w.room.month === ev.month) void w.loadRoom(w.room.year, w.room.month, w.room.eventId).then(() => w.loadShowcase({ keep: true })).catch(() => undefined);
          break;
        case 'reel_ready':
          w.bumpInvites();
          w.addCard({ kind: 'info', title: 'Reel is ready', text: 'Open Reels to play it.' });
          break;
        case 'playback_sync':
          if (w.museum?.me.is_guest && w.seat && ev.year === w.seat.year && ev.month === w.seat.month) w.setGuestSync(Number(ev.index) || 0, !!ev.playing);
          break;
        case 'presence':
          onPresenceEvent(ev);
          break;
      }
    };
    const names = ['call_progress', 'call_outcome', 'guest_message', 'import_done', 'memory_saved', 'reel_ready', 'playback_sync', 'presence'];
    es.onmessage = (e) => handle(e.data);
    names.forEach((n) => es?.addEventListener(n, (e) => handle((e as MessageEvent).data, n)));
    return () => { es?.close(); es = null; };
  }, []);
}
