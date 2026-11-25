import type { ReactNode } from 'react';

/* Pixel art for the public landing page: cast portraits and small feature glyphs.
 * Char-maps drawn as crisp SVG rects, the same way as ../Pixels.tsx. */

function Map({ map, pal, px, label, className }: { map: readonly string[]; pal: Record<string, string>; px: number; label?: string; className?: string }) {
  const w = Math.max(...map.map((r) => r.length));
  const rects: ReactNode[] = [];
  map.forEach((row, y) => [...row].forEach((c, x) => { if (pal[c]) rects.push(<rect key={x + ',' + y} x={x} y={y} width={1} height={1} fill={pal[c]} />); }));
  return (
    <svg className={className} width={w * px} height={map.length * px} viewBox={`0 0 ${w} ${map.length}`} shapeRendering="crispEdges"
      role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      {rects}
    </svg>
  );
}

const RECEPTIONIST = [
  '.......gg.......',
  '.......oo.......',
  '...oooooooooo...',
  '..owwwwwwwwwwo..',
  '.hhwffffffffwhh.',
  '.hhwfeeffeefwhh.',
  '.hhwfeeffeefwhh.',
  '.hhwffffffffwhh.',
  '..hwffeeeeffwo..',
  '..hwffffffffwo..',
  '..hmwwwwwwwwwo..',
  '...mooooooooo...',
  '.....obbbbo.....',
  '...oowwwwwwoo...',
  '..owwwbwwbwwwo..',
  '.owwwwbggbwwwwo.',
  '.owwwwwbbwwwwwo.',
  'GGGGGGGGGGGGGGGG',
  'DsssssssssssssDs',
  'DsssLLssssssssDs',
];
const RECEPTIONIST_PAL = { o: '#061431', w: '#f3f1e2', f: '#0e2457', e: '#6ad5e7', h: '#2481aa', m: '#a8e27c', b: '#2b4c8a', g: '#d9a520', G: '#f0c24a', s: '#d6cfb4', D: '#a89a74', L: '#a8e27c' };

const GUIDE = [
  '.......l........',
  '.......o........',
  '....oooooooo....',
  '...owwwwwwwwo...',
  '..owwwwwwwwwwo..',
  '..offffffffffo..',
  '..offeefffeefo.w',
  '..offffffffffo.w',
  '...owwwwwwwwo..w',
  '....oooooooo..ww',
  '...owwwwwwwwoww.',
  '..owwwbbbbwwww..',
  '..owwwbllbwwo...',
  '..owwwbbbbwwo...',
  '..owwwwwwwwwo...',
  '...oooooooooo...',
  '..okkkkkkkkkko..',
  '..okokokokokko..',
  '...oooooooooo...',
];
const GUIDE_PAL = { o: '#061431', w: '#f3f1e2', f: '#0e2457', e: '#a8e27c', b: '#2b4c8a', l: '#a8e27c', k: '#3d63a8' };

const GRANDMA = [
  '......HHHH......',
  '.....HHhHHH.....',
  '....HHHHHHHH....',
  '...HHffbbffHH...',
  '...HfeeffeefH...',
  '...HfeeffeefH...',
  '...Hffffffffh...',
  '....ffddddff....',
  '.....ffffff.....',
  '...rrgcccccc....',
  '..rrrgccccccrr..',
  '..rrrrgccccrrr..',
  '.frrrrrgrrrrrrf.',
  '.frrrrrrgrrrrrf.',
  '..rrrrrrrgrrrr..',
  '..rrrrrrrrgrrr..',
  '..RRRRRRRRRgRR..',
  '..gggggggggggg..',
  '...ff......ff...',
];
const GRANDMA_PAL = { H: '#d8d4c8', h: '#a19c8f', f: '#b77a4e', d: '#7a4426', e: '#061431', b: '#d6455d', r: '#d6455d', R: '#a8324a', g: '#f0b13a', c: '#2481aa' };

export type CastId = 'receptionist' | 'guide' | 'grandma';
export function CastPortrait({ who, px = 6 }: { who: CastId; px?: number }) {
  if (who === 'receptionist') return <Map map={RECEPTIONIST} pal={RECEPTIONIST_PAL} px={px} className="px-portrait-svg" />;
  if (who === 'guide') return <Map map={GUIDE} pal={GUIDE_PAL} px={px} className="px-portrait-svg" />;
  return <Map map={GRANDMA} pal={GRANDMA_PAL} px={px} className="px-portrait-svg" />;
}

const GLYPHS = {
  bell: ['....aa....', '...abba...', '..abaaaa..', '..abaaaa..', '.abaaaaaa.', '.aaaaaaaa.', 'aaaaaaaaaa', '....bb....'],
  flag: ['.a........', '.abbbbb...', '.abbbbbbb.', '.abbbbbb..', '.abbbbbbb.', '.a........', '.a........', 'aaa.......'],
  screen: ['aaaaaaaaaa', 'abbbbbbbba', 'abbbbbbbba', 'abbbbbbbba', 'aaaaaaaaaa', '..........', 'aa.aa.aa.a', 'aa.aa.aa.a'],
  phone: ['aa......b.', 'aaa...b..b', '.aa....b.b', '.aaa..b..b', '..aaa.....', '...aaa.aa.', '....aaaaaa', '......aaa.'],
  film: ['aaaaaaaaaa', 'a.a.a.a.aa', 'aaaaaaaaaa', 'abbbaabbba', 'abbbaabbba', 'aaaaaaaaaa', 'a.a.a.a.aa', 'aaaaaaaaaa'],
  sparkle: ['....a.....', '....a.....', '..abbba...', 'aabbbbbaa.', '..abbba...', '....a...b.', '....a..bbb', '........b.'],
  speech: ['.aaaaaaaa.', 'aaaaaaaaaa', 'aabbaabbaa', 'aaaaaaaaaa', '.aaaaaaaa.', '..aa......', '.aa.......', 'a.........'],
  grid: ['aaaa.aaaa.', 'abba.abba.', 'aaaa.aaaa.', '..........', 'aaaa.aaaa.', 'abba.abba.', 'aaaa.aaaa.', '..........'],
  plane: ['........aa', '......aaaa', '....aaabaa', '..aaabbaa.', 'aaaabbaaa.', '...abaaa..', '...aa.aa..', '...a...a..'],
  lock: ['..aaaaa...', '.a.....a..', '.a.....a..', 'aaaaaaaaa.', 'abbbbbbba.', 'abbbaabba.', 'abbbaabba.', 'aaaaaaaaa.'],
  door: ['.aaaaaaa..', '.abbbbba..', '.abbbbba..', '.abbbbba..', '.abbbbaa..', '.abbbbba..', '.abbbbba..', 'aaaaaaaaa.'],
} as const;
export type GlyphName = keyof typeof GLYPHS;

export function PixelGlyph({ name, size = 40, main = 'currentColor', hi = '#f3f1e2' }: { name: GlyphName; size?: number; main?: string; hi?: string }) {
  return <Map map={GLYPHS[name]} pal={{ a: main, b: hi }} px={size / 10} className="px-glyph" />;
}
