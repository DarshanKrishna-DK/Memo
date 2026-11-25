import { useEffect, useMemo } from 'react';
import type { FloorSummary, Interactable, MuseumSummary } from '../contract';
import { ATTIC, CORR_CEIL, CORR_HALF_W, DESK, DIRECTORY, LANDING, LATEST_PLAQUE, LIFT, LOBBY, QR_BOARD } from './layout';
import { Box, CanvasPlane, Ceiling, Downlights, FloorPlane, Wall } from './parts';
import { isTap, useRuntime } from './runtime';
import { FONT_DISPLAY, FONT_SANS, PAL, canvasTex, monthName, pixelFrame, qrTexture, usePhoto, wrap, aspectOf } from './textures';

type Act = (i: Interactable) => void;

function clickable(rt: ReturnType<typeof useRuntime>, i: Interactable, act: Act) {
  return {
    onClick: (e: { stopPropagation: () => void }) => { e.stopPropagation(); if (isTap(rt)) act(i); },
    onPointerOver: () => { document.body.style.cursor = 'pointer'; },
    onPointerOut: () => { document.body.style.cursor = ''; },
  };
}

/** Night view through the glass; higher floors see more sky and the city further below. */
export function makeNightTex(level: number) {
  return canvasTex(1024, 384, (g) => {
    const sky = g.createLinearGradient(0, 0, 0, 384);
    sky.addColorStop(0, '#061431');
    sky.addColorStop(0.7, '#133d7e');
    sky.addColorStop(1, '#1c61a1');
    g.fillStyle = sky;
    g.fillRect(0, 0, 1024, 384);
    let seed = 11;
    const rnd = () => ((seed = (seed * 9301 + 49297) % 233280) / 233280);
    for (let i = 0; i < 160; i++) {
      g.fillStyle = `rgba(243,241,226,${0.3 + rnd() * 0.6})`;
      g.fillRect(rnd() * 1024, rnd() * 220, 2, 2);
    }
    g.fillStyle = '#f3f1e2';
    g.beginPath();
    g.arc(820, 70, 26, 0, Math.PI * 2);
    g.fill();
    const horizon = 300 + Math.min(level, 6) * 12;
    for (let i = 0; i < 40; i++) {
      const w = 20 + rnd() * 60, h = 30 + rnd() * 120 - level * 8, x = i * 27 - 10;
      g.fillStyle = '#0a1838';
      g.fillRect(x, horizon - h, w, h + 200);
      for (let y = horizon - h + 6; y < 384; y += 11)
        for (let xx = x + 4; xx < x + w - 4; xx += 9)
          if (rnd() < 0.35) {
            g.fillStyle = rnd() < 0.8 ? '#f0c24a' : '#a8e27c';
            g.fillRect(xx, y, 4, 5);
          }
    }
  });
}

/** Front wall with a night-view window: wall pieces around the opening, glass view, mullions. */
function WindowWall({ halfW, z, y0, y1, h, margin, level }: { halfW: number; z: number; y0: number; y1: number; h: number; margin: number; level: number }) {
  const tex = useMemo(() => makeNightTex(level), [level]);
  useEffect(() => () => tex.dispose(), [tex]);
  const x0 = -halfW + margin, x1 = halfW - margin;
  const w = x1 - x0, wh = y1 - y0;
  const mullions = Math.max(2, Math.round(w / 1.6));
  const T = 0.3;
  return (
    <group>
      <Box p={[0, y0 / 2, z + T / 2]} s={[halfW * 2, y0, T]} color={PAL.wall} rough={0.92} />
      <Box p={[0, (y1 + h) / 2, z + T / 2]} s={[halfW * 2, h - y1, T]} color={PAL.wall} rough={0.92} />
      <Box p={[-halfW + margin / 2, (y0 + y1) / 2, z + T / 2]} s={[margin, wh, T]} color={PAL.wall} rough={0.92} />
      <Box p={[halfW - margin / 2, (y0 + y1) / 2, z + T / 2]} s={[margin, wh, T]} color={PAL.wall} rough={0.92} />
      <mesh position={[0, (y0 + y1) / 2, z + 0.6]} rotation={[0, Math.PI, 0]}>
        <planeGeometry args={[w + 1.2, wh + 0.8]} />
        <meshBasicMaterial map={tex} toneMapped={false} />
      </mesh>
      {Array.from({ length: mullions + 1 }, (_, i) => (
        <Box key={i} p={[x0 + (i * w) / mullions, (y0 + y1) / 2, z + 0.05]} s={[0.08, wh, 0.1]} color={PAL.woodDark} rough={0.5} />
      ))}
      <Box p={[0, y0 - 0.03, z + 0.05]} s={[w, 0.08, 0.3]} color={PAL.woodDark} />
      <Box p={[0, y1 + 0.03, z + 0.05]} s={[w, 0.08, 0.12]} color={PAL.woodDark} />
    </group>
  );
}

function Planter({ p }: { p: [number, number, number] }) {
  return (
    <group position={p}>
      <mesh position={[0, 0.3, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[0.26, 0.2, 0.6, 8]} />
        <meshStandardMaterial color={PAL.navy} roughness={0.6} flatShading />
      </mesh>
      {[[0, 0.95, 0, 0.42], [0.18, 0.78, 0.1, 0.28], [-0.16, 0.82, -0.08, 0.3], [0.05, 1.25, 0.02, 0.26]].map(([x, y, z, r], i) => (
        <mesh key={i} position={[x, y, z]} castShadow>
          <icosahedronGeometry args={[r, 0]} />
          <meshStandardMaterial color={i % 2 ? '#3f7a43' : '#4f8f4a'} roughness={0.8} flatShading />
        </mesh>
      ))}
    </group>
  );
}

function Bench({ p, rotY = 0, len = 1.8 }: { p: [number, number, number]; rotY?: number; len?: number }) {
  return (
    <group position={p} rotation={[0, rotY, 0]}>
      <Box p={[0, 0.44, 0]} s={[len, 0.08, 0.5]} color={PAL.wood} rough={0.5} cast />
      <Box p={[-len / 2 + 0.12, 0.2, 0]} s={[0.08, 0.4, 0.44]} color={PAL.navy} />
      <Box p={[len / 2 - 0.12, 0.2, 0]} s={[0.08, 0.4, 0.44]} color={PAL.navy} />
    </group>
  );
}

function ReceptionDesk({ act, familyName }: { act: Act; familyName: string }) {
  const rt = useRuntime();
  return (
    <group position={[DESK.x, 0, DESK.z]}>
      <group {...clickable(rt, { kind: 'desk' }, act)}>
        <Box p={[0, 0.55, 0]} s={[DESK.depth, 1.1, DESK.len]} color={PAL.navy} rough={0.5} cast />
        <Box p={[0.1, 1.13, 0]} s={[DESK.depth + 0.25, 0.06, DESK.len + 0.15]} color={PAL.wood} rough={0.35} cast />
        <Box p={[DESK.depth / 2 + 0.005, 0.38, 0]} s={[0.01, 0.06, DESK.len - 0.1]} color={PAL.gold} rough={0.3} metal={0.7} />
      </group>
      <CanvasPlane
        w={2.0} h={0.42} px={200}
        position={[DESK.depth / 2 + 0.012, 0.78, 0]} rotation={[0, Math.PI / 2, 0]}
        deps={[familyName]}
        draw={(g, W, H) => {
          g.fillStyle = PAL.navy;
          g.fillRect(0, 0, W, H);
          g.fillStyle = PAL.goldSoft;
          g.font = `${H * 0.62}px ${FONT_DISPLAY}`;
          g.textAlign = 'center';
          g.textBaseline = 'middle';
          g.fillText('RECEPTION', W / 2, H * 0.52);
        }}
      />
      {/* bell + monitor */}
      <mesh position={[0.25, 1.2, 0.9]} castShadow>
        <sphereGeometry args={[0.07, 10, 6, 0, Math.PI * 2, 0, Math.PI / 2]} />
        <meshStandardMaterial color={PAL.gold} metalness={0.9} roughness={0.25} />
      </mesh>
      <group position={[-0.15, 1.16, -0.7]} rotation={[0, Math.PI / 2, 0]}>
        <Box p={[0, 0.22, 0]} s={[0.5, 0.32, 0.03]} color="#101522" rough={0.3} cast />
        <Box p={[0, 0.22, 0.017]} s={[0.46, 0.28, 0.002]} color="#173571" emissive="#2481aa" emissiveIntensity={0.6} />
        <Box p={[0, 0.05, -0.03]} s={[0.06, 0.1, 0.06]} color="#2a2d31" />
      </group>
    </group>
  );
}

function Directory({ floors, act }: { floors: FloorSummary[]; act: Act }) {
  const rt = useRuntime();
  const key = floors.map((f) => `${f.year}:${f.open}:${f.level}`).join('|');
  return (
    <group position={[DIRECTORY.x - 0.02, 0, DIRECTORY.z]} rotation={[0, -Math.PI / 2, 0]}>
      <Box p={[0, 1.65, -0.03]} s={[2.3, 2.5, 0.06]} color={PAL.woodDark} rough={0.45} cast />
      <group {...clickable(rt, { kind: 'directory' }, act)}>
        <CanvasPlane
          w={2.1} h={2.3} px={220}
          position={[0, 1.65, 0.005]}
          deps={[key]}
          draw={(g, W, H) => {
            g.fillStyle = PAL.navy;
            g.fillRect(0, 0, W, H);
            g.fillStyle = PAL.goldSoft;
            g.textAlign = 'center';
            g.font = `${Math.round(H * 0.085)}px ${FONT_DISPLAY}`;
            g.fillText('DIRECTORY', W / 2, H * 0.1);
            g.fillStyle = PAL.line;
            g.fillRect(W * 0.06, H * 0.13, W * 0.88, 4);
            const rows = floors.slice(0, 12);
            const rh = Math.min(H * 0.075, (H * 0.8) / Math.max(1, rows.length));
            rows.forEach((f, i) => {
              const y = H * 0.2 + i * rh + rh * 0.6;
              g.textAlign = 'left';
              g.fillStyle = PAL.cream;
              g.font = `${Math.round(rh * 0.85)}px ${FONT_DISPLAY}`;
              g.fillText(String(f.year), W * 0.07, y);
              g.font = `600 ${Math.round(rh * 0.4)}px ${FONT_SANS}`;
              g.fillStyle = '#a7b6d6';
              g.fillText(f.level === 0 ? 'GROUND FLOOR' : `FLOOR ${f.level}`, W * 0.33, y - rh * 0.05);
              g.textAlign = 'right';
              g.fillStyle = f.open > 0 ? PAL.lime : '#a7b6d6';
              g.font = `${Math.round(rh * 0.8)}px ${FONT_DISPLAY}`;
              g.fillText(`${f.open}/12`, W * 0.93, y);
              // tiny 12-cell bar
              for (let k = 0; k < 12; k++) {
                g.fillStyle = k < f.open ? PAL.gold : '#1d3f82';
                g.fillRect(W * 0.33 + k * (W * 0.022), y + rh * 0.1, W * 0.016, rh * 0.14);
              }
            });
            if (!rows.length) {
              g.textAlign = 'center';
              g.fillStyle = PAL.cream;
              g.font = `600 ${Math.round(H * 0.035)}px ${FONT_SANS}`;
              g.fillText('Loading floors…', W / 2, H / 2);
            }
          }}
        />
      </group>
    </group>
  );
}

function AtticDoor({ count, act }: { count: number; act: Act }) {
  const rt = useRuntime();
  return (
    <group position={[ATTIC.x, 0, ATTIC.z]} rotation={[0, -Math.PI / 2, 0]}>
      <group {...clickable(rt, { kind: 'attic' }, act)}>
        <Box p={[0, 1.1, 0.02]} s={[1.2, 2.2, 0.06]} color={PAL.plum} rough={0.55} cast />
        <Box p={[0, 1.1, 0.0]} s={[1.38, 2.32, 0.04]} color={PAL.gold} rough={0.3} metal={0.6} />
        <Box p={[0.42, 1.05, 0.07]} s={[0.05, 0.18, 0.05]} color={PAL.gold} metal={0.9} rough={0.2} />
      </group>
      <CanvasPlane
        w={1.5} h={0.5} px={220}
        position={[0, 2.62, 0.03]}
        deps={[count]}
        draw={(g, W, H) => {
          g.fillStyle = PAL.navy;
          g.fillRect(0, 0, W, H);
          g.textAlign = 'center';
          g.fillStyle = PAL.goldSoft;
          g.font = `${Math.round(H * 0.5)}px ${FONT_DISPLAY}`;
          g.fillText('THE ATTIC', W / 2, H * 0.5);
          g.fillStyle = PAL.cream;
          g.font = `600 ${Math.round(H * 0.2)}px ${FONT_SANS}`;
          g.fillText(count === 1 ? '1 memory without a date' : `${count} memories without a date`, W / 2, H * 0.84);
        }}
      />
    </group>
  );
}

function LatestPlaque({ latest, act, lang }: { latest: MuseumSummary['latest']; act: Act; lang: string }) {
  const rt = useRuntime();
  const tex = usePhoto(latest?.thumb_url ?? null);
  const a = aspectOf(tex);
  const pw = Math.min(1.2, 0.8 * a), ph = pw / a;
  return (
    <group position={[LATEST_PLAQUE.x, 0, LATEST_PLAQUE.z + 0.02]}>
      <Box p={[0, 1.75, 0]} s={[1.7, 1.75, 0.05]} color={PAL.woodDark} rough={0.45} />
      <group {...(latest ? clickable(rt, { kind: 'plaque', memory_id: latest.id }, act) : {})}>
        {tex && (
          <mesh position={[0, 2.0, 0.035]}>
            <planeGeometry args={[pw, ph]} />
            <meshStandardMaterial map={tex} roughness={0.6} emissive="#ffffff" emissiveMap={tex} emissiveIntensity={0.25} />
          </mesh>
        )}
        <CanvasPlane
          w={1.56} h={tex ? 0.42 : 1.6} px={220}
          position={[0, tex ? 1.12 : 1.75, 0.03]}
          deps={[latest?.id, latest?.title, !!tex, lang]}
          draw={(g, W, H) => {
            g.fillStyle = '#efe4cc';
            g.fillRect(0, 0, W, H);
            g.textAlign = 'center';
            g.fillStyle = PAL.navy;
            const small = Math.round(Math.min(H * 0.2, W * 0.05));
            g.font = `600 ${small}px ${FONT_SANS}`;
            g.fillText('LATEST MEMORY', W / 2, small * 1.3);
            if (!latest) {
              g.font = `${small * 1.6}px ${FONT_DISPLAY}`;
              g.fillText('Nothing yet. Tell Grandma on Telegram.', W / 2, H * 0.6, W * 0.9);
              return;
            }
            g.font = `${Math.round(small * 1.7)}px ${FONT_DISPLAY}`;
            const lines = wrap(g, latest.title || 'Untitled', W * 0.9, tex ? 1 : 4);
            lines.forEach((l, i) => g.fillText(l, W / 2, small * 3 + i * small * 1.7));
            g.font = `600 ${small}px ${FONT_SANS}`;
            g.fillStyle = '#6b4a32';
            g.fillText(`${monthName(latest.month, lang)} ${latest.year}`, W / 2, H - small * 0.5);
          }}
        />
      </group>
    </group>
  );
}

function QrBoard({ bot }: { bot: string | null }) {
  const tex = useMemo(() => (bot ? qrTexture(`https://t.me/${bot}`, 'Add a memory') : null), [bot]);
  useEffect(() => () => tex?.dispose(), [tex]);
  return (
    <group position={[QR_BOARD.x + 0.02, 0, QR_BOARD.z]} rotation={[0, Math.PI / 2, 0]}>
      <Box p={[0, 1.6, -0.02]} s={[1.0, 1.24, 0.04]} color={PAL.gold} rough={0.3} metal={0.6} />
      {tex ? (
        <mesh position={[0, 1.6, 0.005]}>
          <planeGeometry args={[0.9, 1.125]} />
          <meshBasicMaterial map={tex} toneMapped={false} />
        </mesh>
      ) : (
        <CanvasPlane w={0.9} h={1.125} px={256} position={[0, 1.6, 0.005]} deps={[]} draw={(g, W, H) => {
          g.fillStyle = PAL.cream;
          g.fillRect(0, 0, W, H);
          g.fillStyle = PAL.navy;
          g.textAlign = 'center';
          g.font = `${Math.round(W * 0.1)}px ${FONT_DISPLAY}`;
          g.fillText('Telegram bot', W / 2, H * 0.45);
          g.font = `600 ${Math.round(W * 0.05)}px ${FONT_SANS}`;
          g.fillText('not configured yet', W / 2, H * 0.55);
        }} />
      )}
      <CanvasPlane w={1.0} h={0.3} px={256} position={[0, 2.42, 0.005]} deps={[]} draw={(g, W, H) => {
        g.fillStyle = PAL.navy;
        g.fillRect(0, 0, W, H);
        g.fillStyle = PAL.cream;
        g.textAlign = 'center';
        g.font = `600 ${Math.round(H * 0.3)}px ${FONT_SANS}`;
        g.fillText('Scan to tell Grandma', W / 2, H * 0.62);
      }} />
    </group>
  );
}

/** The lobby's back wall pieces (around the corridor mouth and lift), shared with the landing. */
function BackWall({ halfW, h }: { halfW: number; h: number }) {
  const lx0 = LIFT.x - LIFT.doorW / 2, lx1 = LIFT.x + LIFT.doorW / 2;
  return (
    <>
      <Wall a={[-halfW, 0]} b={[-CORR_HALF_W, 0]} h={h} face={1} />
      <Wall a={[CORR_HALF_W, 0]} b={[lx0, 0]} h={h} face={1} />
      <Wall a={[lx1, 0]} b={[halfW, 0]} h={h} face={1} />
      {/* headers above the corridor mouth and the lift */}
      <Box p={[0, (CORR_CEIL + h) / 2, -0.15]} s={[CORR_HALF_W * 2, h - CORR_CEIL, 0.3]} color={PAL.wall} rough={0.92} />
      <Box p={[LIFT.x, (LIFT.h + h) / 2, -0.15]} s={[LIFT.doorW, h - LIFT.h, 0.3]} color={PAL.wall} rough={0.92} />
      {/* gold arch line over the corridor mouth */}
      <Box p={[0, CORR_CEIL + 0.04, 0.02]} s={[CORR_HALF_W * 2 + 0.2, 0.08, 0.06]} color={PAL.gold} rough={0.3} metal={0.7} />
    </>
  );
}

export function Lobby({ museum, act }: { museum: MuseumSummary; act: Act }) {
  const W = LOBBY.halfW, F = LOBBY.frontZ, H = LOBBY.ceil;
  const lights = useMemo(() => {
    const pts: Array<[number, number]> = [];
    for (let x = -6; x <= 6; x += 3) for (let z = 2; z <= 11; z += 3) pts.push([x, z]);
    return pts;
  }, []);
  const lang = museum.family.language;
  return (
    <group>
      <FloorPlane x0={-W} x1={W} z0={0} z1={F} kind="stone" />
      <Ceiling x0={-W} x1={W} z0={0} z1={F} y={H} />
      <Downlights points={lights} y={H} count={4} intensity={6} />
      <BackWall halfW={W} h={H} />
      <Wall a={[-W, F]} b={[-W, 0]} h={H} face={1} />
      <Wall a={[W, 0]} b={[W, F]} h={H} face={1} />
      <WindowWall halfW={W} z={F} y0={0.9} y1={H - 0.5} h={H} margin={1.2} level={0} />
      {/* rug */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0.5, 0.006, 6]} receiveShadow>
        <planeGeometry args={[7, 5]} />
        <meshStandardMaterial color="#7a1f2b" roughness={0.95} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0.5, 0.008, 6]}>
        <ringGeometry args={[1.6, 1.68, 6]} />
        <meshStandardMaterial color={PAL.gold} roughness={0.6} />
      </mesh>
      <ReceptionDesk act={act} familyName={museum.family.name} />
      {/* museum title above the receptionist */}
      <CanvasPlane
        w={4.4} h={1.1} px={200}
        position={[-W + 0.03, 3.4, DESK.z]} rotation={[0, Math.PI / 2, 0]}
        deps={[museum.family.name]}
        draw={(g, Wp, Hp) => {
          g.clearRect(0, 0, Wp, Hp);
          g.fillStyle = PAL.navy;
          g.fillRect(0, 0, Wp, Hp);
          g.textAlign = 'center';
          g.fillStyle = PAL.goldSoft;
          g.font = `${Math.round(Hp * 0.5)}px ${FONT_DISPLAY}`;
          g.fillText(`THE ${museum.family.name.toUpperCase()} MUSEUM`, Wp / 2, Hp * 0.52, Wp * 0.94);
          g.fillStyle = PAL.cream;
          g.font = `600 ${Math.round(Hp * 0.16)}px ${FONT_SANS}`;
          g.fillText('MEMO · FAMILY MEMORIES, ROOM BY ROOM', Wp / 2, Hp * 0.82);
        }}
      />
      <Directory floors={museum.floors} act={act} />
      <AtticDoor count={museum.attic_count} act={act} />
      <LatestPlaque latest={museum.latest} act={act} lang={lang} />
      <QrBoard bot={museum.bot_username} />
      <Bench p={[2.5, 0, 8]} len={1.8} />
      <Planter p={[-1.0, 0, 11.2]} />
      <Planter p={[7.2, 0, 0.7]} />
      <Planter p={[-7.3, 0, 0.7]} />
    </group>
  );
}

export function Landing({ floor, level }: { floor: FloorSummary | null; level: number }) {
  const W = LANDING.halfW, F = LANDING.frontZ, H = LANDING.ceil;
  const lights = useMemo<Array<[number, number]>>(() => [[-3, 2.5], [0, 2.5], [3, 2.5]], []);
  return (
    <group>
      <FloorPlane x0={-W} x1={W} z0={0} z1={F} kind="stone" />
      <Ceiling x0={-W} x1={W} z0={0} z1={F} y={H} />
      <Downlights points={lights} y={H} count={2} intensity={5} />
      <BackWall halfW={W} h={H} />
      <Wall a={[-W, F]} b={[-W, 0]} h={H} face={1} />
      <Wall a={[W, 0]} b={[W, F]} h={H} face={1} />
      <WindowWall halfW={W} z={F} y0={0.9} y1={H - 0.4} h={H} margin={0.8} level={level} />
      <Bench p={[-3.7, 0, 4.2]} len={1.8} />
      <CanvasPlane
        w={2.2} h={1.1} px={200}
        position={[-4.0, 1.75, 0.03]}
        deps={[floor?.year, floor?.open, level]}
        draw={(g, Wp, Hp) => {
          g.fillStyle = PAL.navy;
          g.fillRect(0, 0, Wp, Hp);
          pixelFrame(g, 10, 10, Wp - 26, Hp - 26, PAL.gold, PAL.navyDeep, 4);
          g.fillStyle = PAL.navy;
          g.fillRect(12, 12, Wp - 30, Hp - 30);
          g.textAlign = 'center';
          g.fillStyle = PAL.goldSoft;
          g.font = `${Math.round(Hp * 0.42)}px ${FONT_DISPLAY}`;
          g.fillText(floor ? String(floor.year) : '…', Wp / 2, Hp * 0.45);
          g.fillStyle = PAL.cream;
          g.font = `600 ${Math.round(Hp * 0.13)}px ${FONT_SANS}`;
          g.fillText(`FLOOR ${level} · ${floor ? floor.open : 0} OF 12 ROOMS OPEN`, Wp / 2, Hp * 0.72);
        }}
      />
    </group>
  );
}
