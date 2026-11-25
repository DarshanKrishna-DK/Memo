import { useEffect, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import type { Interactable } from '../contract';
import { isTypingTarget, useRuntime } from './runtime';

export interface Spot {
  i: Interactable;
  x: number;
  z: number;
  /** Reach in metres. */
  r: number;
  /** World point the visitor should roughly face (optional). */
  fx?: number;
  fz?: number;
}

export function keyOf(i: Interactable | null): string {
  return i ? JSON.stringify(i) : '';
}

/** Finds the interactable the visitor stands at (and roughly faces), reports it with
 *  setNearby(), and performs it on E. Taps on objects call interact() directly. */
export function Interactions({
  spots, enabled, setNearby, interact,
}: {
  spots: Spot[]; enabled: boolean; setNearby: (i: Interactable | null) => void; interact: (i: Interactable) => void;
}) {
  const rt = useRuntime();
  const current = useRef<Interactable | null>(null);
  const spotsRef = useRef(spots);
  spotsRef.current = spots;
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  useFrame(() => {
    let best: Spot | null = null;
    let bestD = Infinity;
    if (enabled && !rt.walkActive) {
      const p = rt.player.pos;
      const fx = Math.sin(rt.player.yaw), fz = Math.cos(rt.player.yaw);
      for (const s of spotsRef.current) {
        const d = Math.hypot(s.x - p.x, s.z - p.z);
        if (d > s.r || d >= bestD) continue;
        if (rt.player.seated && s.i.kind === 'seat') continue;
        if (s.fx !== undefined && s.fz !== undefined && d > 0.6) {
          const tx = s.fx - p.x, tz = s.fz - p.z;
          const l = Math.hypot(tx, tz) || 1;
          if ((tx * fx + tz * fz) / l < -0.2) continue;
        }
        best = s;
        bestD = d;
      }
    }
    const next = best?.i ?? null;
    if (keyOf(next) !== keyOf(current.current)) {
      current.current = next;
      setNearby(next);
    }
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.repeat || isTypingTarget(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.code !== 'KeyE') return;
      const i = current.current;
      if (!i || !enabledRef.current) return;
      e.preventDefault();
      interact(i);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [interact]);

  // Clear the prompt when unmounting.
  useEffect(() => () => setNearby(null), [setNearby]);
  return null;
}
