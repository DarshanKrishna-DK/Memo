import { useRef } from 'react';
import type { WorldRuntime } from './runtime';

/** Touch joystick (bottom-left). Writes rt.player.joy; dragging elsewhere on the canvas turns
 *  the camera, and tapping an object interacts with it. */
export function Joystick({ rt }: { rt: WorldRuntime }) {
  const base = useRef<HTMLDivElement>(null);
  const knob = useRef<HTMLDivElement>(null);
  const id = useRef<number | null>(null);
  const R = 52;

  const update = (cx: number, cy: number) => {
    const b = base.current!.getBoundingClientRect();
    let dx = cx - (b.left + b.width / 2);
    let dy = cy - (b.top + b.height / 2);
    const l = Math.hypot(dx, dy);
    if (l > R) { dx = (dx / l) * R; dy = (dy / l) * R; }
    rt.player.joy.x = dx / R;
    rt.player.joy.y = -dy / R;
    if (knob.current) knob.current.style.transform = `translate(${dx}px, ${dy}px)`;
  };
  const end = () => {
    id.current = null;
    rt.player.joy.x = 0;
    rt.player.joy.y = 0;
    if (knob.current) knob.current.style.transform = 'translate(0px, 0px)';
  };

  return (
    <div
      ref={base}
      aria-label="Move"
      role="application"
      onPointerDown={(e) => {
        id.current = e.pointerId;
        e.currentTarget.setPointerCapture(e.pointerId);
        update(e.clientX, e.clientY);
      }}
      onPointerMove={(e) => { if (id.current === e.pointerId) update(e.clientX, e.clientY); }}
      onPointerUp={end}
      onPointerCancel={end}
      style={{
        position: 'absolute', left: 24, bottom: 'calc(24px + env(safe-area-inset-bottom, 0px))', width: R * 2 + 28, height: R * 2 + 28,
        borderRadius: '50%', background: 'rgba(6,20,49,0.45)', boxShadow: '0 0 0 2px #2b4c8a', touchAction: 'none',
        display: 'grid', placeItems: 'center', zIndex: 1,
      }}
    >
      <div
        ref={knob}
        style={{ width: 52, height: 52, borderRadius: '50%', background: '#a8e27c', boxShadow: '3px 3px 0 0 #061431', pointerEvents: 'none' }}
      />
    </div>
  );
}
