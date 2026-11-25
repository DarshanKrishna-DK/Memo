import { useEffect, useMemo, useRef } from 'react';
import { useFrame, type ThreeEvent } from '@react-three/fiber';
import * as THREE from 'three';
import type { ShowcaseItem } from '../contract';
import { theaterVideo, useTheaterVideo } from '../pages/theaterVideo';
import { useWorld } from '../state/worldStore';
import { SCREEN } from './layout';
import { FONT_DISPLAY, FONT_SANS, PAL, canvasTex, monthName, usePhoto, useFontsReady, wrap } from './textures';

/** The big screen: plays the current showcase item. Photos get a slow zoom (Ken Burns) and a
 *  caption bar; written memories become title cards; voice notes show a card with the transcript. */
export function TheaterScreen({
  item, index, total, year, month, memoryCount, lang,
}: {
  item: ShowcaseItem | null; index: number; total: number; year: number; month: number; memoryCount: number | null; lang: string;
}) {
  const fonts = useFontsReady();
  const photoUrl = item?.kind === 'photo' ? item.url ?? item.thumb_url : null;
  const photo = usePhoto(photoUrl);
  const thumb = usePhoto(item?.kind === 'photo' && !photo ? item.thumb_url : null);
  const src = photo ?? thumb;

  // Video items: the poster until it starts, then the shared <video> as a texture, letterboxed (phone videos are tall).
  const isVideo = item?.kind === 'video';
  const vs = useTheaterVideo();
  const poster = usePhoto(isVideo ? item?.poster_url ?? item?.thumb_url ?? null : null);
  const vtex = useMemo(() => {
    if (!isVideo || !vs.url || !theaterVideo.el) return null;
    const t = new THREE.VideoTexture(theaterVideo.el);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }, [isVideo, vs.url]);
  useEffect(() => () => vtex?.dispose(), [vtex]);
  const vMap = vs.started && !vs.error && vtex ? vtex : poster;
  const vAspect = vMap === vtex ? vs.aspect : poster ? (poster.image as { width: number; height: number }).width / Math.max(1, (poster.image as { width: number; height: number }).height) : 16 / 9;
  const sa = SCREEN.w / SCREEN.h;
  const vw = vAspect > sa ? SCREEN.w : SCREEN.h * vAspect, vh = vAspect > sa ? SCREEN.w / vAspect : SCREEN.h;

  // Swipe the big screen on a touch device: left = next, right = previous (guests follow the host instead).
  const swipe = useRef<{ x: number; t: number } | null>(null);
  const onDown = (e: ThreeEvent<PointerEvent>) => { if (e.nativeEvent.pointerType === 'touch') swipe.current = { x: e.nativeEvent.clientX, t: performance.now() }; };
  const onUp = (e: ThreeEvent<PointerEvent>) => {
    const s0 = swipe.current; swipe.current = null;
    if (!s0) return;
    const dx = e.nativeEvent.clientX - s0.x;
    const w = useWorld.getState();
    if (Math.abs(dx) < 60 || performance.now() - s0.t > 600 || !w.seat || w.museum?.me.is_guest) return;
    if (dx < 0) w.nextItem(); else w.prevItem();
  };

  // Our own view of the shared texture so the zoom does not move other users' UVs.
  const view = useMemo(() => {
    if (!src) return null;
    const t = src.clone();
    t.needsUpdate = true;
    return t;
  }, [src]);
  useEffect(() => () => view?.dispose(), [view]);

  const card = useMemo(() => {
    const W = 1280, H = 720;
    return canvasTex(W, H, (g) => {
      const grad = g.createLinearGradient(0, 0, W, H);
      grad.addColorStop(0, PAL.navyDeep);
      grad.addColorStop(1, '#173571');
      g.fillStyle = grad;
      g.fillRect(0, 0, W, H);
      g.textAlign = 'center';
      if (!item) {
        g.fillStyle = PAL.goldSoft;
        g.font = `150px ${FONT_DISPLAY}`;
        g.fillText(`${monthName(month, lang)} ${year}`, W / 2, H * 0.46, W * 0.9);
        g.fillStyle = PAL.cream;
        g.font = `600 38px ${FONT_SANS}`;
        g.fillText(
          memoryCount === null ? 'Getting the room ready…' : memoryCount === 1 ? '1 memory in this room' : `${memoryCount} memories in this room`,
          W / 2, H * 0.62,
        );
        g.fillStyle = '#a7b6d6';
        g.font = `600 28px ${FONT_SANS}`;
        g.fillText('Take a seat and ask Grandma to start the show', W / 2, H * 0.72);
        return;
      }
      if (item.kind === 'photo') {
        g.fillStyle = PAL.cream;
        g.font = `600 36px ${FONT_SANS}`;
        g.fillText('Loading photo…', W / 2, H / 2);
        return;
      }
      const voice = item.kind === 'voice';
      g.fillStyle = voice ? PAL.teal : PAL.goldSoft;
      g.font = `600 30px ${FONT_SANS}`;
      g.fillText(voice ? '♪  A VOICE NOTE' : item.kind === 'video' ? '▶  A VIDEO' : 'A STORY', W / 2, 110);
      g.fillStyle = PAL.cream;
      g.font = `96px ${FONT_DISPLAY}`;
      const title = wrap(g, item.caption || (voice ? 'Voice note' : 'Untitled'), W * 0.84, 3);
      title.forEach((l, k) => g.fillText(l, W / 2, 230 + k * 92));
      const body = voice ? item.transcript : null;
      if (body) {
        g.fillStyle = '#d3d8e6';
        g.font = `500 34px ${FONT_SANS}`;
        const lines = wrap(g, `“${body}”`, W * 0.78, 6);
        lines.forEach((l, k) => g.fillText(l, W / 2, 250 + title.length * 92 + k * 46));
      }
      g.fillStyle = PAL.gold;
      g.fillRect(W / 2 - 80, H - 70, 160, 6);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.memory_id, item?.kind, item?.caption, item?.transcript, year, month, memoryCount, lang, fonts, !!item]);
  useEffect(() => () => card.dispose(), [card]);

  const captionTex = useMemo(() => {
    if (!item || (item.kind !== 'photo' && item.kind !== 'video') || !item.caption) return null;
    return canvasTex(1280, 140, (g) => {
      g.clearRect(0, 0, 1280, 140);
      const grad = g.createLinearGradient(0, 0, 0, 140);
      grad.addColorStop(0, 'rgba(6,20,49,0)');
      grad.addColorStop(0.45, 'rgba(6,20,49,0.78)');
      grad.addColorStop(1, 'rgba(6,20,49,0.9)');
      g.fillStyle = grad;
      g.fillRect(0, 0, 1280, 140);
      g.fillStyle = PAL.cream;
      g.textAlign = 'center';
      g.font = `600 40px ${FONT_SANS}`;
      g.fillText(wrap(g, item.caption, 1180, 1)[0] ?? '', 640, 100);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.memory_id, item?.caption, fonts]);
  useEffect(() => () => captionTex?.dispose(), [captionTex]);

  // Slow zoom per photo, restarting when the item changes.
  const zoom = useRef({ t: 0, key: '' });
  useFrame((_, dt) => {
    if (!view) return;
    const k = `${item?.memory_id}:${index}`;
    if (zoom.current.key !== k) zoom.current = { t: 0, key: k };
    zoom.current.t += Math.min(dt, 0.1);
    const img = view.image as { width: number; height: number };
    const ia = img.width / img.height, sa = SCREEN.w / SCREEN.h;
    // cover-fit base crop, then zoom in up to 8 % over ~7 s with a gentle drift
    let rx = 1, ry = 1;
    if (ia > sa) rx = sa / ia; else ry = ia / sa;
    const z = 1 - Math.min(1, zoom.current.t / 7) * 0.08;
    rx *= z; ry *= z;
    const drift = (index % 2 ? 1 : -1) * Math.min(1, zoom.current.t / 7);
    view.repeat.set(rx, ry);
    view.offset.set((1 - rx) / 2 + drift * (1 - rx) * 0.3, (1 - ry) / 2);
  });

  const showPhoto = item?.kind === 'photo' && !!view;
  const showVideo = isVideo && !!vMap;
  return (
    <group onPointerDown={onDown} onPointerUp={onUp}>
      <mesh>
        <planeGeometry args={[SCREEN.w, SCREEN.h]} />
        {showVideo ? <meshBasicMaterial color="#000000" toneMapped={false} /> : <meshBasicMaterial map={showPhoto ? view : card} toneMapped={false} />}
      </mesh>
      {showVideo && (
        <mesh position={[0, 0, 0.003]}>
          <planeGeometry args={[vw, vh]} />
          <meshBasicMaterial key={vMap === vtex ? 'v' : 'p'} map={vMap} toneMapped={false} />
        </mesh>
      )}
      {(showPhoto || (showVideo && !vs.playing)) && captionTex && (
        <mesh position={[0, -SCREEN.h / 2 + (SCREEN.h * 140) / 720 / 2, 0.005]}>
          <planeGeometry args={[SCREEN.w, (SCREEN.h * 140) / 720]} />
          <meshBasicMaterial map={captionTex} transparent toneMapped={false} depthWrite={false} />
        </mesh>
      )}
      {total > 1 && (
        <mesh position={[-SCREEN.w / 2 + (SCREEN.w * (index + 1)) / total / 2, -SCREEN.h / 2 + 0.02, 0.006]}>
          <planeGeometry args={[(SCREEN.w * (index + 1)) / total, 0.025]} />
          <meshBasicMaterial color={PAL.gold} toneMapped={false} />
        </mesh>
      )}
    </group>
  );
}
