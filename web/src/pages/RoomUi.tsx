import { useEffect, useRef, useState } from 'react';
import { del, get, listOf, patch, post } from '../api/client';
import type { BlurryItem, Reel } from '../api/types';
import type { Exhibit } from '../contract';
import { useWorld } from '../state/worldStore';
import { ConfirmModal, Field, MONTHS, Modal, Spinner, monthName, useAction, useLoad } from '../ui/common';

const canEdit = () => { const m = useWorld.getState().museum; return !!m && !m.me.is_guest && m.me.role !== 'viewer'; };

async function refreshRoom() {
  const s = useWorld.getState();
  if (s.room) await s.loadRoom(s.room.year, s.room.month, s.room.eventId).catch(() => undefined);
  await s.loadShowcase().catch(() => undefined);
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
        <button className="btn btn-sm" onClick={() => open('cleanup')}>Blurry photos</button>
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
              {r.status === 'ready' && r.url && <><button className="btn btn-sm btn-primary" onClick={() => setPlaying(r)}>Play</button><a className="btn btn-sm" href={r.url} download>Download</a></>}
            </div>
          </div>
        ))}
        {list.data?.length === 0 && <p className="muted">No reels yet.</p>}
      </div>
      {playing?.url && <Modal title={`${monthName(playing.month)} ${playing.year}`} onClose={() => setPlaying(null)} size="lg"><video src={playing.url} controls autoPlay style={{ width: '100%', background: '#000', maxHeight: '70dvh' }} /></Modal>}
    </Modal>
  );
}

export function CleanupPanel() {
  const close = useWorld((s) => s.openPanel);
  const list = useLoad(async () => {
    const d = await get<{ photos?: Record<string, unknown>[]; gallery?: Record<string, unknown>[] }>('/api/cleanup/blurry');
    const photos: BlurryItem[] = (d.photos ?? []).map((p) => ({ key: 'm' + p.media_id, media_id: String(p.media_id), memory_id: String(p.memory_id), thumb_url: p.thumb_url as string | null, score: p.score as number | null, room: p.room as BlurryItem['room'] }));
    const gal: BlurryItem[] = (d.gallery ?? []).map((p) => ({ key: 'g' + p.gallery_item_id, gallery_item_id: String(p.gallery_item_id), thumb_url: p.thumb_url as string | null, score: p.score as number | null, name: p.name as string }));
    return [...photos, ...gal];
  }, []);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [confirm, setConfirm] = useState(false);
  const items = list.data ?? [];
  const toggle = (id: string) => setSel((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const split = (xs: BlurryItem[]) => ({ media_ids: xs.filter((i) => i.media_id).map((i) => i.media_id!), gallery_item_ids: xs.filter((i) => i.gallery_item_id).map((i) => i.gallery_item_id!) });
  const apply = useAction(async (mode: 'delete' | 'keep') => {
    const chosen = items.filter((i) => sel.has(i.key));
    const rest = items.filter((i) => !sel.has(i.key));
    await post(mode === 'delete' ? '/api/cleanup/blurry/delete' : '/api/cleanup/blurry/keep', split(mode === 'delete' ? chosen : rest));
    setSel(new Set()); setConfirm(false); list.reload(); await refreshRoom();
  });
  return (
    <Modal title="Blurry photos" size="lg" onClose={() => close(null)}>
      <p className="muted">These photos look out of focus. Tap the ones to delete, then confirm. "Keep the rest" leaves the others on the wall and stops flagging them.</p>
      {list.loading && <Spinner text="Looking for blurry photos" />}
      {list.error && <p className="err">{list.error}</p>}
      {!list.loading && items.length === 0 && <p>No blurry photos found.</p>}
      <div className="gallery-grid">
        {items.map((i) => (
          <button key={i.key} className="thumb" aria-pressed={sel.has(i.key)} onClick={() => toggle(i.key)} aria-label={`${i.name ?? 'Photo'}${i.room ? ', ' + monthName(i.room.month) + ' ' + i.room.year : ''}. ${sel.has(i.key) ? 'Marked for deletion' : 'Kept'}`}>
            {i.thumb_url && <img src={i.thumb_url} alt="" loading="lazy" />}
          </button>
        ))}
      </div>
      {items.length > 0 && (
        <div className="row">
          <button className="btn" onClick={() => setSel(new Set(items.map((i) => i.key)))}>Select all</button>
          <button className="btn" onClick={() => setSel(new Set())} disabled={sel.size === 0}>Clear</button>
          <button className="btn btn-danger" disabled={sel.size === 0} onClick={() => setConfirm(true)}>Delete {sel.size} selected</button>
          <button className="btn btn-primary" onClick={() => void apply.run('keep')} disabled={apply.busy || sel.size === items.length}>Keep the rest</button>
        </div>
      )}
      {apply.error && !confirm && <p className="err" role="alert">{apply.error}</p>}
      {confirm && <ConfirmModal title={`Delete ${sel.size} photo${sel.size === 1 ? '' : 's'}?`} danger confirmLabel={`Yes, delete ${sel.size}`} busy={apply.busy} error={apply.error} onCancel={() => setConfirm(false)} onConfirm={() => void apply.run('delete')}><p>The marked photos will be removed from their rooms for good.</p></ConfirmModal>}
    </Modal>
  );
}
