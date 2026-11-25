import { useEffect, useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import type { PresencePerson } from '../state/worldStore';
import { HumanCharacter, makeControl } from './characters/HumanCharacter';
import { seatLook } from './characters/rigs';
import { SEAT_H, SEAT_Z } from './layout';
import { Box } from './parts';
import { FONT_SANS, PAL, canvasTex, useFontsReady } from './textures';

// The other people in the theater (guests section): family members and invited guests sit in their seats with the
// avatar they chose, in their seat's colours, with a small name tag. Someone who arrives while we watch waves hello.

const WAVE_S = 2.6;

function tagTex(name: string, guest: boolean) {
  return canvasTex(512, 128, (g) => {
    g.font = `600 56px ${FONT_SANS}`;
    const w = Math.min(496, g.measureText(name).width + 56);
    const x = (512 - w) / 2;
    g.fillStyle = PAL.navyDeep;
    g.fillRect(x + 6, 14, w, 100);
    g.fillStyle = guest ? PAL.cream : PAL.goldSoft;
    g.fillRect(x, 8, w, 100);
    g.fillStyle = PAL.navy;
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.fillText(name, 256, 60, 470);
  });
}

/** A small name tag that always faces the camera. */
export function NameTag({ name, guest, y }: { name: string; guest: boolean; y: number }) {
  const fonts = useFontsReady();
  const mat = useMemo(() => new THREE.SpriteMaterial({ transparent: true, toneMapped: false, depthWrite: false }), []);
  useEffect(() => {
    mat.map?.dispose();
    mat.map = tagTex(name, guest);
    mat.needsUpdate = true;
  }, [mat, name, guest, fonts]);
  useEffect(() => () => { mat.map?.dispose(); mat.dispose(); }, [mat]);
  return <sprite material={mat} position={[0, y, 0]} scale={[0.72, 0.18, 1]} renderOrder={5} />;
}

function Member({ p, x, z, yaw, waveOnArrive }: { p: PresencePerson; x: number; z: number; yaw: number; waveOnArrive: boolean }) {
  const control = useMemo(() => makeControl({ action: 'sit', seatHeight: SEAT_H }), []);
  const look = useMemo(() => seatLook(p.avatar, p.index), [p.avatar, p.index]);
  const t = useRef(waveOnArrive ? 0 : WAVE_S);
  useFrame((_, dt) => {
    t.current += dt;
    const k = t.current / WAVE_S;
    control.wave = k < 1 ? Math.min(1, Math.sin(Math.PI * k) * 1.6) : 0;
  });
  return (
    <group position={[x, 0, z]} rotation={[0, yaw, 0]} name={`audience-${p.index}`}>
      <HumanCharacter look={look} control={control} />
      <NameTag name={p.name} guest={p.is_guest} y={p.avatar === 'man' ? 1.47 : 1.37} />
    </group>
  );
}

/** Everyone seated in this room except us. Coordinates are the room's local space. */
export function Audience({ people, seats }: { people: PresencePerson[]; seats: Array<{ x: number; z: number; yaw: number }> }) {
  // People already here when we sat down do not wave; anyone arriving later does.
  const known = useRef<Set<string> | null>(null);
  const arrivals = useRef<Set<string>>(new Set());
  if (known.current === null) known.current = new Set(people.map((p) => p.id));
  for (const p of people) {
    if (!known.current.has(p.id)) { known.current.add(p.id); arrivals.current.add(p.id); }
  }
  return (
    <>
      {people.map((p) => {
        if (p.index == null || p.index < 0 || p.index > 3) return null;
        const st = seats[p.index];
        return <Member key={`${p.id}-${p.index}`} p={p} x={st.x} z={st.z} yaw={st.yaw} waveOnArrive={arrivals.current.has(p.id)} />;
      })}
    </>
  );
}

/** A plain wooden bench behind the seats, for whoever watches without a seat (all four taken). */
export function BackBench() {
  return (
    <group position={[0, 0, SEAT_Z + BENCH_DZ]}>
      <Box p={[0, SEAT_H - 0.05, 0]} s={[1.4, 0.08, 0.42]} color={PAL.wood} rough={0.5} cast />
      {[-0.6, 0.6].map((x) => <Box key={x} p={[x, (SEAT_H - 0.09) / 2, 0]} s={[0.08, SEAT_H - 0.09, 0.36]} color={PAL.woodDark} rough={0.5} />)}
    </group>
  );
}
export const BENCH_DZ = 1.55;
