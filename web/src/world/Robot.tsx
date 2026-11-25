import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { PAL } from './textures';

// Friendly stylised low-poly robots (procedural, flat-shaded to sit with the GTA-style people).
// The receptionist works the lobby desk; the guide walks visitors to their room.

export interface RobotControl {
  action: 'idle' | 'walk';
  speed: number;
  /** 0..1 talking pulse (eyes + head nod). */
  talk?: number;
  /** Wave an arm (greeting / "follow me"). */
  wave?: boolean;
}

export function makeRobotControl(): RobotControl {
  return { action: 'idle', speed: 0, talk: 0, wave: false };
}

type Variant = 'receptionist' | 'guide';

const SCHEME: Record<Variant, { shell: string; trim: string; accent: string; eye: string }> = {
  receptionist: { shell: '#f3f1e2', trim: PAL.navy, accent: PAL.gold, eye: PAL.teal },
  guide: { shell: '#f3f1e2', trim: '#1d3f82', accent: PAL.lime, eye: PAL.lime },
};

const G = {
  torso: new THREE.CapsuleGeometry(0.27, 0.32, 3, 8),
  belly: new THREE.CylinderGeometry(0.2, 0.24, 0.1, 8),
  head: new THREE.SphereGeometry(0.25, 10, 7),
  visor: new THREE.SphereGeometry(0.2, 10, 6, -Math.PI * 0.42, Math.PI * 0.84, Math.PI * 0.3, Math.PI * 0.38),
  eye: new THREE.CapsuleGeometry(0.03, 0.035, 2, 6),
  antenna: new THREE.CylinderGeometry(0.012, 0.012, 0.16, 5),
  bulb: new THREE.IcosahedronGeometry(0.04, 0),
  ear: new THREE.CylinderGeometry(0.06, 0.06, 0.05, 8),
  arm: new THREE.CapsuleGeometry(0.06, 0.28, 2, 6),
  hand: new THREE.IcosahedronGeometry(0.075, 0),
  leg: new THREE.CapsuleGeometry(0.075, 0.22, 2, 6),
  foot: new THREE.BoxGeometry(0.15, 0.07, 0.22),
  base: new THREE.CylinderGeometry(0.2, 0.28, 0.18, 8),
  badge: new THREE.CircleGeometry(0.07, 6),
};

function useMats(v: Variant) {
  return useMemo(() => {
    const c = SCHEME[v];
    const m = {
      shell: new THREE.MeshStandardMaterial({ color: c.shell, roughness: 0.35, metalness: 0.05, flatShading: true }),
      trim: new THREE.MeshStandardMaterial({ color: c.trim, roughness: 0.5, metalness: 0.2, flatShading: true }),
      accent: new THREE.MeshStandardMaterial({ color: c.accent, roughness: 0.4, metalness: 0.3, flatShading: true }),
      visor: new THREE.MeshStandardMaterial({ color: '#0a1430', roughness: 0.15, metalness: 0.4 }),
      eye: new THREE.MeshBasicMaterial({ color: c.eye, toneMapped: false }),
      glow: new THREE.MeshBasicMaterial({ color: c.accent, toneMapped: false }),
    };
    return m;
  }, [v]);
}

export function Robot({ variant, control, scale = 1 }: { variant: Variant; control: RobotControl; scale?: number }) {
  const m = useMats(variant);
  const body = useRef<THREE.Group>(null);
  const head = useRef<THREE.Group>(null);
  const eyes = useRef<THREE.Group>(null);
  const lArm = useRef<THREE.Group>(null);
  const rArm = useRef<THREE.Group>(null);
  const lLeg = useRef<THREE.Group>(null);
  const rLeg = useRef<THREE.Group>(null);
  const st = useRef({ t: Math.random() * 10, phase: 0, walk: 0, blink: 2 + Math.random() * 3 });
  const legged = variant === 'guide';

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.1);
    const s = st.current;
    s.t += dt;
    const walking = control.action === 'walk' && control.speed > 0.05;
    s.walk += ((walking ? 1 : 0) - s.walk) * Math.min(1, dt * 6);
    s.phase += dt * (walking ? Math.max(4, control.speed * 3.2) : 0);
    const w = s.walk;
    const sw = Math.sin(s.phase);
    const talk = control.talk ?? 0;
    if (body.current) {
      body.current.position.y = Math.sin(s.t * 2.1) * 0.015 * (1 - w) + Math.abs(Math.cos(s.phase)) * 0.04 * w;
      body.current.rotation.x = 0.08 * w;
      body.current.rotation.z = sw * 0.03 * w;
    }
    if (head.current) {
      head.current.rotation.z = Math.sin(s.t * 0.7) * 0.06 * (1 - w);
      head.current.rotation.x = Math.sin(s.t * 9) * 0.05 * talk - 0.04 * w;
      head.current.rotation.y = Math.sin(s.t * 0.45) * 0.18 * (1 - w);
    }
    // blink
    s.blink -= dt;
    const closing = s.blink < 0.12 && s.blink > 0;
    if (s.blink <= 0) s.blink = 2.2 + Math.random() * 3.5;
    if (eyes.current) {
      eyes.current.scale.y = closing ? 0.15 : 1 + talk * 0.25 * Math.abs(Math.sin(s.t * 12));
    }
    const wave = control.wave ? 1 : 0;
    if (lArm.current) lArm.current.rotation.x = sw * 0.6 * w + Math.sin(s.t * 1.3) * 0.04;
    if (rArm.current) {
      rArm.current.rotation.x = -sw * 0.6 * w * (1 - wave) - wave * 2.6;
      rArm.current.rotation.z = wave * (0.35 + Math.sin(s.t * 9) * 0.35);
    }
    if (lLeg.current) lLeg.current.rotation.x = -sw * 0.55 * w;
    if (rLeg.current) rLeg.current.rotation.x = sw * 0.55 * w;
  });

  const hipY = legged ? 0.42 : 0.2;
  return (
    <group scale={scale}>
      {legged ? (
        <>
          <group ref={lLeg} position={[0.11, hipY, 0]}>
            <mesh geometry={G.leg} material={m.trim} position={[0, -0.18, 0]} castShadow />
            <mesh geometry={G.foot} material={m.shell} position={[0, -0.38, 0.03]} castShadow />
          </group>
          <group ref={rLeg} position={[-0.11, hipY, 0]}>
            <mesh geometry={G.leg} material={m.trim} position={[0, -0.18, 0]} castShadow />
            <mesh geometry={G.foot} material={m.shell} position={[0, -0.38, 0.03]} castShadow />
          </group>
        </>
      ) : (
        <mesh geometry={G.base} material={m.trim} position={[0, 0.09, 0]} castShadow />
      )}
      <group ref={body} >
        <group position={[0, hipY + 0.34, 0]}>
          <mesh geometry={G.torso} material={m.shell} castShadow />
          <mesh geometry={G.belly} material={m.trim} position={[0, -0.2, 0]} />
          <mesh geometry={G.badge} material={m.glow} position={[0, 0.06, 0.272]} />
          <group ref={lArm} position={[0.33, 0.16, 0]}>
            <mesh geometry={G.arm} material={m.trim} position={[0, -0.18, 0]} castShadow />
            <mesh geometry={G.hand} material={m.shell} position={[0, -0.38, 0]} castShadow />
          </group>
          <group ref={rArm} position={[-0.33, 0.16, 0]}>
            <mesh geometry={G.arm} material={m.trim} position={[0, -0.18, 0]} castShadow />
            <mesh geometry={G.hand} material={m.shell} position={[0, -0.38, 0]} castShadow />
          </group>
          <group ref={head} position={[0, 0.5, 0]}>
            <mesh geometry={G.head} material={m.shell} scale={[1.15, 0.92, 1]} castShadow />
            <mesh geometry={G.visor} material={m.visor} position={[0, 0.0, 0.07]} scale={[1.35, 1.1, 1]} />
            <group ref={eyes} position={[0, 0.02, 0.29]}>
              <mesh geometry={G.eye} material={m.eye} position={[0.075, 0, 0]} />
              <mesh geometry={G.eye} material={m.eye} position={[-0.075, 0, 0]} />
            </group>
            <mesh geometry={G.ear} material={m.accent} position={[0.29, 0, 0]} rotation={[0, 0, Math.PI / 2]} />
            <mesh geometry={G.ear} material={m.accent} position={[-0.29, 0, 0]} rotation={[0, 0, Math.PI / 2]} />
            <mesh geometry={G.antenna} material={m.trim} position={[0, 0.3, 0]} />
            <mesh geometry={G.bulb} material={m.glow} position={[0, 0.39, 0]} />
          </group>
        </group>
      </group>
    </group>
  );
}
