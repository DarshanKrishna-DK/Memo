import { createContext, useContext } from 'react';
import * as THREE from 'three';
import type { Collider, RoomFrame } from './layout';
import { SPAWN } from './layout';

/** Mutable per-frame state shared by the world's components (no React re-render per frame). */
export interface PlayerRuntime {
  pos: THREE.Vector3;
  yaw: number;
  speed: number;
  seated: boolean;
  /** Seat to sit in / sitting in (world). */
  seat: { x: number; z: number; yaw: number; height: number } | null;
  /** False while a scene (walk, ride, screen mode) owns the avatar. */
  inputEnabled: boolean;
  /** A director moves the avatar (guided walk): no input integration, cinematic camera. */
  scripted: boolean;
  camYaw: number;
  camPitch: number;
  /** Pixels moved in the current / last pointer drag (tap filter). */
  dragPx: number;
  /** Touch joystick vector, x right, y forward, |v| <= 1. */
  joy: { x: number; y: number };
  /** True when any movement input happened this frame (stand-up trigger). */
  moved: boolean;
}

export interface WorldRuntime {
  player: PlayerRuntime;
  guide: { x: number; z: number; yaw: number; speed: number; say: string | null };
  lift: { doors: number; doorsTarget: number; indicator: number };
  doors: { open: number[]; target: number[]; shake: number[] };
  colliders: Collider[];
  room: RoomFrame | null;
  ceiling: number;
  /** 0 = follow camera, 1 = screen fills the view. */
  screenBlend: number;
  screenTarget: number;
  screenCam: { pos: THREE.Vector3; look: THREE.Vector3 };
  /** Black overlay 0..1 (reduced-motion walk, teleports). */
  fade: number;
  fadeTarget: number;
  walkActive: boolean;
  /** Light fixtures on display (world positions), keyed per Downlights instance. */
  fixtures: Map<symbol, THREE.Vector3[]>;
}

export function makeWorldRuntime(): WorldRuntime {
  return {
    player: {
      pos: new THREE.Vector3(SPAWN.x, 0, SPAWN.z),
      yaw: SPAWN.yaw,
      speed: 0,
      seated: false,
      seat: null,
      inputEnabled: true,
      scripted: false,
      camYaw: SPAWN.yaw + Math.PI,
      camPitch: 0.2,
      dragPx: 0,
      joy: { x: 0, y: 0 },
      moved: false,
    },
    guide: { x: 0, z: 0, yaw: 0, speed: 0, say: null },
    lift: { doors: 1, doorsTarget: 1, indicator: 0 },
    doors: { open: new Array(12).fill(0), target: new Array(12).fill(0), shake: new Array(12).fill(0) },
    colliders: [],
    room: null,
    ceiling: 4.6,
    screenBlend: 0,
    screenTarget: 0,
    screenCam: { pos: new THREE.Vector3(), look: new THREE.Vector3() },
    fade: 0,
    fadeTarget: 0,
    walkActive: false,
    fixtures: new Map(),
  };
}

export const RuntimeContext = createContext<WorldRuntime | null>(null);

export function useRuntime(): WorldRuntime {
  const rt = useContext(RuntimeContext);
  if (!rt) throw new Error('useRuntime outside <MuseumCanvas>');
  return rt;
}

export function wrapAngle(a: number) {
  return Math.atan2(Math.sin(a), Math.cos(a));
}

export function isTypingTarget(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable);
}

/** Pointer taps on 3D objects count only when the pointer did not drag the camera. */
export function isTap(rt: WorldRuntime) {
  return rt.player.dragPx <= 8;
}
