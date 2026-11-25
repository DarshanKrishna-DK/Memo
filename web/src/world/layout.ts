// Museum layout, in metres. One floor is drawn at a time at y = 0; the lift indicator,
// directory and floor plaques carry the "building grows upward" idea (level = year index).
//
//            x = -8                         x = +8
//   z = 12   ┌──────── entrance glass ────────┐
//            │ QR                      Attic  │   LOBBY (level 0 only)
//            │ desk+robot             Directory│   upper floors: a small landing (x ±6, z 0..5)
//   z = 0    └──────┐ corridor ┌─[lift]───────┘
//                   │ Jan  Feb │   12 doors, Jan..Dec, alternating left / right
//                   │ ...  ... │   a month room opens behind its door (one at a time)
//   z = -24         └──────────┘

export const CORR_HALF_W = 2.1;
export const CORR_CEIL = 3.2;
export const DOOR_SPACING = 3.6;
export const FIRST_DOOR_Z = -3.2;
export const END_Z = FIRST_DOOR_Z - 5 * DOOR_SPACING - 2.8; // -24
export const DOOR_W = 1.2;
export const WALL_T = 0.3;

export const LOBBY = { halfW: 8, frontZ: 12, ceil: 4.6 };
export const LANDING = { halfW: 6, frontZ: 5, ceil: 3.4 };

/** Lift cabin (behind the back wall, right of the corridor mouth). Doors face +z at z = 0. */
export const LIFT = { x: 4.6, z: -1.05, w: 2.0, d: 2.0, doorW: 1.2, h: 2.6 };
export const LIFT_IN = { x: LIFT.x, z: -1.0 };
export const LIFT_OUT = { x: LIFT.x, z: 1.1 };

export const SPAWN = { x: -3.2, z: 5.2, yaw: -Math.PI / 2 };

export const DESK = { x: -5.2, z: 5, len: 3.2, depth: 0.9 };
export const RECEPTIONIST = { x: -6.35, z: 5, yaw: Math.PI / 2 };
export const GUIDE_HOME = { x: -3.9, z: 2.9, yaw: Math.PI / 2 };
export const DIRECTORY = { x: LOBBY.halfW, z: 3.6 };
export const ATTIC = { x: LOBBY.halfW, z: 9.0 };
export const LATEST_PLAQUE = { x: -4.4, z: 0 };
export const QR_BOARD = { x: -LOBBY.halfW, z: 9.0 };

export type Side = 'L' | 'R';

export interface DoorSpec {
  month: number; // 1..12
  side: Side;
  x: number;
  z: number;
  /** Door local +z points into the corridor. Also the month room's rotation. */
  rotY: number;
  standX: number;
  standZ: number;
}

export const DOORS: DoorSpec[] = Array.from({ length: 12 }, (_, i) => {
  const pair = Math.floor(i / 2);
  const side: Side = i % 2 === 0 ? 'L' : 'R';
  const x = side === 'L' ? -CORR_HALF_W : CORR_HALF_W;
  const z = FIRST_DOOR_Z - pair * DOOR_SPACING;
  return {
    month: i + 1,
    side,
    x,
    z,
    rotY: side === 'L' ? Math.PI / 2 : -Math.PI / 2,
    standX: side === 'L' ? x + 0.95 : x - 0.95,
    standZ: z,
  };
});

// ───────── month room (theater) in local space ─────────
// Back wall (with the door) at z = 0, screen on the front wall at z = -ROOM.d.
export const ROOM = { halfW: 3.5, d: 8.5, h: 3.4 };
export const SCREEN = { w: 4.8, h: 2.7, y: 1.95 };
/** Seat x positions in seat-index order (seat 0 = the player's). Seats face the screen. */
export const SEAT_X = [-0.55, 0.55, -1.65, 1.65];
export const SEAT_Z = -4.6;
export const SEAT_H = 0.46;

export interface RoomFrame {
  /** Local x of the door in the back wall: -2.4 for left-side rooms, +2.4 for right. */
  doorLX: number;
  s: 1 | -1;
  ox: number;
  oz: number;
  rotY: number;
}

export function roomFrame(door: DoorSpec): RoomFrame {
  const s: 1 | -1 = door.side === 'L' ? -1 : 1;
  const doorLX = 2.4 * s;
  const c = Math.cos(door.rotY), sn = Math.sin(door.rotY);
  // world = R * local + o, with local door point (doorLX, 0) landing on the door.
  const ox = door.x - (doorLX * c);
  const oz = door.z - (-doorLX * sn);
  return { doorLX, s, ox, oz, rotY: door.rotY };
}

export function toWorld(f: RoomFrame, lx: number, lz: number): { x: number; z: number } {
  const c = Math.cos(f.rotY), s = Math.sin(f.rotY);
  return { x: f.ox + lx * c + lz * s, z: f.oz - lx * s + lz * c };
}

export function toLocal(f: RoomFrame, x: number, z: number): { x: number; z: number } {
  const dx = x - f.ox, dz = z - f.oz;
  const c = Math.cos(f.rotY), s = Math.sin(f.rotY);
  return { x: dx * c - dz * s, z: dx * s + dz * c };
}

/** Local-space room places (sign `s` mirrors the room so the door sits near a back corner). */
export function roomPlaces(f: RoomFrame) {
  const s = f.s;
  return {
    seats: SEAT_X.map((x) => ({ x, z: SEAT_Z, yaw: Math.PI })),
    grandma: { x: -s * 2.55, z: -6.85, yaw: s * 0.55 + 0 },
    guideWait: { x: f.doorLX - s * 1.05, z: -0.85, yaw: Math.PI + s * 0.5 },
    inside: { x: f.doorLX, z: -0.9 },
    jukebox: { x: -s * 3.05, z: -1.35, yaw: s * Math.PI / 2 },
    plaques: [0, 1, 2, 3].map((i) => ({ x: -s * (0.35 + i * 0.62), z: -WALL_T })),
    frames: [
      { x: -3.5, z: -2.4, yaw: Math.PI / 2 }, { x: -3.5, z: -4.6, yaw: Math.PI / 2 }, { x: -3.5, z: -6.6, yaw: Math.PI / 2 },
      { x: 3.5, z: -2.4, yaw: -Math.PI / 2 }, { x: 3.5, z: -4.6, yaw: -Math.PI / 2 }, { x: 3.5, z: -6.6, yaw: -Math.PI / 2 },
    ].filter((p) => !(Math.sign(p.x) === s && p.z > -1.5)),
  };
}

// ───────── colliders (axis-aligned boxes in world XZ) ─────────
export interface Collider { x: number; z: number; w: number; d: number; h?: number }

const box = (x0: number, x1: number, z0: number, z1: number, h?: number): Collider => ({
  x: (x0 + x1) / 2, z: (z0 + z1) / 2, w: Math.abs(x1 - x0), d: Math.abs(z1 - z0), h,
});

/** Walls of the corridor; `openMonth` leaves that month's doorway passable. */
export function corridorColliders(openMonth: number | null): Collider[] {
  const out: Collider[] = [];
  const farZ = END_Z - 8; // walls run on past the end so month rooms behind them stay closed in
  for (const side of ['L', 'R'] as Side[]) {
    const sx = side === 'L' ? -1 : 1;
    const x0 = sx * CORR_HALF_W, x1 = sx * (CORR_HALF_W + WALL_T);
    const doors = DOORS.filter((d) => d.side === side).sort((a, b) => b.z - a.z);
    let z = 0;
    for (const d of doors) {
      out.push(box(x0, x1, z, d.z + DOOR_W / 2));
      if (d.month !== openMonth) out.push(box(x0, x1, d.z + DOOR_W / 2, d.z - DOOR_W / 2));
      z = d.z - DOOR_W / 2;
    }
    out.push(box(x0, x1, z, farZ));
  }
  out.push(box(-CORR_HALF_W, CORR_HALF_W, END_Z, END_Z - WALL_T));
  return out;
}

function backWall(halfW: number, liftOpen: boolean): Collider[] {
  const out = [
    box(-halfW, -CORR_HALF_W, 0, -WALL_T),
    box(CORR_HALF_W, LIFT.x - LIFT.doorW / 2, 0, -WALL_T),
    box(LIFT.x + LIFT.doorW / 2, halfW, 0, -WALL_T),
    // cabin shell
    box(LIFT.x - LIFT.w / 2 - 0.1, LIFT.x - LIFT.w / 2, 0, -LIFT.d - 0.1),
    box(LIFT.x + LIFT.w / 2, LIFT.x + LIFT.w / 2 + 0.1, 0, -LIFT.d - 0.1),
    box(LIFT.x - LIFT.w / 2, LIFT.x + LIFT.w / 2, -LIFT.d, -LIFT.d - 0.1),
  ];
  if (!liftOpen) out.push(box(LIFT.x - LIFT.doorW / 2, LIFT.x + LIFT.doorW / 2, 0.05, -0.1));
  return out;
}

export function lobbyColliders(liftOpen: boolean): Collider[] {
  const W = LOBBY.halfW;
  return [
    ...backWall(W, liftOpen),
    box(-W - WALL_T, -W, 0, LOBBY.frontZ),
    box(W, W + WALL_T, 0, LOBBY.frontZ),
    box(-W, W, LOBBY.frontZ, LOBBY.frontZ + WALL_T),
    // reception desk + robot space behind it
    box(DESK.x - DESK.depth / 2, DESK.x + DESK.depth / 2, DESK.z - DESK.len / 2 - 0.05, DESK.z + DESK.len / 2 + 0.05, 1.1),
    box(-W, DESK.x - DESK.depth / 2, DESK.z - DESK.len / 2 - 0.05, DESK.z - DESK.len / 2 + 0.05, 1.1),
    box(-W, DESK.x - DESK.depth / 2, DESK.z + DESK.len / 2 - 0.05, DESK.z + DESK.len / 2 + 0.05, 1.1),
    // benches + planters
    box(1.6, 3.4, 7.7, 8.3, 0.5),
    box(-1.0 - 0.3, -1.0 + 0.3, 10.9, 11.5, 1.2),
    box(6.9, 7.5, 0.4, 1.0, 1.2),
    box(-7.6, -7.0, 0.4, 1.0, 1.2),
  ];
}

export function landingColliders(liftOpen: boolean): Collider[] {
  const W = LANDING.halfW;
  return [
    ...backWall(W, liftOpen),
    box(-W - WALL_T, -W, 0, LANDING.frontZ),
    box(W, W + WALL_T, 0, LANDING.frontZ),
    box(-W, W, LANDING.frontZ, LANDING.frontZ + WALL_T),
    box(-4.6, -2.8, 3.9, 4.5, 0.5),
  ];
}

export function roomColliders(f: RoomFrame): Collider[] {
  const P = roomPlaces(f);
  const local: Collider[] = [
    box(-ROOM.halfW - WALL_T, -ROOM.halfW, 0, -ROOM.d), // side walls
    box(ROOM.halfW, ROOM.halfW + WALL_T, 0, -ROOM.d),
    box(-ROOM.halfW, ROOM.halfW, -ROOM.d, -ROOM.d - WALL_T), // front (screen) wall
    // back wall either side of the door (same plane as the corridor wall, 0.3 m thick)
    box(-ROOM.halfW - WALL_T, f.doorLX - DOOR_W / 2, 0, -WALL_T),
    box(f.doorLX + DOOR_W / 2, ROOM.halfW + WALL_T, 0, -WALL_T),
    box(-2.3, 2.3, SEAT_Z - 0.3, SEAT_Z + 0.35, 0.9), // the seat row
    box(-SCREEN.w / 2 - 0.2, SCREEN.w / 2 + 0.2, -ROOM.d, -ROOM.d + 0.7, 0.5), // stage under the screen
    box(P.grandma.x - 0.4, P.grandma.x + 0.4, P.grandma.z - 0.4, P.grandma.z + 0.4, 1.2),
    box(P.jukebox.x - 0.3, P.jukebox.x + 0.3, P.jukebox.z - 0.45, P.jukebox.z + 0.45, 1.4),
  ];
  return local.filter((c) => c.w > 0.01).map((c) => {
    const p = toWorld(f, c.x, c.z);
    const swap = Math.abs(Math.sin(f.rotY)) > 0.5;
    return { x: p.x, z: p.z, w: swap ? c.d : c.w, d: swap ? c.w : c.d, h: c.h };
  });
}

export function doorForMonth(month: number): DoorSpec {
  return DOORS[Math.max(0, Math.min(11, month - 1))];
}

/** Where the player is, coarsely (used by the guided walk planner). */
export type Region = 'lobby' | 'landing' | 'corridor' | 'cabin' | 'room';

export function regionOf(x: number, z: number, level: number, room: RoomFrame | null): Region {
  if (room) {
    const l = toLocal(room, x, z);
    if (l.z < -0.05 && Math.abs(l.x) < ROOM.halfW + 0.1 && l.z > -ROOM.d - 0.1) return 'room';
  }
  if (Math.abs(x - LIFT.x) < LIFT.w / 2 && z < 0 && z > -LIFT.d) return 'cabin';
  if (z < 0) return 'corridor';
  return level === 0 ? 'lobby' : 'landing';
}
