import { useEffect } from 'react';
import { onUnauthorized } from './api/client';
import { Landing, SignIn } from './pages/Entry';
import { World } from './pages/World';
import { useWorld } from './state/worldStore';
import { Spinner } from './ui/common';

export default function App() {
  const phase = useWorld((s) => s.phase);
  useEffect(() => {
    void useWorld.getState().boot();
    return onUnauthorized(() => { if (useWorld.getState().phase !== 'signin') useWorld.setState({ phase: 'signin' }); });
  }, []);
  if (phase === 'boot') return <div className="loading-screen night"><Spinner text="Opening the museum" /></div>;
  if (phase === 'signin') return <SignIn />;
  if (phase === 'landing') return <Landing />;
  return <World />;
}
