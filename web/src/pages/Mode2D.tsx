import { useEffect, useState } from 'react';
import type { Room } from '../contract';
import { useWorld } from '../state/worldStore';
import { Spinner, monthName } from '../ui/common';
import { RoomTools } from './RoomUi';

const STATE_LABEL: Record<string, string> = { open: 'Open', locked: 'Locked', not_yet: 'Not yet', current_empty: 'Waiting for its first memory', closed: 'Closed with care' };

function Floor({ year, level, open: openRooms, startOpen }: { year: number; level: number; open: number; startOpen: boolean }) {
  const { floorRooms, loadFloor, goTo } = useWorld();
  const [show, setShow] = useState(startOpen);
  const [err, setErr] = useState<string | null>(null);
  const rooms: Room[] | undefined = floorRooms[year];
  useEffect(() => { if (show && !rooms) loadFloor(year).catch((e) => setErr(e instanceof Error ? e.message : 'Could not load this floor.')); }, [show, rooms, year, loadFloor]);
  return (
    <section className="floor" aria-label={`Floor ${level}, ${year}`}>
      <div className="floor-head">
        <h2 className="floor-year">{year}</h2>
        <span className="chip chip--teal">Floor {level}</span>
        <span className="muted">{openRooms} of 12 rooms open</span>
        <span className="grow" />
        <button className="btn btn-sm" aria-expanded={show} onClick={() => setShow((v) => !v)}>{show ? 'Hide rooms' : 'Show rooms'}</button>
      </div>
      {show && !rooms && !err && <Spinner text={`Loading ${year}`} />}
      {err && <p className="err" role="alert">{err}</p>}
      {show && rooms && (
        <>
          <div className="months">
            {rooms.map((r) => {
              const enterable = r.state === 'open' || r.state === 'current_empty' || r.state === 'closed' || r.state === 'locked' || r.state === 'not_yet';
              return (
                <button key={r.month} className={`month month--${r.state}`} disabled={!enterable} onClick={() => void goTo(r.year, r.month)} aria-label={`${monthName(r.month)} ${r.year}. ${STATE_LABEL[r.state] ?? r.state}. ${r.memory_count} ${r.memory_count === 1 ? 'memory' : 'memories'}`}>
                  {r.hero_thumb_url && <img className="month-hero" src={r.hero_thumb_url} alt="" loading="lazy" />}
                  <span className="month-name">{monthName(r.month)}</span>
                  <span className={'chip ' + (r.state === 'open' ? 'chip--ok' : r.state === 'closed' ? 'chip--bad' : r.state === 'current_empty' ? 'chip--warn' : '')}>{r.state === 'open' ? `${r.memory_count} ${r.memory_count === 1 ? 'memory' : 'memories'}` : STATE_LABEL[r.state]}</span>
                  {r.board_text && <span className="month-board">{r.board_text}</span>}
                </button>
              );
            })}
          </div>
          {rooms.some((r) => r.events.length > 0) && (
            <div className="row">{rooms.flatMap((r) => r.events.map((e) => <button key={e.id} className="btn btn-sm" onClick={() => void goTo(r.year, r.month, e.id)}>{e.name}, {monthName(r.month).slice(0, 3)}</button>))}</div>
          )}
        </>
      )}
    </section>
  );
}

/** PRD M4: the museum as a grid. Years x 12 months, then a room page with exhibits, showcase and Grandma. */
export function Mode2D() {
  const { museum, seat, room, roomExhibits, floorRooms, openExhibit, openPanel } = useWorld();
  if (!museum) return null;
  if (seat && room) {
    const meta = floorRooms[room.year]?.find((r) => r.month === room.month);
    return (
      <main className="room-hall" aria-label={`${monthName(room.month)} ${room.year}`}>
        <div className="shell2d-inner" style={{ paddingLeft: 'clamp(16px, 40vw, 440px)' }}>
          <h1 className="display" style={{ fontSize: 'var(--t-h2)' }}>{monthName(room.month)} {room.year}</h1>
          {meta?.board_text && <p className="plaque">{meta.board_text}</p>}
          {meta && meta.events.length > 0 && <div className="row">{meta.events.map((e) => <button key={e.id} className={'btn btn-sm' + (room.eventId === e.id ? ' btn-brass' : '')} onClick={() => void useWorld.getState().goTo(room.year, room.month, e.id)}>{e.name}</button>)}{room.eventId && <button className="btn btn-sm" onClick={() => void useWorld.getState().goTo(room.year, room.month, null)}>Whole month</button>}</div>}
          <RoomTools />
          {roomExhibits.length === 0 && <p className="muted">Nothing hangs here yet.</p>}
          <div className="exhibit-list">
            {roomExhibits.map((e) => (
              <button key={e.id} className="exhibit" onClick={() => openExhibit(e.id)} aria-label={`Open ${e.title || e.kind}`}>
                {e.photos[0] ? <img src={e.photos[0].thumb_url} alt="" loading="lazy" /> : <div style={{ aspectRatio: '4/3', display: 'grid', placeItems: 'center', background: 'var(--field)' }} className="display">{e.kind === 'voice' ? 'Voice note' : 'Note'}</div>}
                <span className="item-title">{e.title || e.summary || (e.kind === 'voice' ? 'A voice note' : 'A memory')}</span>
                <span className="muted" style={{ fontSize: 13 }}>{e.teller || e.author || ''}{e.photos.length > 1 ? `, ${e.photos.length} photos` : ''}</span>
              </button>
            ))}
          </div>
        </div>
      </main>
    );
  }
  return (
    <main className="shell2d" aria-label="Museum, 2D view">
      <div className="shell2d-inner">
        <header className="stack">
          <h1 className="display" style={{ fontSize: 'var(--t-h2)' }}>{museum.family.name}</h1>
          <div className="row">
            <button className="btn btn-brass" onClick={() => openPanel('reception')}>Reception desk</button>
            <button className="btn" onClick={() => openPanel('attic')}>Attic {museum.attic_count > 0 && `(${museum.attic_count})`}</button>
            {museum.latest && <button className="btn" onClick={() => void useWorld.getState().goTo(museum.latest!.year, museum.latest!.month)}>Latest: {museum.latest.title}</button>}
          </div>
        </header>
        {museum.floors.length === 0 && <p className="plaque">No floors yet. Send a first memory to the Memo bot on Telegram.</p>}
        {museum.floors.map((f, i) => <Floor key={f.year} year={f.year} level={f.level} open={f.open} startOpen={i === 0} />)}
      </div>
    </main>
  );
}
