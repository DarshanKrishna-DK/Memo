import { useEffect, useRef, useState } from 'react';
import { del, get, listOf, patch, post } from '../api/client';
import type { BlurryItem, Reel } from '../api/types';
import type { Exhibit } from '../contract';
import { useWorld } from '../state/worldStore';
import { ConfirmModal, Field, MONTHS, Modal, Spinner, monthName, useAction, useLoad } from '../ui/common';
import { VideoPlayer } from '../ui/MediaControls';

const canEdit = () => { const m = useWorld.getState().museum; return !!m && !m.me.is_guest && m.me.role !== 'viewer'; };

async function refreshRoom() {
  const s = useWorld.getState();
  if (s.room) await s.loadRoom(s.room.year, s.room.month, s.room.eventId).catch(() => undefined);
  await s.loadShowcase({ keep: true }).catch(() => undefined);
  await s.refreshMuseum();
  for (const y of Object.keys(s.floorRooms)) await s.loadFloor(+y, true).catch(() => undefined);
}

export function ExhibitModal() {
  const id = useWorld((s) => s.exhibitId);
  const ex = useWorld((s) => s.roomExhibits.find((e) => e.id === id));
  const close = useWorld((s) => s.closeExhibit);
  const [photo, setPhoto] = useState(0);
  const [edit, setEdit] = useState(false);
  useEffect(() => { setPhoto(0); setEdit(false); }, [id]);
  if (!id) return null;
  if (!ex) return <Modal title="Not on this floor" size="sm" onClose={close}><p>This memory is in another room. Walk there first.</p></Modal>;
  const p = ex.photos[photo];
  return (
    <Modal title={ex.title || 'A memory'} onClose={close} size="lg">
      {p && <img className="exhibit-hero" src={p.url} alt={ex.title || ex.summary || 'Photo'} />}
      {ex.photos.length > 1 && <div className="thumb-strip">{ex.photos.map((ph, i) => <img key={ph.id} src={ph.thumb_url} alt={`Photo ${i + 1}`} tabIndex={0} onClick={() => setPhoto(i)} onKeyDown={(e) => e.key === 'Enter' && setPhoto(i)} style={i === photo ? { boxShadow: '0 0 0 2px var(--brass)' } : undefined} />)}</div>}
      <div className="plaque">
        <p><strong>{ex.title || monthName(ex.event_date.month) + ' ' + ex.event_date.year}</strong></p>
        {ex.summary && <p>{ex.summary}</p>}
        {ex.text && <p style={{ whiteSpace: 'pre-wrap' }}>{ex.text}</p>}
        <p className="muted" style={{ fontSize: 13 }}>{ex.teller || ex.author ? `Told by ${ex.teller || ex.author}. ` : ''}{ex.event_date.day ? `${ex.event_date.day} ` : ''}{monthName(ex.event_date.month)} {ex.event_date.year}{ex.festival ? `, ${ex.festival}` : ''}</p>
      </div>
      {ex.audio_url && (
        <div className="stack">
          <h3>Voice note{ex.duration_s ? `, ${Math.round(ex.duration_s)} s` : ''}</h3>
          <audio controls src={ex.audio_url} style={{ width: '100%' }} />
          {ex.transcript ? <div className="transcript">{ex.transcript}</div> : <p className="muted">The family kept only the voice, no words.</p>}
        </div>
      )}
      {canEdit() && <div className="row"><button className="btn" onClick={() => setEdit(true)}>Edit this memory</button></div>}
      {edit && <MemoryEditor ex={ex} onClose={() => setEdit(false)} onDone={() => { setEdit(false); void refreshRoom(); }} onDeleted={() => { setEdit(false); close(); void refreshRoom(); }} />}
    </Modal>
  );
}

function MemoryEditor({ ex, onClose, onDone, onDeleted }: { ex: Exhibit; onClose: () => void; onDone: () => void; onDeleted: () => void }) {
  const [title, setTitle] = useState(ex.title ?? '');
  const [year, setYear] = useState(ex.event_date.year);
  const [month, setMonth] = useState(ex.event_date.month);
  const [confirmDel, setConfirmDel] = useState(false);
  const save = useAction(async () => {
    const body: Record<string, unknown> = {};
    if (title !== (ex.title ?? '')) body.title = title;
    if (Object.keys(body).length) await patch(`/api/memories/${ex.id}`, body);
    if (year !== ex.event_date.year || month !== ex.event_date.month) await post(`/api/memories/${ex.id}/move`, { year, month });
    onDone();
  });
  const narrate = useAction(async () => { await post(`/api/memories/${ex.id}/narrate_ok`, { narrate_ok: !ex.narrate_ok }); onDone(); });
  const rm = useAction(async () => { await del(`/api/memories/${ex.id}`); onDeleted(); });
  const busy = save.busy || narrate.busy;
  return (
    <>
      <Modal title="Edit memory" size="md" onClose={onClose} busy={busy} footer={
        <>
          <button className="btn btn-danger" style={{ marginRight: 'auto' }} onClick={() => setConfirmDel(true)} disabled={busy}>Delete</button>
          <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn btn-primary" onClick={() => void save.run()} disabled={busy}>Save changes</button>
        </>
      }>
        <form className="stack" onSubmit={(e) => { e.preventDefault(); void save.run(); }}>
          <Field label="Title"><input className="input" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
          <div className="row">
            <Field label="Year"><input className="input" type="number" value={year} onChange={(e) => setYear(+e.target.value)} /></Field>
            <Field label="Month"><select className="input" value={month} onChange={(e) => setMonth(+e.target.value)}>{MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}</select></Field>
          </div>
          <div className="row"><button type="button" className="btn" aria-pressed={!ex.narrate_ok} onClick={() => void narrate.run()} disabled={busy}>{ex.narrate_ok ? "Don't narrate this" : 'Allow narration'}</button></div>
          {(save.error || narrate.error) && <p className="err" role="alert">{save.error || narrate.error}</p>}
        </form>
      </Modal>
      {confirmDel && <ConfirmModal title="Delete this memory?" danger confirmLabel="Yes, delete it" cancelLabel="Keep it" busy={rm.busy} error={rm.error} onCancel={() => setConfirmDel(false)} onConfirm={() => void rm.run()}><p>"{ex.title || ex.summary || 'This memory'}" and its photos will be removed from the museum.</p></ConfirmModal>}
    </>
  );
}

/** Buttons for the current room: closed with care, reels, blurry cleanup. */
export function RoomTools() {
  const room = useWorld((s) => s.room);
  const rooms = useWorld((s) => (room ? s.floorRooms[room.year] : undefined));
  const open = useWorld((s) => s.openPanel);
  const meta = rooms?.find((r) => r.month === room?.month);
  const closed = meta?.state === 'closed';
  const [askClose, setAskClose] = useState(false);
  const toggle = useAction(async () => {
    if (!room) return;
    await post(`/api/rooms/${room.year}/${room.month}/mode`, { mode: closed ? 'auto' : 'closed_with_care' });
    await refreshRoom();
    setAskClose(false);
  });
  if (!room || !canEdit()) return null;
  return (
    <div className="stack">
      <div className="btn-row">
        <button className="btn btn-sm" onClick={() => open('reels')}>Reels</button>
        <button className="btn btn-sm" onClick={() => open('cleanup')} title="Blurry photos Memo skipped or removed in this room">Cleaned up</button>
        <button className="btn btn-sm" aria-pressed={closed} onClick={() => (closed ? void toggle.run() : setAskClose(true))} disabled={toggle.busy} title="Shut this room for a month and say so gently">{closed ? 'Open the room again' : 'Close with care'}</button>
      </div>
      {toggle.error && !askClose && <p className="err" role="alert">{toggle.error}</p>}
      {askClose && room && <ConfirmModal title="Close this room with care?" confirmLabel="Close the room" busy={toggle.busy} error={toggle.error} onCancel={() => setAskClose(false)} onConfirm={() => void toggle.run()}><p>{monthName(room.month)} {room.year} will be shut for a while and the door will say so gently. You can open it again any time.</p></ConfirmModal>}
    </div>
  );
}

export function ReelsPanel() {
  const room = useWorld((s) => s.room);
  const close = useWorld((s) => s.openPanel);
  const q = room ? `?year=${room.year}&month=${room.month}` : '';
  const list = useLoad(() => get<unknown>(`/api/reels${q}`).then((d) => listOf<Reel>(d, 'reels')), [q]);
  const [narrated, setNarrated] = useState(true);
  const [playing, setPlaying] = useState<Reel | null>(null);
  const make = useAction(async () => { if (room) { await post('/api/reels', { year: room.year, month: room.month, event_id: room.eventId, narrated }); list.reload(); } });
  const live = list.data?.some((r) => r.status === 'queued' || r.status === 'rendering');
  const reload = list.reload;
  useEffect(() => { if (!live) return; const t = setInterval(reload, 3000); return () => clearInterval(t); }, [live, reload]);
  const tick = useWorld((s) => s.invitesTick);
  const first = useRef(true);
  useEffect(() => { if (first.current) { first.current = false; return; } reload(); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Modal title="Reels" size="md" onClose={() => close(null)}>
      {!room ? <p className="muted">Sit in a room to make its reel.</p> : (
        <>
          <p className="muted">A short video of {monthName(room.month)} {room.year}, made from the showcase.</p>
          <div className="row">
            <div className="seg" role="radiogroup" aria-label="Narration"><button role="radio" aria-checked={narrated} onClick={() => setNarrated(true)}>Narrated</button><button role="radio" aria-checked={!narrated} onClick={() => setNarrated(false)}>Silent</button></div>
            <button className="btn btn-primary" onClick={() => void make.run()} disabled={make.busy}>Make a reel</button>
          </div>
          {make.error && <p className="err" role="alert">{make.error}</p>}
        </>
      )}
      {list.loading && <Spinner text="Loading reels" />}
      <div className="list">
        {(list.data ?? []).map((r) => (
          <div key={r.id} className="item">
            <div><div className="item-title">{monthName(r.month)} {r.year}, {r.narrated ? 'narrated' : 'silent'}</div>
              {(r.status === 'queued' || r.status === 'rendering') && <div className="muted" style={{ fontSize: 13 }}>Rendering. This takes a minute or two.</div>}
              {r.status === 'failed' && <div className="err">{r.error || 'The reel could not be made.'}</div>}</div>
            <div className="row">
              <span className={'chip ' + (r.status === 'ready' ? 'chip--ok' : r.status === 'failed' ? 'chip--bad' : 'chip--teal')}>{r.status}</span>
              {r.status === 'ready' && r.url && <><button className="btn btn-sm btn-primary" onClick={() => { useWorld.getState().setShowcase({ showcasePlaying: false }); setPlaying(r); }}>Play</button><a className="btn btn-sm" href={r.url} download>Download</a></>}
            </div>
          </div>
        ))}
        {list.data?.length === 0 && <p className="muted">No reels yet.</p>}
      </div>
      {playing?.url && <Modal title={`${monthName(playing.month)} ${playing.year}`} onClose={() => setPlaying(null)} size="lg"><VideoPlayer src={playing.url} autoPlay label="Reel" /><p className="muted" style={{ fontSize: 13 }}>Space plays or pauses, arrows skip 5 seconds, M mutes.</p></Modal>}
    </Modal>
  );
}

type CleanReason = 'auto_skipped' | 'deleted' | 'flagged';
interface CleanItem { id: string; thumb_url: string | null; blur_score: number | null; reason: CleanReason; when: string | null }
const REASON: Record<CleanReason, { label: string; chip: string; long: string }> = {
  auto_skipped: { label: 'Skipped', chip: 'chip--teal', long: 'kept off the screen' },
  deleted: { label: 'Deleted', chip: 'chip--bad', long: 'deleted' },
  flagged: { label: 'Waiting', chip: 'chip--warn', long: 'waiting for you' },
};
const fmtWhen = (w: string | null) => {
  if (!w) return '';
  const d = new Date(w);
  return Number.isNaN(d.getTime()) ? w : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
};

/** "Cleaned up for you": what Memo skipped or removed as blurry in this room (GET /api/cleanup/history), plus the photos
 *  still waiting for a keep/delete decision (the /api/cleanup/blurry endpoints). */
export function CleanupPanel() {
  const close = useWorld((s) => s.openPanel);
  const room = useWorld((s) => s.room);
  const q = room ? `?year=${room.year}&month=${room.month}` : '';
  const hist = useLoad(async () => {
    const d = await get<{ items?: Record<string, unknown>[]; photos?: Record<string, unknown>[]; counts?: Record<string, number> }>(`/api/cleanup/history${q}`);
    const items: CleanItem[] = (d.items ?? d.photos ?? []).map((i) => ({
      id: String(i.id), thumb_url: (i.thumb_url as string | null) ?? null, blur_score: typeof i.blur_score === 'number' ? i.blur_score : null,
      reason: (['auto_skipped', 'deleted', 'flagged'].includes(i.reason as string) ? i.reason : 'auto_skipped') as CleanReason, when: (i.when as string | null) ?? null,
    }));
    return { items, counts: d.counts ?? {} };
  }, [q]);
  const [scope, setScope] = useState<'room' | 'all'>('room');
  const [filter, setFilter] = useState<'all' | CleanReason>('all');
  const list = useLoad(async () => {
    const d = await get<{ photos?: Record<string, unknown>[]; gallery?: Record<string, unknown>[] }>('/api/cleanup/blurry');
    const photos: BlurryItem[] = (d.photos ?? []).map((p) => ({ key: 'm' + p.media_id, media_id: String(p.media_id), memory_id: String(p.memory_id), thumb_url: p.thumb_url as string | null, score: p.score as number | null, room: p.room as BlurryItem['room'] }));
    const gal: BlurryItem[] = (d.gallery ?? []).map((p) => ({ key: 'g' + p.gallery_item_id, gallery_item_id: String(p.gallery_item_id), thumb_url: p.thumb_url as string | null, score: p.score as number | null, name: p.name as string }));
    return [...photos, ...gal];
  }, []);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [confirm, setConfirm] = useState(false);
  const all = list.data ?? [];
  const inRoom = (i: BlurryItem) => !!room && i.room?.year === room.year && i.room?.month === room.month;
  const items = scope === 'room' && room ? all.filter(inRoom) : all;
  const toggle = (id: string) => setSel((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const split = (xs: BlurryItem[]) => ({ media_ids: xs.filter((i) => i.media_id).map((i) => i.media_id!), gallery_item_ids: xs.filter((i) => i.gallery_item_id).map((i) => i.gallery_item_id!) });
  const apply = useAction(async (mode: 'delete' | 'keep') => {
    const chosen = items.filter((i) => sel.has(i.key));
    const rest = items.filter((i) => !sel.has(i.key));
    await post(mode === 'delete' ? '/api/cleanup/blurry/delete' : '/api/cleanup/blurry/keep', split(mode === 'delete' ? chosen : rest));
    setSel(new Set()); setConfirm(false); list.reload(); hist.reload(); await refreshRoom();
  });

  const h = hist.data?.items ?? [];
  const count = (r: CleanReason) => (typeof hist.data?.counts[r] === 'number' ? hist.data.counts[r] : h.filter((i) => i.reason === r).length);
  const shown = filter === 'all' ? h : h.filter((i) => i.reason === filter);
  const where = room ? `${monthName(room.month)} ${room.year}` : 'this room';
  const nothing = !hist.loading && !hist.error && h.length === 0;
  return (
    <Modal title="Cleaned up for you" size="lg" onClose={() => close(null)} busy={apply.busy}>
      <section className="stack" aria-labelledby="clean-h">
        <h3 id="clean-h" className="sr-only">Blurry photos in {where}</h3>
        {hist.loading && <Spinner text="Checking what Memo tidied up" />}
        {hist.error && <p className="muted">The clean-up history for {where} is not available right now. Photos waiting for you are below.</p>}
        {nothing && (
          <div className="clean-empty">
            <PixelCheck />
            <div><p className="clean-empty-title">Nothing blurry this month — every photo was sharp</p><p className="muted" style={{ fontSize: 13 }}>Memo checks every photo in {where} and keeps shaky ones off the screen for you.</p></div>
          </div>
        )}
        {h.length > 0 && (
          <>
            <p className="clean-summary" aria-live="polite">
              In {where}, Memo kept <strong>{count('auto_skipped')}</strong> blurry photo{count('auto_skipped') === 1 ? '' : 's'} off the screen, <strong>{count('deleted')}</strong> {count('deleted') === 1 ? 'was' : 'were'} deleted and <strong>{count('flagged')}</strong> {count('flagged') === 1 ? 'is' : 'are'} waiting for you.
            </p>
            <div className="seg" role="radiogroup" aria-label="Show">
              {(['all', 'auto_skipped', 'deleted', 'flagged'] as const).map((f) => (
                <button key={f} type="button" role="radio" aria-checked={filter === f} onClick={() => setFilter(f)}>{f === 'all' ? `All ${h.length}` : `${REASON[f].label} ${count(f)}`}</button>
              ))}
            </div>
            <ul className="clean-grid" aria-label="Cleaned-up photos">
              {shown.map((i) => (
                <li key={i.id} className="clean-card">
                  <div className="clean-thumb">{i.thumb_url ? <img src={i.thumb_url} alt="" loading="lazy" /> : <span className="muted">No preview</span>}</div>
                  <div className="clean-meta">
                    <span className={'chip ' + REASON[i.reason].chip}>{REASON[i.reason].label}</span>
                    {i.blur_score !== null && <span className="clean-score" title="Sharpness score: lower is blurrier">Blur {Math.round(i.blur_score)}</span>}
                  </div>
                  <span className="sr-only">Photo {REASON[i.reason].long}{i.blur_score !== null ? `, sharpness ${Math.round(i.blur_score)}` : ''}{i.when ? `, ${fmtWhen(i.when)}` : ''}</span>
                  {i.when && <span className="clean-when" aria-hidden="true">{fmtWhen(i.when)}</span>}
                </li>
              ))}
              {shown.length === 0 && <li className="muted">None in this group.</li>}
            </ul>
          </>
        )}
      </section>

      <section className="stack clean-review" aria-labelledby="review-h">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h3 id="review-h">Waiting for your say</h3>
          {room && (
            <div className="seg" role="radiogroup" aria-label="Which rooms">
              <button type="button" role="radio" aria-checked={scope === 'room'} onClick={() => { setScope('room'); setSel(new Set()); }}>This room</button>
              <button type="button" role="radio" aria-checked={scope === 'all'} onClick={() => { setScope('all'); setSel(new Set()); }}>All rooms</button>
            </div>
          )}
        </div>
        <p className="muted" style={{ fontSize: 13 }}>Tap the ones to delete, then confirm. "Keep the rest" leaves the others on the wall and stops flagging them.</p>
        {list.loading && <Spinner text="Looking for blurry photos" />}
        {list.error && <p className="err">{list.error}</p>}
        {!list.loading && !list.error && items.length === 0 && <p className="muted">Nothing waiting{scope === 'room' && room ? ` in ${where}` : ''}.</p>}
        <div className="gallery-grid">
          {items.map((i) => (
            <button key={i.key} type="button" className="thumb" aria-pressed={sel.has(i.key)} onClick={() => toggle(i.key)} aria-label={`${i.name ?? 'Photo'}${i.room ? ', ' + monthName(i.room.month) + ' ' + i.room.year : ''}${typeof i.score === 'number' ? `, blur ${Math.round(i.score)}` : ''}. ${sel.has(i.key) ? 'Marked for deletion' : 'Kept'}`}>
              {i.thumb_url && <img src={i.thumb_url} alt="" loading="lazy" />}
              {typeof i.score === 'number' && <span className="thumb-score" aria-hidden="true">{Math.round(i.score)}</span>}
            </button>
          ))}
        </div>
        {items.length > 0 && (
          <div className="row">
            <button type="button" className="btn" onClick={() => setSel(new Set(items.map((i) => i.key)))}>Select all</button>
            <button type="button" className="btn" onClick={() => setSel(new Set())} disabled={sel.size === 0}>Clear</button>
            <button type="button" className="btn btn-danger" disabled={sel.size === 0} onClick={() => setConfirm(true)}>Delete {sel.size} selected</button>
            <button type="button" className="btn btn-primary" onClick={() => void apply.run('keep')} disabled={apply.busy || sel.size === items.length}>Keep the rest</button>
          </div>
        )}
        {apply.error && !confirm && <p className="err" role="alert">{apply.error}</p>}
      </section>
      {confirm && <ConfirmModal title={`Delete ${sel.size} photo${sel.size === 1 ? '' : 's'}?`} danger confirmLabel={`Yes, delete ${sel.size}`} busy={apply.busy} error={apply.error} onCancel={() => setConfirm(false)} onConfirm={() => void apply.run('delete')}><p>The marked photos will be removed from their rooms for good.</p></ConfirmModal>}
    </Modal>
  );
}

function PixelCheck() {
  const px: [number, number][] = [[9, 2], [8, 3], [9, 3], [7, 4], [8, 4], [6, 5], [7, 5], [1, 5], [2, 5], [2, 6], [3, 6], [5, 6], [6, 6], [3, 7], [4, 7], [5, 7], [4, 8]];
  return <svg className="clean-check" width="44" height="44" viewBox="0 0 11 11" shapeRendering="crispEdges" aria-hidden="true"><rect width="11" height="11" fill="var(--green-tint)" />{px.map(([x, y]) => <rect key={x + ',' + y} x={x} y={y} width="1" height="1" fill="var(--green)" />)}</svg>;
}
