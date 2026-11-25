import type { ReactNode } from 'react';
import type { Avatar } from '../state/worldStore';

/** Draw a char-map as crisp SVG rects. */
function Sprite({ map, pal, px = 6, label }: { map: string[]; pal: Record<string, string>; px?: number; label?: string }) {
  const rects: ReactNode[] = [];
  map.forEach((row, y) => [...row].forEach((c, x) => { if (pal[c]) rects.push(<rect key={x + ',' + y} x={x} y={y} width={1} height={1} fill={pal[c]} />); }));
  return (
    <svg width={map[0].length * px} height={map.length * px} viewBox={`0 0 ${map[0].length} ${map.length}`} role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true} shapeRendering="crispEdges">
      {rects}
    </svg>
  );
}

/**
 * Memo mark: a museum whose columns form an "M" under a gold pediment, with a lime spark (a memory) in the
 * doorway. Same grid as web/public/brand/* (favicon, app icons, og image); keep them in sync.
 */
export const BRAND_GRID = [
  '................',
  '.......GG.......',
  '.....GGggGG.....',
  '...GGGggggGGG...',
  '.GGGGGGGGGGGGGG.',
  '.CCCCCCCCCCCCCC.',
  '................',
  '..CCC......CCC..',
  '..CCCC....CCCC..',
  '..CC.CC..CC.CC..',
  '..CC..CCCC..CC..',
  '..CC...LL...CC..',
  '..CC..LLLL..CC..',
  '..CC...LL...CC..',
  '.CCCCCCCCCCCCCC.',
  'GGGGGGGGGGGGGGGG',
];
export function BrandMark({ size = 28, label }: { size?: number; label?: string }) {
  return <Sprite map={BRAND_GRID} px={size / 16} label={label} pal={{ G: '#d9a520', g: '#f0c24a', C: '#f3f1e2', L: '#a8e27c' }} />;
}

const MAN = [
  '....hhhh....',
  '...hhhhhh...',
  '...ffffff...',
  '...ffeeff...',
  '....ffff....',
  '..tttttttt..',
  '.tttttttttt.',
  '.ftttttttttf'.slice(0, 12),
  '.fttttttttf.',
  '..tttttttt..',
  '..pppppppp..',
  '..pppppppp..',
  '..ppp..ppp..',
  '..ppp..ppp..',
  '..ppp..ppp..',
  '..kkk..kkk..',
];
const WOMAN = [
  '...hhhhhh...',
  '..hhhhhhhh..',
  '..hhffffhh..',
  '..hhfeefhh..',
  '..hh.ff.hh..',
  '..rrrrrrrr..',
  '.rrrgrrrrrr.',
  '.frrrgrrrrf.',
  '.frrrrgrrrf.',
  '..rrrrrrrr..',
  '..rrgrrrrr..',
  '..rrrrgrrr..',
  '..rrrrrrrr..',
  '..rrrrrrrr..',
  '..rrrrrrrr..',
  '..ff....ff..',
];
export function AvatarSprite({ kind, px = 7 }: { kind: Avatar; px?: number }) {
  return kind === 'man'
    ? <Sprite map={MAN} px={px} pal={{ h: '#2b1a12', f: '#d9a171', e: '#061431', t: '#6ad5e7', p: '#173571', k: '#061431' }} label="Man in shirt and trousers" />
    : <Sprite map={WOMAN} px={px} pal={{ h: '#1a1010', f: '#c98d5e', e: '#061431', r: '#d6455d', g: '#f0b13a' }} label="Woman in a saree" />;
}

/** Landing hero: the museum at night, one door lit. */
export function Facade() {
  const stars: ReactNode[] = [];
  for (let i = 0; i < 26; i++) stars.push(<rect key={i} x={(i * 37) % 120 + 2} y={(i * 53) % 34 + 2} width={1} height={1} fill="#f3f1e2" opacity={0.4 + ((i * 7) % 5) / 10} />);
  const cols: ReactNode[] = [];
  for (let i = 0; i < 6; i++) cols.push(<g key={i}><rect x={14 + i * 18} y={52} width={6} height={44} fill="#d6cfb4" /><rect x={14 + i * 18} y={52} width={2} height={44} fill="#f3f1e2" /><rect x={12 + i * 18} y={50} width={10} height={3} fill="#f3f1e2" /><rect x={12 + i * 18} y={96} width={10} height={3} fill="#a89a74" /></g>);
  const frames: ReactNode[] = [];
  [[18, 62], [36, 70], [54, 60], [72, 70], [90, 62]].forEach(([x, y], i) => frames.push(<g key={i} className="glow" style={{ animationDelay: `${i * 0.5}s` }}><rect x={x} y={y} width={12} height={9} fill="#f0b13a" /><rect x={x + 1} y={y + 1} width={10} height={7} fill={['#133d7e', '#2481aa', '#133d7e', '#1c61a1', '#2481aa'][i]} /><rect x={x + 4} y={y + 3} width={3} height={3} fill="#f3f1e2" /></g>));
  return (
    <svg className="facade" viewBox="0 0 124 130" role="img" aria-label="The Memo museum at night with its doors lit" shapeRendering="crispEdges">
      {stars}
      <rect x={104} y={8} width={8} height={8} fill="#f3f1e2" /><rect x={106} y={6} width={4} height={2} fill="#f3f1e2" /><rect x={106} y={16} width={4} height={2} fill="#f3f1e2" />
      <rect x={8} y={40} width={108} height={4} fill="#a89a74" /><rect x={14} y={34} width={96} height={6} fill="#d6cfb4" /><rect x={26} y={28} width={72} height={6} fill="#f3f1e2" /><rect x={42} y={22} width={40} height={6} fill="#d6cfb4" />
      <rect x={56} y={24} width={12} height={4} fill="#f0b13a" /><rect x={8} y={44} width={108} height={8} fill="#2b4c8a" />
      <rect x={10} y={52} width={104} height={46} fill="#0e2457" />
      {frames}
      <rect x={52} y={78} width={20} height={20} fill="#061431" /><rect x={54} y={80} width={16} height={18} className="glow" fill="#f0b13a" /><rect x={61} y={80} width={2} height={18} fill="#b9801a" />
      {cols}
      <rect x={6} y={99} width={112} height={4} fill="#a89a74" /><rect x={2} y={103} width={120} height={4} fill="#8b7d58" /><rect x={0} y={107} width={124} height={23} fill="#061431" />
      <rect x={0} y={107} width={124} height={2} fill="#2b4c8a" />
    </svg>
  );
}
