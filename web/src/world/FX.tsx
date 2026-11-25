import { useEffect } from 'react';
import { useThree } from '@react-three/fiber';
import { Bloom, EffectComposer, ToneMapping, Vignette } from '@react-three/postprocessing';
import { ToneMappingMode } from 'postprocessing';
import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

/** Image-based lighting from three's procedural RoomEnvironment (no HDR download), warmed and
 *  kept low so the downlights and lamps carry the museum mood. */
export function MuseumEnvironment({ intensity = 0.35 }: { intensity?: number }) {
  const { gl, scene } = useThree();
  useEffect(() => {
    const pmrem = new THREE.PMREMGenerator(gl);
    const env = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environment = env;
    scene.environmentIntensity = intensity;
    return () => {
      scene.environment = null;
      env.dispose();
      pmrem.dispose();
    };
  }, [gl, scene, intensity]);
  return null;
}

export type FxQuality = 'high' | 'low';

/** Bloom on emissive signs / lamps only, a soft vignette, ACES filmic last. On 'low' (phones,
 *  slow GPUs) the composer is skipped entirely and the renderer tone-maps directly. */
export function PostFX({ quality }: { quality: FxQuality }) {
  const { gl } = useThree();
  useEffect(() => {
    gl.toneMapping = quality === 'high' ? THREE.NoToneMapping : THREE.ACESFilmicToneMapping;
    gl.toneMappingExposure = 1.05;
  }, [gl, quality]);
  if (quality === 'low') return null;
  return (
    <EffectComposer multisampling={4} enableNormalPass={false}>
      <Bloom mipmapBlur luminanceThreshold={0.85} luminanceSmoothing={0.2} intensity={0.35} radius={0.65} />
      <Vignette offset={0.3} darkness={0.5} />
      <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
    </EffectComposer>
  );
}
