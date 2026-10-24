// Avatar as a single-colour relief (lithophane-style height map), like the print would carry it.
import { BufferAttribute, BufferGeometry, Mesh, type Material } from 'three';

export interface HeightMap {
  n: number;
  /** n*n heights in [0, 1], row 0 = top of the image. */
  data: Float32Array;
}

const N = 72;

/** Load an image (CORS) and reduce it to a contrast-stretched luminance grid. */
export async function loadHeightMap(url: string): Promise<HeightMap> {
  const img = new Image();
  img.crossOrigin = 'anonymous';
  img.decoding = 'async';
  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve();
    img.onerror = () => reject(new Error('avatar failed to load'));
    img.src = url;
  });
  const c = document.createElement('canvas');
  c.width = c.height = N;
  const g = c.getContext('2d', { willReadFrequently: true });
  if (!g) throw new Error('no 2d context');
  // Cover-crop to a square.
  const s = Math.min(img.naturalWidth, img.naturalHeight) || 1;
  g.filter = 'blur(0.6px)';
  g.drawImage(img, (img.naturalWidth - s) / 2, (img.naturalHeight - s) / 2, s, s, 0, 0, N, N);
  const px = g.getImageData(0, 0, N, N).data; // throws if the image is tainted (no CORS)
  const data = new Float32Array(N * N);
  let lo = 1;
  let hi = 0;
  for (let i = 0; i < N * N; i++) {
    const a = px[i * 4 + 3]! / 255;
    const l = ((0.2126 * px[i * 4]! + 0.7152 * px[i * 4 + 1]! + 0.0722 * px[i * 4 + 2]!) / 255) * a + (1 - a);
    data[i] = l;
    const x = i % N;
    const y = Math.floor(i / N);
    if ((x - N / 2 + 0.5) ** 2 + (y - N / 2 + 0.5) ** 2 < (N / 2) ** 2) {
      lo = Math.min(lo, l);
      hi = Math.max(hi, l);
    }
  }
  const span = Math.max(0.05, hi - lo);
  for (let i = 0; i < data.length; i++) data[i] = Math.min(1, Math.max(0, (data[i]! - lo) / span));
  return { n: N, data };
}

/**
 * Circular height-field centred at (cx, cy): z from zMin (dark) to zMax (light), clipped to radius r.
 */
export function heightDisc(hm: HeightMap, cx: number, cy: number, r: number, zMin: number, zMax: number, mat: Material): Mesh {
  const n = hm.n;
  const pos = new Float32Array(n * n * 3);
  const step = (2 * r) / (n - 1);
  for (let j = 0; j < n; j++) {
    for (let i = 0; i < n; i++) {
      const k = j * n + i;
      pos[k * 3] = cx - r + i * step;
      pos[k * 3 + 1] = cy + r - j * step;
      pos[k * 3 + 2] = zMin + (zMax - zMin) * hm.data[k]!;
    }
  }
  const idx: number[] = [];
  const inside = (i: number, j: number): boolean => (i * step - r) ** 2 + (j * step - r) ** 2 <= r * r;
  for (let j = 0; j < n - 1; j++) {
    for (let i = 0; i < n - 1; i++) {
      const a = j * n + i;
      const b = a + 1;
      const c = a + n;
      const d = c + 1;
      if (inside(i, j) && inside(i + 1, j) && inside(i, j + 1)) idx.push(a, c, b);
      if (inside(i + 1, j) && inside(i, j + 1) && inside(i + 1, j + 1)) idx.push(b, c, d);
    }
  }
  const geo = new BufferGeometry();
  geo.setAttribute('position', new BufferAttribute(pos, 3));
  geo.setIndex(idx);
  geo.computeVertexNormals();
  const m = new Mesh(geo, mat);
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}
