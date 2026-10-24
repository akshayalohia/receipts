// Product geometry per docs/CONTRACT.md "Print geometry" (outer sizes, raise heights). All units are millimetres.
// Each preset has its own designed face: the Tweet Trophy is laid out like the real post card, the Milestone
// Plaque picks a platform look (YouTube, revenue dashboard, GitHub stars, followers, downloads, classic laurel)
// from its label, and the Team Pack is a classic award plaque.
import { ExtrudeGeometry, Group, Mesh, PlaneGeometry, BoxGeometry, type Material, type Object3D, type Shape } from 'three';
import type { Font } from 'three/examples/jsm/loaders/FontLoader.js';
import { capToFit, fitBlock, measure, sanitize, textMesh } from './text';
import {
  capsule,
  disc,
  downloadIcon,
  extrude,
  heart,
  laurel,
  personIcon,
  playLogo,
  polygon,
  polyline,
  replyIcon,
  repoIcon,
  repostIcon,
  ring,
  roundRect,
  roundRectRing,
  shareIcon,
  star,
  trendBadge,
  verifiedBadge,
  viewsIcon,
  xLogo,
  type Pt,
} from './shapes';
import { heightDisc, type HeightMap } from './relief';
import type { PreviewProduct } from './types';

export const DIMS = {
  tweet: { w: 120, h: 80, t: 6, r: 3, raise: 0.8 },
  milestone: { w: 140, h: 100, t: 8, r: 3, raise: 1 },
  fullcolour: { w: 150, h: 100, t: 4, baseW: 150, baseD: 30, baseH: 15, raise: 0.8 },
} as const;

const STAND_ANGLE_DEG = 75; // from horizontal, per contract
// TODO(geometry): stand base size and slot depth are not in CONTRACT; keep in sync with the backend generator.
const STAND = { d: 34, h: 10, r: 4, slot: 3 };
const BEVEL = 0.6;

export interface Mats {
  body: Material;
  text: Material;
  front: Material;
}

export type AnchorId = 'front' | 'back' | 'baseFront';

export interface Frame {
  root: Group;
  anchors: Partial<Record<AnchorId, Group>>;
  /** Extra front faces that mirror every 'front' part (the Team Pack shows a few plaques of the set). */
  copies?: Group[];
  /** Mesh carrying the full-colour texture (fullcolour only). */
  imagePlane?: Mesh;
}

export interface Norm {
  product: PreviewProduct;
  author_name: string;
  handle: string;
  text: string;
  likes: string;
  replies: string;
  reposts: string;
  verified: boolean;
  date: string;
  number: string;
  label: string;
  name: string;
  team: string;
  subline: string;
  image_url: string;
  avatar_url: string;
  founding: string;
}

export interface Assets {
  avatar: HeightMap | null;
  /** Changes whenever `avatar` changes (part cache key). */
  avatarKey: string;
}

export interface PartSpec {
  id: string;
  anchor: AnchorId;
  key: string;
  build(font: Font, mat: Material, assets: Assets): Object3D | null;
}

/** Rounded slab centred on the origin, front face at z = t/2, bevelled edges (outer size unchanged). */
function slab(w: number, h: number, t: number, r: number, mat: Material): Mesh {
  const b = BEVEL;
  const geo = new ExtrudeGeometry(roundRect(0, 0, w - 2 * b, h - 2 * b, Math.max(0.1, r - b)), {
    depth: t - 2 * b,
    bevelEnabled: true,
    bevelThickness: b,
    bevelSize: b,
    bevelSegments: 3,
    curveSegments: 10,
  });
  geo.translate(0, 0, -(t / 2 - b));
  const m = new Mesh(geo, mat);
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

/** Rounded block lying on the ground (y from y0 to y0+h), centred in x/z. */
function block(w: number, d: number, h: number, r: number, mat: Material, y0 = 0): Mesh {
  const b = Math.min(BEVEL, h / 4);
  const geo = new ExtrudeGeometry(roundRect(0, 0, w - 2 * b, d - 2 * b, Math.max(0.1, r - b)), {
    depth: h - 2 * b,
    bevelEnabled: true,
    bevelThickness: b,
    bevelSize: b,
    bevelSegments: 3,
    curveSegments: 10,
  });
  geo.translate(0, 0, b + y0);
  geo.rotateX(-Math.PI / 2);
  // rotateX(-90deg) maps +z to +y, so the block spans y0..y0+h.
  const m = new Mesh(geo, mat);
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

/** Slab on a two-tier angled stand; returns the root plus front/back anchors in slab-face coordinates. */
function standingSlab(w: number, h: number, t: number, r: number, mats: Mats): { root: Group; front: Group; back: Group } {
  const root = new Group();
  const lean = ((90 - STAND_ANGLE_DEG) * Math.PI) / 180;
  const zShift = -(h / 2) * Math.sin(lean) * 0.6;
  const plinthH = 4;
  const plinth = block(w + 6, STAND.d + 6, plinthH, STAND.r + 2, mats.body);
  plinth.position.z = zShift;
  root.add(plinth);
  const top = block(w, STAND.d, STAND.h - plinthH, STAND.r, mats.body, plinthH);
  top.position.z = zShift;
  root.add(top);

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
  return { root, front, back };
}

function border(w: number, h: number, inset: number, width: number, r: number, depth: number, mat: Material): Mesh {
  return extrude(roundRectRing(0, 0, w - 2 * inset, h - 2 * inset, r, width), depth, mat);
}

export function buildFrame(product: PreviewProduct, mats: Mats): Frame {
  if (product === 'fullcolour') {
    const d = DIMS.fullcolour;
    const root = new Group();
    root.add(block(d.baseW, d.baseD, d.baseH, 3, mats.body));
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

  if (product === 'tweet') {
    const d = DIMS.tweet;
    const s = standingSlab(d.w, d.h, d.t, d.r, mats);
    return { root: s.root, anchors: { front: s.front, back: s.back } };
  }

  const d = DIMS.milestone;
  const plaque = (): ReturnType<typeof standingSlab> => {
    const s = standingSlab(d.w, d.h, d.t, d.r, mats);
    // Contract border: 2 mm in from the edge.
    s.front.add(border(d.w, d.h, 2, 1.5, 2.2, d.raise, mats.text));
    if (product === 'team') s.front.add(border(d.w, d.h, 5.2, 0.6, 1.2, d.raise * 0.6, mats.text));
    return s;
  };
  const main = plaque();
  if (product !== 'team') return { root: main.root, anchors: { front: main.front, back: main.back } };

  // Team Pack: the front plaque plus two more of the set staggered behind it.
  const root = new Group();
  root.add(main.root);
  const copies: Group[] = [];
  for (const [x, z] of [
    [26, -46],
    [52, -92],
  ] as const) {
    const c = plaque();
    c.root.position.set(x, 0, z);
    root.add(c.root);
    copies.push(c.front);
  }
  return { root, anchors: { front: main.front, back: main.back }, copies };
}

function group(...objs: (Object3D | null | undefined)[]): Object3D | null {
  const g = new Group();
  for (const o of objs) if (o) g.add(o);
  return g.children.length ? g : null;
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

/** X-style compact counts: 1234 -> 1.2K, 1218913 -> 1.2M. Non-numeric input (e.g. "12K") passes through. */
export function compactCount(s: string): string {
  const v = s.trim();
  if (!/^[\d,.\s]+$/.test(v)) return v;
  const n = Number(v.replace(/[,\s]/g, ''));
  if (!Number.isFinite(n)) return v;
  const f = (x: number): string => (x >= 100 ? Math.floor(x).toString() : (Math.floor(x * 10) / 10).toString());
  if (n >= 1e9) return f(n / 1e9) + 'B';
  if (n >= 1e6) return f(n / 1e6) + 'M';
  if (n >= 1e4) return f(n / 1e3) + 'K';
  return Math.round(n).toLocaleString('en-US');
}

function oneLine(font: Font, s: string): string {
  return sanitize(font, s).replace(/\n+/g, ' ').trim();
}

// ---------------------------------------------------------------- Tweet Trophy

function tweetSpecs(p: Norm): PartSpec[] {
  const d = DIMS.tweet;
  const R = d.raise;
  const m = 6;
  const left = -d.w / 2 + m;
  const right = d.w / 2 - m;
  const innerW = right - left;
  const av = 5.6; // avatar radius
  const avX = left + av;
  const avY = d.h / 2 - m - av;
  const nameX = left + 2 * av + 3;
  const nameCap = 3.5;
  const nameBase = avY + 0.9;
  const handleCap = 2.8;
  const handleBase = avY - 0.9 - handleCap;
  const actionY = -d.h / 2 + m + 1.6; // icon centre line
  const iconS = 4.2;
  const countCap = 2.5;
  const dividerY = actionY + iconS / 2 + 3.2;
  const dateCap = 2.5;
  const dateBase = dividerY + 2.6;
  const hasDate = !!p.date;
  const specs: PartSpec[] = [];

  specs.push({
    id: 'avatar',
    anchor: 'front',
    key: JSON.stringify([p.avatar_url, p.author_name || p.handle]),
    build(font, mat, assets) {
      if (assets.avatar && p.avatar_url) {
        return group(
          extrude(disc(avX, avY, av), 0.25, mat, 0, false),
          heightDisc(assets.avatar, avX, avY, av - 0.35, 0.25, R, mat),
          extrude(ring(avX, avY, av, 0.5), R, mat),
        );
      }
      // No photo: a raised disc with the initial standing proud of it.
      const initial = Array.from(oneLine(font, (p.author_name || p.handle.replace(/^@/, '')).toUpperCase()))[0] ?? '';
      const cap = 4.6;
      return group(
        extrude(disc(avX, avY, av), R * 0.5, mat),
        textMesh(font, initial, cap, R * 0.5, mat, avX, avY - cap / 2, 'center', R * 0.5),
      );
    },
  });

  specs.push({
    id: 'header',
    anchor: 'front',
    key: JSON.stringify([p.author_name, p.handle, p.verified]),
    build(font, mat) {
      const logoS = 4.6;
      const maxW = right - logoS - 3 - nameX;
      let name = oneLine(font, p.author_name || p.handle.replace(/^@/, ''));
      const badge = p.verified ? 3.6 : 0;
      const badgeGap = badge ? 1.1 : 0;
      let nameCapFit = name ? Math.min(nameCap, capToFit(font, name, maxW - badge - badgeGap, nameCap)) : 0;
      if (nameCapFit < 2.4 && name) {
        while (name.length > 1 && measure(font, name + '…', 2.4) > maxW - badge - badgeGap) name = name.slice(0, -1);
        name = name.trimEnd() + '…';
        nameCapFit = 2.4;
      }
      const nameW = name ? measure(font, name, nameCapFit) : 0;
      const handle = oneLine(font, handleLabel(p.handle));
      const hCap = handle ? Math.min(handleCap, capToFit(font, handle, maxW, handleCap)) : 0;
      return group(
        textMesh(font, name, nameCapFit, R, mat, nameX, nameBase),
        badge ? extrude(verifiedBadge(nameX + nameW + badgeGap + badge / 2, nameBase + nameCapFit / 2, badge), R, mat) : null,
        textMesh(font, handle, hCap, R * 0.75, mat, nameX, handleBase),
        extrude(xLogo(right - logoS / 2, avY + 1.2, logoS), R, mat),
      );
    },
  });

  specs.push({
    id: 'body',
    anchor: 'front',
    key: JSON.stringify([p.text, hasDate]),
    build(font, mat) {
      const text = sanitize(font, p.text.slice(0, 280)).trim();
      if (!text) return null;
      const boxTop = avY - av - 3.2;
      const boxBottom = (hasDate ? dateBase + dateCap : dividerY) + 2.6;
      // Leave room for descenders on the last line (fitBlock budgets cap height only).
      // Short tweets get big type (up to 9 mm caps), matching the print file (backend/receipts/tweet_card.py).
      const b = fitBlock(font, text, innerW, boxTop - boxBottom - 2, 2.6, 9);
      // X keeps generous leading; stretch a little when there is room.
      let free = boxTop - boxBottom - 2 - (b.cap + Math.max(0, b.lines.length - 1) * b.lineStep);
      const extra = b.lines.length > 1 ? Math.min(free / (b.lines.length - 1), b.cap * 0.35) : 0;
      const step = b.lineStep + extra;
      free -= extra * Math.max(0, b.lines.length - 1);
      const top = boxTop - Math.max(0, free) * 0.4;
      const g = new Group();
      b.lines.forEach((line, i) => {
        const mesh = textMesh(font, line, b.cap, R, mat, left, top - b.cap - i * step);
        if (mesh) g.add(mesh);
      });
      return g.children.length ? g : null;
    },
  });

  specs.push({
    id: 'footer',
    anchor: 'front',
    key: JSON.stringify([p.likes, p.replies, p.reposts, p.date]),
    build(font, mat) {
      const parts: (Object3D | null)[] = [];
      if (hasDate) parts.push(textMesh(font, oneLine(font, p.date), Math.min(dateCap, capToFit(font, oneLine(font, p.date), innerW, dateCap)), R * 0.75, mat, left, dateBase));
      parts.push(extrude(capsule(left, dividerY, right, dividerY, 0.45), R * 0.45, mat, 0, false));
      const slot = innerW / 4.4;
      const icons: [(x: number, y: number, s: number) => Shape | Shape[], string][] = [
        [replyIcon, p.replies],
        [repostIcon, p.reposts],
        [(x, y, s) => heart(x, y, s * 1.05, true), p.likes],
        [viewsIcon, ''],
      ];
      icons.forEach(([icon, count], i) => {
        const x = left + iconS / 2 + i * slot;
        parts.push(extrude(icon(x, actionY, iconS), R, mat));
        const c = oneLine(font, compactCount(count));
        if (c) parts.push(textMesh(font, c, countCap, R * 0.85, mat, x + iconS / 2 + 1.3, actionY - countCap / 2));
      });
      parts.push(extrude(shareIcon(right - iconS / 2, actionY, iconS), R, mat));
      return group(...parts);
    },
  });

  specs.push({
    id: 'founding',
    anchor: 'back',
    key: JSON.stringify([p.founding]),
    build(font, mat) {
      return textMesh(font, sanitize(font, foundingLabel(p.founding)), 4, R, mat, 0, -d.h / 2 + 10, 'center');
    },
  });
  return specs;
}

// ---------------------------------------------------------------- Milestone Plaque

export type MilestoneTheme = 'youtube' | 'revenue' | 'github' | 'followers' | 'downloads' | 'classic';

/** Pick the platform look from what the number counts. */
export function milestoneTheme(label: string, number: string): MilestoneTheme {
  const l = label.toLowerCase();
  if (/youtube|subscri|\bsubs\b/.test(l)) return 'youtube';
  if (/github|\bstars?\b|stargazer/.test(l)) return 'github';
  if (/\bmrr\b|\barr\b|revenue|sales|stripe|profit|gmv|income|paid|\bmoney\b|raised|funding/.test(l) || /^[$€£¥]/.test(number.trim())) return 'revenue';
  if (/follower|twitter|\bon x\b|^x\b|instagram|tiktok|linkedin|threads|bluesky/.test(l)) return 'followers';
  if (/download|install|\bnpm\b|\bpypi\b|app store/.test(l)) return 'downloads';
  return 'classic';
}

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

/** Deterministic up-and-to-the-right series in [0, 1], ending at 1. */
function growth(seed: string, n: number): number[] {
  let h = hash(seed || 'receipts') || 1;
  const rnd = (): number => {
    h ^= h << 13;
    h ^= h >>> 17;
    h ^= h << 5;
    return ((h >>> 0) % 1000) / 1000;
  };
  const out: number[] = [];
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1);
    const base = 0.08 + 0.82 * Math.pow(t, 1.6);
    out.push(i === n - 1 ? 1 : Math.min(0.95, Math.max(0.02, base + (rnd() - 0.5) * 0.14)));
  }
  return out;
}

function milestoneSpecs(p: Norm): PartSpec[] {
  const d = DIMS.milestone;
  const R = d.raise;
  const left = -d.w / 2 + 10;
  const right = d.w / 2 - 10;
  const innerW = right - left;
  const top = d.h / 2 - 9;
  const bottomBase = -d.h / 2 + 8.5;
  const bottomCap = 3.8;
  const theme = milestoneTheme(p.label, p.number);
  const big = p.number.slice(0, 10);
  const who = [p.name, p.name ? '' : handleLabel(p.handle)].filter(Boolean).join('');
  const specs: PartSpec[] = [];

  specs.push({
    id: 'headline',
    anchor: 'front',
    key: JSON.stringify([theme, big, p.label, theme === 'github' ? p.name : '']),
    build(font, mat) {
      const num = oneLine(font, big);
      const label = oneLine(font, p.label);
      const T = (s: string, cap: number, x: number, y: number, align: 'left' | 'center' | 'right' = 'center', depth = R) =>
        textMesh(font, s, cap, depth, mat, x, y, align);

      if (theme === 'revenue') {
        const lbl = label.toUpperCase();
        const lblCap = lbl ? Math.min(4.2, capToFit(font, lbl, innerW - 30, 4.2)) : 0;
        const lblBase = top - 4.2;
        const lblW = lbl ? measure(font, lbl, lblCap) : 0;
        const numCap = num ? capToFit(font, num, innerW, 19) : 0;
        const numBase = lblBase - 5.5 - numCap;
        // Chart fills the space between the number and the bottom line.
        const cTop = numBase - 5;
        const cBot = bottomBase + bottomCap + 5;
        const vals = growth(big + label, 16);
        const pts: Pt[] = vals.map((v, i) => [left + (innerW * i) / (vals.length - 1), cBot + (cTop - cBot) * v]);
        const area = polygon([[left, cBot], ...pts, [right, cBot]]);
        const last = pts[pts.length - 1]!;
        return group(
          T(lbl, lblCap, left, lblBase, 'left'),
          lbl ? extrude(trendBadge(left + lblW + 2.5 + 5.2, lblBase + lblCap / 2, 5.4), R, mat) : null,
          T(num, numCap, left, numBase, 'left'),
          extrude(area, R * 0.3, mat, 0, false),
          extrude(polyline(pts, 1.1), R, mat),
          extrude(disc(last[0], last[1], 1.7), R, mat),
          extrude(capsule(left, cBot, right, cBot, 0.5), R * 0.5, mat, 0, false),
        );
      }

      if (theme === 'github') {
        const repo = oneLine(font, p.name);
        const repoCap = repo ? Math.min(3.8, capToFit(font, repo, innerW - 8, 3.8)) : 0;
        const starR = 10.5;
        const gap = 4;
        const numCap = num ? capToFit(font, num, innerW - 2 * starR - gap, 22) : 0;
        const numW = num ? measure(font, num, numCap) : 0;
        const rowW = 2 * starR + (num ? gap + numW : 0);
        const rowY = 6;
        const x0 = -rowW / 2;
        const lblCap = label ? Math.min(5.5, capToFit(font, label, innerW, 5.5)) : 0;
        return group(
          repo ? extrude(repoIcon(left + 2.2, top - 1.6, 5.2), R, mat) : null,
          T(repo, repoCap, left + 6.5, top - 3.5, 'left'),
          extrude(star(x0 + starR, rowY, starR, 0.46), R, mat),
          T(num, numCap, x0 + 2 * starR + gap, rowY - numCap / 2, 'left'),
          T(label, lblCap, 0, rowY - Math.max(starR, numCap / 2) - 6 - lblCap),
        );
      }

      if (theme === 'classic') {
        const wreathR = 33;
        const cy = 3;
        const numCap = num ? capToFit(font, num, 2 * (wreathR - 11), 22) : 0;
        const lblCap = label ? Math.min(4.6, capToFit(font, label, 2 * (wreathR - 9), 4.6)) : 0;
        const gap = num && label ? 4.5 : 0;
        const blockH = numCap + gap + lblCap;
        const bt = cy + blockH / 2;
        return group(
          extrude([...laurel(0, cy, wreathR, -1), ...laurel(0, cy, wreathR, 1)], R, mat),
          extrude(star(0, top - 1, 3.2), R, mat),
          T(num, numCap, 0, bt - numCap),
          T(label, lblCap, 0, bt - numCap - gap - lblCap),
        );
      }

      // Icon-on-top layouts: YouTube, followers, downloads.
      const iconY = top - 6.5;
      let icon: Shape | Shape[];
      if (theme === 'youtube') icon = playLogo(0, iconY, 19);
      else if (theme === 'followers') icon = /twitter|\bx\b/.test(p.label.toLowerCase()) ? xLogo(0, iconY, 11) : personIcon(0, iconY, 13);
      else icon = downloadIcon(0, iconY, 13);
      const numCap = num ? capToFit(font, num, innerW, 24) : 0;
      const lblCap = label ? Math.min(6, capToFit(font, label, innerW, 6)) : 0;
      const gap = num && label ? 5 : 0;
      const regionTop = iconY - 9;
      const regionBottom = bottomBase + bottomCap + 6;
      const blockH = numCap + gap + lblCap;
      const bt = (regionTop + regionBottom) / 2 + blockH / 2;
      return group(extrude(icon, R, mat), T(num, numCap, 0, bt - numCap), T(label, lblCap, 0, bt - numCap - gap - lblCap));
    },
  });

  specs.push({
    id: 'bottom',
    anchor: 'front',
    key: JSON.stringify([theme, p.name, p.handle, p.date, theme === 'github' ? big : '']),
    build(font, mat) {
      const date = oneLine(font, p.date);
      if (theme === 'github') {
        // GitHub's star button: [ ★ Star | 12.3k ]
        const h = 8;
        const cy = bottomBase + bottomCap / 2;
        const cap = 3.1;
        const sw = measure(font, 'Star', cap);
        const w1 = 4.6 + 4.2 + sw + 3;
        const count = oneLine(font, compactCount(big.replace(/[^\d.,kKmM]/g, '')) || big).toLowerCase();
        const cw = count ? measure(font, count, cap) + 6 : 0;
        return group(
          extrude(roundRectRing(left + w1 / 2, cy, w1, h, 1.6, 0.7), R, mat),
          extrude(star(left + 4.6, cy, 2.3, 0.45), R, mat),
          textMesh(font, 'Star', cap, R, mat, left + 8.4, cy - cap / 2),
          count ? extrude(roundRectRing(left + w1 - 0.7 + cw / 2, cy, cw, h, 1.6, 0.7), R, mat) : null,
          count ? textMesh(font, count, cap, R, mat, left + w1 - 0.7 + cw / 2, cy - cap / 2, 'center') : null,
          textMesh(font, date, Math.min(bottomCap, capToFit(font, date, innerW - w1 - cw - 6, bottomCap)), R, mat, right, bottomBase, 'right'),
        );
      }
      const whoS = oneLine(font, who);
      if (theme === 'revenue') {
        const dateW = date ? measure(font, date, bottomCap) + 6 : 0;
        const whoCap = whoS ? Math.min(bottomCap, capToFit(font, whoS, innerW - dateW, bottomCap)) : 0;
        return group(
          textMesh(font, whoS, whoCap, R, mat, left, bottomBase),
          textMesh(font, date, bottomCap, R, mat, right, bottomBase, 'right'),
        );
      }
      // Centred "name · date" line.
      const line = [whoS, date].filter(Boolean).join('  ·  ');
      const cap = line ? Math.min(bottomCap, capToFit(font, line, innerW, bottomCap)) : 0;
      return textMesh(font, line, cap, R, mat, 0, bottomBase, 'center');
    },
  });
  return specs;
}

// ---------------------------------------------------------------- Team Pack

function teamSpecs(p: Norm): PartSpec[] {
  const d = DIMS.milestone;
  const R = d.raise;
  const innerW = d.w - 2 * 14;
  return [
    {
      id: 'team',
      anchor: 'front',
      key: JSON.stringify([p.team, p.subline]),
      build(font, mat) {
        const team = oneLine(font, p.team).toUpperCase();
        const sub = oneLine(font, p.subline);
        const block = team ? fitBlock(font, team, innerW, 34, 6, 17) : null;
        const lines = block?.lines ?? [];
        const teamH = block ? block.cap + (lines.length - 1) * block.lineStep : 0;
        const subCap = sub ? Math.min(5, capToFit(font, sub, innerW, 5)) : 0;
        const ruleGap = 6;
        const totalH = teamH + (sub ? ruleGap * 2 + subCap : ruleGap);
        const starsY = d.h / 2 - 15;
        const regionTop = starsY - 6;
        const regionBottom = -d.h / 2 + 12;
        const t0 = (regionTop + regionBottom) / 2 + totalH / 2;
        const parts: (Object3D | null)[] = [
          extrude([star(0, starsY, 3.4), star(-9, starsY - 0.6, 2.4), star(9, starsY - 0.6, 2.4)], R, mat),
        ];
        lines.forEach((line, i) => parts.push(textMesh(font, line, block!.cap, R, mat, 0, t0 - block!.cap - i * block!.lineStep, 'center')));
        const ruleY = t0 - teamH - ruleGap;
        const k = 2.2;
        parts.push(
          extrude(
            [
              capsule(-30, ruleY, -k - 2, ruleY, 0.6),
              capsule(k + 2, ruleY, 30, ruleY, 0.6),
              polygon([[0, ruleY + k], [k, ruleY], [0, ruleY - k], [-k, ruleY]]),
            ],
            R,
            mat,
          ),
        );
        if (sub) parts.push(textMesh(font, sub, subCap, R, mat, 0, ruleY - ruleGap - subCap, 'center'));
        return group(...parts);
      },
    },
  ];
}

export function partSpecs(p: Norm): PartSpec[] {
  if (p.product === 'tweet') return tweetSpecs(p);
  if (p.product === 'team') return teamSpecs(p);
  if (p.product === 'fullcolour') {
    const d = DIMS.fullcolour;
    return [
      {
        id: 'basename',
        anchor: 'baseFront',
        key: JSON.stringify([p.name, p.author_name, p.handle]),
        build(font, mat) {
          const name = oneLine(font, p.name || p.author_name || handleLabel(p.handle));
          const cap = Math.min(6, capToFit(font, name, d.baseW - 16, 6));
          return textMesh(font, name, cap, d.raise, mat, 0, -cap / 2, 'center');
        },
      },
    ];
  }
  return milestoneSpecs(p);
}

