// Product geometry per docs/CONTRACT.md "Print geometry". All units are millimetres.
import { BoxGeometry, ExtrudeGeometry, Group, Mesh, PlaneGeometry, Shape, type Material, type Object3D } from 'three';
import type { Font } from 'three/examples/jsm/loaders/FontLoader.js';
import { capToFit, fitBlock, sanitize, textMesh, measure } from './text';
import type { PreviewProduct } from './types';

export const DIMS = {
  tweet: { w: 120, h: 80, t: 6, r: 3, raise: 0.8 },
  milestone: { w: 140, h: 100, t: 8, r: 3, raise: 1 },
  fullcolour: { w: 150, h: 100, t: 4, baseW: 150, baseD: 30, baseH: 15, raise: 0.8 },
} as const;

const STAND_ANGLE_DEG = 75; // from horizontal, per contract
// TODO(geometry): stand base size and slot depth are not in CONTRACT; keep in sync with the backend generator.
const STAND = { d: 34, h: 10, r: 4, slot: 3 };
const BEVEL = 0.5;

export interface Mats {
  body: Material;
  text: Material;
  front: Material;
}

export type AnchorId = 'front' | 'back' | 'baseFront';

export interface Frame {
  root: Group;
  anchors: Partial<Record<AnchorId, Group>>;
  /** Mesh carrying the full-colour texture (fullcolour only). */
  imagePlane?: Mesh;
}

export interface Norm {
  product: PreviewProduct;
  author_name: string;
  handle: string;
  text: string;
  likes: string;
  date: string;
  number: string;
  label: string;
  name: string;
  team: string;
  subline: string;
  image_url: string;
  founding: string;
}

export interface PartSpec {
  id: string;
  anchor: AnchorId;
  key: string;
  build(font: Font, mat: Material): Object3D | null;
}

function roundedRect(w: number, h: number, r: number): Shape {
  const s = new Shape();
  const x = -w / 2;
  const y = -h / 2;
  s.moveTo(x + r, y);
  s.lineTo(x + w - r, y);
  s.absarc(x + w - r, y + r, r, -Math.PI / 2, 0, false);
  s.lineTo(x + w, y + h - r);
  s.absarc(x + w - r, y + h - r, r, 0, Math.PI / 2, false);
  s.lineTo(x + r, y + h);
  s.absarc(x + r, y + h - r, r, Math.PI / 2, Math.PI, false);
  s.lineTo(x, y + r);
  s.absarc(x + r, y + r, r, Math.PI, Math.PI * 1.5, false);
  return s;
}

/** Rounded slab centred on the origin, front face at z = t/2, small bevel for realism (outer size unchanged). */
function slab(w: number, h: number, t: number, r: number, mat: Material): Mesh {
  const b = BEVEL;
  const geo = new ExtrudeGeometry(roundedRect(w - 2 * b, h - 2 * b, Math.max(0.1, r - b)), {
    depth: t - 2 * b,
    bevelEnabled: true,
    bevelThickness: b,
    bevelSize: b,
    bevelSegments: 2,
    curveSegments: 8,
  });
  geo.translate(0, 0, -(t / 2 - b));
  const m = new Mesh(geo, mat);
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

/** Rounded block lying on the ground (y from 0 to h), centred in x/z. */
function block(w: number, d: number, h: number, r: number, mat: Material): Mesh {
  const b = BEVEL;
  const geo = new ExtrudeGeometry(roundedRect(w - 2 * b, d - 2 * b, Math.max(0.1, r - b)), {
    depth: h - 2 * b,
    bevelEnabled: true,
    bevelThickness: b,
    bevelSize: b,
    bevelSegments: 2,
    curveSegments: 8,
  });
  geo.translate(0, 0, b);
  geo.rotateX(-Math.PI / 2);
  const m = new Mesh(geo, mat);
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

/** Slab on an angled stand; returns the root plus front/back anchors in slab-face coordinates. */
function standingSlab(w: number, h: number, t: number, r: number, mats: Mats): { root: Group; slabGroup: Group; front: Group; back: Group } {
  const root = new Group();
  const lean = ((90 - STAND_ANGLE_DEG) * Math.PI) / 180;
  const base = block(w, STAND.d, STAND.h, STAND.r, mats.body);
  // Shift the base back so it sits under the leaning slab's centre of mass.
  const zShift = -(h / 2) * Math.sin(lean) * 0.6;
  base.position.z = zShift;
  root.add(base);

  const pivot = new Group();
  pivot.position.set(0, STAND.h - STAND.slot, zShift + (h / 2) * Math.sin(lean) * 0.6);
  pivot.rotation.x = -lean;
  root.add(pivot);

  const slabGroup = new Group();
  slabGroup.position.y = h / 2;
  pivot.add(slabGroup);
  slabGroup.add(slab(w, h, t, r, mats.body));

  const front = new Group();
  front.position.z = t / 2;
  slabGroup.add(front);
  const back = new Group();
  back.position.z = -t / 2;
  back.rotation.y = Math.PI;
  slabGroup.add(back);
  return { root, slabGroup, front, back };
}

export function buildFrame(product: PreviewProduct, mats: Mats): Frame {
  if (product === 'fullcolour') {
    const d = DIMS.fullcolour;
    const root = new Group();
    const base = block(d.baseW, d.baseD, d.baseH, 3, mats.body);
    root.add(base);
    const slot = 4;
    const panel = new Mesh(new BoxGeometry(d.w, d.h, d.t), mats.body);
    panel.position.set(0, d.baseH - slot + d.h / 2, 0);
    panel.castShadow = true;
    panel.receiveShadow = true;
    root.add(panel);
    const imagePlane = new Mesh(new PlaneGeometry(d.w - 0.2, d.h - 0.2), mats.front);
    imagePlane.position.set(0, panel.position.y, d.t / 2 + 0.02);
    imagePlane.receiveShadow = true;
    root.add(imagePlane);
    const baseFront = new Group();
    baseFront.position.set(0, d.baseH / 2, d.baseD / 2);
    root.add(baseFront);
    return { root, anchors: { baseFront }, imagePlane };
  }

  const d = product === 'tweet' ? DIMS.tweet : DIMS.milestone;
  const s = standingSlab(d.w, d.h, d.t, d.r, mats);
  if (product !== 'tweet') {
    // Thin raised border, 2 mm in from the edge.
    const inset = 2;
    const width = 1.2;
    const ring = roundedRect(d.w - 2 * inset, d.h - 2 * inset, 2);
    ring.holes.push(roundedRect(d.w - 2 * (inset + width), d.h - 2 * (inset + width), 1.2));
    const border = new Mesh(new ExtrudeGeometry(ring, { depth: d.raise, bevelEnabled: false, curveSegments: 8 }), mats.text);
    border.castShadow = true;
    s.front.add(border);
  }
  return { root: s.root, anchors: { front: s.front, back: s.back } };
}

function group(...objs: (Object3D | null)[]): Object3D | null {
  const g = new Group();
  for (const o of objs) if (o) g.add(o);
  return g.children.length ? g : null;
}

/** Heart outline (for the likes row) as a raised shape; the font has no U+2665. */
function heart(cap: number, depth: number, mat: Material, x: number, y: number): Mesh {
  // Classic two-lobe heart in a 22 x 19 box, flipped so the tip points down.
  const sx = (cap * 1.1) / 22;
  const sy = (cap * 1.0) / 19;
  const P = (px: number, py: number): [number, number] => [x + (px + 6) * sx, y + (19 - py) * sy - cap * 0.05];
  const s = new Shape();
  s.moveTo(...P(5, 5));
  s.bezierCurveTo(...P(5, 5), ...P(4, 0), ...P(0, 0));
  s.bezierCurveTo(...P(-6, 0), ...P(-6, 7), ...P(-6, 7));
  s.bezierCurveTo(...P(-6, 11), ...P(-3, 15.4), ...P(5, 19));
  s.bezierCurveTo(...P(12, 15.4), ...P(16, 11), ...P(16, 7));
  s.bezierCurveTo(...P(16, 7), ...P(16, 0), ...P(10, 0));
  s.bezierCurveTo(...P(7, 0), ...P(5, 5), ...P(5, 5));
  const m = new Mesh(new ExtrudeGeometry(s, { depth, bevelEnabled: false, curveSegments: 8 }), mat);
  m.castShadow = true;
  return m;
}

function foundingLabel(f: string): string {
  const v = f.replace(/^#/, '').trim();
  if (!v) return '';
  return '#' + (/^\d+$/.test(v) ? v.padStart(3, '0') : v);
}

function handleLabel(h: string): string {
  const v = h.replace(/^@+/, '').trim();
  return v ? '@' + v : '';
}

export function partSpecs(p: Norm): PartSpec[] {
  const specs: PartSpec[] = [];

  if (p.product === 'tweet') {
    const d = DIMS.tweet;
    const m = 6; // margin
    const innerW = d.w - 2 * m;
    const top = d.h / 2 - m;
    const headerCap = 5;
    const headerBase = top - headerCap;
    const footerCap = 3.5;
    const footerBase = -d.h / 2 + m;

    specs.push({
      id: 'header',
      anchor: 'front',
      key: JSON.stringify([p.author_name, p.handle]),
      build(font, mat) {
        const name = sanitize(font, p.author_name).replace(/\n/g, ' ');
        const handle = sanitize(font, handleLabel(p.handle));
        const handleCap = 3.6;
        const gap = 3;
        const total = measure(font, name, headerCap) + (handle ? gap + measure(font, handle, handleCap) : 0);
        const k = total > innerW ? innerW / total : 1;
        const nameMesh = textMesh(font, name, headerCap * k, d.raise, mat, -innerW / 2, headerBase);
        const nx = -innerW / 2 + (name ? measure(font, name, headerCap * k) + gap * k : 0);
        return group(nameMesh, textMesh(font, handle, handleCap * k, d.raise, mat, nx, headerBase));
      },
    });

    specs.push({
      id: 'body',
      anchor: 'front',
      key: JSON.stringify([p.text]),
      build(font, mat) {
        const text = sanitize(font, p.text.slice(0, 280)).trim();
        if (!text) return null;
        const boxTop = headerBase - 3.5;
        const boxBottom = footerBase + footerCap + 3;
        const b = fitBlock(font, text, innerW, boxTop - boxBottom, 4, 7);
        const g = new Group();
        b.lines.forEach((line, i) => {
          const mesh = textMesh(font, line, b.cap, d.raise, mat, -innerW / 2, boxTop - b.cap - i * b.lineStep);
          if (mesh) g.add(mesh);
        });
        return g.children.length ? g : null;
      },
    });

    specs.push({
      id: 'footer',
      anchor: 'front',
      key: JSON.stringify([p.likes, p.date]),
      build(font, mat) {
        const likes = sanitize(font, p.likes);
        const date = sanitize(font, p.date);
        const parts: (Object3D | null)[] = [];
        if (likes) {
          parts.push(heart(footerCap, d.raise, mat, -innerW / 2, footerBase));
          parts.push(textMesh(font, likes, footerCap, d.raise, mat, -innerW / 2 + footerCap * 1.1 + 2, footerBase));
        }
        parts.push(textMesh(font, date, footerCap, d.raise, mat, innerW / 2, footerBase, 'right'));
        return group(...parts);
      },
    });

    specs.push({
      id: 'founding',
      anchor: 'back',
      key: JSON.stringify([p.founding]),
      build(font, mat) {
        return textMesh(font, sanitize(font, foundingLabel(p.founding)), 4, d.raise, mat, 0, -d.h / 2 + 10, 'center');
      },
    });
    return specs;
  }

  if (p.product === 'fullcolour') {
    const d = DIMS.fullcolour;
    specs.push({
      id: 'basename',
      anchor: 'baseFront',
      key: JSON.stringify([p.name, p.author_name, p.handle]),
      build(font, mat) {
        const name = sanitize(font, p.name || p.author_name || handleLabel(p.handle)).replace(/\n/g, ' ');
        const cap = Math.min(6, capToFit(font, name, d.baseW - 16, 6));
        return textMesh(font, name, cap, d.raise, mat, 0, -cap / 2, 'center');
      },
    });
    return specs;
  }

  // milestone and team share the plaque layout.
  const d = DIMS.milestone;
  const innerW = d.w - 2 * 10;
  const bottomCap = 4;
  const bottomBase = -d.h / 2 + 8;
  const big = p.product === 'team' ? p.team : p.number.slice(0, 10);
  const sub = p.product === 'team' ? p.subline : p.label;

  specs.push({
    id: 'headline',
    anchor: 'front',
    key: JSON.stringify([p.product, big, sub]),
    build(font, mat) {
      const bigS = sanitize(font, big).replace(/\n/g, ' ').trim();
      const subS = sanitize(font, sub).replace(/\n/g, ' ').trim();
      const bigCap = bigS ? capToFit(font, bigS, innerW, 30) : 0;
      const subCap = subS ? capToFit(font, subS, innerW, 7) : 0;
      const gap = bigS && subS ? 7 : 0;
      const blockH = bigCap + gap + subCap;
      // Centre the block between the top border and the bottom line.
      const regionTop = d.h / 2 - 8;
      const regionBottom = bottomBase + bottomCap + 6;
      const blockTop = (regionTop + regionBottom) / 2 + blockH / 2;
      return group(
        textMesh(font, bigS, bigCap, d.raise, mat, 0, blockTop - bigCap, 'center'),
        textMesh(font, subS, subCap, d.raise, mat, 0, blockTop - bigCap - gap - subCap, 'center'),
      );
    },
  });

  specs.push({
    id: 'bottom',
    anchor: 'front',
    key: JSON.stringify([p.name, p.handle, p.date]),
    build(font, mat) {
      const who = sanitize(font, [p.name, handleLabel(p.handle)].filter(Boolean).join('  ')).replace(/\n/g, ' ');
      const date = sanitize(font, p.date);
      const dateW = date ? measure(font, date, bottomCap) + 6 : 0;
      const whoCap = who ? Math.min(bottomCap, capToFit(font, who, innerW - dateW, bottomCap)) : 0;
      return group(
        textMesh(font, who, whoCap, d.raise, mat, -innerW / 2, bottomBase),
        textMesh(font, date, bottomCap, d.raise, mat, innerW / 2, bottomBase, 'right'),
      );
    },
  });
  // TODO(geometry): CONTRACT has no back-side founding number for plaques; only the Tweet Trophy shows it.
  return specs;
}
