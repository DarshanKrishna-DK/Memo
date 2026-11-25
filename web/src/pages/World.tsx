import { Component, Suspense, lazy, useEffect, type ComponentType, type ReactNode } from 'react';
import { use2d, useWorld } from '../state/worldStore';
import { Spinner } from '../ui/common';
import { Hud } from './Hud';
import { Mode2D } from './Mode2D';
import { AtticPanel, DirectoryPanel, LiftPanel, OpsPanel, SettingsPanel } from './Panels';
import { ReceptionPanel } from './Reception';
import { CleanupPanel, ExhibitModal, ReelsPanel } from './RoomUi';
import { ScreenView, TheaterPanel, useShowcaseEngine } from './Theater';
import { useLiveStream } from './stream';
import { usePresence } from './presence';

// The 3D museum is owned by the web-3d agent. glob() keeps the build green while the file is absent.
const canvasMods = import.meta.glob('../world/MuseumCanvas.tsx');
const webglMods = import.meta.glob('../world/webgl.ts');
const CANVAS_KEY = '../world/MuseumCanvas.tsx';
const HAS_CANVAS = CANVAS_KEY in canvasMods;
const MuseumCanvas = lazy(() => (HAS_CANVAS ? (canvasMods[CANVAS_KEY]() as Promise<{ default: ComponentType }>) : Promise.reject(new Error('3D museum not built yet'))));

class Boundary extends Component<{ children: ReactNode; onFail: () => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() { this.props.onFail(); }
  render() { return this.state.failed ? null : this.props.children; }
}

function Panels() {
  const panel = useWorld((s) => s.panel);
  switch (panel) {
    case 'reception': return <ReceptionPanel />;
    case 'lift': return <LiftPanel />;
    case 'directory': return <DirectoryPanel />;
    case 'attic': return <AtticPanel />;
    case 'settings': return <SettingsPanel />;
    case 'reels': return <ReelsPanel />;
    case 'cleanup': return <CleanupPanel />;
    case 'ops': return <OpsPanel />;
    case 'exhibit': return <ExhibitModal />;
    default: return null;
  }
}

function Cards() {
  const cards = useWorld((s) => s.cards);
  const dismiss = useWorld((s) => s.dismissCard);
  return (
    <div className="cards" role="status" aria-live="polite">
      {cards.map((c) => (
        <div key={c.id} className={`card card--${c.kind}`}>
          <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}><span className="card-title">{c.title}</span><button className="btn btn-sm btn-ghost" onClick={() => dismiss(c.id)} aria-label="Dismiss">X</button></div>
          <p>{c.text}</p>
        </div>
      ))}
    </div>
  );
}

export function World() {
  const is2d = use2d();
  const setWebgl = useWorld((s) => s.setWebgl);
  const seat = useWorld((s) => s.seat);
  useLiveStream();
  useShowcaseEngine();
  usePresence();

  useEffect(() => {
    (async () => {
      if (!HAS_CANVAS) { setWebgl(false); return; }
      const k = '../world/webgl.ts';
      if (k in webglMods) {
        const m = (await webglMods[k]()) as { isWebGLAvailable?: () => boolean };
        setWebgl(m.isWebGLAvailable ? m.isWebGLAvailable() : true);
      }
    })().catch(() => setWebgl(false));
  }, [setWebgl]);

  return (
    <>
      {is2d ? <Mode2D /> : (
        <div className="stage">
          <Boundary onFail={() => setWebgl(false)}>
            <Suspense fallback={<div className="loading-screen"><Spinner text="Building the museum" /></div>}><MuseumCanvas /></Suspense>
          </Boundary>
        </div>
      )}
      {is2d && <ScreenView />}
      <Hud />
      {seat && <TheaterHost />}
      <Panels />
      <Cards />
    </>
  );
}

function TheaterHost() {
  const screenMode = useWorld((s) => s.screenMode);
  return screenMode ? null : <TheaterPanel />;
}
