import { useEffect, useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import type { FloorSummary, Interactable } from '../contract';
import { LIFT } from './layout';
import { Box } from './parts';
import { useRuntime, isTap } from './runtime';
import { FONT_DISPLAY, PAL, canvasTex } from './textures';
import { floorShort, yearOfLevel } from '../lib/floors';

/** Lift on the back wall, right of the corridor: cabin, sliding doors, a floor indicator that
 *  counts during a ride, and a call panel (E / tap → lift_panel). Same spot on every floor. */
export function Lift({ floors, onInteract }: { floors: FloorSummary[]; onInteract: (i: Interactable) => void }) {
  const rt = useRuntime();
  const left = useRef<THREE.Mesh>(null);
  const right = useRef<THREE.Mesh>(null);
  void floors; // the calendar is fixed (lib/floors): any level maps to its year, listed or not

  const ind = useMemo(() => {
    const c = document.createElement('canvas');
    c.width = 256;
    c.height = 96;
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return { c, t, shown: NaN };
  }, []);
  useEffect(() => () => ind.t.dispose(), [ind]);

  const draw = (level: number, dir: number) => {
    const g = ind.c.getContext('2d')!;
    g.fillStyle = '#05080f';
    g.fillRect(0, 0, 256, 96);
    g.fillStyle = PAL.goldSoft;
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.font = `64px ${FONT_DISPLAY}`;
    g.fillText(`${floorShort(level)} · ${yearOfLevel(level)}`, 128, 52, 236);
    if (dir !== 0) {
      g.fillStyle = PAL.lime;
      g.beginPath();
      if (dir > 0) { g.moveTo(18, 30); g.lineTo(32, 12); g.lineTo(46, 30); } else { g.moveTo(18, 66); g.lineTo(32, 84); g.lineTo(46, 66); }
      g.fill();
    }
    ind.t.needsUpdate = true;
  };

  const last = useRef({ level: NaN, dir: 0 });
  useFrame((_, dt) => {
    const L = rt.lift;
    L.doors += (L.doorsTarget - L.doors) * Math.min(1, dt * 4);
    if (Math.abs(L.doors - L.doorsTarget) < 0.002) L.doors = L.doorsTarget;
    const o = L.doors * (LIFT.doorW / 2 - 0.02);
    if (left.current) left.current.position.x = -LIFT.doorW / 4 - o;
    if (right.current) right.current.position.x = LIFT.doorW / 4 + o;
    const lvl = Math.round(L.indicator);
    const dir = Math.abs(L.indicator - lvl) > 0.02 ? Math.sign(L.indicator - last.current.level || 0) : 0;
    if (lvl !== last.current.level || dir !== last.current.dir) {
      draw(lvl, dir);
      last.current = { level: lvl, dir };
    }
  });

  const panelTex = useMemo(
    () =>
      canvasTex(128, 256, (g) => {
        g.fillStyle = '#1b2333';
        g.fillRect(0, 0, 128, 256);
        g.fillStyle = PAL.gold;
        for (let i = 0; i < 4; i++) {
          g.beginPath();
          g.arc(64, 50 + i * 50, 16, 0, Math.PI * 2);
          g.fill();
        }
        g.fillStyle = PAL.lime;
        g.beginPath();
        g.arc(64, 50, 9, 0, Math.PI * 2);
        g.fill();
      }),
    [],
  );
  useEffect(() => () => panelTex.dispose(), [panelTex]);

  const click = () => { if (isTap(rt)) onInteract({ kind: 'lift_panel' }); };
  const W = LIFT.w, D = LIFT.d, H = LIFT.h;
  return (
    <group>
      {/* cabin */}
      <group position={[LIFT.x, 0, -D / 2]}>
        <Box p={[0, 0.005, 0]} s={[W, 0.01, D]} color="#2a2f3a" rough={0.5} />
        <Box p={[0, H, 0]} s={[W, 0.05, D]} color="#c9c2b0" emissive="#ffe8c0" emissiveIntensity={0.5} />
        <Box p={[-W / 2 - 0.05, H / 2, 0]} s={[0.1, H, D]} color="#b8a27a" rough={0.35} metal={0.6} />
        <Box p={[W / 2 + 0.05, H / 2, 0]} s={[0.1, H, D]} color="#b8a27a" rough={0.35} metal={0.6} />
        <Box p={[0, H / 2, -D / 2 - 0.05]} s={[W, H, 0.1]} color="#b8a27a" rough={0.35} metal={0.6} />
        <Box p={[0, 1.0, -D / 2 + 0.02]} s={[W - 0.2, 0.05, 0.05]} color={PAL.gold} rough={0.3} metal={0.8} />
        {/* inner panel */}
        <mesh position={[W / 2 - 0.01, 1.25, -0.3]} rotation={[0, -Math.PI / 2, 0]} onClick={(e) => { e.stopPropagation(); click(); }}>
          <planeGeometry args={[0.22, 0.44]} />
          <meshStandardMaterial map={panelTex} emissive="#ffffff" emissiveMap={panelTex} emissiveIntensity={0.5} />
        </mesh>
      </group>
      {/* surround + doors at z = 0 */}
      <group position={[LIFT.x, 0, 0]}>
        <Box p={[-LIFT.doorW / 2 - 0.08, H / 2, 0.04]} s={[0.16, H, 0.12]} color={PAL.gold} rough={0.3} metal={0.75} cast />
        <Box p={[LIFT.doorW / 2 + 0.08, H / 2, 0.04]} s={[0.16, H, 0.12]} color={PAL.gold} rough={0.3} metal={0.75} cast />
        <Box p={[0, H + 0.08, 0.04]} s={[LIFT.doorW + 0.32, 0.16, 0.12]} color={PAL.gold} rough={0.3} metal={0.75} />
        <Box p={[0, H / 2 + 0.6, -0.06]} s={[LIFT.doorW + 0.4, 0.1, 0.02]} color="#000000" />
        <mesh ref={left} position={[-LIFT.doorW / 4, H / 2, 0]} castShadow>
          <boxGeometry args={[LIFT.doorW / 2, H, 0.05]} />
          <meshStandardMaterial color="#c8ccd2" roughness={0.25} metalness={0.9} />
        </mesh>
        <mesh ref={right} position={[LIFT.doorW / 4, H / 2, 0]} castShadow>
          <boxGeometry args={[LIFT.doorW / 2, H, 0.05]} />
          <meshStandardMaterial color="#c8ccd2" roughness={0.25} metalness={0.9} />
        </mesh>
        {/* indicator */}
        <mesh position={[0, H + 0.42, 0.06]}>
          <planeGeometry args={[0.9, 0.34]} />
          <meshBasicMaterial map={ind.t} toneMapped={false} />
        </mesh>
        {/* call panel */}
        <mesh
          position={[-LIFT.doorW / 2 - 0.42, 1.25, 0.012]}
          onClick={(e) => { e.stopPropagation(); click(); }}
          onPointerOver={() => { document.body.style.cursor = 'pointer'; }}
          onPointerOut={() => { document.body.style.cursor = ''; }}
        >
          <planeGeometry args={[0.24, 0.48]} />
          <meshStandardMaterial map={panelTex} emissive="#ffffff" emissiveMap={panelTex} emissiveIntensity={0.6} />
        </mesh>
      </group>
    </group>
  );
}
