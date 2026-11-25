import { useEffect, useMemo, useRef, useState } from 'react';
import { del, get, listOf, patch, post, upload } from '../api/client';
import type { Contact, EventRec, GalleryFilter, GalleryQueryResult, Invite } from '../api/types';
import { useWorld } from '../state/worldStore';
import { useVoiceUi, voice } from '../voice/controller';
import { ConfirmModal, Field, MONTHS, Modal, Orb, Spinner, fmtBytes, monthName, useAction, useLoad } from '../ui/common';
import { filterLocal, isImage, readLocalPhoto, type LocalPhoto } from '../lib/exif';

type Tab = 'talk' | 'photos';
type Sub = null | 'event' | 'room' | 'contacts' | 'invites';
const TABS: [Tab, string][] = [['talk', 'Talk'], ['photos', 'Photos']];

export function ReceptionPanel() {
  const close = useWorld((s) => s.openPanel);
  const [tab, setTab] = useState<Tab>('talk');
  const [sub, setSub] = useState<Sub>(null);
  const [eventForPhotos, setEventForPhotos] = useState<string | null>(null);
  return (
    <Modal title="Reception" size="lg" onClose={() => close(null)}>
      <div className="tabs" role="tablist" aria-label="Reception">
        {TABS.map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>{label}</button>)}
      </div>
      <div className="btn-row" aria-label="Quick actions">
        <button className="btn btn-sm" onClick={() => setSub('event')}>New event</button>
        <button className="btn btn-sm" onClick={() => setSub('room')}>Go to a room</button>
        <button className="btn btn-sm" onClick={() => setSub('contacts')}>Contacts</button>
        <button className="btn btn-sm" onClick={() => setSub('invites')}>Invites</button>
      </div>
      {tab === 'talk' && <TalkTab />}
      {tab === 'photos' && <PhotosTab initialEvent={eventForPhotos} />}
      {sub === 'event' && <Modal title="New event" size="md" onClose={() => setSub(null)}><EventTab onAddPhotos={(id) => { setEventForPhotos(id); setTab('photos'); setSub(null); }} /></Modal>}
      {sub === 'room' && <Modal title="Go to a room" size="lg" onClose={() => setSub(null)}><RoomTab /></Modal>}
      {sub === 'contacts' && <Modal title="Contacts" size="md" onClose={() => setSub(null)}><ContactsTab /></Modal>}
      {sub === 'invites' && <Modal title="Invites" size="md" onClose={() => setSub(null)}><InvitesTab /></Modal>}
    </Modal>
  );
}

function TalkTab() {
  const ui = useVoiceUi();
  const museum = useWorld((s) => s.museum);
  const [text, setText] = useState('');
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }); }, [ui.thread.length]);
  const hint = museum?.flags?.voice_enabled === false ? 'Voice is off, so type or use the other tabs.' : 'Say it or type it. Everything here also has a button.';
  return (
    <div className="stack">
      <p className="muted">{hint}</p>
      <div className="list" style={{ maxHeight: 280, overflow: 'auto' }} aria-live="polite">
        {ui.thread.length === 0 && <p className="muted">Try: "Add a new festival called Diwali", "Upload everything from yesterday", or "Take me to March 2025".</p>}
        {ui.thread.map((t, i) => (
          <div key={i} className="item" style={{ justifyContent: t.who === 'you' ? 'flex-end' : 'flex-start', background: t.who === 'you' ? 'var(--teal-tint)' : undefined }}>
            <span>{t.label && <em className="muted">{t.label} </em>}{t.text}</span>
          </div>
        ))}
        <div ref={end} />
      </div>
      {ui.busy && <div className="row"><Orb state="working" size={32} label="The receptionist is working" /><span className="muted">{ui.toolSteps[ui.toolSteps.length - 1] ?? 'Working on it'}</span></div>}
      {ui.toolSteps.length > 0 && !ui.busy && <div className="row">{ui.toolSteps.map((s, i) => <span key={i} className="chip chip--warn">{s}</span>)}</div>}
      {ui.pending && (
        <div className="plaque" role="group" aria-label="The receptionist is waiting for your answer">
          <p>Waiting for your answer.</p>
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn btn-primary" onClick={() => void voice.sendText('Yes')} disabled={ui.busy}>Yes</button>
            <button className="btn" onClick={() => void voice.sendText('No')} disabled={ui.busy}>No</button>
          </div>
        </div>
      )}
      {ui.error && <p className="err" role="alert">{ui.error}</p>}
      <form className="row" style={{ flexWrap: 'nowrap' }} onSubmit={(e) => { e.preventDefault(); const t = text; setText(''); void voice.sendText(t); }}>
        <input className="input grow" value={text} onChange={(e) => setText(e.target.value)} placeholder="Type to the receptionist" aria-label="Message to the receptionist" />
        <button className="btn btn-primary" disabled={!text.trim() || ui.busy}>Send</button>
      </form>
    </div>
  );
}

function EventTab({ onAddPhotos }: { onAddPhotos: (id: string) => void }) {
  const now = new Date();
  const [name, setName] = useState('');
  const [kind, setKind] = useState('festival');
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [made, setMade] = useState<{ event: EventRec; level: number; state?: string } | null>(null);
  const a = useAction(async () => {
    const r = await post<{ event: EventRec; level: number; room_state?: string; room?: { year: number; month: number } }>('/api/events', { name: name.trim(), kind, year, month });
    setMade({ event: r.event, level: r.level, state: r.room_state });
    await useWorld.getState().refreshMuseum();
    await useWorld.getState().loadFloor(year, true).catch(() => undefined);
  });
  return (
    <form className="stack" onSubmit={(e) => { e.preventDefault(); void a.run(); }}>
      <Field label="Event name"><input className="input" required value={name} onChange={(e) => setName(e.target.value)} placeholder="Diwali" /></Field>
      <div className="row">
        <Field label="Kind"><select className="input" value={kind} onChange={(e) => setKind(e.target.value)}>{['festival', 'trip', 'birthday', 'other'].map((k) => <option key={k}>{k}</option>)}</select></Field>
        <Field label="Year"><input className="input" type="number" min={1900} max={2100} value={year} onChange={(e) => setYear(+e.target.value)} /></Field>
        <Field label="Month"><select className="input" value={month} onChange={(e) => setMonth(+e.target.value)}>{MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}</select></Field>
      </div>
      <button className="btn btn-primary" disabled={a.busy || !name.trim()}>Create event</button>
      {a.error && <p className="err" role="alert">{a.error}</p>}
      {made && (
        <div className="plaque" role="status">
          <p>{made.event.name} {made.event.year} is added. It lives on floor {made.level}, in the {monthName(made.event.month)} room. A room with no memories keeps its door shut.</p>
          <div className="row" style={{ marginTop: 8 }}><button type="button" className="btn btn-brass" onClick={() => onAddPhotos(made.event.id)}>Add photos</button></div>
        </div>
      )}
    </form>
  );
}

function PhotosTab({ initialEvent }: { initialEvent: string | null }) {
  const events = useLoad(() => get<unknown>('/api/events').then((d) => listOf<EventRec>(d, 'events')), []);
  const [eventId, setEventId] = useState(initialEvent ?? '');
  const [source, setSource] = useState<'folder' | 'browser'>('folder');
  const [local, setLocal] = useState<LocalPhoto[]>([]);
  const [scan, setScan] = useState<string | null>(null);
  const [mode, setMode] = useState<'all' | 'latest' | 'range' | 'day'>('latest');
  const [n, setN] = useState(20);
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [camera, setCamera] = useState('');
  const [maxMb, setMaxMb] = useState('');
  const [q, setQ] = useState<GalleryQueryResult | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const importLimit = Number(useWorld.getState().museum?.flags?.import_limit ?? 200) || 200;
  const hasPicker = typeof (window as unknown as { showDirectoryPicker?: unknown }).showDirectoryPicker === 'function';
  useEffect(() => { if (events.data && !eventId && events.data[0]) setEventId(events.data[0].id); }, [events.data, eventId]);

  const filter = useMemo<GalleryFilter>(() => {
    const f: GalleryFilter = {};
    if (mode === 'all') f.all = true;
    if (mode === 'latest') f.latest_n = n;
    if (mode === 'range') { if (from) f.date_from = from; if (to) f.date_to = to; }
    if (mode === 'day') { f.date_from = from; f.date_to = from; }
    if (camera) f.camera = camera;
    if (maxMb) f.max_size = Math.round(+maxMb * 1024 * 1024);
    return f;
  }, [mode, n, from, to, camera, maxMb]);

  const doScan = useAction(async () => {
    setQ(null); setDone(null);
    if (source === 'folder') {
      const r = await post<{ scanned: number; new: number }>('/api/gallery/scan', {});
      setScan(`${r.scanned} photos seen, ${r.new} new.`);
    } else {
      setScan(`${local.length} photos read from this computer. Nothing is uploaded until you confirm.`);
    }
  });
  const doQuery = useAction(async () => {
    setDone(null);
    if (source === 'browser') {
      // Browser pick: the files stay here until confirmed. Count locally with the same rules the server uses.
      const chosen = filterLocal(local, filter as Parameters<typeof filterLocal>[1]);
      setQ({ count: chosen.length, total_bytes: chosen.reduce((a, p) => a + p.size, 0), preview_token: '', over_limit: chosen.length > importLimit, limit: importLimit, sample: [] });
      return;
    }
    const r = await post<GalleryQueryResult>('/api/gallery/query', { ...filter });
    setQ(r);
  });
  const doImport = useAction(async () => {
    if (!q) return;
    let token = q.preview_token;
    if (source === 'browser') {
      // Upload only the confirmed files (meta list + files), then ask the server for the matching preview token.
      const chosen = filterLocal(local, filter as Parameters<typeof filterLocal>[1]).slice(-(q.limit || importLimit));
      const label = `browser-${Date.now()}`;
      for (let i = 0; i < chosen.length; i += 12) {
        const part = chosen.slice(i, i + 12);
        const fd = new FormData();
        fd.append('meta', JSON.stringify(part.map((p) => ({ name: p.name, path: p.name, folder: label, last_modified: new Date(p.taken_at).getTime(), taken_at: p.taken_at, camera: p.camera }))));
        part.forEach((p) => fd.append('files', p.file, p.name));
        await upload('/api/gallery/scan', fd);
      }
      const r2 = await post<GalleryQueryResult>('/api/gallery/query', { folder: label, all: true });
      token = r2.preview_token;
    }
    const r = await post<{ job_id: string; count: number }>('/api/gallery/import', { preview_token: token, event_id: eventId });
    setDone(`Import started: ${r.count} photos. You will see a card here when they are on the wall.`);
    setQ(null);
  });

  async function pickFolder() {
    try {
      const dir = await (window as unknown as { showDirectoryPicker: () => Promise<{ name: string; values(): AsyncIterable<{ kind: string; getFile(): Promise<File> }> }> }).showDirectoryPicker();
      const out: LocalPhoto[] = [];
      for await (const h of dir.values()) { if (h.kind === 'file') { const f = await h.getFile(); if (isImage(f)) out.push(await readLocalPhoto(f, dir.name)); } }
      setLocal(out);
    } catch { /* cancelled */ }
  }
  async function onFiles(files: FileList | null) {
    if (!files) return;
    const out: LocalPhoto[] = [];
    for (const f of Array.from(files)) if (isImage(f)) out.push(await readLocalPhoto(f, (f as File & { webkitRelativePath?: string }).webkitRelativePath?.split('/')[0] || null));
    setLocal(out);
  }
  const localSize = local.reduce((a, p) => a + p.size, 0);
  const ready = source === 'folder' || local.length > 0;

  return (
    <div className="stack">
      <Field label="Where are the photos?">
        <div className="seg" role="radiogroup" aria-label="Photo source">
          <button role="radio" aria-checked={source === 'folder'} onClick={() => setSource('folder')}>Gallery folder</button>
          <button role="radio" aria-checked={source === 'browser'} onClick={() => setSource('browser')}>This computer</button>
        </div>
      </Field>
      {source === 'browser' && (
        <div className="row">
          {hasPicker && <button className="btn" onClick={() => void pickFolder()}>Pick a folder</button>}
          <button className="btn" onClick={() => fileRef.current?.click()}>Choose photos</button>
          <input ref={fileRef} type="file" accept="image/*" multiple hidden onChange={(e) => void onFiles(e.target.files)} />
          {local.length > 0 && <span className="chip chip--teal">{local.length} photos, {fmtBytes(localSize)}</span>}
          <span className="muted" style={{ fontSize: 13 }}>Only the photos you confirm are uploaded.</span>
        </div>
      )}
      <div className="row"><button className="btn" onClick={() => void doScan.run()} disabled={doScan.busy || !ready}>{source === 'folder' ? 'Scan the folder' : 'Read dates'}</button>{scan && <span className="ok">{scan}</span>}</div>
      {doScan.error && <p className="err" role="alert">{doScan.error}</p>}

      <Field label="Which photos?">
        <div className="seg" role="radiogroup" aria-label="Photo filter">
          {([['latest', 'Latest'], ['day', 'One day'], ['range', 'Date range'], ['all', 'All']] as const).map(([id, l]) => <button key={id} role="radio" aria-checked={mode === id} onClick={() => setMode(id)}>{l}</button>)}
        </div>
      </Field>
      <div className="row">
        {mode === 'latest' && <Field label="How many"><input className="input" type="number" min={1} value={n} onChange={(e) => setN(+e.target.value)} /></Field>}
        {(mode === 'day' || mode === 'range') && <Field label={mode === 'day' ? 'Day' : 'From'}><input className="input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>}
        {mode === 'range' && <Field label="To"><input className="input" type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>}
        <Field label="Camera (optional)"><input className="input" value={camera} onChange={(e) => setCamera(e.target.value)} /></Field>
        <Field label="Max size, MB (optional)"><input className="input" type="number" min={0} value={maxMb} onChange={(e) => setMaxMb(e.target.value)} /></Field>
      </div>
      <button className="btn" onClick={() => void doQuery.run()} disabled={doQuery.busy || !ready || ((mode === 'day' || mode === 'range') && !from)}>Count them</button>
      {doQuery.error && <p className="err" role="alert">{doQuery.error}</p>}

      {q && (
        <div className="plaque" role="group" aria-label="Confirm the import">
          <p><strong>{q.count} photos, {fmtBytes(q.total_bytes)}.</strong>{q.over_limit && ` That is more than one import allows (${q.limit}). Only the newest ${q.limit} will be added.`}</p>
          {q.count === 0 ? <p className="muted">Nothing matched. Try a wider filter.</p> : (
            <>
              <Field label="Add them to which event?">
                <select className="input" value={eventId} onChange={(e) => setEventId(e.target.value)} aria-label="Event">
                  {(events.data ?? []).map((ev) => <option key={ev.id} value={ev.id}>{ev.name} {ev.year}</option>)}
                </select>
              </Field>
              {events.data?.length === 0 && <p className="err">Create an event first.</p>}
              {q.sample && q.sample.length > 0 && <div className="gallery-grid" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(64px,1fr))', marginTop: 8 }}>{q.sample.slice(0, 8).map((s, i) => s.thumb_url ? <img key={i} src={s.thumb_url} alt={s.name ?? 'Photo'} style={{ width: '100%', aspectRatio: '1', objectFit: 'cover' }} /> : null)}</div>}
              <div className="row" style={{ marginTop: 8 }}>
                <button className="btn btn-primary" disabled={doImport.busy || !eventId} onClick={() => void doImport.run()}>Add {Math.min(q.count, q.limit || q.count)} photos</button>
                <button className="btn" onClick={() => setQ(null)}>Cancel</button>
              </div>
            </>
          )}
        </div>
      )}
      {doImport.busy && <Spinner text="Uploading and starting the import" />}
      {doImport.error && <p className="err" role="alert">{doImport.error}</p>}
      {done && <p className="ok" role="status">{done}</p>}
    </div>
  );
}

export function RoomTab() {
  const museum = useWorld((s) => s.museum);
  const floorRooms = useWorld((s) => s.floorRooms);
  const loadFloor = useWorld((s) => s.loadFloor);
  const goTo = useWorld((s) => s.goTo);
  const [year, setYear] = useState(museum?.floors[0]?.year ?? new Date().getFullYear());
  useEffect(() => { void loadFloor(year).catch(() => undefined); }, [year, loadFloor]);
  const rooms = floorRooms[year] ?? [];
  return (
    <div className="stack">
      <Field label="Floor"><select className="input" value={year} onChange={(e) => setYear(+e.target.value)}>{(museum?.floors ?? []).map((f) => <option key={f.year} value={f.year}>{f.year} (floor {f.level}, {f.open} of 12 open)</option>)}</select></Field>
      <div className="months">
        {rooms.map((r) => (
          <button key={r.month} className={`month month--${r.state}`} onClick={() => void goTo(r.year, r.month)} aria-label={`${monthName(r.month)} ${r.year}, ${r.state.replace('_', ' ')}`}>
            <span className="month-name">{monthName(r.month).slice(0, 3)}</span>
            <span className="chip">{r.state === 'open' ? `${r.memory_count} ${r.memory_count === 1 ? 'memory' : 'memories'}` : r.state.replace('_', ' ')}</span>
          </button>
        ))}
      </div>
      {rooms.some((r) => r.events.length > 0) && (
        <div className="stack"><h3>Events</h3>{rooms.flatMap((r) => r.events.map((e) => <button key={e.id} className="btn" onClick={() => void goTo(r.year, r.month, e.id)}>{e.name}, {monthName(r.month)} {r.year}</button>))}</div>
      )}
    </div>
  );
}

function ContactsTab() {
  const list = useLoad(() => get<unknown>('/api/contacts').then((d) => listOf<Contact>(d, 'contacts')), []);
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<Contact | null>(null);
  const rm = useAction(async (id: string) => { await del(`/api/contacts/${id}`); setRemoving(null); list.reload(); });
  const dnc = useAction(async (id: string) => { await patch(`/api/contacts/${id}`, { do_not_call: true }); list.reload(); });
  return (
    <div className="stack">
      <p className="muted">Numbers are typed here, never spoken, so a misheard digit cannot call a stranger.</p>
      <div className="row"><button className="btn btn-primary" onClick={() => setAdding(true)}>Add contact</button></div>
      {list.loading && <Spinner text="Loading contacts" />}
      {list.error && <p className="err">{list.error}</p>}
      <div className="list">
        {(list.data ?? []).map((c) => (
          <div key={c.id} className="item">
            <div><div className="item-title">{c.name}{c.relation ? `, ${c.relation}` : ''}</div><div className="muted mono" style={{ fontSize: 13 }}>ends {c.phone_last4 ?? c.phone_e164?.slice(-4) ?? '----'}</div></div>
            <div className="row">
              {c.do_not_call ? <span className="chip chip--bad">Do not call</span> : c.consent_to_calls ? <span className="chip chip--ok">Agreed to calls</span> : <span className="chip chip--warn">No consent</span>}
              {!c.do_not_call && <button className="btn btn-sm" onClick={() => void dnc.run(c.id)}>Stop calling</button>}
              <button className="btn btn-sm btn-danger" onClick={() => setRemoving(c)}>Remove</button>
            </div>
          </div>
        ))}
        {list.data?.length === 0 && <p className="muted">No contacts yet.</p>}
      </div>
      {adding && <AddContactModal onClose={() => setAdding(false)} onAdded={() => { setAdding(false); list.reload(); }} />}
      {removing && <ConfirmModal title="Remove this contact?" danger confirmLabel="Remove" busy={rm.busy} error={rm.error} onCancel={() => setRemoving(null)} onConfirm={() => void rm.run(removing.id)}><p>{removing.name} will no longer be on the list. Their past invites stay in the history.</p></ConfirmModal>}
    </div>
  );
}

function AddContactModal({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const [name, setName] = useState(''); const [relation, setRelation] = useState(''); const [phone, setPhone] = useState(''); const [consent, setConsent] = useState(false);
  const add = useAction(async () => {
    await post('/api/contacts', { name: name.trim(), relation: relation.trim() || null, phone: phone.trim(), consent_to_calls: consent, language: useWorld.getState().language });
    onAdded();
  });
  const ok = !!name.trim() && !!phone.trim() && consent;
  return (
    <Modal title="Add a contact" size="md" onClose={onClose} busy={add.busy} footer={
      <>
        <button className="btn" onClick={onClose} disabled={add.busy}>Cancel</button>
        <button className="btn btn-primary" type="submit" form="add-contact" disabled={add.busy || !ok}>Add contact</button>
      </>
    }>
      <form id="add-contact" className="stack" onSubmit={(e) => { e.preventDefault(); if (ok) void add.run(); }}>
        <Field label="Name"><input className="input" required value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Relation"><input className="input" value={relation} onChange={(e) => setRelation(e.target.value)} placeholder="cousin" /></Field>
        <Field label="Phone with country code"><input className="input" required type="tel" inputMode="tel" pattern="\+?[0-9 ()-]{8,18}" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+91 98765 43210" /></Field>
        <label className="check"><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} /><span>This person has agreed to get calls from Memo.</span></label>
        {add.error && <p className="err" role="alert">{add.error}</p>}
      </form>
    </Modal>
  );
}

const CALL_LABEL: Record<string, string> = { queued: 'Queued', dialling: 'Dialling', ringing: 'Ringing', talking: 'Talking', accepted: 'Accepted', declined: 'Declined', no_answer: 'No answer', message_left: 'Left a message', failed: 'Failed' };

export function InvitesTab() {
  const tick = useWorld((s) => s.invitesTick);
  const room = useWorld((s) => s.room);
  const museum = useWorld((s) => s.museum);
  const contacts = useLoad(() => get<unknown>('/api/contacts').then((d) => listOf<Contact>(d, 'contacts')), []);
  const invites = useLoad(() => get<unknown>('/api/invites').then((d) => listOf<Invite>(d, 'invites')), [tick]);
  const [contactId, setContactId] = useState('');
  const [year, setYear] = useState(room?.year ?? museum?.floors[0]?.year ?? new Date().getFullYear());
  const [month, setMonth] = useState(room?.month ?? new Date().getMonth() + 1);
  const [pending, setPending] = useState<{ invite: Invite; text: string } | null>(null);
  useEffect(() => { if (!contactId && contacts.data?.[0]) setContactId(contacts.data[0].id); }, [contacts.data, contactId]);
  const create = useAction(async () => {
    const r = await post<{ invite: Invite; confirm_text?: string; text?: string }>('/api/invites', { contact_id: contactId, year, month, event_id: room?.eventId ?? null });
    setPending({ invite: r.invite, text: r.confirm_text ?? r.text ?? 'Place the call?' });
    invites.reload();
  });
  const call = useAction(async (id: string) => { await post(`/api/invites/${id}/call`, {}); setPending(null); invites.reload(); });
  const reload = invites.reload;
  useEffect(() => { const t = setInterval(reload, 15000); return () => clearInterval(t); }, [reload]);
  return (
    <div className="stack">
      <form className="stack" onSubmit={(e) => { e.preventDefault(); void create.run(); }}>
        <Field label="Who"><select className="input" value={contactId} onChange={(e) => setContactId(e.target.value)}>{(contacts.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
        <Field label="Year"><input className="input" type="number" value={year} onChange={(e) => setYear(+e.target.value)} /></Field>
        <Field label="Month"><select className="input" value={month} onChange={(e) => setMonth(+e.target.value)}>{MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}</select></Field>
        <button className="btn btn-primary" disabled={!contactId || create.busy}>Create invite</button>
      </form>
      {create.error && <p className="err" role="alert">{create.error}</p>}
      {contacts.data?.length === 0 && <p className="muted">Add a contact first.</p>}
      {pending && <ConfirmModal title="Place the call?" confirmLabel="Yes, call now" cancelLabel="Not now" busy={call.busy} error={call.error} onCancel={() => setPending(null)} onConfirm={() => void call.run(pending.invite.id)}><p>{pending.text}</p></ConfirmModal>}
      <div className="list" aria-live="polite">
        {(invites.data ?? []).map((i) => (
          <div key={i.id} className="item">
            <div><div className="item-title">{i.contact_name ?? 'Guest'}, {monthName(i.month)} {i.year}</div>{(i.call?.summary || i.call?.message) && <div className="muted" style={{ fontSize: 13 }}>{i.call?.message || i.call?.summary}</div>}</div>
            <span className={'chip ' + (['accepted'].includes(i.call?.status ?? '') ? 'chip--ok' : ['failed', 'declined'].includes(i.call?.status ?? '') ? 'chip--bad' : 'chip--teal')}>{CALL_LABEL[i.call?.status ?? ''] ?? i.status}</span>
          </div>
        ))}
        {invites.data?.length === 0 && <p className="muted">No invites yet.</p>}
      </div>
    </div>
  );
}

