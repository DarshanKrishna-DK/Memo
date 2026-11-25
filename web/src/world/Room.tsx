import { useEffect, useMemo, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { createInstances } from '@react-three/drei';
import * as THREE from 'three';
import type { Exhibit, Interactable, ShowcaseItem } from '../contract';
import { GRANDMA_LOOK } from './characters/rigs';
import { HumanCharacter, makeControl } from './characters/HumanCharacter';
import { DOOR_W, ROOM, SCREEN, SEAT_H, WALL_T, roomPlaces, toWorld, type RoomFrame } from './layout';
import { Box, CanvasPlane, Downlights, FloorPlane } from './parts';
import { TheaterScreen } from './TheaterScreen';
import { Audience, BackBench } from './Audience';
import type { PresencePerson } from '../state/worldStore';
import { isTap, useRuntime } from './runtime';
import { Atlas, FONT_DISPLAY, FONT_SANS, PAL, aspectOf, monthName, useFontsReady, usePhoto, wrap } from './textures';

type Act = (i: Interactable) => void;

const [FrameI, FrameInst] = createInstances();
const [MatI, MatInst] = createInstances();
const [SeatBackI, SeatBack] = createInstances();
const [SeatBaseI, SeatBase] = createInstances();
const [ArmI, Arm] = createInstances();

function clickProps(rt: ReturnType<typeof useRuntime>, i: Interactable, act: Act) {
  return {
    onClick: (e: { stopPropagation: () => void }) => { e.stopPropagation(); if (isTap(rt)) act(i); },
    onPointerOver: () => { document.body.style.cursor = 'pointer'; },
    onPointerOut: () => { document.body.style.cursor = ''; },
  };
}

function Photo({ url, memoryId, act }: { url: string; memoryId: string; act: Act }) {
  const rt = useRuntime();
  const tex = usePhoto(url);
  const a = aspectOf(tex);
  const maxW = 1.05, maxH = 0.8;
  const w = a > maxW / maxH ? maxW : maxH * a;
  const h = w / a;
  return (
    <mesh position={[0, 0, 0.03]} {...clickProps(rt, { kind: 'frame', memory_id: memoryId }, act)}>
      <planeGeometry args={[w, h]} />
      {tex ? (
        <meshStandardMaterial map={tex} roughness={0.7} emissive="#ffffff" emissiveMap={tex} emissiveIntensity={0.18} />
      ) : (
        <meshStandardMaterial color="#2b3550" roughness={0.9} />
      )}
    </mesh>
  );
}

/** Up to ~6 highlighted photos from the room's memories (first photo of each photo / album). */
function pickFrames(exhibits: Exhibit[], slots: number) {
  const out: Array<{ memoryId: string; url: string }> = [];
  for (const e of exhibits) {
    if (out.length >= slots) break;
    const p = e.photos.find((x) => !x.is_blurry) ?? e.photos[0];
    if (p && (e.kind === 'photo' || e.kind === 'album' || e.kind === 'forward')) out.push({ memoryId: e.id, url: p.thumb_url });
  }
  if (out.length < slots) {
    // albums can lend a second photo
    for (const e of exhibits) {
      if (e.kind !== 'album') continue;
      for (const p of e.photos.slice(1)) {
        if (out.length >= slots) break;
        out.push({ memoryId: e.id, url: p.thumb_url });
      }
    }
  }
  return out;
}

function Jukebox({ voices, act, pos, yaw }: { voices: Exhibit[]; act: Act; pos: { x: number; z: number }; yaw: number }) {
  const rt = useRuntime();
  const next = useRef(0);
  const glow = useRef<THREE.MeshBasicMaterial>(null);
  useFrame(({ clock }) => {
    if (glow.current) glow.current.color.setHSL((clock.elapsedTime * 0.05) % 1, 0.7, 0.6);
  });
  const play = () => {
    if (!voices.length || !isTap(rt)) return;
    const v = voices[next.current % voices.length];
    next.current++;
    act({ kind: 'jukebox', memory_id: v.id });
  };
  return (
    <group position={[pos.x, 0, pos.z]} rotation={[0, yaw, 0]}>
      <group
        onClick={(e) => { e.stopPropagation(); play(); }}
        onPointerOver={() => { document.body.style.cursor = voices.length ? 'pointer' : ''; }}
        onPointerOut={() => { document.body.style.cursor = ''; }}
      >
        <Box p={[0, 0.6, 0]} s={[0.8, 1.2, 0.5]} color={PAL.wood} rough={0.4} cast />
        <mesh position={[0, 1.2, 0]} rotation={[Math.PI / 2, 0, 0]} castShadow>
          <cylinderGeometry args={[0.4, 0.4, 0.5, 16, 1, false, -Math.PI / 2, Math.PI]} />
          <meshStandardMaterial color={PAL.wood} roughness={0.4} />
        </mesh>
        <mesh position={[0, 1.2, 0.252]}>
          <ringGeometry args={[0.28, 0.34, 16, 1, 0, Math.PI]} />
          <meshBasicMaterial ref={glow} toneMapped={false} />
        </mesh>
        <Box p={[0, 0.85, 0.252]} s={[0.56, 0.36, 0.01]} color="#1a1020" emissive={PAL.goldSoft} emissiveIntensity={0.25} />
        {[-0.2, 0, 0.2].map((x) => (
          <Box key={x} p={[x, 0.35, 0.255]} s={[0.1, 0.4, 0.01]} color={PAL.gold} rough={0.3} metal={0.7} />
        ))}
      </group>
      <CanvasPlane
        w={0.56} h={0.36} px={300}
        position={[0, 0.85, 0.259]}
        deps={[voices.length]}
        draw={(g, W, H) => {
          g.fillStyle = '#1a1020';
          g.fillRect(0, 0, W, H);
          g.textAlign = 'center';
          g.fillStyle = PAL.goldSoft;
          g.font = `${Math.round(H * 0.34)}px ${FONT_DISPLAY}`;
          g.fillText('JUKEBOX', W / 2, H * 0.4);
          g.fillStyle = PAL.cream;
          g.font = `600 ${Math.round(H * 0.14)}px ${FONT_SANS}`;
          g.fillText(voices.length ? `${voices.length} voice note${voices.length === 1 ? '' : 's'} · press to play` : 'no voice notes yet', W / 2, H * 0.72, W * 0.92);
        }}
      />
    </group>
  );
}

function Plaques({ stories, places, act }: { stories: Exhibit[]; places: Array<{ x: number; z: number }>; act: Act }) {
  const rt = useRuntime();
  const fonts = useFontsReady();
  const key = stories.map((s) => s.id).join('|');
  const atlas = useMemo(
    () => new Atlas(2, 2, 300, 380, (g, i, W, H) => {
      const s = stories[i];
      if (!s) return;
      const grad = g.createLinearGradient(0, 0, W, H);
      grad.addColorStop(0, '#e2c56a');
      grad.addColorStop(1, '#b8902e');
      g.fillStyle = grad;
      g.fillRect(0, 0, W, H);
      g.strokeStyle = '#7a5a18';
      g.lineWidth = 6;
      g.strokeRect(10, 10, W - 20, H - 20);
      g.fillStyle = '#2a1e08';
      g.textAlign = 'center';
      g.font = `40px ${FONT_DISPLAY}`;
      const title = wrap(g, s.title || 'A story', W * 0.8, 2);
      title.forEach((l, k) => g.fillText(l, W / 2, 62 + k * 38));
      g.font = `500 19px ${FONT_SANS}`;
      const body = wrap(g, s.summary || s.text || '', W * 0.8, 8);
      body.forEach((l, k) => g.fillText(l, W / 2, 80 + title.length * 38 + k * 25));
      if (s.author || s.teller) {
        g.font = `600 17px ${FONT_SANS}`;
        g.fillText(`— ${s.teller || s.author}`, W / 2, H - 28);
      }
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key, fonts],
  );
  useEffect(() => () => atlas.dispose(), [atlas]);
  return (
    <>
      {stories.slice(0, places.length).map((s, i) => (
        <group key={s.id} position={[places[i].x, 1.45, places[i].z - 0.012]} rotation={[0, Math.PI, 0]}>
          <mesh {...clickProps(rt, { kind: 'plaque', memory_id: s.id }, act)}>
            <planeGeometry args={[0.48, 0.6]} />
            <meshStandardMaterial map={atlas.cell(i)} roughness={0.35} metalness={0.5} emissive="#ffffff" emissiveMap={atlas.cell(i)} emissiveIntensity={0.25} />
          </mesh>
        </group>
      ))}
    </>
  );
}

function Grandma({ pos, yaw, speaking }: { pos: { x: number; z: number }; yaw: number; speaking: () => boolean }) {
  const rt = useRuntime();
  const control = useMemo(() => makeControl({ action: 'sit', seatHeight: 0.48 }), []);
  const head = useMemo(() => new THREE.Vector3(), []);
  const t = useRef(0);
  control.mouth = () => (speaking() ? 0.45 + 0.4 * Math.abs(Math.sin(t.current * 6.5)) : 0);
  useFrame((_, dt) => {
    t.current += dt;
    head.set(rt.player.pos.x, rt.player.seated ? 1.2 : 1.6, rt.player.pos.z);
    control.lookAt = head;
  });
  return (
    <group position={[pos.x, 0, pos.z]} rotation={[0, yaw, 0]}>
      {/* her armchair */}
      <Box p={[0, 0.24, -0.08]} s={[0.66, 0.48, 0.6]} color="#7a1f2b" rough={0.8} cast />
      <Box p={[0, 0.72, -0.36]} s={[0.66, 0.9, 0.14]} color="#7a1f2b" rough={0.8} cast />
      <Box p={[0.3, 0.6, -0.08]} s={[0.1, 0.2, 0.6]} color="#6a1a25" rough={0.8} />
      <Box p={[-0.3, 0.6, -0.08]} s={[0.1, 0.2, 0.6]} color="#6a1a25" rough={0.8} />
      <group position={[0, 0, 0.05]}>
        <HumanCharacter look={GRANDMA_LOOK} control={control} />
      </group>
    </group>
  );
}

export function MonthRoom({
  frame, year, month, exhibits, showcase, showcaseIndex, memoryCount, lang, screenMode, act, grandmaSpeaking,
  audience = [], overflow = false,
}: {
  frame: RoomFrame; year: number; month: number; exhibits: Exhibit[]; showcase: ShowcaseItem[]; showcaseIndex: number;
  memoryCount: number | null; lang: string; screenMode: boolean; act: Act; grandmaSpeaking: () => boolean;
  /** Other people seated here (not us). */
  audience?: PresencePerson[];
  /** We watch without a seat: draw the back bench. */
  overflow?: boolean;
}) {
  const rt = useRuntime();
  const { camera, size } = useThree();
  const P = useMemo(() => roomPlaces(frame), [frame]);
  const frames = useMemo(() => pickFrames(exhibits, P.frames.length), [exhibits, P.frames.length]);
  const stories = useMemo(() => exhibits.filter((e) => e.kind === 'text' || (e.kind === 'forward' && !e.photos.length)).slice(0, 4), [exhibits]);
  const voices = useMemo(() => exhibits.filter((e) => e.kind === 'voice' && e.audio_url), [exhibits]);
  const item = showcase[showcaseIndex] ?? null;
  const lights = useMemo<Array<[number, number]>>(() => [[-1.8, -2.2], [1.8, -2.2], [-1.8, -5.4], [1.8, -5.4]], []);
  const s = frame.s;

  // Screen-mode camera target: in front of the screen, far enough that it fills the view.
  useFrame(() => {
    const cam = camera as THREE.PerspectiveCamera;
    const half = THREE.MathUtils.degToRad(cam.fov / 2);
    const aspect = size.width / Math.max(1, size.height);
    const dH = SCREEN.h / 2 / Math.tan(half);
    const dW = SCREEN.w / 2 / (Math.tan(half) * aspect);
    const d = Math.min(dH, dW) * 0.985; // cover: the screen overfills slightly, no wall visible
    const c = toWorld(frame, 0, -ROOM.d + 0.12);
    const p = toWorld(frame, 0, -ROOM.d + 0.12 + d);
    rt.screenCam.look.set(c.x, SCREEN.y, c.z);
    rt.screenCam.pos.set(p.x, SCREEN.y, p.z);
    rt.screenTarget = screenMode && rt.player.seated ? 1 : 0;
  });

  return (
    <group position={[frame.ox, 0, frame.oz]} rotation={[0, frame.rotY, 0]}>
      <FloorPlane x0={-ROOM.halfW} x1={ROOM.halfW} z0={-ROOM.d} z1={-WALL_T} kind="parquet" />
      <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, ROOM.h, -ROOM.d / 2]}>
        <planeGeometry args={[ROOM.halfW * 2, ROOM.d]} />
        <meshStandardMaterial color="#14224a" roughness={0.95} />
      </mesh>
      <Downlights points={lights} y={ROOM.h} count={3} intensity={3.2} />
      {/* walls: plum fabric panels above a navy wainscot */}
      {[-1, 1].map((sx) => (
        <group key={sx}>
          <Box p={[sx * (ROOM.halfW + 0.15), ROOM.h / 2, -ROOM.d / 2]} s={[0.3, ROOM.h, ROOM.d]} color="#3a2440" rough={0.95} />
          <Box p={[sx * (ROOM.halfW - 0.012), 0.55, -ROOM.d / 2]} s={[0.024, 1.1, ROOM.d]} color={PAL.navy} rough={0.7} />
          <Box p={[sx * (ROOM.halfW - 0.03), 1.12, -ROOM.d / 2]} s={[0.04, 0.05, ROOM.d]} color={PAL.gold} rough={0.35} metal={0.6} />
        </group>
      ))}
      <Box p={[0, ROOM.h / 2, -ROOM.d - 0.15]} s={[ROOM.halfW * 2, ROOM.h, 0.3]} color="#231633" rough={0.95} />
      {/* back wall (door wall), with an opening at the door */}
      {(() => {
        const a = -ROOM.halfW, b = frame.doorLX - DOOR_W / 2 - 0.1, c = frame.doorLX + DOOR_W / 2 + 0.1, d = ROOM.halfW;
        return (
          <>
            {b - a > 0.01 && <Box p={[(a + b) / 2, ROOM.h / 2, -WALL_T - 0.02]} s={[b - a, ROOM.h, 0.04]} color="#3a2440" rough={0.95} />}
            {d - c > 0.01 && <Box p={[(c + d) / 2, ROOM.h / 2, -WALL_T - 0.02]} s={[d - c, ROOM.h, 0.04]} color="#3a2440" rough={0.95} />}
            <Box p={[frame.doorLX, (2.37 + ROOM.h) / 2, -WALL_T - 0.02]} s={[DOOR_W + 0.2, ROOM.h - 2.37, 0.04]} color="#3a2440" rough={0.95} />
            {/* door reveal through the wall thickness */}
            <Box p={[frame.doorLX - DOOR_W / 2 - 0.06, 1.18, -WALL_T / 2]} s={[0.12, 2.37, WALL_T]} color={PAL.gold} rough={0.3} metal={0.6} />
            <Box p={[frame.doorLX + DOOR_W / 2 + 0.06, 1.18, -WALL_T / 2]} s={[0.12, 2.37, WALL_T]} color={PAL.gold} rough={0.3} metal={0.6} />
            <Box p={[frame.doorLX, 2.42, -WALL_T / 2]} s={[DOOR_W + 0.24, 0.1, WALL_T]} color={PAL.gold} rough={0.3} metal={0.6} />
          </>
        );
      })()}

      {/* the screen, its frame, stage and curtains */}
      <group position={[0, SCREEN.y, -ROOM.d + 0.12]}>
        <Box p={[0, 0, -0.04]} s={[SCREEN.w + 0.24, SCREEN.h + 0.24, 0.06]} color="#0a0d14" rough={0.4} />
        <TheaterScreen item={item} index={showcaseIndex} total={showcase.length} year={year} month={month} memoryCount={memoryCount} lang={lang} />
      </group>
      <Box p={[0, 0.2, -ROOM.d + 0.35]} s={[SCREEN.w + 0.4, 0.4, 0.7]} color={PAL.woodDark} rough={0.5} cast />
      {[-1, 1].map((sx) => (
        <mesh key={sx} position={[sx * (SCREEN.w / 2 + 0.45), ROOM.h / 2, -ROOM.d + 0.25]} castShadow>
          <cylinderGeometry args={[0.32, 0.4, ROOM.h, 10, 1, true]} />
          <meshStandardMaterial color="#8a1f2e" roughness={0.85} side={THREE.DoubleSide} flatShading />
        </mesh>
      ))}

      {/* side-wall frames (instanced frames + mats, one texture per photo) */}
      <FrameI limit={6} castShadow frustumCulled={false}>
        <boxGeometry args={[1.25, 1.0, 0.06]} />
        <meshStandardMaterial color={PAL.gold} roughness={0.35} metalness={0.65} />
        <MatI limit={6} frustumCulled={false}>
          <boxGeometry args={[1.13, 0.88, 0.01]} />
          <meshStandardMaterial color="#efe4cc" roughness={0.9} />
          {P.frames.map((f, i) => (
            <group key={i} position={[f.x - Math.sign(f.x) * 0.04, 1.75, f.z]} rotation={[0, f.yaw, 0]}>
              <FrameInst position={[0, 0, 0]} />
              <MatInst position={[0, 0, 0.032]} />
              {frames[i] && <Photo url={frames[i].url} memoryId={frames[i].memoryId} act={act} />}
            </group>
          ))}
        </MatI>
      </FrameI>
      {/* picture lights over the frames */}
      {P.frames.map((f, i) => (
        <Box key={i} p={[f.x - Math.sign(f.x) * 0.1, 2.38, f.z]} s={[0.12, 0.04, 0.6]} color={PAL.gold} emissive="#ffe2b0" emissiveIntensity={frames[i] ? 1.2 : 0.2} />
      ))}

      <Plaques stories={stories} places={P.plaques} act={act} />
      <Jukebox voices={voices} act={act} pos={P.jukebox} yaw={P.jukebox.yaw} />

      {/* one row of four seats facing the screen */}
      <SeatBaseI limit={4} castShadow receiveShadow frustumCulled={false}>
        <boxGeometry args={[0.66, 0.16, 0.6]} />
        <meshStandardMaterial color="#8a1f2e" roughness={0.75} />
        <SeatBackI limit={4} castShadow frustumCulled={false}>
          <boxGeometry args={[0.66, 0.55, 0.12]} />
          <meshStandardMaterial color="#8a1f2e" roughness={0.75} />
          <ArmI limit={8} castShadow frustumCulled={false}>
            <boxGeometry args={[0.08, 0.6, 0.62]} />
            <meshStandardMaterial color={PAL.woodDark} roughness={0.5} />
            {P.seats.map((st, i) => (
              <group
                key={i}
                position={[st.x, 0, st.z]}
                rotation={[0, st.yaw, 0]}
                {...clickProps(rt, { kind: 'seat', year, month, index: i }, act)}
              >
                <SeatBase position={[0, SEAT_H - 0.08, 0]} />
                <SeatBack position={[0, SEAT_H + 0.24, -0.3]} />
                <Arm position={[-0.37, 0.3, 0]} />
                <Arm position={[0.37, 0.3, 0]} />
              </group>
            ))}
          </ArmI>
        </SeatBackI>
      </SeatBaseI>

      <Grandma pos={P.grandma} yaw={P.grandma.yaw} speaking={grandmaSpeaking} />
      <Audience people={audience} seats={P.seats} />
      {overflow && <BackBench />}

      {/* room title above the door, facing in */}
      <CanvasPlane
        w={1.8} h={0.42} px={200}
        position={[frame.doorLX, 2.85, -WALL_T - 0.045]} rotation={[0, 0, 0]}
        deps={[year, month, lang]}
        draw={(g, W, H) => {
          g.fillStyle = PAL.navy;
          g.fillRect(0, 0, W, H);
          g.textAlign = 'center';
          g.textBaseline = 'middle';
          g.fillStyle = PAL.goldSoft;
          g.font = `${Math.round(H * 0.6)}px ${FONT_DISPLAY}`;
          g.fillText(`${monthName(month, lang)} ${year}`, W / 2, H * 0.55, W * 0.92);
        }}
      />
      {/* keep `s` meaningful for mirrored rooms: a little side table by Grandma */}
      <Box p={[P.grandma.x + s * 0.65, 0.3, P.grandma.z]} s={[0.4, 0.6, 0.4]} color={PAL.woodDark} rough={0.5} cast />
      <mesh position={[P.grandma.x + s * 0.65, 0.72, P.grandma.z]}>
        <cylinderGeometry args={[0.05, 0.07, 0.24, 8]} />
        <meshStandardMaterial color="#efe4cc" emissive="#ffd9a6" emissiveIntensity={0.6} />
      </mesh>
    </group>
  );
}
