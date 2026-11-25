import { useEffect, useState } from 'react';
import { del, get, listOf, patch, post } from '../api/client';
import type { FamilySettings, JobRec, Member } from '../api/types';
import type { Exhibit, Lang } from '../contract';
import { useWorld } from '../state/worldStore';
import { ConfirmModal, Field, Modal, LANGS, MONTHS, Spinner, monthName, useAction, useLoad } from '../ui/common';
import { RoomTab } from './Reception';

export function LiftPanel() {
  const museum = useWorld((s) => s.museum);
  const ride = useWorld((s) => s.rideLift);
  const close = useWorld((s) => s.openPanel);
  const level = useWorld((s) => s.currentLevel);
  return (
    <Modal title="Lift" size="sm" onClose={() => close(null)}>
      <p className="muted">Floor 0 is the oldest year with memories, beside the lobby. Each later year is one floor up.</p>
      <div className="lift-btns">
        {(museum?.floors ?? []).map((f) => (
          <button key={f.year} className={'btn' + (f.level === level ? ' btn-brass' : '')} onClick={() => void ride(f.level)} aria-label={`Floor ${f.level}, ${f.year}, ${f.open} of 12 rooms open`}>
            <span>Floor {f.level}</span><span>{f.year}</span><span className="chip">{f.open} of 12 open</span>
          </button>
        ))}
      </div>
    </Modal>
  );
}

export function DirectoryPanel() {
  const close = useWorld((s) => s.openPanel);
  return <Modal title="Go to a room" size="lg" onClose={() => close(null)}><RoomTab /></Modal>;
}

export function AtticPanel() {
  const close = useWorld((s) => s.openPanel);
  const list = useLoad(() => get<unknown>('/api/attic').then((d) => listOf<Exhibit>(d, 'memories')), []);
  const editable = useWorld((s) => s.museum?.me.role !== 'viewer');
  return (
    <Modal title="The Attic" size="lg" onClose={() => close(null)}>
      <p className="muted">Memories with no known date. Give each a year and month and it moves to its room.</p>
      {list.loading && <Spinner text="Opening the Attic" />}
      {list.error && <p className="err">{list.error}</p>}
      {list.data?.length === 0 && <p>The Attic is empty. Every memory has a place.</p>}
      <div className="list">{(list.data ?? []).map((m) => <AtticRow key={m.id} m={m} editable={editable} onDone={() => { list.reload(); void useWorld.getState().refreshMuseum(); }} />)}</div>
    </Modal>
  );
}

function AtticRow({ m, editable, onDone }: { m: Exhibit; editable: boolean; onDone: () => void }) {
  const [year, setYear] = useState(new Date().getFullYear());
  const [month, setMonth] = useState(1);
  const a = useAction(async () => { await post(`/api/memories/${m.id}/move`, { year, month }); onDone(); });
  return (
    <div className="item">
      <div className="row" style={{ flexWrap: 'nowrap' }}>
        {m.photos[0] && <img src={m.photos[0].thumb_url} alt="" width={64} height={48} style={{ objectFit: 'cover' }} />}
        <div><div className="item-title">{m.title || m.summary || 'A memory'}</div><div className="muted" style={{ fontSize: 13 }}>{m.teller || m.author || ''} {m.kind}</div></div>
      </div>
      {editable && (
        <div className="row">
          <input className="input" style={{ width: 96 }} type="number" aria-label="Year" value={year} onChange={(e) => setYear(+e.target.value)} />
          <select className="input" style={{ width: 130 }} aria-label="Month" value={month} onChange={(e) => setMonth(+e.target.value)}>{MONTHS.map((n, i) => <option key={n} value={i + 1}>{n}</option>)}</select>
          <button className="btn btn-primary btn-sm" onClick={() => void a.run()} disabled={a.busy}>Move to {monthName(month).slice(0, 3)} {year}</button>
          {a.error && <span className="err">{a.error}</span>}
        </div>
      )}
    </div>
  );
}

export function SettingsPanel() {
  const close = useWorld((s) => s.openPanel);
  const museum = useWorld((s) => s.museum);
  const mode2d = useWorld((s) => s.mode2d);
  const setMode2d = useWorld((s) => s.setMode2d);
  const webgl = useWorld((s) => s.webgl);
  const setLanguage = useWorld((s) => s.setLanguage);
  const owner = museum?.me.role === 'owner';
  const fam = useLoad(() => get<FamilySettings>('/api/family'), []);
  const [f, setF] = useState<FamilySettings | null>(null);
  useEffect(() => { if (fam.data) setF(fam.data); }, [fam.data]);
  const save = useAction(async (patchBody: { name?: string; language?: Lang; grandma_name?: string; settings?: Record<string, unknown> }) => {
    const r = await patch<FamilySettings>('/api/family', patchBody);
    setF(r);
    if (patchBody.language) setLanguage(patchBody.language);
    await useWorld.getState().refreshMuseum();
  });
  const [members, setMembers] = useState(false);
  const [delOpen, setDelOpen] = useState(false);
  return (
    <Modal title="Settings" size="md" onClose={() => close(null)}>
      {fam.loading && <Spinner text="Loading settings" />}
      {fam.error && <p className="err">{fam.error}</p>}
      {f && (
        <div className="stack">
          <Field label="Family name"><input className="input" defaultValue={f.name} disabled={!owner} onBlur={(e) => e.target.value !== f.name && void save.run({ name: e.target.value })} /></Field>
          <Field label="Language">
            <div className="seg" role="radiogroup" aria-label="Language">{LANGS.map((l) => <button key={l.id} role="radio" aria-checked={f.language === l.id} onClick={() => void save.run({ language: l.id })}>{l.label}</button>)}</div>
          </Field>
          <Field label="Grandma's name"><input className="input" defaultValue={f.grandma_name} disabled={!owner} onBlur={(e) => e.target.value !== f.grandma_name && void save.run({ grandma_name: e.target.value })} /></Field>
          <label className="check"><input type="checkbox" checked={f.settings.sarcasm_on} disabled={!owner || museum?.flags?.sarcasm_enabled === false} onChange={(e) => void save.run({ settings: { sarcasm: e.target.checked } })} /><span>Grandma may tease a little on the room boards.</span></label>
          <label className="check"><input type="checkbox" checked={f.settings.keep_location} disabled={!owner} onChange={(e) => void save.run({ settings: { keep_location: e.target.checked } })} /><span>Keep location data in stored photos. Off removes it.</span></label>
          {save.error && <p className="err" role="alert">{save.error}</p>}
        </div>
      )}
      <hr className="divider" />
      <Field label="View" hint={webgl ? undefined : 'This device cannot draw the 3D museum, so the 2D view is used.'}>
        <div className="seg" role="radiogroup" aria-label="View">
          {([[null, 'Automatic'], [false, '3D'], [true, '2D grid']] as const).map(([v, l]) => <button key={l} role="radio" aria-checked={mode2d === v} onClick={() => setMode2d(v)} disabled={v === false && !webgl}>{l}</button>)}
        </div>
      </Field>
      <div className="row">
        <a className="btn" href="/api/export" download>Export everything</a>
        {owner && <button className="btn" onClick={() => setMembers(true)}>Members and roles</button>}
        {owner && <button className="btn" onClick={() => useWorld.getState().openPanel('ops')}>Operator</button>}
      </div>
      {owner && (
        <>
          <hr className="divider" />
          <div className="row"><button className="btn btn-danger" onClick={() => setDelOpen(true)}>Delete the family museum</button></div>
        </>
      )}
      {members && owner && <Modal title="Members and roles" size="md" onClose={() => setMembers(false)}><MembersList /></Modal>}
      {delOpen && owner && <DeleteFamilyModal name={museum?.family.name ?? ''} onClose={() => setDelOpen(false)} />}
    </Modal>
  );
}

function DeleteFamilyModal({ name, onClose }: { name: string; onClose: () => void }) {
  const [confirmDel, setConfirmDel] = useState('');
  const delFam = useAction(async () => { await del('/api/family', { confirm: confirmDel }); location.href = '/'; });
  return (
    <ConfirmModal title="Delete the family museum" danger confirmLabel="Delete everything" busy={delFam.busy} error={delFam.error} confirmDisabled={confirmDel !== name} onCancel={onClose} onConfirm={() => confirmDel === name && void delFam.run()}>
      <p>This deletes the family and every memory, photo and voice note. It cannot be undone.</p>
      <Field label={`Type "${name}" to confirm`}><input className="input" data-autofocus value={confirmDel} onChange={(e) => setConfirmDel(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && confirmDel === name) void delFam.run(); }} /></Field>
      {confirmDel !== name && <p className="muted" style={{ fontSize: 13 }}>The delete button only works once the name matches.</p>}
    </ConfirmModal>
  );
}

function MembersList() {
  const list = useLoad(() => get<unknown>('/api/family/members').then((d) => listOf<Member>(d, 'members')), []);
  const set = useAction(async (id: string, role: string) => { await patch(`/api/family/members/${id}`, { role }); list.reload(); });
  return (
    <div className="list">
      {list.loading && <Spinner text="Loading members" />}
      {(list.data ?? []).map((m) => (
        <div key={m.id} className="item">
          <span className="item-title">{m.nickname ?? 'Member'}</span>
          <select className="input" style={{ width: 130 }} aria-label={`Role for ${m.nickname}`} value={m.role} disabled={m.role === 'owner'} onChange={(e) => void set.run(m.id, e.target.value)}>{['owner', 'editor', 'viewer'].map((r) => <option key={r} disabled={r === 'owner' && m.role !== 'owner'}>{r}</option>)}</select>
        </div>
      ))}
      {set.error && <p className="err" role="alert">{set.error}</p>}
    </div>
  );
}

export function OpsPanel() {
  const close = useWorld((s) => s.openPanel);
  const jobs = useLoad(async () => {
    const [a, b] = await Promise.all([get<unknown>('/api/ops/jobs?status=failed'), get<unknown>('/api/ops/jobs?status=dead')]);
    return [...listOf<JobRec>(a, 'jobs'), ...listOf<JobRec>(b, 'jobs')];
  }, []);
  const flags = useLoad(() => get<unknown>('/api/ops/flags'), []);
  const replay = useAction(async (id: string) => { await post(`/api/ops/jobs/${id}/replay`, {}); jobs.reload(); });
  const setFlag = useAction(async (key: string, value: unknown) => { await post('/api/ops/flags', { key, value, scope: 'family' }); flags.reload(); });
  const entries: [string, unknown][] = (() => {
    const d = flags.data as unknown;
    if (Array.isArray(d)) return d.map((x: { key: string; value: unknown }) => [x.key, x.value]);
    if (d && typeof d === 'object') {
      const o = d as Record<string, unknown>;
      const inner = (o.flags ?? o) as Record<string, unknown> | { key: string; value: unknown }[];
      if (Array.isArray(inner)) return inner.map((x) => [x.key, x.value]);
      return Object.entries(inner).map(([k, v]) => [k, v && typeof v === 'object' && 'value' in (v as object) ? (v as { value: unknown }).value : v]);
    }
    return [];
  })();
  const fd = (flags.data ?? {}) as { sources?: Record<string, string>; provider?: { provider?: string; last_refresh_at?: string | null } };
  const sources = fd.sources ?? {};
  return (
    <Modal title="Operator" size="lg" onClose={() => close(null)}>
      <h3>Failed and dead jobs</h3>
      {jobs.loading && <Spinner text="Loading jobs" />}
      {jobs.error && <p className="err">{jobs.error}</p>}
      {jobs.data?.length === 0 && <p>No failed jobs.</p>}
      {(jobs.data?.length ?? 0) > 0 && (
        <table className="table"><thead><tr><th>Type</th><th>Status</th><th>Tries</th><th>Last error</th><th /></tr></thead>
          <tbody>{(jobs.data ?? []).map((j) => <tr key={j.id}><td>{j.type}</td><td><span className={'chip ' + (j.status === 'dead' ? 'chip--bad' : 'chip--warn')}>{j.status}</span></td><td>{j.attempts}</td><td className="mono" style={{ fontSize: 12 }}>{j.last_error ?? ''}</td><td><button className="btn btn-sm" onClick={() => void replay.run(j.id)} disabled={replay.busy}>Replay</button></td></tr>)}</tbody></table>
      )}
      {replay.error && <p className="err" role="alert">{replay.error}</p>}
      <hr className="divider" />
      <h3>Flags</h3>
      {fd.provider && <p className="mono" style={{ fontSize: 12 }}>Provider: {fd.provider.provider}{fd.provider.last_refresh_at ? ` (refreshed ${new Date(fd.provider.last_refresh_at).toLocaleTimeString()})` : ''}</p>}
      {flags.loading && <Spinner text="Loading flags" />}
      {flags.error && <p className="err">{flags.error}</p>}
      <div className="list">
        {entries.map(([k, v]) => (
          <div key={k} className="item">
            <span className="mono">{k}</span>
            {sources[k] && <span className="chip" title="Where this value comes from">{sources[k]}</span>}
            {typeof v === 'boolean'
              ? <button className="btn btn-sm" aria-pressed={v} onClick={() => void setFlag.run(k, !v)}>{v ? 'On' : 'Off'}</button>
              : <input className="input" style={{ width: 140 }} defaultValue={String(v)} aria-label={k} onBlur={(e) => { const n = Number(e.target.value); const nv = e.target.value !== '' && !Number.isNaN(n) ? n : e.target.value; if (String(nv) !== String(v)) void setFlag.run(k, nv); }} />}
          </div>
        ))}
      </div>
      {setFlag.error && <p className="err" role="alert">{setFlag.error}</p>}
    </Modal>
  );
}
