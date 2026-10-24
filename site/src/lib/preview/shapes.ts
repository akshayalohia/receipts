// 2D primitives and icons for the raised relief. Units: mm, y up, origin at the given centre.
// Overlapping pieces are fine: everything is one body colour, so unions need no boolean ops.
import { ExtrudeGeometry, Mesh, Path, Shape, type Material } from 'three';

export type Pt = [number, number];

/** Extrude shapes from z=z0 to z0+depth with a tiny edge bevel (outer size unchanged). */
export function extrude(shapes: Shape | Shape[], depth: number, mat: Material, z0 = 0, bevel = true): Mesh {
  const b = bevel ? Math.min(0.12, depth * 0.25) : 0;
  const geo = new ExtrudeGeometry(shapes, {
    depth: Math.max(0.01, depth - b),
    bevelEnabled: b > 0,
    bevelThickness: b,
    bevelSize: b * 0.6,
    bevelOffset: -b * 0.6,
    bevelSegments: 1,
    curveSegments: 10,
  });
  geo.translate(0, 0, z0);
  const m = new Mesh(geo, mat);
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

export function roundedRectPath<T extends Path>(p: T, cx: number, cy: number, w: number, h: number, r: number): T {
  r = Math.max(0.01, Math.min(r, w / 2, h / 2));
  const x = cx - w / 2;
  const y = cy - h / 2;
  p.moveTo(x + r, y);
  p.lineTo(x + w - r, y);
  p.absarc(x + w - r, y + r, r, -Math.PI / 2, 0, false);
  p.lineTo(x + w, y + h - r);
  p.absarc(x + w - r, y + h - r, r, 0, Math.PI / 2, false);
  p.lineTo(x + r, y + h);
  p.absarc(x + r, y + h - r, r, Math.PI / 2, Math.PI, false);
  p.lineTo(x, y + r);
  p.absarc(x + r, y + r, r, Math.PI, Math.PI * 1.5, false);
  return p;
}

export function roundRect(cx: number, cy: number, w: number, h: number, r: number): Shape {
  return roundedRectPath(new Shape(), cx, cy, w, h, r);
}

/** Rounded-rectangle outline of the given stroke width. */
export function roundRectRing(cx: number, cy: number, w: number, h: number, r: number, stroke: number): Shape {
  const s = roundRect(cx, cy, w, h, r);
  s.holes.push(roundedRectPath(new Path(), cx, cy, w - 2 * stroke, h - 2 * stroke, Math.max(0.05, r - stroke)));
  return s;
}

export function disc(cx: number, cy: number, r: number): Shape {
  const s = new Shape();
  s.absarc(cx, cy, r, 0, Math.PI * 2, false);
  return s;
}

export function ring(cx: number, cy: number, r: number, stroke: number): Shape {
  const s = disc(cx, cy, r);
  const h = new Path();
  h.absarc(cx, cy, r - stroke, 0, Math.PI * 2, true);
  s.holes.push(h);
  return s;
}

export function polygon(pts: Pt[]): Shape {
  const s = new Shape();
  pts.forEach(([x, y], i) => (i ? s.lineTo(x, y) : s.moveTo(x, y)));
  s.closePath();
  return s;
}

/** Thick line segment with round caps. */
export function capsule(x1: number, y1: number, x2: number, y2: number, w: number): Shape {
  const r = w / 2;
  const a = Math.atan2(y2 - y1, x2 - x1);
  const s = new Shape();
  s.absarc(x2, y2, r, a - Math.PI / 2, a + Math.PI / 2, false);
  s.absarc(x1, y1, r, a + Math.PI / 2, a + (Math.PI * 3) / 2, false);
  s.closePath();
  return s;
}

/** Polyline as a chain of capsules. */
export function polyline(pts: Pt[], w: number): Shape[] {
  const out: Shape[] = [];
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1]!;
    const c = pts[i]!;
    out.push(capsule(a[0], a[1], c[0], c[1], w));
  }
  return out;
}

export function star(cx: number, cy: number, R: number, inner = 0.45, points = 5, rot = Math.PI / 2): Shape {
  const pts: Pt[] = [];
  for (let i = 0; i < points * 2; i++) {
    const r = i % 2 ? R * inner : R;
    const a = rot + (i * Math.PI) / points;
    pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
  }
  return polygon(pts);
}

// ---------------------------------------------------------------- icons (s = nominal icon size)

/** Heart, outline (X's like icon) or filled. */
export function heart(cx: number, cy: number, s: number, outline = true): Shape {
  const pathAt = <T extends Path>(p: T, k: number): T => {
    // 24-unit heart, y down in the source, mapped to y up around (12, 12).
    const P = (x: number, y: number): Pt => [cx + ((x - 12) * s * k) / 22, cy - ((y - 12.4) * s * k) / 22];
    p.moveTo(...P(12, 21));
    p.bezierCurveTo(...P(12, 21), ...P(2.5, 14.8), ...P(2.5, 8.6));
    p.bezierCurveTo(...P(2.5, 5.4), ...P(5, 3), ...P(8.1, 3));
    p.bezierCurveTo(...P(9.9, 3), ...P(11.3, 4), ...P(12, 5.4));
    p.bezierCurveTo(...P(12.7, 4), ...P(14.1, 3), ...P(15.9, 3));
    p.bezierCurveTo(...P(19, 3), ...P(21.5, 5.4), ...P(21.5, 8.6));
    p.bezierCurveTo(...P(21.5, 14.8), ...P(12, 21), ...P(12, 21));
    return p;
  };
  const sh = pathAt(new Shape(), 1);
  if (outline) {
    // Shift the hole up a touch so the stroke reads evenly at the point and the lobes.
    const hole = new Path();
    const k = 0.66;
    const P = (x: number, y: number): Pt => [cx + ((x - 12) * s * k) / 22, cy + s * 0.04 - ((y - 12.4) * s * k) / 22];
    hole.moveTo(...P(12, 21));
    hole.bezierCurveTo(...P(12, 21), ...P(2.5, 14.8), ...P(2.5, 8.6));
    hole.bezierCurveTo(...P(2.5, 5.4), ...P(5, 3), ...P(8.1, 3));
    hole.bezierCurveTo(...P(9.9, 3), ...P(11.3, 4), ...P(12, 5.4));
    hole.bezierCurveTo(...P(12.7, 4), ...P(14.1, 3), ...P(15.9, 3));
    hole.bezierCurveTo(...P(19, 3), ...P(21.5, 5.4), ...P(21.5, 8.6));
    hole.bezierCurveTo(...P(21.5, 14.8), ...P(12, 21), ...P(12, 21));
    sh.holes.push(hole);
  }
  return sh;
}

/** Speech bubble outline (reply). */
export function replyIcon(cx: number, cy: number, s: number): Shape[] {
  const w = s * 0.95;
  const h = s * 0.72;
  const st = s * 0.12;
  const bubble = roundRectRing(cx, cy + s * 0.06, w, h, h * 0.45, st);
  const by = cy + s * 0.06 - h / 2;
  const tail = polygon([
    [cx - w * 0.22, by + st * 0.5],
    [cx - w * 0.36, by - s * 0.24],
    [cx + w * 0.02, by + st * 0.5],
  ]);
  return [bubble, tail];
}

/** Two looping arrows (repost). */
export function repostIcon(cx: number, cy: number, s: number): Shape[] {
  const w = s * 0.11;
  const X = (u: number): number => cx + u * s;
  const Y = (v: number): number => cy + v * s;
  return [
    ...polyline([[X(-0.3), Y(0.16)], [X(-0.3), Y(-0.28)], [X(0.12), Y(-0.28)]], w),
    polygon([[X(-0.3), Y(0.44)], [X(-0.5), Y(0.17)], [X(-0.1), Y(0.17)]]),
    ...polyline([[X(0.3), Y(-0.16)], [X(0.3), Y(0.28)], [X(-0.12), Y(0.28)]], w),
    polygon([[X(0.3), Y(-0.44)], [X(0.5), Y(-0.17)], [X(0.1), Y(-0.17)]]),
  ];
}

/** Bar chart (views). */
export function viewsIcon(cx: number, cy: number, s: number): Shape[] {
  const w = s * 0.12;
  const b = cy - s * 0.38;
  return [
    capsule(cx - s * 0.3, b, cx - s * 0.3, cy + 0.0 * s, w),
    capsule(cx - s * 0.05, b, cx - s * 0.05, cy + s * 0.38, w),
    capsule(cx + s * 0.2, b, cx + s * 0.2, cy + s * 0.12, w),
  ];
}

/** Arrow out of a tray (share). */
export function shareIcon(cx: number, cy: number, s: number): Shape[] {
  const w = s * 0.11;
  const X = (u: number): number => cx + u * s;
  const Y = (v: number): number => cy + v * s;
  return [
    ...polyline([[X(-0.38), Y(0.0)], [X(-0.38), Y(-0.38)], [X(0.38), Y(-0.38)], [X(0.38), Y(0.0)]], w),
    capsule(X(0), Y(-0.15), X(0), Y(0.36), w),
    ...polyline([[X(-0.2), Y(0.2)], [X(0), Y(0.42)], [X(0.2), Y(0.2)]], w),
  ];
}

/** Scalloped rosette with a check cut through it (verified badge). */
export function verifiedBadge(cx: number, cy: number, s: number): Shape {
  const R = s / 2;
  const pts: Pt[] = [];
  const n = 96;
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2;
    const r = R * (0.9 + 0.1 * Math.cos(8 * a));
    pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
  }
  const sh = polygon(pts);
  const k = R * 0.55;
  const check = new Path();
  const C: Pt[] = [
    [-0.62, 0.02],
    [-0.18, -0.44],
    [0.66, 0.4],
    [0.48, 0.58],
    [-0.18, -0.08],
    [-0.44, 0.2],
  ];
  C.forEach(([x, y], i) => (i ? check.lineTo(cx + x * k, cy + y * k) : check.moveTo(cx + x * k, cy + y * k)));
  check.closePath();
  sh.holes.push(check);
  return sh;
}

/** X wordmark-style cross: one heavy stroke, one light stroke. */
export function xLogo(cx: number, cy: number, s: number): Shape[] {
  const h = s / 2;
  const heavy = polygon([
    [cx - h * 0.95, cy + h],
    [cx - h * 0.35, cy + h],
    [cx + h * 0.95, cy - h],
    [cx + h * 0.35, cy - h],
  ]);
  const light = capsule(cx + h * 0.82, cy + h * 0.94, cx - h * 0.82, cy - h * 0.94, s * 0.09);
  return [heavy, light];
}

/** Rounded rectangle with a play triangle cut out (video platform logo). */
export function playLogo(cx: number, cy: number, w: number): Shape {
  const h = w * 0.7;
  const sh = roundRect(cx, cy, w, h, h * 0.3);
  const t = new Path();
  const k = h * 0.22;
  t.moveTo(cx - k * 0.8, cy + k);
  t.lineTo(cx + k * 1.15, cy);
  t.lineTo(cx - k * 0.8, cy - k);
  t.closePath();
  sh.holes.push(t);
  return sh;
}

/** Simple person glyph (followers). */
export function personIcon(cx: number, cy: number, s: number): Shape[] {
  const head = disc(cx, cy + s * 0.2, s * 0.2);
  const body = new Shape();
  body.absarc(cx, cy - s * 0.42, s * 0.36, 0, Math.PI, false);
  body.closePath();
  return [head, body];
}

/** Down arrow into a tray (downloads). */
export function downloadIcon(cx: number, cy: number, s: number): Shape[] {
  const w = s * 0.13;
  return [
    capsule(cx, cy + s * 0.42, cx, cy - s * 0.1, w),
    ...polyline([[cx - s * 0.25, cy + s * 0.08], [cx, cy - s * 0.16], [cx + s * 0.25, cy + s * 0.08]], w),
    ...polyline([[cx - s * 0.42, cy - s * 0.12], [cx - s * 0.42, cy - s * 0.42], [cx + s * 0.42, cy - s * 0.42], [cx + s * 0.42, cy - s * 0.12]], w),
  ];
}

/** Repository book glyph. */
export function repoIcon(cx: number, cy: number, s: number): Shape[] {
  const w = s * 0.7;
  const h = s;
  return [roundRectRing(cx, cy, w, h, s * 0.1, s * 0.12), capsule(cx - w * 0.2, cy - h * 0.5 + s * 0.06, cx - w * 0.2, cy + h * 0.5 - s * 0.06, s * 0.12)];
}

/** Up-trend pill badge (dashboard delta). */
export function trendBadge(cx: number, cy: number, h: number): Shape[] {
  const w = h * 1.9;
  const k = h * 0.26;
  return [
    roundRectRing(cx, cy, w, h, h / 2, h * 0.13),
    polygon([[cx, cy + k * 1.05], [cx + k * 1.1, cy - k * 0.75], [cx - k * 1.1, cy - k * 0.75]]),
  ];
}

/** One laurel branch curving up the left (side = -1) or right (side = 1) of a centre point. */
export function laurel(cx: number, cy: number, radius: number, side: 1 | -1, leaves = 7): Shape[] {
  const out: Shape[] = [];
  const a0 = -Math.PI * 0.42;
  const a1 = Math.PI * 0.36;
  const stem: Pt[] = [];
  for (let i = 0; i <= 16; i++) {
    const a = a0 + ((a1 - a0) * i) / 16;
    stem.push([cx + side * -radius * Math.cos(a), cy + radius * Math.sin(a)]);
  }
  out.push(...polyline(stem, radius * 0.035));
  const half = radius * 0.105; // leaf half-length
  const thick = radius * 0.05; // leaf half-width
  for (let i = 0; i < leaves; i++) {
    const t = (i + 0.5) / leaves;
    const a = a0 + (a1 - a0) * t;
    const px = cx + side * -radius * Math.cos(a);
    const py = cy + radius * Math.sin(a);
    // Tangent along the stem, pointing up the branch.
    const ta = Math.atan2(radius * Math.cos(a), side * radius * Math.sin(a));
    for (const dir of [1, -1]) {
      const la = ta + dir * 0.62;
      const ex = px + Math.cos(la) * half * 0.92;
      const ey = py + Math.sin(la) * half * 0.92;
      const leaf = new Shape();
      leaf.absellipse(ex, ey, half, thick, 0, Math.PI * 2, false, la);
      out.push(leaf);
    }
  }
  // Tip leaf.
  const tip = new Shape();
  const ta = a1 + 0.12;
  const tx = cx + side * -radius * Math.cos(ta);
  const ty = cy + radius * Math.sin(ta);
  tip.absellipse(tx, ty, half, thick, 0, Math.PI * 2, false, Math.atan2(radius * Math.cos(a1), side * radius * Math.sin(a1)));
  out.push(tip);
  return out;
}
