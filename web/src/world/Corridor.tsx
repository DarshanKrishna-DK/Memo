import { useEffect, useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { createInstances } from '@react-three/drei';
import * as THREE from 'three';
import type { Interactable, Room, RoomState } from '../contract';
import { CORR_CEIL, CORR_HALF_W, DOORS, DOOR_W, END_Z, type DoorSpec } from './layout';
import { Box, CanvasPlane, Ceiling, Downlights, FloorPlane, Wall } from './parts';
import { isTap, useRuntime } from './runtime';
import { Atlas, FONT_DISPLAY, FONT_SANS, PAL, monthName, useFontsReady, wrap } from './textures';

const STATE_COLOR: Record<RoomState | 'unknown', string> = {
  open: PAL.lime,
  locked: PAL.gold,
  not_yet: '#a7b6d6',
  current_empty: PAL.teal,
  closed: '#c9a0c9',
  unknown: '#5a6a8a',
};
const STATE_LABEL: Record<RoomState, string> = {
  open: '',
  locked: 'LOCKED',
  not_yet: 'NOT YET',
  current_empty: 'THIS MONTH',
  closed: 'CLOSED WITH CARE',
};

// Instanced door parts: one draw call per part for all 12 doors.
const [JambI, Jamb] = createInstances();
const [HeadI, Head] = createInstances();
const [LeafI, Leaf] = createInstances();
const [KickI, Kick] = createInstances();
const [HandleI, Handle] = createInstances();
const [GlassI, Glass] = createInstances();
const [LedI, Led] = createInstances();
const [RecessI, Recess] = createInstances();

function DoorParts({ children }: { children: React.ReactNode }) {
  return (
    <JambI limit={24} castShadow receiveShadow frustumCulled={false}>
      <boxGeometry args={[0.1, 2.3, 0.14]} />
      <meshStandardMaterial color={PAL.gold} roughness={0.3} metalness={0.7} />
      <HeadI limit={12} castShadow frustumCulled={false}>
        <boxGeometry args={[DOOR_W + 0.3, 0.12, 0.14]} />
        <meshStandardMaterial color={PAL.gold} roughness={0.3} metalness={0.7} />
        <LeafI limit={12} castShadow receiveShadow frustumCulled={false}>
          <boxGeometry args={[DOOR_W - 0.08, 2.18, 0.06]} />
          <meshStandardMaterial roughness={0.5} />
          <KickI limit={12} frustumCulled={false}>
            <boxGeometry args={[DOOR_W - 0.12, 0.22, 0.066]} />
            <meshStandardMaterial color="#b89a60" roughness={0.3} metalness={0.8} />
            <HandleI limit={24} frustumCulled={false}>
              <boxGeometry args={[0.04, 0.2, 0.05]} />
              <meshStandardMaterial color={PAL.gold} roughness={0.2} metalness={0.9} />
              <GlassI limit={12} frustumCulled={false}>
                <boxGeometry args={[0.18, 0.9, 0.066]} />
                <meshStandardMaterial roughness={0.15} />
                <LedI limit={12} frustumCulled={false}>
                  <boxGeometry args={[0.05, 0.05, 0.02]} />
                  <meshBasicMaterial toneMapped={false} />
                  <RecessI limit={12} frustumCulled={false}>
                    <planeGeometry args={[DOOR_W, 2.25]} />
                    <meshBasicMaterial color="#05080f" />
                    {children}
                  </RecessI>
                </LedI>
              </GlassI>
            </HandleI>
          </KickI>
        </LeafI>
      </HeadI>
    </JambI>
  );
}

function leafColor(state: RoomState | 'unknown') {
  switch (state) {
    case 'open': return '#8a5a3a';
    case 'closed': return '#5a4a5f';
    case 'not_yet': return '#4a5670';
    default: return '#6b4f3a';
  }
}

function Door({
  door, room, year, signTex, boardTex, isCurrent, act,
}: {
  door: DoorSpec; room: Room | undefined; year: number; signTex: THREE.Texture; boardTex: THREE.Texture | null;
  isCurrent: boolean; act: (i: Interactable) => void;
}) {
  const rt = useRuntime();
  const pivot = useRef<THREE.Group>(null);
  const i = door.month - 1;
  const state: RoomState | 'unknown' = room?.state ?? 'unknown';
  const open = state === 'open';

  useFrame((_, dt) => {
    const d = rt.doors;
    d.open[i] += (d.target[i] - d.open[i]) * Math.min(1, dt * 4);
    let r = d.open[i] * 1.4;
    if (d.shake[i] > 0) {
      d.shake[i] = Math.max(0, d.shake[i] - dt);
      r += Math.sin(d.shake[i] * 60) * 0.025 * Math.min(1, d.shake[i] * 2.5);
    }
    if (pivot.current) pivot.current.rotation.y = r;
  });

  return (
    <group position={[door.x, 0, door.z]} rotation={[0, door.rotY, 0]}>
      {!isCurrent && <Recess position={[0, 1.12, -0.28]} />}
      <Jamb position={[-DOOR_W / 2 - 0.05, 1.15, 0.0]} />
      <Jamb position={[DOOR_W / 2 + 0.05, 1.15, 0.0]} />
      <Head position={[0, 2.31, 0.0]} />
      <group ref={pivot} position={[-DOOR_W / 2 + 0.04, 0, -0.05]}>
        <Leaf position={[DOOR_W / 2 - 0.04, 1.1, 0]} color={leafColor(state)} />
        <Kick position={[DOOR_W / 2 - 0.04, 0.13, 0]} />
        <Handle position={[DOOR_W - 0.2, 1.05, 0.05]} />
        <Handle position={[DOOR_W - 0.2, 1.05, -0.05]} />
        <Glass position={[DOOR_W / 2 - 0.04, 1.55, 0]} color={open ? '#ffe2b0' : '#1a2233'} />
        {boardTex && (
          <group position={[DOOR_W / 2 - 0.04, 1.2, 0.04]}>
            <mesh position={[0, 0, -0.005]}>
              <boxGeometry args={[0.96, 0.78, 0.02]} />
              <meshStandardMaterial color={PAL.woodDark} roughness={0.6} />
            </mesh>
            <mesh position={[0, 0, 0.007]}>
              <planeGeometry args={[0.9, 0.72]} />
              <meshStandardMaterial map={boardTex} emissive="#ffffff" emissiveMap={boardTex} emissiveIntensity={0.35} roughness={0.85} />
            </mesh>
            {/* hanging cord */}
            <mesh position={[0, 0.5, 0]} rotation={[0, 0, Math.PI / 4]}>
              <torusGeometry args={[0.15, 0.006, 4, 4, Math.PI]} />
              <meshStandardMaterial color={PAL.gold} />
            </mesh>
          </group>
        )}
      </group>
      <Led position={[DOOR_W / 2 + 0.22, 1.7, 0.02]} color={STATE_COLOR[state]} />
      {/* month sign over the door */}
      <mesh position={[0, 2.7, 0.04]}>
        <planeGeometry args={[1.62, 0.6]} />
        <meshBasicMaterial map={signTex} toneMapped={false} />
      </mesh>
      {open && (
        <mesh position={[0, 0.012, 0.9]} rotation={[-Math.PI / 2, 0, 0]}>
          <planeGeometry args={[1.5, 1.4]} />
          <meshBasicMaterial color="#ffcf8a" transparent opacity={0.16} depthWrite={false} toneMapped={false} />
        </mesh>
      )}
      {/* click target */}
      <mesh
        position={[0, 1.15, 0.2]}
        onClick={(e) => {
          e.stopPropagation();
          if (isTap(rt)) act({ kind: 'door', year, month: door.month });
        }}
        onPointerOver={() => { document.body.style.cursor = 'pointer'; }}
        onPointerOut={() => { document.body.style.cursor = ''; }}
      >
        <boxGeometry args={[1.3, 2.3, 0.3]} />
        <meshBasicMaterial visible={false} />
      </mesh>
    </group>
  );
}

function drawSign(g: CanvasRenderingContext2D, W: number, H: number, month: number, year: number, room: Room | undefined, lang: string) {
  const state: RoomState | 'unknown' = room?.state ?? 'unknown';
  g.fillStyle = PAL.navy;
  g.fillRect(0, 0, W, H);
  g.fillStyle = STATE_COLOR[state];
  g.fillRect(0, 0, W, 10);
  g.fillStyle = PAL.line;
  g.fillRect(0, H - 6, W, 6);
  g.textAlign = 'center';
  g.textBaseline = 'alphabetic';
  g.fillStyle = PAL.cream;
  g.font = `${Math.round(H * 0.5)}px ${FONT_DISPLAY}`;
  g.fillText(monthName(month, lang).toUpperCase(), W / 2, H * 0.55, W * 0.92);
  g.font = `600 ${Math.round(H * 0.15)}px ${FONT_SANS}`;
  let sub = String(year);
  if (room) {
    if (room.state === 'open') {
      const n = room.memory_count;
      sub = `${n} ${n === 1 ? 'MEMORY' : 'MEMORIES'}${room.festival ? ' · ' + room.festival.toUpperCase() : ''}`;
    } else sub = STATE_LABEL[room.state];
  }
  g.fillStyle = STATE_COLOR[state];
  g.fillText(sub, W / 2, H * 0.83, W * 0.92);
}

function drawBoard(g: CanvasRenderingContext2D, W: number, H: number, room: Room | undefined) {
  g.fillStyle = '#efe4cc';
  g.fillRect(0, 0, W, H);
  if (!room || room.state === 'open') return;
  g.strokeStyle = room.state === 'closed' ? '#8a6d8a' : PAL.gold;
  g.lineWidth = 6;
  g.strokeRect(10, 10, W - 20, H - 20);
  const text = room.board_text || STATE_LABEL[room.state];
  g.fillStyle = PAL.navy;
  g.textAlign = 'center';
  let size = Math.round(H * 0.16);
  let lines: string[] = [];
  for (; size > 12; size -= 2) {
    g.font = `${size}px ${FONT_DISPLAY}`;
    lines = wrap(g, text, W * 0.84, 99);
    if (lines.length * size * 1.05 < H * 0.78) break;
  }
  g.font = `${size}px ${FONT_DISPLAY}`;
  lines = wrap(g, text, W * 0.84, Math.max(1, Math.floor((H * 0.8) / (size * 1.05))));
  const top = H / 2 - ((lines.length - 1) * size * 1.05) / 2 + size * 0.35;
  lines.forEach((l, k) => g.fillText(l, W / 2, top + k * size * 1.05));
}

export function Corridor({
  year, level, rooms, openMonth, lang, act,
}: {
  year: number; level: number; rooms: Room[] | undefined; openMonth: number | null; lang: string; act: (i: Interactable) => void;
}) {
  const fonts = useFontsReady();
  const byMonth = useMemo(() => {
    const m = new Map<number, Room>();
    rooms?.forEach((r) => m.set(r.month, r));
    return m;
  }, [rooms]);
  const roomsKey = rooms?.map((r) => `${r.month}:${r.state}:${r.memory_count}:${r.board_text ?? ''}:${r.festival ?? ''}`).join('|') ?? '';

  // Two atlases per floor (signs + boards): 2 texture uploads for 24 signs. Disposed on floor change.
  const signs = useMemo(
    () => new Atlas(4, 3, 384, 142, (g, i, W, H) => drawSign(g, W, H, i + 1, year, byMonth.get(i + 1), lang)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [year, roomsKey, lang, fonts],
  );
  const boards = useMemo(
    () => new Atlas(4, 3, 300, 240, (g, i, W, H) => drawBoard(g, W, H, byMonth.get(i + 1))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [roomsKey, fonts],
  );
  useEffect(() => () => signs.dispose(), [signs]);
  useEffect(() => () => boards.dispose(), [boards]);

  const openCount = rooms ? rooms.filter((r) => r.state === 'open').length : null;
  const lights = useMemo<Array<[number, number]>>(() => {
    const pts: Array<[number, number]> = [];
    for (let z = -1.4; z > END_Z + 0.5; z -= 3.6) pts.push([0, z]);
    return pts;
  }, []);

  // Wall segments between door openings, plus headers above each door.
  const walls = useMemo(() => {
    const out: JSX.Element[] = [];
    for (const side of ['L', 'R'] as const) {
      const x = side === 'L' ? -CORR_HALF_W : CORR_HALF_W;
      const ds = DOORS.filter((d) => d.side === side).sort((a, b) => b.z - a.z);
      let z = 0;
      const seg = (z0: number, z1: number, k: string) =>
        side === 'L'
          ? <Wall key={k} a={[x, z0]} b={[x, z1]} h={CORR_CEIL} face={1} />
          : <Wall key={k} a={[x, z1]} b={[x, z0]} h={CORR_CEIL} face={1} />;
      ds.forEach((d, k) => {
        out.push(seg(z, d.z + DOOR_W / 2, `${side}${k}`));
        out.push(
          <Box key={`${side}h${k}`} p={[x + (side === 'L' ? -0.15 : 0.15), (2.37 + CORR_CEIL) / 2, d.z]} s={[0.3, CORR_CEIL - 2.37, DOOR_W]} color={PAL.wall} rough={0.92} />,
        );
        z = d.z - DOOR_W / 2;
      });
      out.push(seg(z, END_Z, `${side}end`));
    }
    return out;
  }, []);

  return (
    <group>
      <FloorPlane x0={-CORR_HALF_W} x1={CORR_HALF_W} z0={END_Z} z1={0} kind="parquet" />
      <Ceiling x0={-CORR_HALF_W} x1={CORR_HALF_W} z0={END_Z} z1={0} y={CORR_CEIL} />
      <Downlights points={lights} y={CORR_CEIL} count={4} intensity={4.5} />
      {walls}
      <Wall a={[-CORR_HALF_W, END_Z]} b={[CORR_HALF_W, END_Z]} h={CORR_CEIL} face={1} />
      {/* runner carpet */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.005, END_Z / 2]} receiveShadow>
        <planeGeometry args={[1.4, -END_Z - 0.6]} />
        <meshStandardMaterial color="#7a1f2b" roughness={0.95} />
      </mesh>
      {[-0.66, 0.66].map((x) => (
        <mesh key={x} rotation={[-Math.PI / 2, 0, 0]} position={[x, 0.007, END_Z / 2]}>
          <planeGeometry args={[0.05, -END_Z - 0.6]} />
          <meshStandardMaterial color={PAL.gold} roughness={0.6} />
        </mesh>
      ))}
      <DoorParts>
        {DOORS.map((d) => {
          const room = byMonth.get(d.month);
          return (
            <Door
              key={d.month}
              door={d}
              room={room}
              year={year}
              signTex={signs.cell(d.month - 1)}
              boardTex={room && room.state !== 'open' ? boards.cell(d.month - 1) : null}
              isCurrent={openMonth === d.month}
              act={act}
            />
          );
        })}
      </DoorParts>
      {/* floor plaque on the end wall + hanging sign at the corridor mouth */}
      <CanvasPlane
        w={2.6} h={1.3} px={200}
        position={[0, 1.7, END_Z + 0.03]}
        deps={[year, openCount, level, fonts]}
        draw={(g, W, H) => {
          g.fillStyle = PAL.navy;
          g.fillRect(0, 0, W, H);
          g.strokeStyle = PAL.gold;
          g.lineWidth = 8;
          g.strokeRect(12, 12, W - 24, H - 24);
          g.textAlign = 'center';
          g.fillStyle = PAL.goldSoft;
          g.font = `${Math.round(H * 0.44)}px ${FONT_DISPLAY}`;
          g.fillText(String(year), W / 2, H * 0.48);
          g.fillStyle = PAL.cream;
          g.font = `600 ${Math.round(H * 0.12)}px ${FONT_SANS}`;
          g.fillText(openCount === null ? 'LOADING ROOMS…' : `${openCount} OF 12 ROOMS OPEN`, W / 2, H * 0.68);
          g.fillStyle = '#a7b6d6';
          g.font = `600 ${Math.round(H * 0.09)}px ${FONT_SANS}`;
          g.fillText(level === 0 ? 'GROUND FLOOR' : `FLOOR ${level}`, W / 2, H * 0.84);
        }}
      />
      <group position={[0, CORR_CEIL - 0.5, -0.6]}>
        <Box p={[-0.9, 0.35, 0]} s={[0.02, 0.4, 0.02]} color={PAL.gold} />
        <Box p={[0.9, 0.35, 0]} s={[0.02, 0.4, 0.02]} color={PAL.gold} />
        <CanvasPlane
          w={2.4} h={0.42} px={200}
          position={[0, 0, 0.012]} rotation={[0, Math.PI, 0]}
          deps={[year, openCount, fonts]}
          draw={(g, W, H) => {
            g.fillStyle = PAL.navy;
            g.fillRect(0, 0, W, H);
            g.textAlign = 'center';
            g.textBaseline = 'middle';
            g.fillStyle = PAL.goldSoft;
            g.font = `${Math.round(H * 0.62)}px ${FONT_DISPLAY}`;
            g.fillText(`${year} · ${openCount ?? '…'} of 12 open`, W / 2, H * 0.54, W * 0.94);
          }}
        />
        <CanvasPlane
          w={2.4} h={0.42} px={200}
          position={[0, 0, -0.012]}
          deps={[year, openCount, fonts]}
          draw={(g, W, H) => {
            g.fillStyle = PAL.navy;
            g.fillRect(0, 0, W, H);
            g.textAlign = 'center';
            g.textBaseline = 'middle';
            g.fillStyle = PAL.goldSoft;
            g.font = `${Math.round(H * 0.62)}px ${FONT_DISPLAY}`;
            g.fillText(`${year} · ${openCount ?? '…'} of 12 open`, W / 2, H * 0.54, W * 0.94);
          }}
        />
      </group>
    </group>
  );
}
