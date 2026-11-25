// Rigged low-poly humans for the museum, ported from MedSim (src/components/world/rigs.ts).
//
// Only three people exist in Memo's museum: the player (a man in shirt and trousers, or a
// woman in a saree) and Grandma (an elderly woman in a saree). The robots are procedural
// (see ../Robot.tsx). Animation clips come from Xbot.glb, retargeted per rig at load time
// (retarget.ts). Files live in public/assets/characters; sources and licences are in
// public/assets/CREDITS.md.

export type RigId = 'male' | 'saree';

export const RIG_URL: Record<RigId, string> = {
  // Blender-cleaned Ready Player Me male (MedSim build_male.py): fitted short haircut, cloth top
  // ("Kurta_Cloth") over trousers. Memo trims the top at the hip (Look.hem) so it reads as a shirt.
  male: '/assets/characters/male-kurta.glb',
  // Built in Blender (MedSim build_saree.py) on the same skeleton: a draped saree with front
  // pleats (Saree_Skirt), border, a pallu over the left shoulder (Saree_Pallu), short-sleeved
  // blouse, bindi and bangles.
  saree: '/assets/characters/female-saree.glb',
};

/** Source of the shared animation library. Xbot is never rendered. */
export const ANIM_URL = '/assets/characters/Xbot.glb';

export interface Garment {
  color: string;
  /** Keep the baked fabric texture (multiplied by `color`). */
  map: boolean;
  roughness?: number;
}

export interface Look {
  rig: RigId;
  /** Standing height in metres. */
  height: number;
  /** Multiply tint over the base skin texture. */
  skin: string;
  hair: string;
  hairGrey?: boolean;
  top: Garment;
  bottom: Garment;
  shoes?: string;
  beard?: 'hide' | 'keep';
  glasses?: boolean;
  /** Saree border / zari colour (saree rig). */
  border?: string;
  /** Blouse colour (saree rig). */
  blouse?: string;
  /** Cut the top garment at this height (fraction of standing height): turns the long kurta
   *  cloth into a hip-length shirt. */
  hem?: number;
  /** Dark collar / placket line drawn down the shirt front. */
  placket?: string;
}

export function lookKey(l: Look): string {
  return JSON.stringify(l);
}

/** The player, man: brick-red shirt (hip length) over charcoal trousers, clean-shaven. */
export const PLAYER_MAN: Look = {
  rig: 'male',
  height: 1.76,
  skin: '#c88f6c',
  hair: '#2a1f17',
  // Brick-red casual shirt: a light blue read as a white doctor's coat under the warm museum lights.
  top: { color: '#9a3b2c', map: false, roughness: 0.8 },
  bottom: { color: '#2f3440', map: false, roughness: 0.85 },
  shoes: '#3a2a20',
  beard: 'hide',
  hem: 0.5,
  placket: '#6e2a1f',
};

/** The player, woman: a deep teal silk saree with a gold zari border and a maroon blouse. */
export const PLAYER_WOMAN: Look = {
  rig: 'saree',
  height: 1.62,
  skin: '#b77b58',
  hair: '#3a2f2a',
  top: { color: '#0f6b5c', map: false, roughness: 0.6 },
  bottom: { color: '#0f6b5c', map: false, roughness: 0.7 },
  border: '#d9a520',
  blouse: '#7a1f2b',
  shoes: '#5a3a28',
};

/** Grandma: an elderly woman in a soft cream cotton saree with a maroon border, grey hair, glasses. */
export const GRANDMA_LOOK: Look = {
  rig: 'saree',
  height: 1.54,
  skin: '#a56a49',
  hair: '#c9c4bc',
  hairGrey: true,
  top: { color: '#efe4cc', map: false, roughness: 0.82 },
  bottom: { color: '#efe4cc', map: false, roughness: 0.85 },
  border: '#8a1f2e',
  blouse: '#8a1f2e',
  shoes: '#5a3a28',
  glasses: true,
};

export function playerLook(avatar: 'man' | 'woman'): Look {
  return avatar === 'man' ? PLAYER_MAN : PLAYER_WOMAN;
}

// Theater seats (guests section): everyone in the room keeps the same rig as their landing choice, but each seat
// has its own colours so four people are told apart at a glance. Seat 0 = the default player look.
const SEAT_SHIRTS: Array<[string, string]> = [
  ['#9a3b2c', '#6e2a1f'], // brick red
  ['#2c4f86', '#1c3358'], // navy blue
  ['#b8892a', '#7d5c19'], // mustard
  ['#3f6b3a', '#284526'], // forest green
];
const SEAT_SAREES: Array<{ cloth: string; border: string; blouse: string }> = [
  { cloth: '#0f6b5c', border: '#d9a520', blouse: '#7a1f2b' }, // teal, gold zari
  { cloth: '#a0285f', border: '#d9a520', blouse: '#2d3f7a' }, // magenta
  { cloth: '#d0661c', border: '#7a1f2b', blouse: '#7a1f2b' }, // saffron, maroon border
  { cloth: '#2d4aa0', border: '#d8dbe2', blouse: '#c8a235' }, // royal blue, silver border
];

/** The look for a person in theater seat `index` (0-3; anything else = the default look). */
export function seatLook(avatar: 'man' | 'woman', index: number | null | undefined): Look {
  const i = index != null && index >= 0 && index < 4 ? index : 0;
  if (avatar === 'man') {
    const [shirt, placket] = SEAT_SHIRTS[i];
    return i === 0 ? PLAYER_MAN : { ...PLAYER_MAN, top: { ...PLAYER_MAN.top, color: shirt }, placket };
  }
  const c = SEAT_SAREES[i];
  return i === 0 ? PLAYER_WOMAN : {
    ...PLAYER_WOMAN,
    top: { ...PLAYER_WOMAN.top, color: c.cloth },
    bottom: { ...PLAYER_WOMAN.bottom, color: c.cloth },
    border: c.border,
    blouse: c.blouse,
  };
}
