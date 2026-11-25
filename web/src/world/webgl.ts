/** True when this browser can create a WebGL context the museum can run on (PRD M4: the app
 *  switches to the 2D grid otherwise). Cached after the first call; never throws. */
let cached: boolean | null = null;

export function isWebGLAvailable(): boolean {
  if (cached !== null) return cached;
  try {
    if (typeof window === 'undefined' || typeof document === 'undefined') return (cached = false);
    const canvas = document.createElement('canvas');
    const opts: WebGLContextAttributes = { failIfMajorPerformanceCaveat: true };
    const gl = (canvas.getContext('webgl2', opts) || canvas.getContext('webgl', opts)) as WebGLRenderingContext | WebGL2RenderingContext | null;
    if (!gl) return (cached = false);
    // A context that is already lost or has a tiny texture limit cannot hold the museum.
    const ok = !gl.isContextLost() && (gl.getParameter(gl.MAX_TEXTURE_SIZE) as number) >= 2048;
    gl.getExtension('WEBGL_lose_context')?.loseContext();
    return (cached = ok);
  } catch {
    return (cached = false);
  }
}
