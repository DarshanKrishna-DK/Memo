import * as THREE from 'three';

/** Mixamo-family bone name without the `mixamorig` / `mixamorig:` prefix. */
export function baseBoneName(name: string): string {
  return name.replace(/^mixamorig:?/, '');
}

function collectBones(root: THREE.Object3D): Map<string, THREE.Bone> {
  const m = new Map<string, THREE.Bone>();
  root.traverse((o) => {
    if ((o as THREE.Bone).isBone) {
      const k = baseBoneName(o.name);
      if (!m.has(k)) m.set(k, o as THREE.Bone);
    }
  });
  return m;
}

/** The child bone that defines a bone's direction (Mixamo naming). */
function childKey(k: string): string | null {
  const fixed: Record<string, string> = {
    Hips: 'Spine', Spine: 'Spine1', Spine1: 'Spine2', Spine2: 'Neck', Neck: 'Head', Head: 'HeadTop_End',
  };
  if (fixed[k]) return fixed[k];
  const side = k.startsWith('Left') ? 'Left' : k.startsWith('Right') ? 'Right' : '';
  if (!side) return null;
  const rest = k.slice(side.length);
  const chain: Record<string, string> = {
    Shoulder: 'Arm', Arm: 'ForeArm', ForeArm: 'Hand', Hand: 'HandMiddle1',
    UpLeg: 'Leg', Leg: 'Foot', Foot: 'ToeBase', ToeBase: 'Toe_End',
  };
  if (chain[rest]) return side + chain[rest];
  const m = rest.match(/^(Hand(?:Thumb|Index|Middle|Ring|Pinky))(\d)$/);
  if (m) return `${side}${m[1]}${Number(m[2]) + 1}`;
  return null;
}

/**
 * Bake `clip` (authored for `source`) onto `target` by transferring each
 * bone's WORLD-space rotation delta from the rest pose. Works across rigs
 * whose bone local axes differ (Xbot's axis-aligned bones vs Michelle /
 * Ready Player Me's bone-aligned ones) as long as both rest poses are the
 * same pose (all Mixamo-family rigs here bind in T-pose).
 *
 * Both roots must be detached (no parent) and in their bind pose.
 * The returned clip uses the target's bone names, so it can be played by a
 * mixer on any clone of the target.
 */
export function bakeRetargetedClip(
  source: THREE.Object3D,
  target: THREE.Object3D,
  clip: THREE.AnimationClip,
  fps = 30,
): THREE.AnimationClip {
  const srcBones = collectBones(source);
  const tgtBones = collectBones(target);
  const srcRestLocal: Array<[THREE.Bone, THREE.Quaternion, THREE.Vector3]> = [];
  srcBones.forEach((b) => srcRestLocal.push([b, b.quaternion.clone(), b.position.clone()]));

  source.updateMatrixWorld(true);
  target.updateMatrixWorld(true);

  // Rest-pose world rotations.
  const srcRest = new Map<string, THREE.Quaternion>();
  const srcRestInv = new Map<string, THREE.Quaternion>();
  srcBones.forEach((b, k) => {
    const q = b.getWorldQuaternion(new THREE.Quaternion());
    srcRest.set(k, q);
    srcRestInv.set(k, q.clone().invert());
  });
  // Target rest rotations, each bone swung so its direction matches the
  // source rest pose (puts A-pose / wide-stance rigs into the source's
  // T-pose before the deltas are applied).
  const tgtRest = new Map<string, THREE.Quaternion>();
  tgtBones.forEach((b, k) => {
    const q = b.getWorldQuaternion(new THREE.Quaternion());
    const child = childKey(k);
    const sb = srcBones.get(k);
    const tc = child ? tgtBones.get(child) : undefined;
    const sc = child ? srcBones.get(child) : undefined;
    if (sb && tc && sc) {
      const dT = tc.getWorldPosition(new THREE.Vector3()).sub(b.getWorldPosition(new THREE.Vector3()));
      const dS = sc.getWorldPosition(new THREE.Vector3()).sub(sb.getWorldPosition(new THREE.Vector3()));
      if (dT.lengthSq() > 1e-10 && dS.lengthSq() > 1e-10) {
        const align = new THREE.Quaternion().setFromUnitVectors(dT.normalize(), dS.normalize());
        q.premultiply(align);
      }
    }
    tgtRest.set(k, q);
  });

  // Target bones in parent-first order.
  const order: THREE.Bone[] = [];
  target.traverse((o) => {
    if ((o as THREE.Bone).isBone) order.push(o as THREE.Bone);
  });
  const restLocal = new Map<THREE.Bone, THREE.Quaternion>();
  order.forEach((b) => restLocal.set(b, b.quaternion.clone()));

  // Hips translation transfer.
  const sHips = srcBones.get('Hips');
  const tHips = tgtBones.get('Hips');
  const sHipsRest = sHips ? sHips.getWorldPosition(new THREE.Vector3()) : new THREE.Vector3();
  const tHipsRest = tHips ? tHips.getWorldPosition(new THREE.Vector3()) : new THREE.Vector3();
  const hipRatio = sHipsRest.y > 1e-4 ? tHipsRest.y / sHipsRest.y : 1;
  const tHipsParentInv = tHips?.parent
    ? tHips.parent.matrixWorld.clone().invert()
    : new THREE.Matrix4();

  const mixer = new THREE.AnimationMixer(source);
  const action = mixer.clipAction(clip);
  action.play();

  const frames = Math.max(2, Math.ceil(clip.duration * fps) + 1);
  const times = new Float32Array(frames);
  const qValues = new Map<THREE.Bone, Float32Array>();
  order.forEach((b) => qValues.set(b, new Float32Array(frames * 4)));
  const hipPos = new Float32Array(frames * 3);

  const worldQ = new Map<THREE.Object3D, THREE.Quaternion>();
  const tmpQ = new THREE.Quaternion();
  const tmpV = new THREE.Vector3();
  const targetRootParentQ = new THREE.Quaternion();

  for (let f = 0; f < frames; f++) {
    const t = Math.min(clip.duration, (f / (frames - 1)) * clip.duration);
    times[f] = t;
    mixer.setTime(t);
    source.updateMatrixWorld(true);
    worldQ.clear();

    for (const b of order) {
      const k = baseBoneName(b.name);
      const parent = b.parent!;
      let parentWorld = worldQ.get(parent);
      if (!parentWorld) {
        // Non-bone ancestor (Armature / Character node): static.
        parentWorld = parent ? parent.getWorldQuaternion(targetRootParentQ.clone()) : new THREE.Quaternion();
      }
      const sb = srcBones.get(k);
      let local: THREE.Quaternion;
      let world: THREE.Quaternion;
      if (sb && srcRestInv.has(k) && tgtRest.has(k)) {
        const sWorld = sb.getWorldQuaternion(tmpQ);
        world = sWorld.clone().multiply(srcRestInv.get(k)!).multiply(tgtRest.get(k)!);
        local = parentWorld.clone().invert().multiply(world);
      } else {
        local = restLocal.get(b)!.clone();
        world = parentWorld.clone().multiply(local);
      }
      worldQ.set(b, world);
      local.toArray(qValues.get(b)!, f * 4);
    }

    if (sHips && tHips) {
      const sp = sHips.getWorldPosition(tmpV);
      const wp = new THREE.Vector3(
        tHipsRest.x + (sp.x - sHipsRest.x) * hipRatio,
        tHipsRest.y + (sp.y - sHipsRest.y) * hipRatio,
        tHipsRest.z + (sp.z - sHipsRest.z) * hipRatio,
      ).applyMatrix4(tHipsParentInv);
      wp.toArray(hipPos, f * 3);
    }
  }

  mixer.stopAllAction();
  mixer.uncacheRoot(source);

  const tracks: THREE.KeyframeTrack[] = [];
  for (const b of order) {
    if (!srcBones.has(baseBoneName(b.name))) continue;
    tracks.push(new THREE.QuaternionKeyframeTrack(`${b.name}.quaternion`, times, qValues.get(b)!));
  }
  if (tHips) tracks.push(new THREE.VectorKeyframeTrack(`${tHips.name}.position`, times, hipPos));

  // Restore both rigs to rest so later bakes start clean.
  order.forEach((b) => b.quaternion.copy(restLocal.get(b)!));
  for (const [b, q, p] of srcRestLocal) {
    b.quaternion.copy(q);
    b.position.copy(p);
  }
  source.updateMatrixWorld(true);
  return new THREE.AnimationClip(clip.name, clip.duration, tracks);
}
