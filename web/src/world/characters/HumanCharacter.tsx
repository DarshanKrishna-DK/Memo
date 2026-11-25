import { useEffect, useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import { clone as cloneSkinned } from 'three/examples/jsm/utils/SkeletonUtils.js';
import { ANIM_URL, RIG_URL, lookKey, type Look, type RigId } from './rigs';
import { bakeRetargetedClip, baseBoneName } from './retarget';
import { addPlacket, applyLook, trimTop } from './appearance';

// Ported from MedSim src/components/world/HumanCharacter.tsx (idle / walk / run clips
// retargeted from Xbot, procedural sit blend, head look-at, speech head motion).

export type CharacterAction = 'idle' | 'walk' | 'run' | 'sit';

/** Mutable per-frame control block: parents mutate it, no React re-render per frame. */
export interface CharacterControl {
  action: CharacterAction;
  /** Ground speed in m/s: drives walk/run playback rate. */
  speed: number;
  /** 0..1 speech level for head motion. */
  mouth?: () => number;
  /** World point the head should turn toward (clamped). */
  lookAt?: THREE.Vector3 | null;
  /** Seat height in metres for the `sit` action. */
  seatHeight?: number;
  /** 0..1 right-hand wave (a hello when someone sits down in the theater). */
  wave?: number;
}

export function makeControl(partial: Partial<CharacterControl> = {}): CharacterControl {
  return { action: 'idle', speed: 0, ...partial };
}

const CLIP_SOURCE_NAMES = { idle: 'idle', walk: 'walk', run: 'run' } as const;
type BaseClip = keyof typeof CLIP_SOURCE_NAMES;

const clipCache = new Map<RigId, Record<BaseClip, THREE.AnimationClip>>();
let animSource: THREE.Object3D | null = null;

function getClips(rig: RigId, rigScene: THREE.Object3D, animGltf: { scene: THREE.Object3D; animations: THREE.AnimationClip[] }) {
  const cached = clipCache.get(rig);
  if (cached) return cached;
  if (!animSource) animSource = cloneSkinned(animGltf.scene);
  const target = cloneSkinned(rigScene);
  const out = {} as Record<BaseClip, THREE.AnimationClip>;
  (Object.keys(CLIP_SOURCE_NAMES) as BaseClip[]).forEach((k) => {
    const src = THREE.AnimationClip.findByName(animGltf.animations, CLIP_SOURCE_NAMES[k]);
    out[k] = bakeRetargetedClip(animSource!, target, src, 30);
  });
  clipCache.set(rig, out);
  return out;
}

interface Bones {
  hips?: THREE.Bone; spine?: THREE.Bone; spine2?: THREE.Bone; neck?: THREE.Bone; head?: THREE.Bone;
  lUpLeg?: THREE.Bone; rUpLeg?: THREE.Bone; lLeg?: THREE.Bone; rLeg?: THREE.Bone; lFoot?: THREE.Bone; rFoot?: THREE.Bone;
  lArm?: THREE.Bone; rArm?: THREE.Bone; lForeArm?: THREE.Bone; rForeArm?: THREE.Bone; lHand?: THREE.Bone; rHand?: THREE.Bone;
}

interface Built {
  root: THREE.Group;
  model: THREE.Object3D;
  mixer: THREE.AnimationMixer;
  actions: Record<BaseClip, THREE.AnimationAction>;
  bones: Bones;
  hipHeight: number;
  baseY: number;
  materials: THREE.Material[];
  geometries: THREE.BufferGeometry[];
}

const BONE_KEY: Record<string, keyof Bones> = {
  Hips: 'hips', Spine: 'spine', Spine2: 'spine2', Neck: 'neck', Head: 'head',
  LeftUpLeg: 'lUpLeg', RightUpLeg: 'rUpLeg', LeftLeg: 'lLeg', RightLeg: 'rLeg', LeftFoot: 'lFoot', RightFoot: 'rFoot',
  LeftArm: 'lArm', RightArm: 'rArm', LeftForeArm: 'lForeArm', RightForeArm: 'rForeArm', LeftHand: 'lHand', RightHand: 'rHand',
};

function build(rigScene: THREE.Object3D, animGltf: { scene: THREE.Object3D; animations: THREE.AnimationClip[] }, look: Look): Built {
  const clips = getClips(look.rig, rigScene, animGltf);
  const model = cloneSkinned(rigScene);
  const materials: THREE.Material[] = [];
  const bones: Bones = {};
  model.traverse((o) => {
    if ((o as THREE.Bone).isBone) {
      const k = BONE_KEY[baseBoneName(o.name)];
      if (k && !bones[k]) bones[k] = o as THREE.Bone;
    }
    const mesh = o as THREE.Mesh;
    if (mesh.isMesh) {
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.frustumCulled = false;
      applyLook(mesh, look, materials);
    }
  });

  model.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(model);
  const natural = Math.max(0.2, box.max.y - box.min.y);
  const before = new Set<THREE.BufferGeometry>();
  model.traverse((o) => { if ((o as THREE.Mesh).isMesh) before.add((o as THREE.Mesh).geometry); });
  if (look.hem) {
    const hemY = box.min.y + natural * look.hem;
    trimTop(model, hemY);
    if (look.placket) addPlacket(model, bones.spine2, bones.neck, look.placket, hemY, materials);
  }
  // Geometries created here (trimmed clones, placket) are ours to dispose.
  const geometries: THREE.BufferGeometry[] = [];
  model.traverse((o) => {
    const g = (o as THREE.Mesh).geometry;
    if ((o as THREE.Mesh).isMesh && g && !before.has(g)) geometries.push(g);
  });

  const s = look.height / natural;
  const root = new THREE.Group();
  root.scale.setScalar(s);
  const baseY = -box.min.y * s;
  root.position.y = baseY;
  root.add(model);
  const hipHeight = bones.hips ? bones.hips.getWorldPosition(new THREE.Vector3()).y * s + baseY : look.height * 0.53;

  const mixer = new THREE.AnimationMixer(model);
  const actions = {
    idle: mixer.clipAction(clips.idle),
    walk: mixer.clipAction(clips.walk),
    run: mixer.clipAction(clips.run),
  };
  actions.idle.play();
  return { root, model, mixer, actions, bones, hipHeight, baseY, materials, geometries };
}

const _pq = new THREE.Quaternion();
const _pqi = new THREE.Quaternion();
const _rq = new THREE.Quaternion();
const _v = new THREE.Vector3();
const _v2 = new THREE.Vector3();
const _rootQ = new THREE.Quaternion();
const _hp = new THREE.Vector3();
const _fwd = new THREE.Vector3();
const _to = new THREE.Vector3();

/** Rotate a bone by `angle` around a WORLD-space axis (bone-axis agnostic). */
function rotateWorld(bone: THREE.Bone | undefined, axis: THREE.Vector3, angle: number) {
  if (!bone || !bone.parent || Math.abs(angle) < 1e-5) return;
  bone.parent.getWorldQuaternion(_pq);
  _pqi.copy(_pq).invert();
  _rq.setFromAxisAngle(axis, angle);
  bone.quaternion.premultiply(_pq).premultiply(_rq).premultiply(_pqi);
  bone.updateMatrixWorld(true);
}

export function HumanCharacter({ look, control }: { look: Look; control: CharacterControl }) {
  const rigGltf = useGLTF(RIG_URL[look.rig]);
  const animGltf = useGLTF(ANIM_URL);
  const key = lookKey(look);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const built = useMemo(() => build(rigGltf.scene, animGltf, look), [rigGltf.scene, animGltf, key]);

  useEffect(
    () => () => {
      built.mixer.stopAllAction();
      built.mixer.uncacheRoot(built.model);
      built.materials.forEach((m) => m.dispose());
      built.geometries.forEach((g) => g.dispose());
    },
    [built],
  );

  const st = useRef({ current: 'idle' as BaseClip, sit: 0, talk: 0, wave: 0, t: Math.random() * 10, look: 0, lookYaw: 0 });

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.1);
    const s = st.current;
    s.t += dt;
    const a = control.action;
    const want: BaseClip = a === 'walk' ? 'walk' : a === 'run' ? 'run' : 'idle';
    if (want !== s.current) {
      const from = built.actions[s.current];
      const to = built.actions[want];
      to.reset().setEffectiveWeight(1).play();
      from.crossFadeTo(to, 0.25, false);
      s.current = want;
    }
    const hScale = look.height / 1.78;
    if (want === 'walk') built.actions.walk.timeScale = THREE.MathUtils.clamp(control.speed / (1.45 * hScale), 0.6, 1.8);
    if (want === 'run') built.actions.run.timeScale = THREE.MathUtils.clamp(control.speed / (3.9 * hScale), 0.7, 1.6);
    built.mixer.update(dt);

    const sitTarget = a === 'sit' ? 1 : 0;
    s.sit += (sitTarget - s.sit) * Math.min(1, dt * 5);
    if (Math.abs(s.sit - sitTarget) < 0.002) s.sit = sitTarget;

    const root = built.root;
    root.updateMatrixWorld(true);
    const rq = root.getWorldQuaternion(_rootQ);
    const right = _v.set(-1, 0, 0).applyQuaternion(rq).normalize();
    const b = built.bones;
    const w = s.sit;
    if (w > 0.001) {
      rotateWorld(b.spine, right, 0.06 * w);
      rotateWorld(b.lUpLeg, right, 1.5 * w);
      rotateWorld(b.rUpLeg, right, 1.5 * w);
      rotateWorld(b.lLeg, right, -1.45 * w);
      rotateWorld(b.rLeg, right, -1.45 * w);
      rotateWorld(b.lFoot, right, -0.05 * w);
      rotateWorld(b.rFoot, right, -0.05 * w);
      rotateWorld(b.lArm, right, 0.45 * w);
      rotateWorld(b.rArm, right, 0.45 * w);
      rotateWorld(b.lForeArm, right, 0.75 * w);
      rotateWorld(b.rForeArm, right, 0.75 * w);
      const seat = control.seatHeight ?? 0.47;
      const drop = Math.max(0, built.hipHeight - (seat + 0.1 * hScale));
      root.position.y = built.baseY - drop * w;
      root.position.z = -0.12 * hScale * w;
    } else {
      root.position.y = built.baseY;
      root.position.z = 0;
    }

    const wv = control.wave ?? 0;
    s.wave += (wv - s.wave) * Math.min(1, dt * 6);
    if (s.wave > 0.01) {
      const fwd = _v2.set(0, 0, 1).applyQuaternion(rq).normalize();
      rotateWorld(b.rArm, fwd, -2.3 * s.wave);
      rotateWorld(b.rForeArm, fwd, (-0.35 + Math.sin(s.t * 9) * 0.4) * s.wave);
    }

    const m = control.mouth ? THREE.MathUtils.clamp(control.mouth(), 0, 1) : 0;
    s.talk += (m - s.talk) * Math.min(1, dt * 18);
    if (s.talk > 0.02) {
      rotateWorld(b.head, right, Math.sin(s.t * 7.3) * 0.045 * s.talk);
      rotateWorld(b.neck, _v2.set(0, 1, 0), Math.sin(s.t * 2.1) * 0.06 * s.talk);
    }

    const target = control.lookAt;
    s.look += ((target ? 1 : 0) - s.look) * Math.min(1, dt * 3);
    if (target && b.head) {
      b.head.getWorldPosition(_hp);
      _fwd.set(0, 0, 1).applyQuaternion(rq);
      _to.copy(target).sub(_hp);
      const yawFwd = Math.atan2(_fwd.x, _fwd.z);
      let yaw = Math.atan2(_to.x, _to.z) - yawFwd;
      yaw = Math.atan2(Math.sin(yaw), Math.cos(yaw));
      yaw = THREE.MathUtils.clamp(yaw, -1.0, 1.0);
      s.lookYaw += (yaw - s.lookYaw) * Math.min(1, dt * 4);
    }
    if (s.look > 0.01) {
      const up = _v2.set(0, 1, 0);
      rotateWorld(b.neck, up, s.lookYaw * 0.45 * s.look);
      rotateWorld(b.head, up, s.lookYaw * 0.4 * s.look);
    }
  });

  return <primitive object={built.root} />;
}

/** Bake the retargeted clips for every rig up front (call inside Suspense, behind the loading
 *  overlay) so the first Grandma / player mount does not hitch mid-walk. */
export function WarmCharacters() {
  const anim = useGLTF(ANIM_URL);
  const male = useGLTF(RIG_URL.male);
  const saree = useGLTF(RIG_URL.saree);
  useMemo(() => {
    getClips('male', male.scene, anim);
    getClips('saree', saree.scene, anim);
  }, [anim, male.scene, saree.scene]);
  return null;
}

export function preloadCharacters() {
  useGLTF.preload(ANIM_URL);
  useGLTF.preload(RIG_URL.male);
  useGLTF.preload(RIG_URL.saree);
}
