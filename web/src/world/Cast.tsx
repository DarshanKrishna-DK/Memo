import { useEffect, useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { RECEPTIONIST } from './layout';
import { Robot, makeRobotControl } from './Robot';
import { useRuntime } from './runtime';
import { FONT_SANS, PAL, canvasTex } from './textures';

const FOLLOW: Record<string, string> = {
  'en-IN': 'Follow me!',
  'hi-IN': 'मेरे पीछे आइए!',
  'kn-IN': 'ನನ್ನ ಹಿಂದೆ ಬನ್ನಿ!',
};

export function guideLine(lang: string) {
  return FOLLOW[lang] ?? FOLLOW['en-IN'];
}

function bubbleTex(text: string) {
  return canvasTex(512, 160, (g) => {
    g.fillStyle = PAL.navyDeep;
    g.fillRect(14, 14, 484, 110);
    g.fillStyle = PAL.cream;
    g.fillRect(6, 6, 484, 110);
    g.beginPath();
    g.moveTo(230, 116);
    g.lineTo(256, 152);
    g.lineTo(282, 116);
    g.fill();
    g.fillStyle = PAL.navy;
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.font = `600 52px ${FONT_SANS}`;
    g.fillText(text, 248, 62, 460);
  });
}

/** The guide robot: driven by rt.guide (the walk director, or its rest spot). */
export function GuideRobot() {
  const rt = useRuntime();
  const g = useRef<THREE.Group>(null);
  const bubble = useRef<THREE.Sprite>(null);
  const control = useMemo(() => makeRobotControl(), []);
  const lastSay = useRef<string | null>(null);
  const mat = useMemo(() => new THREE.SpriteMaterial({ transparent: true, depthTest: false, toneMapped: false }), []);
  useEffect(() => () => { mat.map?.dispose(); mat.dispose(); }, [mat]);
  useFrame(() => {
    const gd = rt.guide;
    if (g.current) {
      g.current.position.set(gd.x, 0, gd.z);
      g.current.rotation.y = gd.yaw;
    }
    control.action = gd.speed > 0.1 ? 'walk' : 'idle';
    control.speed = gd.speed;
    control.wave = !!gd.say;
    control.talk = gd.say ? 0.8 : 0;
    if (gd.say !== lastSay.current) {
      lastSay.current = gd.say;
      mat.map?.dispose();
      mat.map = gd.say ? bubbleTex(gd.say) : null;
      mat.needsUpdate = true;
    }
    if (bubble.current) bubble.current.visible = !!gd.say;
  });

  return (
    <group ref={g}>
      <Robot variant="guide" control={control} />
      <sprite ref={bubble} material={mat} position={[0, 1.95, 0]} scale={[1.2, 0.375, 1]} visible={false} renderOrder={10} />
    </group>
  );
}

/** The receptionist robot behind the lobby desk; nods and pulses while the agent speaks. */
export function ReceptionistRobot({ speaking }: { speaking: () => boolean }) {
  const rt = useRuntime();
  const control = useMemo(() => makeRobotControl(), []);
  const g = useRef<THREE.Group>(null);
  const t = useRef(0);
  useFrame((_, dt) => {
    t.current += dt;
    const talk = speaking() ? 0.5 + 0.5 * Math.abs(Math.sin(t.current * 5)) : 0;
    control.talk = talk;
    // turn a little toward the visitor
    if (g.current) {
      const want = Math.atan2(rt.player.pos.x - RECEPTIONIST.x, rt.player.pos.z - RECEPTIONIST.z);
      const base = RECEPTIONIST.yaw;
      let d = Math.atan2(Math.sin(want - base), Math.cos(want - base));
      d = THREE.MathUtils.clamp(d, -0.7, 0.7);
      g.current.rotation.y += (base + d - g.current.rotation.y) * Math.min(1, dt * 2);
    }
  });
  return (
    <group ref={g} position={[RECEPTIONIST.x, 0, RECEPTIONIST.z]} rotation={[0, RECEPTIONIST.yaw, 0]}>
      <group position={[0, 0.32, 0]}>
        <mesh position={[0, -0.16, 0]} castShadow receiveShadow>
          <cylinderGeometry args={[0.42, 0.48, 0.32, 10]} />
          <meshStandardMaterial color="#1d3f82" roughness={0.5} flatShading />
        </mesh>
        <Robot variant="receptionist" control={control} scale={1.2} />
      </group>
    </group>
  );
}
