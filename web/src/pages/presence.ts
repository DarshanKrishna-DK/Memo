import { useEffect, useRef } from 'react';
import { ApiError, get, post } from '../api/client';
import type { StreamEvent } from '../api/types';
import { NO_SEAT, useWorld, type Presence, type PresencePerson } from '../state/worldStore';

/** Theater presence (guests section of BUILD_CONTRACT): join when we sit down, heartbeat every 15 s, leave when we
 *  stand up or the page goes away. The server picks the seat; the local player moves to it. */
interface JoinReply extends Presence { me: PresencePerson | null }

const HEARTBEAT_MS = 15_000;

function apply(r: Presence) {
  const w = useWorld.getState();
  if (!w.seat || w.seat.year !== r.year || w.seat.month !== r.month) return;
  w.setPresence({ year: r.year, month: r.month, seats: r.seats ?? [], watchers: r.watchers ?? [] });
}

export function usePresence() {
  const seat = useWorld((s) => s.seat);
  const avatar = useWorld((s) => s.avatar);
  const displayName = useWorld((s) => s.displayName);
  const confirmed = useRef<string | null>(null);   // `${year}-${month}-${index}-${avatar}-${name}` the server agreed to
  const joined = useRef(false);
  const busy = useRef(false);

  const keyOf = (y: number, m: number, i: number) => `${y}-${m}-${i}-${useWorld.getState().avatar}-${useWorld.getState().displayName ?? ''}`;

  const join = useRef(async () => {
    const w = useWorld.getState();
    const st = w.seat;
    if (!st || busy.current) return;
    busy.current = true;
    try {
      const guest = !!w.museum?.me.is_guest;
      const r = await post<JoinReply>('/api/presence/join', {
        year: st.year, month: st.month, avatar: w.avatar,
        name: (guest ? w.displayName : null) || undefined,
        prefer_seat: st.index < NO_SEAT ? st.index : undefined,
      });
      joined.current = true;
      const now = useWorld.getState().seat;
      if (!now || now.year !== st.year || now.month !== st.month) return;   // moved on meanwhile
      const granted = r.me?.index ?? NO_SEAT;
      confirmed.current = keyOf(st.year, st.month, granted);
      apply(r);
      if (granted !== now.index) useWorld.setState({ seat: { ...now, index: granted } });
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 401)) console.warn('presence join failed', e);
      return;
    } finally {
      busy.current = false;
    }
    // The seat (or avatar) changed while we waited: ask again for the newest choice.
    const again = useWorld.getState().seat;
    if (again && confirmed.current !== keyOf(again.year, again.month, again.index)) void join.current();
  });

  // Sit down / change seat / change avatar -> (re)join. The server's answer is final.
  useEffect(() => {
    if (!seat) return;
    if (confirmed.current === keyOf(seat.year, seat.month, seat.index)) return;
    void join.current();
  }, [seat?.year, seat?.month, seat?.index, avatar, displayName]); // eslint-disable-line react-hooks/exhaustive-deps

  // Stand up -> leave. (Moving to another room needs no leave: the join there replaces our row.)
  const roomKey = seat ? `${seat.year}-${seat.month}` : null;
  useEffect(() => {
    if (roomKey || !joined.current) return;
    joined.current = false;
    confirmed.current = null;
    void post('/api/presence/leave').catch(() => undefined);
  }, [roomKey]);

  // Heartbeat + a state refresh, in case an SSE message was missed.
  useEffect(() => {
    if (!roomKey) return;
    const t = window.setInterval(async () => {
      const st = useWorld.getState().seat;
      if (!st) return;
      try {
        const hb = await post<{ ok: boolean; rejoin?: boolean }>('/api/presence/heartbeat');
        if (hb.rejoin) { confirmed.current = null; await join.current(); return; }
        apply(await get<Presence>(`/api/presence/${st.year}/${st.month}`));
      } catch { /* network blip: the next beat tries again */ }
    }, HEARTBEAT_MS);
    return () => window.clearInterval(t);
  }, [roomKey]);

  // Closing the tab frees the seat right away; coming back from the bfcache sits down again.
  useEffect(() => {
    const hide = () => {
      if (!joined.current) return;
      try { navigator.sendBeacon('/api/presence/leave', new Blob(['{}'], { type: 'text/plain' })); } catch { /* ignore */ }
      joined.current = false;
      confirmed.current = null;
    };
    const show = (e: PageTransitionEvent) => { if (e.persisted && useWorld.getState().seat) void join.current(); };
    window.addEventListener('pagehide', hide);
    window.addEventListener('pageshow', show);
    return () => { window.removeEventListener('pagehide', hide); window.removeEventListener('pageshow', show); };
  }, []);
}

/** SSE `presence`: refresh the seats; a join/leave by someone else shows a card (also in screen mode). */
export function onPresenceEvent(ev: StreamEvent) {
  const w = useWorld.getState();
  const y = Number(ev.year), m = Number(ev.month);
  if (!w.seat || w.seat.year !== y || w.seat.month !== m) return;
  const seats = (ev.seats as PresencePerson[]) ?? [];
  const watchers = (ev.watchers as PresencePerson[]) ?? [];
  w.setPresence({ year: y, month: m, seats, watchers });
  const ch = ev.change as { kind?: string; id?: string; name?: string; is_guest?: boolean } | null | undefined;
  if (!ch || !ch.name) return;
  const me = [...seats, ...watchers].find((p) => p.is_me);
  if (me && me.id === ch.id) return;
  if (ch.kind === 'joined') {
    const seated = seats.some((p) => p.id === ch.id);
    w.presenceCard(`${ch.name} is here`, seated ? `${ch.name} took a seat to watch with you.` : `${ch.name} is watching from the back. All four seats are taken.`);
  } else if (ch.kind === 'left') {
    w.presenceCard(`${ch.name} left`, `${ch.name} has left the room.`);
  }
}

/** "Watching with: Priya, Ravi" (everyone but me). */
export function watchingWith(p: Presence | null): string[] {
  if (!p) return [];
  return [...p.seats, ...p.watchers].filter((x) => !x.is_me).map((x) => x.name);
}
