import * as THREE from 'three';
import type { Garment, Look } from './rigs';

// Ported from MedSim src/components/world/appearance.ts: recolours the Ready Player Me style
// materials per character. Memo adds `trimTop` (kurta cloth cut at the hip = a shirt) and
// drops MedSim's clinical attachments (stethoscope, theatre attire, dupatta).

const HAIR_SHELL_CUTOFF = [0.13, 0.45, 0.68];
const HAIR_SHELL_TINT = [0.75, 0.95, 1.06];

/** Recolour one mesh by material name. Materials are cloned per character and pushed to
 *  `owned` for disposal. */
export function applyLook(mesh: THREE.Mesh, look: Look, owned: THREE.Material[]) {
  const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
  const next = mats.map((m): THREE.Material => {
    const shell = /^Hair_Shell_(\d)$/.exec(m.name);
    if (shell) {
      const k = Number(shell[1]);
      const src = m as THREE.MeshStandardMaterial;
      const hair = new THREE.MeshStandardMaterial({
        name: m.name,
        map: src.map,
        normalMap: src.normalMap,
        normalScale: new THREE.Vector2(0.8, 0.8),
        color: new THREE.Color(look.hair).multiplyScalar(HAIR_SHELL_TINT[k] ?? 1),
        roughness: look.hairGrey ? 0.7 : 0.78,
        metalness: 0,
        envMapIntensity: 0.35,
        vertexColors: true,
        transparent: false,
        depthWrite: true,
        alphaTest: HAIR_SHELL_CUTOFF[k] ?? 0.5,
        alphaToCoverage: true,
      });
      owned.push(hair);
      return hair;
    }
    const c = (m as THREE.MeshStandardMaterial).clone();
    owned.push(c);
    c.envMapIntensity = 0.9;
    const garment = (g: Garment) => {
      if (!g.map) c.map = null;
      c.color.set(g.color);
      if (g.roughness !== undefined) c.roughness = g.roughness;
      c.needsUpdate = true;
    };
    switch (m.name) {
      case 'Wolf3D_Skin':
      case 'Wolf3D_Body':
      case 'Skin_Extra':
        c.color.set(look.skin);
        c.roughness = Math.max(0.58, c.roughness);
        break;
      case 'Wolf3D_Hair':
      case 'Wolf3D_Beard':
        if (look.hairGrey) {
          c.map = null;
          c.needsUpdate = true;
        }
        c.color.set(look.hair);
        break;
      case 'Wolf3D_Outfit_Top':
      case 'Kurta_Cloth':
      case 'Saree_Cloth':
        garment(look.top);
        break;
      case 'Wolf3D_Outfit_Bottom':
        garment(look.bottom);
        break;
      case 'Saree_Border':
        c.color.set(look.border ?? '#d4a640');
        (c as THREE.MeshStandardMaterial).metalness = 0.35;
        (c as THREE.MeshStandardMaterial).roughness = 0.45;
        break;
      case 'Saree_Blouse':
        c.color.set(look.blouse ?? look.border ?? '#d4a640');
        break;
      case 'Wolf3D_Outfit_Footwear':
        if (look.shoes) c.color.set(look.shoes);
        break;
    }
    return c;
  });
  mesh.material = Array.isArray(mesh.material) ? next : next[0];
  const names = mats.map((m) => m.name);
  if (names.includes('Wolf3D_Headwear')) mesh.visible = false;
  if (names.includes('Wolf3D_Glasses')) mesh.visible = !!look.glasses;
  if (names.includes('Wolf3D_Beard') && look.beard === 'hide') mesh.visible = false;
}

/**
 * Cut the top garment (Kurta_Cloth) at a world height in bind pose: triangles whose centroid
 * lies below `hemY` are dropped. The geometry is cloned so other characters keep theirs.
 * Call with the model detached, in bind pose, after updateMatrixWorld.
 */
export function trimTop(model: THREE.Object3D, hemY: number) {
  model.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh || !mesh.geometry) return;
    const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    const geo = mesh.geometry;
    const groups = geo.groups.length ? geo.groups : [{ start: 0, count: geo.index ? geo.index.count : geo.getAttribute('position').count, materialIndex: 0 }];
    const isTop = (mi: number | undefined) => /^Kurta_Cloth$/.test(mats[mi ?? 0]?.name ?? '');
    if (!groups.some((g) => isTop(g.materialIndex))) return;
    const g2 = geo.clone();
    const pos = g2.getAttribute('position');
    const idx = g2.index ? Array.from(g2.index.array as ArrayLike<number>) : Array.from({ length: pos.count }, (_, i) => i);
    const v = new THREE.Vector3();
    const wy = (i: number) => v.fromBufferAttribute(pos, i).applyMatrix4(mesh.matrixWorld).y;
    const out: number[] = [];
    const newGroups: Array<{ start: number; count: number; materialIndex: number }> = [];
    for (const gr of groups) {
      const start = out.length;
      for (let t = gr.start; t < gr.start + gr.count; t += 3) {
        const a = idx[t], b = idx[t + 1], c = idx[t + 2];
        if (isTop(gr.materialIndex)) {
          const cy = (wy(a) + wy(b) + wy(c)) / 3;
          if (cy < hemY) continue;
        }
        out.push(a, b, c);
      }
      newGroups.push({ start, count: out.length - start, materialIndex: gr.materialIndex ?? 0 });
    }
    g2.setIndex(out);
    g2.clearGroups();
    if (geo.groups.length) newGroups.forEach((g) => g2.addGroup(g.start, g.count, g.materialIndex));
    mesh.geometry = g2;
  });
}

/** Thin placket + collar strip down the shirt front, parented to the chest bone. */
export function addPlacket(model: THREE.Object3D, chest: THREE.Bone | undefined, neck: THREE.Bone | undefined, color: string, hemY: number, owned: THREE.Material[]) {
  if (!chest || !neck) return;
  model.updateMatrixWorld(true);
  // Front surface of the top garment along the centre line.
  const pts: THREE.Vector3[] = [];
  model.traverse((o) => {
    const m = o as THREE.Mesh;
    if (!m.isMesh) return;
    const mats = Array.isArray(m.material) ? m.material : [m.material];
    if (!mats.some((mm) => mm.name === 'Kurta_Cloth')) return;
    const pos = m.geometry.getAttribute('position');
    const v = new THREE.Vector3();
    for (let i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld);
      if (Math.abs(v.x) < 0.02) pts.push(v.clone());
    }
  });
  const N = neck.getWorldPosition(new THREE.Vector3());
  const top = N.y - 0.06;
  const front = (y: number) => {
    let best = -Infinity;
    for (const p of pts) if (Math.abs(p.y - y) < 0.03) best = Math.max(best, p.z);
    return Number.isFinite(best) ? best + 0.004 : null;
  };
  const curve: THREE.Vector3[] = [];
  for (let y = top; y > hemY + 0.02; y -= 0.04) {
    const z = front(y);
    if (z !== null) curve.push(new THREE.Vector3(0, y, z));
  }
  if (curve.length < 3) return;
  const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.7 });
  owned.push(mat);
  const tube = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(curve), 24, 0.006, 4, false), mat);
  const inv = chest.matrixWorld.clone().invert();
  tube.applyMatrix4(inv);
  chest.add(tube);
  // Buttons.
  const btnMat = new THREE.MeshStandardMaterial({ color: '#f4f1e8', roughness: 0.4 });
  owned.push(btnMat);
  const btnGeo = new THREE.SphereGeometry(0.008, 6, 4);
  for (let i = 1; i < curve.length - 1; i += 2) {
    const b = new THREE.Mesh(btnGeo, btnMat);
    b.position.copy(curve[i]).add(new THREE.Vector3(0, 0, 0.004));
    b.applyMatrix4(inv);
    chest.add(b);
  }
}
