import { useEffect, useMemo, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { HumanCharacter, makeControl } from './characters/HumanCharacter';
import { seatLook } from './characters/rigs';
import type { Collider } from './layout';
import { isTypingTarget, useRuntime, wrapAngle } from './runtime';

// Third-person player, ported from MedSim ThirdPersonPlayer.tsx: WASD / arrows / touch joystick,
// camera-relative movement, AABB wall sliding, a camera that pulls in instead of clipping walls.
// Memo changes: drag-to-look (mouse or touch) instead of pointer lock so frames and doors stay
// clickable; a scripted mode for the guided walk; screen mode blends the camera onto the theater
// screen and hides the avatar.

const WALK = 2.3;
const RUN = 5.0;
const RADIUS = 0.3;
const RIG = { distance: 3.3, minDistance: 1.4, maxDistance: 6, pivotHeight: 1.55, seatedPivot: 1.5, shoulder: 0.35 };

function blocked(x: number, z: number, colliders: Collider[]): boolean {
  for (const c of colliders) {
    if (Math.abs(x - c.x) < c.w / 2 + RADIUS && Math.abs(z - c.z) < c.d / 2 + RADIUS) return true;
  }
  return false;
}

/** Earliest hit fraction (0..1) of segment p→q against colliders taller than y, expanded by r. */
function segmentHit(px: number, pz: number, qx: number, qz: number, y: number, r: number, colliders: Collider[]): number {
  let best = 1;
  const dx = qx - px, dz = qz - pz;
  for (const c of colliders) {
    if (c.h !== undefined && c.h < y) continue;
    const minX = c.x - c.w / 2 - r, maxX = c.x + c.w / 2 + r;
    const minZ = c.z - c.d / 2 - r, maxZ = c.z + c.d / 2 + r;
    if (px > minX && px < maxX && pz > minZ && pz < maxZ) continue;
    let t0 = 0, t1 = 1;
    if (Math.abs(dx) < 1e-9) {
      if (px < minX || px > maxX) continue;
    } else {
      let a = (minX - px) / dx, b = (maxX - px) / dx;
      if (a > b) [a, b] = [b, a];
      t0 = Math.max(t0, a); t1 = Math.min(t1, b);
      if (t0 > t1) continue;
    }
    if (Math.abs(dz) < 1e-9) {
      if (pz < minZ || pz > maxZ) continue;
    } else {
      let a = (minZ - pz) / dz, b = (maxZ - pz) / dz;
      if (a > b) [a, b] = [b, a];
      t0 = Math.max(t0, a); t1 = Math.min(t1, b);
      if (t0 > t1) continue;
    }
    if (t0 < best) best = t0;
  }
  return best;
}

export function Player({ avatar, onStand, seatIndex = 0 }: { avatar: 'man' | 'woman'; onStand: () => void; seatIndex?: number }) {
  const rt = useRuntime();
  const runtime = rt.player;
  const look = useMemo(() => seatLook(avatar, seatIndex), [avatar, seatIndex]);
  const { camera, gl } = useThree();
  const group = useRef<THREE.Group>(null);
  const control = useMemo(() => makeControl(), []);
  const keys = useRef({ f: false, b: false, l: false, r: false, run: false, rotL: false, rotR: false });
  const standRef = useRef(onStand);
  standRef.current = onStand;
  const cam = useRef({
    dist: RIG.distance, want: RIG.distance, effDist: RIG.distance,
    pivot: new THREE.Vector3(runtime.pos.x, RIG.pivotHeight, runtime.pos.z),
    lastDrag: -10, t: 0, idle: 0, init: false, wasSeated: false,
  });

  // keyboard
  useEffect(() => {
    const map = (e: KeyboardEvent): keyof typeof keys.current | null => {
      switch (e.code) {
        case 'KeyW': case 'ArrowUp': return 'f';
        case 'KeyS': case 'ArrowDown': return 'b';
        case 'KeyA': return 'l';
        case 'KeyD': return 'r';
        case 'ArrowLeft': return 'rotL';
        case 'ArrowRight': return 'rotR';
        case 'ShiftLeft': case 'ShiftRight': return 'run';
        default: return null;
      }
    };
    const down = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
      const k = map(e);
      if (!k) return;
      keys.current[k] = true;
      if (k !== 'run') e.preventDefault();
    };
    const up = (e: KeyboardEvent) => {
      const k = map(e);
      if (k) keys.current[k] = false;
    };
    const blur = () => {
      const k = keys.current;
      k.f = k.b = k.l = k.r = k.run = k.rotL = k.rotR = false;
    };
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    window.addEventListener('blur', blur);
    return () => {
      window.removeEventListener('keydown', down);
      window.removeEventListener('keyup', up);
      window.removeEventListener('blur', blur);
    };
  }, []);

  // drag-to-look (mouse or touch on the canvas), wheel / pinch zoom
  useEffect(() => {
    const el = gl.domElement;
    const s = cam.current;
    const pointers = new Map<number, { x: number; y: number }>();
    let pinch = 0;
    const onDown = (e: PointerEvent) => {
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      runtime.dragPx = 0;
      if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        pinch = Math.hypot(a.x - b.x, a.y - b.y);
      }
    };
    const onMove = (e: PointerEvent) => {
      const p = pointers.get(e.pointerId);
      if (!p) return;
      const dx = e.clientX - p.x, dy = e.clientY - p.y;
      p.x = e.clientX; p.y = e.clientY;
      runtime.dragPx += Math.abs(dx) + Math.abs(dy);
      if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        if (pinch > 0) s.want = THREE.MathUtils.clamp(s.want - (d - pinch) * 0.01, RIG.minDistance, RIG.maxDistance);
        pinch = d;
        return;
      }
      if (!runtime.inputEnabled && !runtime.seated) return;
      runtime.camYaw -= dx * 0.006;
      runtime.camPitch = THREE.MathUtils.clamp(runtime.camPitch + dy * 0.004, -0.3, 1.05);
      s.lastDrag = s.t;
    };
    const onUp = (e: PointerEvent) => { pointers.delete(e.pointerId); pinch = 0; };
    const onWheel = (e: WheelEvent) => {
      s.want = THREE.MathUtils.clamp(s.want + Math.sign(e.deltaY) * 0.4, RIG.minDistance, RIG.maxDistance);
    };
    const noMenu = (e: Event) => e.preventDefault();
    el.style.touchAction = 'none';
    el.addEventListener('pointerdown', onDown);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
    el.addEventListener('wheel', onWheel, { passive: true });
    el.addEventListener('contextmenu', noMenu);
    return () => {
      el.removeEventListener('pointerdown', onDown);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
      el.removeEventListener('wheel', onWheel);
      el.removeEventListener('contextmenu', noMenu);
    };
  }, [gl, runtime]);

  const tmp = useMemo(() => ({ look: new THREE.Vector3(), cam: new THREE.Vector3(), follow: new THREE.Vector3(), lookAt: new THREE.Vector3() }), []);

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05);
    const s = cam.current;
    s.t += dt;
    const k = keys.current;
    const enabled = runtime.inputEnabled && !runtime.scripted;

    if (enabled && (k.rotL || k.rotR)) {
      runtime.camYaw += (k.rotL ? 1 : -1) * dt * 2.2;
      s.lastDrag = s.t;
    }

    // input → camera-relative direction
    const fwdX = -Math.sin(runtime.camYaw), fwdZ = -Math.cos(runtime.camYaw);
    const rightX = Math.cos(runtime.camYaw), rightZ = -Math.sin(runtime.camYaw);
    let ix = 0, iz = 0;
    if (enabled) {
      if (k.f) { ix += fwdX; iz += fwdZ; }
      if (k.b) { ix -= fwdX; iz -= fwdZ; }
      if (k.r) { ix += rightX; iz += rightZ; }
      if (k.l) { ix -= rightX; iz -= rightZ; }
      const j = runtime.joy;
      if (j.x * j.x + j.y * j.y > 0.02) {
        ix += fwdX * j.y + rightX * j.x;
        iz += fwdZ * j.y + rightZ * j.x;
      }
    }
    const hasInput = ix * ix + iz * iz > 1e-4;
    runtime.moved = hasInput;

    if (hasInput && runtime.seated) {
      runtime.seated = false;
      runtime.seat = null;
      standRef.current();
    }

    if (!runtime.scripted) {
      let targetSpeed = 0;
      if (hasInput) {
        const len = Math.hypot(ix, iz);
        const mag = Math.min(1, len);
        ix /= len; iz /= len;
        const joyRun = Math.hypot(runtime.joy.x, runtime.joy.y) > 0.92;
        targetSpeed = (k.run || joyRun ? RUN : WALK) * (k.f || k.b || k.l || k.r ? 1 : Math.max(0.35, mag));
        runtime.yaw += wrapAngle(Math.atan2(ix, iz) - runtime.yaw) * Math.min(1, dt * 10);
        s.idle = 0;
      } else s.idle += dt;
      runtime.speed += (targetSpeed - runtime.speed) * Math.min(1, dt * (targetSpeed > runtime.speed ? 6 : 9));
      if (runtime.speed < 0.02) runtime.speed = 0;

      if (!runtime.seated && runtime.speed > 0) {
        const mx = (hasInput ? ix : Math.sin(runtime.yaw)) * runtime.speed * dt;
        const mz = (hasInput ? iz : Math.cos(runtime.yaw)) * runtime.speed * dt;
        const nx = runtime.pos.x + mx;
        if (!blocked(nx, runtime.pos.z, rt.colliders)) runtime.pos.x = nx;
        const nz = runtime.pos.z + mz;
        if (!blocked(runtime.pos.x, nz, rt.colliders)) runtime.pos.z = nz;
      }
      const seat = runtime.seat;
      if (seat && runtime.seated) {
        runtime.pos.x += (seat.x - runtime.pos.x) * Math.min(1, dt * 8);
        runtime.pos.z += (seat.z - runtime.pos.z) * Math.min(1, dt * 8);
        runtime.yaw += wrapAngle(seat.yaw - runtime.yaw) * Math.min(1, dt * 6);
      }
      if (hasInput && k.f && !k.b && s.t - s.lastDrag > 1.2) {
        runtime.camYaw += wrapAngle(runtime.yaw + Math.PI - runtime.camYaw) * Math.min(1, dt * 1.1);
      }
    } else {
      // cinematic follow: swing in behind the walker
      runtime.camYaw += wrapAngle(runtime.yaw + Math.PI - runtime.camYaw) * Math.min(1, dt * 2.2);
      runtime.camPitch += (0.28 - runtime.camPitch) * Math.min(1, dt * 2);
    }

    // when the avatar sits down, swing the camera behind the seat
    if (runtime.seated && !s.wasSeated && runtime.seat) {
      runtime.camYaw = runtime.seat.yaw + Math.PI;
      runtime.camPitch = 0.26;
      s.want = 2.3;
    }
    s.wasSeated = runtime.seated;

    const g = group.current;
    if (g) {
      g.position.set(runtime.pos.x, 0, runtime.pos.z);
      g.rotation.y = runtime.yaw;
    }
    control.action = runtime.seated ? 'sit' : runtime.speed > 3.2 ? 'run' : runtime.speed > 0.15 ? 'walk' : 'idle';
    control.speed = runtime.speed;
    control.seatHeight = runtime.seat?.height;

    // camera
    s.dist += (s.want - s.dist) * Math.min(1, dt * 8);
    const pivotH = runtime.seated ? RIG.seatedPivot : RIG.pivotHeight;
    const shoulderX = Math.cos(runtime.camYaw) * RIG.shoulder;
    const shoulderZ = -Math.sin(runtime.camYaw) * RIG.shoulder;
    const pivotTarget = tmp.look.set(runtime.pos.x + shoulderX, pivotH, runtime.pos.z + shoulderZ);
    if (!s.init) s.pivot.copy(pivotTarget);
    if (s.pivot.distanceToSquared(pivotTarget) > 25) s.pivot.copy(pivotTarget); // teleports
    s.pivot.lerp(pivotTarget, Math.min(1, dt * 12));
    const cp = Math.cos(runtime.camPitch), sp = Math.sin(runtime.camPitch);
    const ox = Math.sin(runtime.camYaw) * cp, oz = Math.cos(runtime.camYaw) * cp;
    const wantX = s.pivot.x + ox * s.dist, wantZ = s.pivot.z + oz * s.dist;
    const camY = Math.min(rt.ceiling - 0.15, s.pivot.y + sp * s.dist);
    const hit = segmentHit(s.pivot.x, s.pivot.z, wantX, wantZ, camY, 0.22, rt.colliders);
    const target = Math.max(0.35, s.dist * hit - 0.05);
    s.effDist = target < s.effDist ? target : s.effDist + (target - s.effDist) * Math.min(1, dt * 4);
    if (!s.init) { s.effDist = target; s.init = true; }
    const ed = s.effDist;
    tmp.follow.set(s.pivot.x + ox * ed, Math.max(0.3, Math.min(rt.ceiling - 0.15, s.pivot.y + sp * ed)), s.pivot.z + oz * ed);

    // screen mode blend (camera dolly until the screen fills the view)
    rt.screenBlend += (rt.screenTarget - rt.screenBlend) * Math.min(1, dt * 2.4);
    if (Math.abs(rt.screenBlend - rt.screenTarget) < 0.002) rt.screenBlend = rt.screenTarget;
    const b = rt.screenBlend;
    if (b > 0.001) {
      const e = b * b * (3 - 2 * b);
      tmp.cam.copy(tmp.follow).lerp(rt.screenCam.pos, e);
      tmp.lookAt.copy(s.pivot).lerp(rt.screenCam.look, e);
      camera.position.copy(tmp.cam);
      camera.lookAt(tmp.lookAt);
    } else {
      camera.position.copy(tmp.follow);
      camera.lookAt(s.pivot);
    }
    if (g) g.visible = ed > 0.55 && b < 0.6;
  });

  return (
    <group ref={group} position={[runtime.pos.x, 0, runtime.pos.z]} rotation={[0, runtime.yaw, 0]}>
      <HumanCharacter look={look} control={control} />
    </group>
  );
}
