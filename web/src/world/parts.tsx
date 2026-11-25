import { useEffect, useMemo, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { PAL, canvasTex } from './textures';
import { useRuntime } from './runtime';

export function Box({
  p, s, color, rough = 0.85, metal = 0, cast = false, emissive, emissiveIntensity = 1, rot,
}: {
  p: [number, number, number]; s: [number, number, number]; color: string; rough?: number; metal?: number; cast?: boolean;
  emissive?: string; emissiveIntensity?: number; rot?: [number, number, number];
}) {
  return (
    <mesh position={p} rotation={rot} castShadow={cast} receiveShadow>
      <boxGeometry args={s} />
      <meshStandardMaterial color={color} roughness={rough} metalness={metal} emissive={emissive ?? '#000000'} emissiveIntensity={emissive ? emissiveIntensity : 0} />
    </mesh>
  );
}

/** Warm herringbone parquet, one texture tile = 2 m. */
export function makeParquetTex() {
  return canvasTex(512, 512, (g) => {
    g.fillStyle = '#6b4a32';
    g.fillRect(0, 0, 512, 512);
    const plankW = 32, plankL = 128;
    let seed = 7;
    const rnd = () => ((seed = (seed * 9301 + 49297) % 233280) / 233280);
    for (let row = -4; row < 20; row++) {
      for (let col = -2; col < 10; col++) {
        const x = col * plankL / 2 + (row % 2) * 0;
        const y = row * plankW + col * plankW;
        for (const dir of [0, 1]) {
          const tone = 92 + rnd() * 34;
          g.fillStyle = `rgb(${tone + 30},${tone - 4},${tone - 36})`;
          g.save();
          g.translate(x + dir * plankW, y);
          g.rotate(dir ? Math.PI / 4 : -Math.PI / 4);
          g.fillRect(0, 0, plankL, plankW - 2);
          g.globalAlpha = 0.12;
          g.fillStyle = '#2a1a10';
          for (let k = 0; k < 4; k++) g.fillRect(0, 4 + k * 7 + rnd() * 3, plankL, 1);
          g.restore();
          g.globalAlpha = 1;
        }
      }
    }
  });
}

/** Low-cost speckled stone for the lobby. */
export function makeStoneTex() {
  return canvasTex(512, 512, (g) => {
    g.fillStyle = '#d9cfbb';
    g.fillRect(0, 0, 512, 512);
    const chips = ['#bfb39c', '#e8e0cf', '#a89a80', '#cbbfa8', '#8f8370'];
    let seed = 3;
    const rnd = () => ((seed = (seed * 9301 + 49297) % 233280) / 233280);
    for (let i = 0; i < 9000; i++) {
      g.fillStyle = chips[(rnd() * chips.length) | 0];
      g.globalAlpha = 0.3 + rnd() * 0.5;
      g.fillRect(rnd() * 512, rnd() * 512, 1.5 + rnd() * 2, 1.5 + rnd() * 2);
    }
    g.globalAlpha = 1;
    g.fillStyle = 'rgba(90,70,50,0.45)';
    for (let i = 0; i <= 2; i++) {
      g.fillRect(i * 256 - 1, 0, 2, 512);
      g.fillRect(0, i * 256 - 1, 512, 2);
    }
  });
}

export function FloorPlane({ x0, x1, z0, z1, kind }: { x0: number; x1: number; z0: number; z1: number; kind: 'parquet' | 'stone' }) {
  const w = x1 - x0, d = z1 - z0;
  const map = useMemo(() => {
    const t = kind === 'parquet' ? makeParquetTex() : makeStoneTex();
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(w / (kind === 'parquet' ? 2 : 2.4), d / (kind === 'parquet' ? 2 : 2.4));
    return t;
  }, [w, d, kind]);
  useEffect(() => () => map.dispose(), [map]);
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[(x0 + x1) / 2, 0, (z0 + z1) / 2]} receiveShadow>
      <planeGeometry args={[w, d]} />
      <meshStandardMaterial map={map} roughness={kind === 'parquet' ? 0.55 : 0.4} />
    </mesh>
  );
}

/** A wall slab from (x0,z0) to (x1,z1) on the floor, with a navy wainscot and gold rail facing `face`. */
export function Wall({ a, b, h, face, wainscot = true, color = PAL.wall }: { a: [number, number]; b: [number, number]; h: number; face: 1 | -1; wainscot?: boolean; color?: string }) {
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
  if (len < 0.01) return null;
  const cx = (a[0] + b[0]) / 2, cz = (a[1] + b[1]) / 2;
  const ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
  // local +z is the face normal side
  return (
    <group position={[cx, 0, cz]} rotation={[0, -ang, 0]}>
      <mesh position={[0, h / 2, -face * 0.15]} receiveShadow>
        <boxGeometry args={[len, h, 0.3]} />
        <meshStandardMaterial color={color} roughness={0.92} />
      </mesh>
      {wainscot && (
        <>
          <mesh position={[0, 0.55, face * 0.012]} receiveShadow>
            <boxGeometry args={[len, 1.1, 0.024]} />
            <meshStandardMaterial color={PAL.navy} roughness={0.7} />
          </mesh>
          <mesh position={[0, 1.12, face * 0.03]}>
            <boxGeometry args={[len, 0.05, 0.04]} />
            <meshStandardMaterial color={PAL.gold} roughness={0.35} metalness={0.6} />
          </mesh>
          <mesh position={[0, 0.06, face * 0.03]}>
            <boxGeometry args={[len, 0.12, 0.03]} />
            <meshStandardMaterial color={PAL.woodDark} roughness={0.6} />
          </mesh>
        </>
      )}
    </group>
  );
}

export function Ceiling({ x0, x1, z0, z1, y }: { x0: number; x1: number; z0: number; z1: number; y: number }) {
  return (
    <mesh rotation={[Math.PI / 2, 0, 0]} position={[(x0 + x1) / 2, y, (z0 + z1) / 2]}>
      <planeGeometry args={[x1 - x0, z1 - z0]} />
      <meshStandardMaterial color="#1a2a52" roughness={0.95} />
    </mesh>
  );
}

/** Instanced warm downlight discs. Their positions register as light fixtures; one global
 *  <LightPool> hops a few real point lights to the fixtures nearest the player (constant
 *  shader cost whatever is on display). */
export function Downlights({ points, y }: { points: Array<[number, number]>; y: number; count?: number; intensity?: number }) {
  const rt = useRuntime();
  const mesh = useRef<THREE.InstancedMesh>(null);
  useEffect(() => {
    const m = mesh.current;
    if (!m) return;
    const o = new THREE.Object3D();
    points.forEach(([x, z], i) => {
      o.position.set(x, y - 0.01, z);
      o.rotation.set(Math.PI / 2, 0, 0);
      o.updateMatrix();
      m.setMatrixAt(i, o.matrix);
    });
    m.count = points.length;
    m.instanceMatrix.needsUpdate = true;
    m.updateWorldMatrix(true, false);
    const id = Symbol('fixtures');
    const world = points.map(([x, z]) => new THREE.Vector3(x, y - 0.5, z).applyMatrix4(m.matrixWorld));
    rt.fixtures.set(id, world);
    return () => { rt.fixtures.delete(id); };
  }, [points, y, rt]);
  return (
    <instancedMesh ref={mesh} args={[undefined, undefined, Math.max(1, points.length)]} frustumCulled={false}>
      <circleGeometry args={[0.16, 12]} />
      <meshBasicMaterial color="#ffe2b0" toneMapped={false} side={THREE.DoubleSide} />
    </instancedMesh>
  );
}

export function LightPool({ count = 4, intensity = 5 }: { count?: number; intensity?: number }) {
  const rt = useRuntime();
  const refs = useRef<Array<THREE.PointLight | null>>([]);
  const all = useRef<THREE.Vector3[]>([]);
  useFrame(() => {
    const p = rt.player.pos;
    const list = all.current;
    list.length = 0;
    rt.fixtures.forEach((v) => { for (const x of v) list.push(x); });
    list.sort((a, b) => ((a.x - p.x) ** 2 + (a.z - p.z) ** 2) - ((b.x - p.x) ** 2 + (b.z - p.z) ** 2));
    for (let k = 0; k < count; k++) {
      const l = refs.current[k];
      if (!l) continue;
      const f = list[k];
      if (f) { l.position.copy(f); l.intensity = intensity; } else l.intensity = 0;
    }
  });
  return (
    <>
      {Array.from({ length: count }, (_, i) => (
        <pointLight key={i} ref={(l) => { refs.current[i] = l; }} intensity={intensity} distance={8} decay={1.6} color="#ffd9a6" />
      ))}
    </>
  );
}

/** Shadow-casting key light that follows the player (tight frustum = cheap, sharp). */
export function FollowKey({ intensity = 0.9 }: { intensity?: number }) {
  const rt = useRuntime();
  const light = useRef<THREE.DirectionalLight>(null);
  const { scene } = useThree();
  useEffect(() => {
    const l = light.current;
    if (!l) return;
    scene.add(l.target);
    return () => { scene.remove(l.target); };
  }, [scene]);
  useFrame(() => {
    const l = light.current;
    if (!l) return;
    const p = rt.player.pos;
    l.position.set(p.x + 1.8, 7, p.z + 2.6);
    l.target.position.set(p.x, 0, p.z);
    l.target.updateMatrixWorld();
  });
  return (
    <directionalLight
      ref={light}
      intensity={intensity}
      color="#ffe6c4"
      castShadow
      shadow-mapSize-width={1024}
      shadow-mapSize-height={1024}
      shadow-camera-left={-6}
      shadow-camera-right={6}
      shadow-camera-top={6}
      shadow-camera-bottom={-6}
      shadow-camera-near={0.5}
      shadow-camera-far={20}
      shadow-bias={-0.0004}
      shadow-normalBias={0.03}
    />
  );
}

/** Text drawn on a canvas, shown as a self-lit plane. Redraws when `deps` change. */
export function CanvasPlane({
  w, h, px = 256, draw, deps, position, rotation, emissive = 0.9, transparent = false, onClick,
}: {
  w: number; h: number; px?: number; draw: (g: CanvasRenderingContext2D, W: number, H: number) => void; deps: unknown[];
  position: [number, number, number]; rotation?: [number, number, number]; emissive?: number; transparent?: boolean;
  onClick?: () => void;
}) {
  const W = Math.round(px * w), H = Math.round(px * h);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const tex = useMemo(() => canvasTex(W, H, (g) => draw(g, W, H)), [W, H, ...deps]);
  useEffect(() => () => tex.dispose(), [tex]);
  return (
    <mesh
      position={position}
      rotation={rotation}
      onClick={onClick ? (e) => { e.stopPropagation(); onClick(); } : undefined}
      onPointerOver={onClick ? () => { document.body.style.cursor = 'pointer'; } : undefined}
      onPointerOut={onClick ? () => { document.body.style.cursor = ''; } : undefined}
    >
      <planeGeometry args={[w, h]} />
      <meshStandardMaterial map={tex} emissive="#ffffff" emissiveMap={tex} emissiveIntensity={emissive} roughness={0.7} transparent={transparent} toneMapped={false} />
    </mesh>
  );
}
