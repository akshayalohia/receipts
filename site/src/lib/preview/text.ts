import { Mesh, type Material } from 'three';
import { FontLoader, type Font } from 'three/examples/jsm/loaders/FontLoader.js';
import { TextGeometry } from 'three/examples/jsm/geometries/TextGeometry.js';

export const DEFAULT_FONT_URL = '/fonts3d/space-grotesk-bold.typeface.json';

const fontCache = new Map<string, Promise<Font>>();

export function loadFont(url: string = DEFAULT_FONT_URL): Promise<Font> {
  let p = fontCache.get(url);
  if (!p) {
    p = new FontLoader().loadAsync(url);
    p.catch(() => fontCache.delete(url));
    fontCache.set(url, p);
  }
  return p;
}

interface Glyph {
  ha: number;
  o?: string;
}

function glyphs(font: Font): Record<string, Glyph> {
  return (font.data as unknown as { glyphs: Record<string, Glyph> }).glyphs;
}

const capCache = new WeakMap<Font, number>();

/** Cap height of the font as a fraction of the font size (from the "H" outline). */
export function capRatio(font: Font): number {
  const cached = capCache.get(font);
  if (cached !== undefined) return cached;
  let ratio = 0.7;
  const h = glyphs(font)['H'];
  if (h?.o) {
    const t = h.o.split(' ');
    let maxY = 0;
    for (let i = 0; i < t.length; ) {
      const cmd = t[i++];
      const n = cmd === 'm' || cmd === 'l' ? 2 : cmd === 'q' ? 4 : cmd === 'b' ? 6 : 0;
      for (let k = 0; k < n; k += 2) maxY = Math.max(maxY, Number(t[i + k + 1]));
      i += n;
    }
    if (maxY > 0) ratio = maxY / font.data.resolution;
  }
  capCache.set(font, ratio);
  return ratio;
}

/** Drop characters the font cannot draw (emoji etc.) so they do not render as "?". */
export function sanitize(font: Font, s: string): string {
  const g = glyphs(font);
  let out = '';
  for (const ch of Array.from(s.replace(/\t/g, ' ').replace(/\r\n?/g, '\n'))) {
    if (ch === '\n' || ch === ' ' || g[ch]) out += ch;
  }
  return out;
}

/** Width in mm of a single line at a given cap height. */
export function measure(font: Font, s: string, cap: number): number {
  const g = glyphs(font);
  const scale = cap / capRatio(font) / font.data.resolution;
  let w = 0;
  for (const ch of Array.from(s)) w += (g[ch]?.ha ?? 0) * scale;
  return w;
}

/** Largest cap height <= maxCap at which s fits in maxWidth. */
export function capToFit(font: Font, s: string, maxWidth: number, maxCap: number): number {
  const w1 = measure(font, s, 1);
  if (w1 <= 0) return maxCap;
  return Math.min(maxCap, maxWidth / w1);
}

function wrap(font: Font, text: string, cap: number, maxWidth: number): string[] {
  const lines: string[] = [];
  for (const para of text.split('\n')) {
    const words = para.split(/ +/).filter((w) => w.length > 0);
    if (words.length === 0) {
      lines.push('');
      continue;
    }
    let line = '';
    for (let word of words) {
      const candidate = line ? line + ' ' + word : word;
      if (measure(font, candidate, cap) <= maxWidth) {
        line = candidate;
        continue;
      }
      if (line) lines.push(line);
      line = '';
      // Break words longer than a full line (URLs etc.) by character.
      while (measure(font, word, cap) > maxWidth) {
        const chars = Array.from(word);
        let n = chars.length - 1;
        while (n > 1 && measure(font, chars.slice(0, n).join(''), cap) > maxWidth) n--;
        lines.push(chars.slice(0, n).join(''));
        word = chars.slice(n).join('');
      }
      line = word;
    }
    if (line) lines.push(line);
  }
  while (lines.length > 0 && lines[lines.length - 1] === '') lines.pop();
  return lines;
}

export const LINE_HEIGHT = 1.15; // x font size

export interface Block {
  lines: string[];
  cap: number;
  /** Baseline-to-baseline distance in mm. */
  lineStep: number;
}

/**
 * Wrap and auto-size a paragraph into a box: largest cap height in [minCap, maxCap] (0.25 mm steps)
 * whose wrapped lines fit maxHeight. If it does not fit at minCap, the overflow is cut with an ellipsis.
 */
export function fitBlock(font: Font, text: string, maxWidth: number, maxHeight: number, minCap: number, maxCap: number): Block {
  const ratio = capRatio(font);
  for (let cap = maxCap; cap >= minCap - 1e-6; cap -= 0.25) {
    const step = (cap / ratio) * LINE_HEIGHT;
    const lines = wrap(font, text, cap, maxWidth);
    if (cap + Math.max(0, lines.length - 1) * step <= maxHeight) return { lines, cap, lineStep: step };
  }
  const cap = minCap;
  const step = (cap / ratio) * LINE_HEIGHT;
  const maxLines = Math.max(1, Math.floor((maxHeight - cap) / step) + 1);
  const lines = wrap(font, text, cap, maxWidth).slice(0, maxLines);
  const ell = glyphs(font)['…'] ? '…' : '...';
  let last = lines[lines.length - 1] ?? '';
  while (last.length > 0 && measure(font, last + ell, cap) > maxWidth) last = last.slice(0, -1).trimEnd();
  lines[lines.length - 1] = last + ell;
  return { lines, cap, lineStep: step };
}

export type Align = 'left' | 'center' | 'right';

/** Raised text mesh: baseline at y, extruded from z=0 to z=depth. Returns null for empty strings. */
export function textMesh(
  font: Font,
  s: string,
  cap: number,
  depth: number,
  material: Material,
  x: number,
  y: number,
  align: Align = 'left',
): Mesh | null {
  const str = s.trim();
  if (!str || cap <= 0) return null;
  const size = cap / capRatio(font);
  const geo = new TextGeometry(str, { font, size, depth, curveSegments: 5, bevelEnabled: false });
  const w = measure(font, str, cap);
  const dx = align === 'center' ? -w / 2 : align === 'right' ? -w : 0;
  geo.translate(x + dx, y, 0);
  const mesh = new Mesh(geo, material);
  mesh.castShadow = true;
  return mesh;
}
