"""CadQuery print files for the four products (docs/CONTRACT.md "Print geometry"). Units: mm.

Slant products are single-body STLs. Plaques print flat (front face up, raised text, founding number engraved
into the bed face) plus a separate slotted 75° stand STL, since Slant takes STL only and charges extra
for multi-body files. The Tweet Trophy is one piece, card standing in its stand (receipts/tweet_card.py). Full colour is an OBJ + MTL + PNG zip with the screenshot on the panel's front face.
"""
from __future__ import annotations

import io
import re
import zipfile
from functools import lru_cache
from pathlib import Path

import numpy as np
import trimesh

from factory.cad import _font_path, _rounded_slab, shape_to_trimesh

CAP_RATIO = 0.729  # DejaVu Sans Bold cap height / font size (measured)
STAND_ANGLE_DEG = 75.0
ENGRAVE_MM = 0.6

MILESTONE = {"w": 140.0, "h": 100.0, "t": 8.0, "r": 3.0, "raise": 1.0, "border_in": 2.0, "border_w": 1.5}
FULLCOLOUR = {"panel_w": 150.0, "panel_h": 100.0, "panel_t": 4.0, "base_w": 150.0, "base_d": 30.0, "base_h": 15.0}
COLOUR_RGB = {"black": (0.08, 0.08, 0.08), "white": (0.95, 0.95, 0.95), "red": (0.78, 0.12, 0.12),
              "blue": (0.10, 0.27, 0.70), "green": (0.10, 0.55, 0.25), "gold": (0.83, 0.66, 0.22)}


class GenerationError(Exception):
    pass


# ---------------------------------------------------------------- text helpers

@lru_cache(maxsize=1)
def _charmap() -> frozenset[int]:
    from matplotlib.ft2font import FT2Font

    return frozenset(FT2Font(_font_path()).get_charmap())


def clean_text(s: str, keep_newlines: bool = False) -> str:
    s = re.sub(r"https?://t\.co/\S+", "", s or "")
    cm = _charmap()
    out = "".join(c for c in s if c == "\n" or c == " " or ord(c) in cm)
    if not keep_newlines:
        out = " ".join(out.split())
    return out.strip()


def _text(txt: str, cap: float, height: float, max_w: float | None = None, max_h: float | None = None):
    """Text solid with z in [0, height]; shrunk to fit max_w/max_h. Returns (workplane, font_size)."""
    import cadquery as cq

    size = cap / CAP_RATIO

    def make(sz):
        return cq.Workplane("XY").text(txt, sz, height, fontPath=_font_path(), halign="left", valign="top")

    wp = make(size)
    bb = wp.val().BoundingBox()
    fit = 1.0
    if max_w:
        fit = min(fit, max_w / max(bb.xlen, 1e-6))
    if max_h:
        fit = min(fit, max_h / max(bb.ylen, 1e-6))
    if fit < 1.0:
        size *= fit * 0.97
        wp = make(size)
    return wp, size


def _place(wp, x: float, y: float, z: float, h: str = "left", v: str = "top"):
    bb = wp.val().BoundingBox()
    dx = {"left": x - bb.xmin, "center": x - bb.center.x, "right": x - bb.xmax}[h]
    dy = {"top": y - bb.ymax, "center": y - bb.center.y, "bottom": y - bb.ymin}[v]
    return wp.translate((dx, dy, z - bb.zmin))


def _bb(wp):
    return wp.val().BoundingBox()


def _engrave_back(body, txt: str, x: float, y: float, cap: float = 4.0):
    """Cut mirrored text into the bed face (z=0) so it reads correctly from the back."""
    wp, _ = _text(txt, cap, ENGRAVE_MM + 0.01)
    wp = wp.mirror("YZ")
    wp = _place(wp, x, y, -0.01, "center", "center")
    return body.cut(wp)


def _export_stl(shape, path: Path, label: str) -> Path:
    if not shape.val().isValid():
        raise GenerationError(f"{label}: CadQuery produced an invalid solid")
    mesh = shape_to_trimesh(shape)
    mesh.merge_vertices()
    mesh.apply_translation([0, 0, -mesh.bounds[0][2]])
    if not mesh.is_watertight:
        raise GenerationError(f"{label}: mesh is not watertight")
    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(path), file_type="stl")
    return path


# ---------------------------------------------------------------- stand (shared)

def make_stand(card_w: float, card_t: float, out: Path) -> Path:
    """Wedge block with a slot that holds the card at 75° from horizontal."""
    import cadquery as cq

    sw, sd, sh, floor = round(card_w * 0.6), 36.0, 20.0, 6.0
    block = cq.Workplane("XY").box(sw, sd, sh, centered=(True, True, False)).edges("|Z").fillet(3)
    slot = cq.Workplane("XY").box(sw + 2, card_t + 0.5, 60, centered=(True, True, False))
    slot = slot.rotate((0, 0, 0), (1, 0, 0), -(90.0 - STAND_ANGLE_DEG)).translate((0, -6, floor))
    return _export_stl(block.cut(slot), out, "stand")


# ---------------------------------------------------------------- tweet trophy

def tweet_trophy(meta: dict, founding: str | None, out: Path, avatar: bytes | None = None) -> tuple[Path, dict]:
    """One-piece card + stand laid out like the X post (see receipts/tweet_card.py). Returns (path, layout info)."""
    from .tweet_card import TweetCardError, tweet_trophy_mesh

    try:
        mesh, info = tweet_trophy_mesh(meta, founding, avatar)
    except TweetCardError as e:
        raise GenerationError(str(e)) from e
    out.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(out), file_type="stl")
    return out, info


# ---------------------------------------------------------------- milestone plaque / team pack

def plaque(big: str, under: str, bottom_left: str, bottom_right: str, founding: str | None, out: Path) -> Path:
    import cadquery as cq

    p = MILESTONE
    W, H, T, R, r = p["w"], p["h"], p["t"], p["raise"], p["r"]
    body = _rounded_slab(cq, W, H, T, r)
    bi, bw = p["border_in"], p["border_w"]
    outer = _rounded_slab(cq, W - 2 * bi, H - 2 * bi, R, max(r - bi, 0.5))
    inner = _rounded_slab(cq, W - 2 * (bi + bw), H - 2 * (bi + bw), R, max(r - bi - bw, 0.3))
    body = body.union(outer.cut(inner).translate((0, 0, T)))
    pad = bi + bw + 5.0
    x0, x1, ytop, ybot = -W / 2 + pad, W / 2 - pad, H / 2 - pad, -H / 2 + pad
    cw = x1 - x0
    parts = []
    y = ytop
    big = clean_text(big)[:24]
    if big:
        wp, _ = _text(big, 24.0, R, max_w=cw, max_h=30.0)
        wp = _place(wp, 0, y, T, "center")
        parts.append(wp)
        y = _bb(wp).ymin - 4.0
    under = clean_text(under)[:60]
    if under:
        wp, _ = _text(under, 7.0, R, max_w=cw, max_h=10.0)
        parts.append(_place(wp, 0, y, T, "center"))
    bl, br = clean_text(bottom_left)[:40], clean_text(bottom_right)[:30]
    if bl and br:
        wp, _ = _text(bl, 5.0, R, max_w=cw * 0.6)
        parts.append(_place(wp, x0, ybot, T, "left", "bottom"))
        wp, _ = _text(br, 5.0, R, max_w=cw * 0.35)
        parts.append(_place(wp, x1, ybot, T, "right", "bottom"))
    elif bl or br:
        wp, _ = _text(bl or br, 5.0, R, max_w=cw)
        parts.append(_place(wp, 0, ybot, T, "center", "bottom"))
    for wp in parts:
        body = body.union(wp)
    if founding:
        body = _engrave_back(body, f"#{founding}", W / 2 - 20, -H / 2 + 12)
    return _export_stl(body, out, "plaque")


def milestone_plaque(meta: dict, founding: str | None, out: Path) -> Path:
    return plaque(meta.get("number", "")[:10], meta.get("label", ""), meta.get("name", ""), meta.get("date", ""),
                  founding, out)


def team_pack(meta: dict, founding: str | None, out: Path) -> Path:
    return plaque(meta.get("team", ""), meta.get("subline", ""), meta.get("name", ""), meta.get("date", ""),
                  founding, out)


# ---------------------------------------------------------------- full-colour receipt

def _screenshot_png(image_bytes: bytes, px_w: int = 1500, px_h: int = 1000) -> bytes:
    """Cover-crop to the panel's 3:2 aspect and re-encode as PNG."""
    from PIL import Image, ImageOps

    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as e:
        raise GenerationError(f"screenshot is not a readable image: {e}") from e
    img = ImageOps.fit(img, (px_w, px_h), method=Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def placeholder_png() -> bytes:
    """Mock-mode stand-in for a customer screenshot (clearly labelled sample)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1500, 1000), (230, 236, 245))
    d = ImageDraw.Draw(img)
    d.rectangle((60, 60, 1440, 940), outline=(40, 60, 120), width=12)
    d.text((120, 120), "SAMPLE SCREENSHOT (mock mode)", fill=(40, 60, 120))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _base_shape(name: str, founding: str | None):
    import cadquery as cq

    f = FULLCOLOUR
    bw, bd, bh = f["base_w"], f["base_d"], f["base_h"]
    base = cq.Workplane("XY").box(bw, bd, bh, centered=(True, True, False)).edges("|Z").fillet(2)
    name = clean_text(name)[:40]
    if name:
        wp, _ = _text(name, 6.0, 1.0, max_w=bw - 16, max_h=bh - 6)
        wp = _place(wp, 0, 0, 0, "center", "center").rotate((0, 0, 0), (1, 0, 0), 90)
        base = base.cut(wp.translate((0, -bd / 2 + 0.8, bh / 2)))
    if founding:
        wp, _ = _text(f"#{founding}", 4.0, 1.0)
        wp = _place(wp.mirror("YZ"), 0, 0, 0, "center", "center").rotate((0, 0, 0), (1, 0, 0), 90)
        base = base.cut(wp.translate((bw / 2 - 18, bd / 2 + 0.4, bh / 2)))
    return base


def fullcolour_receipt(meta: dict, founding: str | None, out: Path, image_bytes: bytes, colour: str = "white") -> Path:
    f = FULLCOLOUR
    png = _screenshot_png(image_bytes)
    base = shape_to_trimesh(_base_shape(meta.get("name", ""), founding))
    base.merge_vertices()
    base.apply_translation([0, 0, -base.bounds[0][2]])
    if not base.is_watertight:
        raise GenerationError("fullcolour base is not watertight")

    hw, ht, z0, z1 = f["panel_w"] / 2, f["panel_t"] / 2, f["base_h"], f["base_h"] + f["panel_h"]
    pv = [(-hw, -ht, z0), (hw, -ht, z0), (hw, -ht, z1), (-hw, -ht, z1),
          (-hw, ht, z0), (hw, ht, z0), (hw, ht, z1), (-hw, ht, z1)]
    lines = ["# Full-Colour Receipt, units mm", "mtllib model.mtl", "o base", "usemtl base"]
    lines += [f"v {x:.4f} {y:.4f} {z:.4f}" for x, y, z in base.vertices]
    lines += [f"f {a + 1} {b + 1} {c + 1}" for a, b, c in base.faces]
    n = len(base.vertices)
    lines += ["o panel"] + [f"v {x:.4f} {y:.4f} {z:.4f}" for x, y, z in pv]
    lines += ["vt 0 0", "vt 1 0", "vt 1 1", "vt 0 1"]
    i = lambda k: n + k + 1  # noqa: E731
    lines += ["usemtl screen", f"f {i(0)}/1 {i(1)}/2 {i(2)}/3", f"f {i(0)}/1 {i(2)}/3 {i(3)}/4"]
    lines += ["usemtl panel"]
    for a, b, c in ((0, 4, 5), (0, 5, 1), (3, 2, 6), (3, 6, 7), (0, 3, 7), (0, 7, 4), (1, 5, 6), (1, 6, 2),
                    (5, 4, 7), (5, 7, 6)):
        lines.append(f"f {i(a)} {i(b)} {i(c)}")
    kd = COLOUR_RGB.get(colour, COLOUR_RGB["white"])
    mtl = "\n".join([
        "newmtl base", f"Kd {kd[0]:.3f} {kd[1]:.3f} {kd[2]:.3f}", "",
        "newmtl panel", "Kd 0.950 0.950 0.950", "",
        "newmtl screen", "Kd 1.000 1.000 1.000", "map_Kd screenshot.png", "",
    ])
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("model.obj", "\n".join(lines) + "\n")
        z.writestr("model.mtl", mtl)
        z.writestr("screenshot.png", png)
    return out


# ---------------------------------------------------------------- dispatch

def generate_files(product: str, meta: dict, colour: str, founding: str | None, out_dir: Path,
                   image_bytes: bytes | None = None, avatar_bytes: bytes | None = None) -> dict:
    """Returns {"main": path, "stand": path?, "info": dict?}. Tweet trophies are one piece (no stand file)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        if product == "fullcolour":
            if not image_bytes:
                raise GenerationError("fullcolour order has no screenshot")
            return {"main": fullcolour_receipt(meta, founding, out_dir / "receipt_fullcolour.zip", image_bytes, colour)}
        if product == "tweet":
            main, info = tweet_trophy(meta, founding, out_dir / "tweet_trophy.stl", avatar_bytes)
            stale = out_dir / "stand.stl"  # older two-piece tweet files: never upload a leftover stand
            if stale.exists():
                stale.unlink()
            return {"main": main, "info": info}
        if product == "milestone":
            main = milestone_plaque(meta, founding, out_dir / "milestone_plaque.stl")
            stand = make_stand(MILESTONE["w"], MILESTONE["t"], out_dir / "stand.stl")
        elif product == "team":
            main = team_pack(meta, founding, out_dir / "team_plaque.stl")
            stand = make_stand(MILESTONE["w"], MILESTONE["t"], out_dir / "stand.stl")
        else:
            raise GenerationError(f"unknown product {product!r}")
    except GenerationError:
        raise
    except Exception as e:  # OCC errors surface as generic exceptions
        raise GenerationError(f"{product}: {type(e).__name__}: {e}") from e
    return {"main": main, "stand": stand}


def stl_extents(path: Path) -> np.ndarray:
    return trimesh.load(str(path), force="mesh").extents


def obj_zip_extents(path: Path) -> np.ndarray:
    with zipfile.ZipFile(path) as z:
        text = z.read("model.obj").decode()
    v = np.array([[float(t) for t in ln.split()[1:4]] for ln in text.splitlines() if ln.startswith("v ")])
    return v.max(axis=0) - v.min(axis=0)
