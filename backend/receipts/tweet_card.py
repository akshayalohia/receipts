"""Tweet Trophy print file: a one-piece card + two-tier stand laid out like the real X post.

Mirrors the on-site preview (site/src/lib/preview/layout.ts, tweetSpecs + standingSlab): same font
(Space Grotesk Bold, from the preview's typeface JSON), same card size, same element positions, with
small print-driven adjustments (minimum cap heights, emboldened strokes, thicker icon lines).
Units: mm. Built with manifold3d (robust 2D/3D booleans), exported as one watertight STL.

Depth layering on the single-colour card face (z = card face):
  +1.0  name, tweet text, icons, X mark, verified badge, avatar rim
  +0.8  @handle, timestamp, counts (secondary)
  -0.6  divider groove; founding number engraved 0.6 into the back.
The card stands at 75° in a slot of the stand (printed as one body, base on the bed).
"""
from __future__ import annotations

import io
import json
import math
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import trimesh
from manifold3d import CrossSection, FillRule, JoinType, Manifold, OpType

FONT_JSON = Path(__file__).parent / "fonts" / "space-grotesk-bold.typeface.json"

CARD = {"w": 120.0, "h": 80.0, "t": 6.0, "r": 3.0, "chamfer": 0.8}
STAND = {"d": 34.0, "h": 10.0, "r": 4.0, "slot": 3.0, "plinth_h": 4.0, "lip": 3.0, "chamfer": 0.8}
STAND_ANGLE_DEG = 75.0  # card angle from horizontal (contract)
RAISE = 1.0  # primary relief
RAISE_2 = 0.8  # secondary relief (handle, timestamp, counts)
GROOVE_W, GROOVE_D = 0.8, 0.6
ENGRAVE = 0.6
MIN_STROKE = 0.65  # stems thinner than this are emboldened up to it (Slant: strokes >= 0.6 mm)
TRACKING_EM = 0.03  # extra letter spacing so raised glyphs stay apart on FDM
LINE_HEIGHT = 1.15  # x font size, as the preview
EMBED = 0.02  # raised parts start this far below the face so unions fuse


class TweetCardError(Exception):
    pass


# ---------------------------------------------------------------- 2D helpers

def _cs(contours, rule=FillRule.Positive) -> CrossSection:
    cs = [np.asarray(c, dtype=float) for c in contours if len(c) >= 3]
    return CrossSection(cs, rule) if cs else CrossSection()


def _union(items) -> CrossSection:
    items = [c for c in items if c is not None and not c.is_empty()]
    if not items:
        return CrossSection()
    return CrossSection.batch_boolean(items, OpType.Add) if len(items) > 1 else items[0]


def circle(cx: float, cy: float, r: float, n: int = 64) -> CrossSection:
    return CrossSection.circle(r, n).translate((cx, cy))


def round_rect(cx: float, cy: float, w: float, h: float, r: float, n: int = 48) -> CrossSection:
    r = max(0.01, min(r, w / 2 - 1e-3, h / 2 - 1e-3))
    return CrossSection.square((w - 2 * r, h - 2 * r), True).offset(r, JoinType.Round, 2.0, n).translate((cx, cy))


def round_rect_ring(cx, cy, w, h, r, stroke) -> CrossSection:
    return round_rect(cx, cy, w, h, r) - round_rect(cx, cy, w - 2 * stroke, h - 2 * stroke, max(0.05, r - stroke))


def ring(cx, cy, r, stroke) -> CrossSection:
    return circle(cx, cy, r, 96) - circle(cx, cy, r - stroke, 96)


def polygon(pts) -> CrossSection:
    pts = np.asarray(pts, dtype=float)
    a = 0.5 * np.sum(pts[:, 0] * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1) * pts[:, 1])
    return _cs([pts if a > 0 else pts[::-1]])


def capsule(x1, y1, x2, y2, w) -> CrossSection:
    r = w / 2
    return CrossSection.batch_hull([circle(x1, y1, r, 24), circle(x2, y2, r, 24)])


def polyline(pts, w) -> CrossSection:
    return _union([capsule(*pts[i - 1], *pts[i], w) for i in range(1, len(pts))])


def _bezier3(p0, p1, p2, p3, n=10):
    t = np.linspace(0, 1, n + 1)[1:, None]
    p0, p1, p2, p3 = map(np.asarray, (p0, p1, p2, p3))
    return ((1 - t) ** 3) * p0 + 3 * ((1 - t) ** 2) * t * p1 + 3 * (1 - t) * t * t * p2 + t ** 3 * p3


# ---------------------------------------------------------------- icons (s = nominal icon size)

def _stroke(s: float) -> float:
    return max(0.75, s * 0.13)


def heart(cx, cy, s, outline=True) -> CrossSection:
    def path(k, dy=0.0):
        P = lambda x, y: (cx + (x - 12) * s * k / 22, cy + dy - (y - 12.4) * s * k / 22)  # noqa: E731
        segs = [((12, 21), (12, 21), (2.5, 14.8), (2.5, 8.6)), ((2.5, 8.6), (2.5, 5.4), (5, 3), (8.1, 3)),
                ((8.1, 3), (9.9, 3), (11.3, 4), (12, 5.4)), ((12, 5.4), (12.7, 4), (14.1, 3), (15.9, 3)),
                ((15.9, 3), (19, 3), (21.5, 5.4), (21.5, 8.6)), ((21.5, 8.6), (21.5, 14.8), (12, 21), (12, 21))]
        pts = [P(12, 21)]
        for a, b, c, d in segs:
            pts.extend(map(tuple, _bezier3(P(*a), P(*b), P(*c), P(*d), 14)))
        return polygon(pts[:-1])

    sh = path(1.0)
    if outline:
        sh = sh - path(0.6, s * 0.035)
    return sh


def reply_icon(cx, cy, s) -> CrossSection:
    w, h, st = s * 0.95, s * 0.72, _stroke(s)
    bubble = round_rect_ring(cx, cy + s * 0.06, w, h, h * 0.45, st)
    by = cy + s * 0.06 - h / 2
    tail = polygon([(cx - w * 0.24, by + st * 0.6), (cx - w * 0.38, by - s * 0.24), (cx + w * 0.04, by + st * 0.6)])
    return bubble + tail


def repost_icon(cx, cy, s) -> CrossSection:
    w = _stroke(s)
    X = lambda u: cx + u * s  # noqa: E731
    Y = lambda v: cy + v * s  # noqa: E731
    return _union([
        polyline([(X(-0.3), Y(0.16)), (X(-0.3), Y(-0.28)), (X(0.12), Y(-0.28))], w),
        polygon([(X(-0.3), Y(0.46)), (X(-0.52), Y(0.15)), (X(-0.08), Y(0.15))]),
        polyline([(X(0.3), Y(-0.16)), (X(0.3), Y(0.28)), (X(-0.12), Y(0.28))], w),
        polygon([(X(0.3), Y(-0.46)), (X(0.52), Y(-0.15)), (X(0.08), Y(-0.15))]),
    ])


def views_icon(cx, cy, s) -> CrossSection:
    w = _stroke(s)
    b = cy - s * 0.36
    return _union([capsule(cx - s * 0.3, b, cx - s * 0.3, cy, w), capsule(cx - s * 0.03, b, cx - s * 0.03, cy + s * 0.38, w),
                   capsule(cx + s * 0.24, b, cx + s * 0.24, cy + s * 0.12, w)])


def share_icon(cx, cy, s) -> CrossSection:
    w = _stroke(s)
    X = lambda u: cx + u * s  # noqa: E731
    Y = lambda v: cy + v * s  # noqa: E731
    return _union([
        polyline([(X(-0.38), Y(0.0)), (X(-0.38), Y(-0.38)), (X(0.38), Y(-0.38)), (X(0.38), Y(0.0))], w),
        capsule(X(0), Y(-0.15), X(0), Y(0.36), w),
        polyline([(X(-0.21), Y(0.19)), (X(0), Y(0.42)), (X(0.21), Y(0.19))], w),
    ])


def verified_badge(cx, cy, s) -> CrossSection:
    R = s / 2
    a = np.linspace(0, 2 * np.pi, 96, endpoint=False)
    r = R * (0.9 + 0.1 * np.cos(8 * a))
    sh = polygon(np.c_[cx + r * np.cos(a), cy + r * np.sin(a)])
    k = R * 0.55
    check = polyline([(cx - 0.55 * k, cy + 0.02 * k), (cx - 0.15 * k, cy - 0.4 * k), (cx + 0.6 * k, cy + 0.42 * k)],
                     max(0.6, s * 0.15))
    return sh - check


def x_logo(cx, cy, s) -> CrossSection:
    h = s / 2
    heavy = polygon([(cx - h * 0.95, cy + h), (cx - h * 0.35, cy + h), (cx + h * 0.95, cy - h), (cx + h * 0.35, cy - h)])
    light = capsule(cx + h * 0.82, cy + h * 0.94, cx - h * 0.82, cy - h * 0.94, max(0.7, s * 0.12))
    return heavy + light


# ---------------------------------------------------------------- font (the preview's typeface JSON)

class Font:
    def __init__(self, path: Path = FONT_JSON):
        d = json.loads(Path(path).read_text())
        self.res = float(d["resolution"])
        self.glyphs: dict[str, dict] = d["glyphs"]
        hy = [float(v) for v in self.glyphs["H"]["o"].split() if _isnum(v)][1::2]
        self.cap_ratio = max(hy) / self.res
        lg = self.glyphs["l"]
        self.stem = (lg["x_max"] - lg["x_min"]) / self.res  # em
        self._contours: dict[str, list[np.ndarray]] = {}

    def has(self, ch: str) -> bool:
        return ch in self.glyphs

    def sanitize(self, s: str) -> str:
        s = (s or "").replace("\t", " ").replace("\r\n", "\n").replace("\r", "\n")
        return "".join(c for c in s if c in ("\n", " ") or c in self.glyphs)

    def grow(self, cap: float) -> float:
        """Outline offset that brings the stem width up to MIN_STROKE at this cap height."""
        g = (MIN_STROKE - self.stem * cap / self.cap_ratio) / 2
        return min(max(g, 0.0), 0.15)

    def tracking(self, cap: float) -> float:
        """Extra advance per glyph (mm): restores the gap emboldening eats, plus a little air."""
        return 2 * self.grow(cap) + TRACKING_EM * cap / self.cap_ratio

    def measure(self, s: str, cap: float) -> float:
        k = cap / self.cap_ratio / self.res
        n = sum(1 for c in s if c in self.glyphs)
        return sum(float(self.glyphs.get(c, {}).get("ha", 0)) for c in s) * k + max(0, n - 1) * self.tracking(cap)

    def cap_to_fit(self, s: str, max_w: float, max_cap: float) -> float:
        w1 = self.measure(s, 1.0)
        return max_cap if w1 <= 0 else min(max_cap, max_w / w1)

    def contours(self, ch: str) -> list[np.ndarray]:
        """Glyph contours in font units, oriented CCW = solid / CW = hole (by nesting depth)."""
        if ch in self._contours:
            return self._contours[ch]
        t = (self.glyphs.get(ch, {}).get("o") or "").split()
        out, cur, i = [], None, 0
        while i < len(t):
            c = t[i]
            i += 1
            if c == "m":
                if cur:
                    out.append(cur)
                cur = [(float(t[i]), float(t[i + 1]))]
                i += 2
            elif c == "l":
                cur.append((float(t[i]), float(t[i + 1])))
                i += 2
            elif c == "q":
                x, y, qx, qy = map(float, t[i:i + 4])
                i += 4
                p0 = np.array(cur[-1])
                for tt in np.linspace(0, 1, 7)[1:]:
                    cur.append(tuple((1 - tt) ** 2 * p0 + 2 * (1 - tt) * tt * np.array([qx, qy]) + tt * tt * np.array([x, y])))
            elif c == "b":
                x, y, c1x, c1y, c2x, c2y = map(float, t[i:i + 6])
                i += 6
                cur.extend(map(tuple, _bezier3(cur[-1], (c1x, c1y), (c2x, c2y), (x, y), 8)))
        if cur:
            out.append(cur)
        polys = []
        for c in out:
            p = np.array(c, dtype=float)
            keep = np.r_[True, np.any(np.abs(np.diff(p, axis=0)) > 1e-9, axis=1)]
            p = p[keep]
            if len(p) > 1 and np.allclose(p[0], p[-1]):
                p = p[:-1]
            if len(p) >= 3:
                polys.append(p)
        res = []
        for j, p in enumerate(polys):
            depth = sum(1 for k, q in enumerate(polys) if k != j and _inside(p[0], q))
            a = _area(p)
            solid = depth % 2 == 0
            res.append(p if (a > 0) == solid else p[::-1])
        self._contours[ch] = res
        return res

    def line(self, s: str, cap: float, x: float, y: float, align: str = "left") -> CrossSection:
        """One line of text, baseline at y, emboldened so strokes are >= MIN_STROKE."""
        s = s.strip()
        if not s or cap <= 0:
            return CrossSection()
        size = cap / self.cap_ratio
        k = size / self.res
        w = self.measure(s, cap)
        x0 = x - (w / 2 if align == "center" else w if align == "right" else 0.0)
        contours, pen, track = [], 0.0, self.tracking(cap)
        for ch in s:
            g = self.glyphs.get(ch)
            if not g:
                continue
            for p in self.contours(ch):
                contours.append(np.c_[x0 + pen + p[:, 0] * k, y + p[:, 1] * k])
            pen += float(g["ha"]) * k + track
        cs = _cs(contours, FillRule.Positive)
        grow = self.grow(cap)
        if grow > 0.005:
            cs = cs.offset(grow, JoinType.Miter, 2.0)
        return cs

    def wrap(self, text: str, cap: float, max_w: float) -> list[str]:
        lines: list[str] = []
        for para in text.split("\n"):
            words = [w for w in para.split(" ") if w]
            if not words:
                lines.append("")
                continue
            line = ""
            for word in words:
                cand = f"{line} {word}" if line else word
                if self.measure(cand, cap) <= max_w:
                    line = cand
                    continue
                if line:
                    lines.append(line)
                line = ""
                while self.measure(word, cap) > max_w:
                    n = len(word) - 1
                    while n > 1 and self.measure(word[:n], cap) > max_w:
                        n -= 1
                    lines.append(word[:n])
                    word = word[n:]
                line = word
            if line:
                lines.append(line)
        while lines and not lines[-1]:
            lines.pop()
        return lines

    def fit_block(self, text: str, max_w: float, max_h: float, min_cap: float, max_cap: float):
        """Largest cap in [min_cap, max_cap] (0.25 steps) whose wrapped lines fit; else cut with an ellipsis."""
        cap = max_cap
        while cap >= min_cap - 1e-6:
            step = cap / self.cap_ratio * LINE_HEIGHT
            lines = self.wrap(text, cap, max_w)
            if cap + max(0, len(lines) - 1) * step <= max_h:
                return lines, cap, step
            cap -= 0.25
        cap = min_cap
        step = cap / self.cap_ratio * LINE_HEIGHT
        n = max(1, int((max_h - cap) // step) + 1)
        lines = self.wrap(text, cap, max_w)[:n]
        ell = "…" if self.has("…") else "..."
        last = lines[-1] if lines else ""
        while last and self.measure(last + ell, cap) > max_w:
            last = last[:-1].rstrip()
        lines[-1:] = [last + ell]
        return lines, cap, step


def _isnum(v: str) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False


def _area(p: np.ndarray) -> float:
    return 0.5 * float(np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]))


def _inside(pt, poly: np.ndarray) -> bool:
    x, y = pt
    xs, ys = poly[:, 0], poly[:, 1]
    xj, yj = np.roll(xs, 1), np.roll(ys, 1)
    cross = ((ys > y) != (yj > y)) & (x < (xj - xs) * (y - ys) / np.where(yj == ys, 1e-12, yj - ys) + xs)
    return bool(np.count_nonzero(cross) % 2)


@lru_cache(maxsize=1)
def font() -> Font:
    return Font()


# ---------------------------------------------------------------- meta -> fields (same rules as the preview)

def compact_count(s: str) -> str:
    """X-style compact counts: 1234 -> 1,234, 12345 -> 12.3K, 1218913 -> 1.2M; non-numeric passes through."""
    v = (s or "").strip()
    if not v or not re.fullmatch(r"[\d,.\s]+", v):
        return v
    try:
        n = float(re.sub(r"[,\s]", "", v))
    except ValueError:
        return v

    def f(x: float) -> str:
        return str(math.floor(x)) if x >= 100 else f"{math.floor(x * 10) / 10:g}"

    if n >= 1e9:
        return f(n / 1e9) + "B"
    if n >= 1e6:
        return f(n / 1e6) + "M"
    if n >= 1e4:
        return f(n / 1e3) + "K"
    return f"{round(n):,}"


def x_date(meta: dict) -> str:
    """'9:41 AM · Oct 24, 2026' from created_at (UTC) if present, else the order's date string as given."""
    iso = (meta.get("created_at") or "").strip()
    if iso:
        try:
            d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            if d.tzinfo:
                d = d.astimezone(timezone.utc)
            return f"{d.strftime('%I:%M %p').lstrip('0')} · {d.strftime('%b')} {d.day}, {d.year}"
        except ValueError:
            pass
    date = (meta.get("date") or "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", date)
    if m:
        d = datetime(int(m[1]), int(m[2]), int(m[3]))
        return f"{d.strftime('%b')} {d.day}, {d.year}"
    return date


def handle_from(meta: dict) -> str:
    h = (meta.get("handle") or "").strip()
    if not h and (meta.get("label") or "").strip().startswith("@"):
        h = meta["label"].strip()
    if not h:
        mt = re.search(r"(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status", meta.get("tweet_url") or "")
        h = mt.group(1) if mt else ""
    h = h.lstrip("@").strip()
    return "@" + h if h else ""


def card_text(t: str) -> str:
    t = re.sub(r"https?://t\.co/\S+", "", t or "")
    t = re.sub(r"(\s*(https?://)?(pic\.twitter\.com|pic\.x\.com)/\S+)+\s*$", "", t, flags=re.I)
    return t.strip()


def _truthy(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "y")


# ---------------------------------------------------------------- avatar height map

def height_map(image_bytes: bytes, n: int = 40) -> np.ndarray | None:
    """Square, contrast-stretched luminance grid in [0, 1] (row 0 = top), or None if unreadable."""
    try:
        from PIL import Image, ImageFilter, ImageOps

        img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes)))
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img).convert("L")
        img = ImageOps.fit(img, (n, n), method=Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.5))
    except Exception:
        return None
    a = np.asarray(img, dtype=float) / 255.0
    yy, xx = np.mgrid[0:n, 0:n]
    inside = (xx - n / 2 + 0.5) ** 2 + (yy - n / 2 + 0.5) ** 2 < (n / 2) ** 2
    lo, hi = np.percentile(a[inside], 2), np.percentile(a[inside], 98)
    return np.clip((a - lo) / max(0.05, hi - lo), 0, 1)


def _height_disc(hm: np.ndarray, cx: float, cy: float, r: float, z_min: float, z_max: float) -> Manifold:
    """Solid from z=0 up to a height field (z_min dark .. z_max light), clipped to a disc of radius r."""
    n = hm.shape[0]
    half = r + 0.6  # box larger than the disc so its side walls are clipped away
    box = Manifold.cube((2 * half, 2 * half, 1.0)).translate((-half, -half, 0)).refine(n + 4)

    def warp(v: np.ndarray) -> np.ndarray:
        v = np.array(v, dtype=float)
        u = np.clip((v[:, 0] + r) / (2 * r) * (n - 1), 0, n - 1)
        w = np.clip((r - v[:, 1]) / (2 * r) * (n - 1), 0, n - 1)
        i0, j0 = np.floor(u).astype(int), np.floor(w).astype(int)
        i1, j1 = np.minimum(i0 + 1, n - 1), np.minimum(j0 + 1, n - 1)
        fu, fw = u - i0, w - j0
        h = (hm[j0, i0] * (1 - fu) * (1 - fw) + hm[j0, i1] * fu * (1 - fw) + hm[j1, i0] * (1 - fu) * fw
             + hm[j1, i1] * fu * fw)
        v[:, 2] = v[:, 2] * (z_min + (z_max - z_min) * h)  # scale each column: no folds, flat bottom
        return v

    solid = box.warp_batch(warp) ^ Manifold.cylinder(z_max + 1, r, r, 96)
    return solid.translate((cx, cy, 0))


# ---------------------------------------------------------------- 3D helpers

def _slab(w, h, t, r, ch_bottom, ch_top, z0=0.0) -> Manifold:
    """Rounded slab with 45° chamfers on the bottom / top edges (outer size unchanged)."""
    sl = []
    for z, inset in ((0, ch_bottom), (ch_bottom, 0), (t - ch_top, 0), (t, ch_top)):
        cs = round_rect(0, 0, w - 2 * inset, h - 2 * inset, max(0.3, r - inset), 64)
        sl.append(Manifold.extrude(cs, 1e-3).translate((0, 0, z - (1e-3 if z >= t else 0))))
    return Manifold.batch_hull(sl).translate((0, 0, z0))


def _raise(cs: CrossSection, z_face: float, height: float) -> Manifold | None:
    if cs is None or cs.is_empty():
        return None
    return Manifold.extrude(cs, height + EMBED).translate((0, 0, z_face - EMBED))


# ---------------------------------------------------------------- the card

def _layout(meta: dict, avatar_hm: np.ndarray | None, founding: str | None):
    """Returns (raised: list[Manifold], cuts_front: list[Manifold], cuts_back: list[Manifold], info)."""
    F = font()
    W, H, T = CARD["w"], CARD["h"], CARD["t"]
    m = 6.0
    left, right = -W / 2 + m, W / 2 - m
    inner_w = right - left
    av = 5.6
    av_x, av_y = left + av, H / 2 - m - av
    name_x = left + 2 * av + 3
    name_cap, name_base = 3.5, av_y + 0.9
    handle_cap = 2.8
    handle_base = av_y - 0.9 - handle_cap
    icon_s = 4.6
    action_y = -H / 2 + m + 2.0
    count_cap = 2.7
    divider_y = action_y + icon_s / 2 + 3.0
    date_cap = 2.7
    date_base = divider_y + 2.6

    raised: list[Manifold] = []
    cut_f: list[Manifold] = []
    cut_b: list[Manifold] = []
    info: dict = {}

    def one(s):
        return " ".join(F.sanitize(s).split())

    def add(cs, h=RAISE, z=T):
        mm = _raise(cs, z, h)
        if mm is not None:
            raised.append(mm)

    name_raw = (meta.get("name") or meta.get("author_name") or "").strip()
    handle = one(handle_from(meta))
    # avatar: photo relief if we have one, else a raised disc with the initial (as the preview)
    if avatar_hm is not None:
        rim = 0.8
        raised.append(_height_disc(avatar_hm, av_x, av_y, av - rim + 0.05, 0.4, 1.2).translate((0, 0, T - EMBED)))
        add(circle(av_x, av_y, av - 0.3, 96), 0.3)
        add(ring(av_x, av_y, av, rim), 1.2)
        info["avatar"] = "photo"
    else:
        initial = (one(name_raw or handle.lstrip("@")).upper()[:1]).strip()
        disc_h = 0.5
        add(circle(av_x, av_y, av, 96), disc_h)
        if initial:
            cap = 4.6
            add(F.line(initial, cap, av_x, av_y - cap / 2, "center"), RAISE_2 + EMBED, T + disc_h)
        info["avatar"] = "initial" if initial else "disc"

    # header: name (+ verified badge), @handle, X mark top-right
    logo_s = 4.6
    max_w = right - logo_s - 3 - name_x
    name = one(name_raw or handle.lstrip("@"))
    badge = 4.0 if _truthy(meta.get("verified")) else 0.0
    gap = 1.1 if badge else 0.0
    min_name = 2.8
    nc = min(name_cap, F.cap_to_fit(name, max_w - badge - gap, name_cap)) if name else 0.0
    if name and nc < min_name:
        nc = min_name
        if F.measure(name, min_name) > max_w - badge - gap:
            while len(name) > 1 and F.measure(name + "…", min_name) > max_w - badge - gap:
                name = name[:-1]
            name = name.rstrip() + "…"
    if name:
        add(F.line(name, nc, name_x, name_base))
        if badge:
            add(verified_badge(name_x + F.measure(name, nc) + gap + badge / 2, name_base + nc / 2, badge))
    if handle:
        hc = min(handle_cap, F.cap_to_fit(handle, max_w, handle_cap))
        add(F.line(handle, max(hc, 2.4), name_x, handle_base), RAISE_2)
    add(x_logo(right - logo_s / 2, av_y + 1.2, logo_s))
    info.update(name=name, handle=handle, verified=bool(badge))

    # body text
    date = one(x_date(meta))
    text = F.sanitize(card_text((meta.get("tweet_text") or meta.get("text") or ""))[:280]).strip()
    text = "\n".join(" ".join(ln.split()) for ln in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if text:
        box_top = av_y - av - 3.2
        box_bottom = (date_base + date_cap if date else divider_y) + 2.6
        avail = box_top - box_bottom - 2.0  # room for descenders on the last line
        lines, cap, step = F.fit_block(text, inner_w, avail, 2.6, 5.5)
        free = avail - (cap + max(0, len(lines) - 1) * step)
        if len(lines) > 1:
            step += min(free / (len(lines) - 1), cap * 0.35)
        add(_union([F.line(ln, cap, left, box_top - cap - i * step) for i, ln in enumerate(lines) if ln.strip()]))
        info.update(lines=lines, cap=cap)

    # footer: timestamp, divider groove, action row (real counts only)
    if date:
        add(F.line(date, min(date_cap, F.cap_to_fit(date, inner_w, date_cap)), left, date_base), RAISE_2)
    groove = capsule(left, divider_y, right, divider_y, GROOVE_W)
    cut_f.append(Manifold.extrude(groove, GROOVE_D + 1).translate((0, 0, T - GROOVE_D)))
    slot = inner_w / 4.4
    counts = {
        "replies": compact_count(meta.get("replies", "")),
        "reposts": compact_count(meta.get("reposts") or meta.get("retweets") or ""),
        "likes": compact_count(meta.get("likes", "")),
        "views": compact_count(meta.get("views", "")),
    }
    icons = [(reply_icon, "replies"), (repost_icon, "reposts"), (lambda x, y, s: heart(x, y, s * 1.05), "likes"),
             (views_icon, "views")]
    shown = {}
    for i, (icon, key) in enumerate(icons):
        x = left + icon_s / 2 + i * slot
        add(icon(x, action_y, icon_s))
        c = one(counts[key])
        if c:
            cw = slot - icon_s - 2.0
            cc = min(count_cap, F.cap_to_fit(c, cw, count_cap))
            add(F.line(c, max(cc, 2.2), x + icon_s / 2 + 1.3, action_y - count_cap / 2), RAISE_2)
            shown[key] = c
    add(share_icon(right - icon_s / 2, action_y, icon_s))
    info["counts"] = shown

    # founding number, engraved into the back so it reads from behind
    f = (founding or "").strip().lstrip("#")
    if f:
        label = "#" + (f.zfill(3) if f.isdigit() else f)
        cs = F.line(one(label), 4.0, 0, -H / 2 + 10).mirror((1, 0))
        cut_b.append(Manifold.extrude(cs, ENGRAVE + 1).translate((0, 0, -1)))
        info["founding"] = label
    return raised, cut_f, cut_b, info


def build_card(meta: dict, founding: str | None = None, avatar: bytes | None = None) -> tuple[Manifold, dict]:
    """The card alone, lying flat: back at z=0, face at z=t, centred in x/y."""
    W, H, T = CARD["w"], CARD["h"], CARD["t"]
    body = _slab(W, H, T, CARD["r"], CARD["chamfer"] * 0.75, CARD["chamfer"])
    hm = height_map(avatar) if avatar else None
    raised, cut_f, cut_b, info = _layout(meta, hm, founding)
    if raised:
        body = Manifold.batch_boolean([body] + raised, OpType.Add)
    cuts = cut_f + cut_b
    if cuts:
        body = Manifold.batch_boolean([body] + cuts, OpType.Subtract)
    return body, info


def build_stand() -> Manifold:
    """Two-tier bevelled stand (as the preview): plinth + upper block, base on z=0, centred."""
    W = CARD["w"]
    d, h, r, ph, lip, ch = STAND["d"], STAND["h"], STAND["r"], STAND["plinth_h"], STAND["lip"], STAND["chamfer"]
    plinth = _slab(W + 2 * lip, d + 2 * lip, ph, r + 2, 0.4, ch)
    top = _slab(W, d, h - ph + 0.01, r, 0.0, ch, z0=ph - 0.01)
    return plinth + top


def build_trophy(meta: dict, founding: str | None = None, avatar: bytes | None = None) -> tuple[Manifold, dict]:
    """One piece: the card standing at 75° in the stand. Face toward -y, base on z=0."""
    card, info = build_card(meta, founding, avatar)
    W, H, T = CARD["w"], CARD["h"], CARD["t"]
    lean = 90.0 - STAND_ANGLE_DEG
    pivot_z = STAND["h"] - STAND["slot"]
    # card: bottom edge centre-plane at the origin, then stand it up (face -> -y) and lean the top back (+y)
    card = card.translate((0, H / 2, -T / 2)).rotate((90, 0, 0)).rotate((-lean, 0, 0)).translate((0, 0, pivot_z))
    stand = build_stand().translate((0, (H / 2) * math.sin(math.radians(lean)) * 0.6, 0))
    solid = card + stand
    return solid, info


def to_trimesh(m: Manifold) -> trimesh.Trimesh:
    mesh = m.to_mesh64()
    tm = trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3], faces=np.asarray(mesh.tri_verts), process=False)
    # STL stores float32: weld near-coincident vertices and drop the slivers that collapse, so the file
    # read back by the supplier is as watertight as the solid.
    tm.vertices = tm.vertices.astype(np.float32).astype(np.float64)
    tm.merge_vertices()
    tm.apply_translation([0, 0, -tm.bounds[0][2]])
    return tm


def _stl_watertight(tm: trimesh.Trimesh) -> bool:
    buf = io.BytesIO()
    tm.export(buf, file_type="stl")
    buf.seek(0)
    return bool(tm.is_watertight and trimesh.load(buf, file_type="stl").is_watertight)


def tweet_trophy_mesh(meta: dict, founding: str | None = None, avatar: bytes | None = None) -> tuple[trimesh.Trimesh, dict]:
    solid, info = build_trophy(meta, founding, avatar)
    if solid.status().name != "NoError" or solid.is_empty():
        raise TweetCardError(f"tweet trophy: manifold status {solid.status().name}")
    if len(solid.decompose()) != 1:
        raise TweetCardError("tweet trophy: geometry is not a single body")
    # STL stores float32 and loaders weld by position: booleans can leave sub-micron slivers that weld into
    # non-manifold edges. Collapse them with a growing tolerance (far below print resolution) until the
    # file the supplier reads back is watertight.
    for tol in (None, 1e-3, 1e-2, 2e-2):
        tm = to_trimesh(solid if tol is None else solid.simplify(tol))
        if _stl_watertight(tm):
            return tm, info
    raise TweetCardError("tweet trophy: mesh is not watertight")
