"""Parametric CAD: five CadQuery templates + a sandboxed runner for bot-written CadQuery code. Units: mm."""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import trimesh

from .convert import to_all_formats
from .types import Artifact

BUILD_LIMIT_MM = 250.0  # A1 build volume is 256^3; keep a margin
MIN_WALL_MM = 1.2
SANDBOX_MEM_BYTES = 3 * 1024**3  # RLIMIT_AS for the child (OCP alone maps ~1 GiB of address space)
_TEXT_RAISE_MM = 1.0
_HOLE_D_MM = 4.0


class CadError(Exception):
    def __init__(self, message: str, traceback_tail: str = ""):
        super().__init__(message)
        self.message = message
        self.traceback_tail = traceback_tail

    def __str__(self) -> str:
        return f"{self.message}\n{self.traceback_tail}" if self.traceback_tail else self.message


def _font_path() -> str:
    import matplotlib

    return str(Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans-Bold.ttf")


def _num(default, lo, hi, desc, kind="number", unit="mm"):
    d = {"type": kind, "default": default, "minimum": lo, "maximum": hi, "description": desc}
    if unit:
        d["unit"] = unit
    return d


_TEMPLATES: dict[str, dict] = {
    "nametag": {
        "title": "Name tag / desk nameplate",
        "description": "Rounded plate with raised bold text, optional raised border and keyring hole.",
        "params": {
            "text": {"type": "string", "default": "NAME", "minLength": 1, "maxLength": 24, "description": "Text to raise"},
            "width": _num(80.0, 30, 200, "Plate width (X)"),
            "height": _num(25.0, 10, 80, "Plate height (Y)"),
            "thickness": _num(3.0, 1.5, 8, "Plate thickness (Z), text adds 1 mm"),
            "font_size": _num(12.0, 4, 40, "Cap height of the text; shrunk automatically to fit"),
            "border": _num(1.5, 0, 5, "Raised border width, 0 = none"),
            "hole": {"type": "boolean", "default": True, "description": "4 mm hole at the left end for a ring"},
        },
    },
    "keychain_ring": {
        "title": "Keychain ring",
        "description": "Flat ring lying on the bed; unioned onto meshes to make keychains.",
        "params": {
            "outer_d": _num(10.0, 6, 30, "Outer diameter"),
            "inner_d": _num(5.0, 2, 24, "Hole diameter"),
            "thickness": _num(3.0, 1.5, 8, "Ring thickness (Z)"),
        },
    },
    "holder": {
        "title": "Perfect-fit holder",
        "description": "Cup/stand with a pocket sized to an object, optionally tilted back like a phone stand.",
        "params": {
            "item_w": _num(60.0, 5, 200, "Object width (X)"),
            "item_d": _num(30.0, 5, 200, "Object depth (Y)"),
            "item_h": _num(80.0, 5, 240, "Object height; pocket depth is 40% of it, 8-60 mm"),
            "wall": _num(2.0, MIN_WALL_MM, 6, "Wall and floor thickness"),
            "clearance": _num(0.5, 0, 3, "Gap per side between object and pocket"),
            "angle_deg": _num(0.0, 0, 30, "Backward tilt of the pocket", unit="deg"),
        },
    },
    "knob": {
        "title": "Replacement knob",
        "description": "Round knob with grip ribs and a blind D-shaft hole from the bottom.",
        "params": {
            "d": _num(30.0, 8, 80, "Knob diameter"),
            "h": _num(15.0, 5, 60, "Knob height"),
            "shaft_d": _num(6.0, 2, 20, "Shaft diameter (hole)"),
            "shaft_flat": _num(1.0, 0, 5, "Depth of the D-flat on the shaft, 0 = round shaft"),
            "grip_ribs": _num(12, 0, 48, "Number of vertical grip ribs", kind="integer", unit=None),
        },
    },
    "cable_clip": {
        "title": "Cable clip",
        "description": "Snap-in cable clips on a base plate with a screw hole at each end.",
        "params": {
            "cable_d": _num(6.0, 2, 20, "Cable diameter"),
            "count": _num(1, 1, 8, "Number of cables side by side", kind="integer", unit=None),
            "base_w": _num(12.0, 6, 40, "Clip length along the cable (Y)"),
        },
    },
}


def list_templates() -> list[dict]:
    out = []
    for name, t in _TEMPLATES.items():
        out.append({
            "name": name, "title": t["title"], "description": t["description"],
            "params": {"type": "object", "properties": json.loads(json.dumps(t["params"]))},
        })
    return out


def _validate(name: str, params: dict) -> dict:
    if name not in _TEMPLATES:
        raise CadError(f"unknown template {name!r}; choose one of {sorted(_TEMPLATES)}")
    schema = _TEMPLATES[name]["params"]
    unknown = set(params) - set(schema)
    if unknown:
        raise CadError(f"unknown params for {name}: {sorted(unknown)}; allowed: {sorted(schema)}")
    out = {}
    for key, spec in schema.items():
        val = params.get(key, spec["default"])
        try:
            if spec["type"] == "string":
                val = str(val)
                if not spec["minLength"] <= len(val.strip()) <= spec["maxLength"]:
                    raise ValueError(f"length must be {spec['minLength']}-{spec['maxLength']}")
            elif spec["type"] == "boolean":
                if not isinstance(val, bool):
                    raise ValueError("must be true or false")
            else:
                num = float(val)
                if spec["type"] == "integer":
                    if num != int(num):
                        raise ValueError("must be a whole number")
                    num = int(num)
                if not spec["minimum"] <= num <= spec["maximum"]:
                    raise ValueError(f"must be between {spec['minimum']} and {spec['maximum']}")
                val = num
        except (TypeError, ValueError) as e:
            raise CadError(f"{name}.{key}={params.get(key)!r}: {e}") from None
        out[key] = val
    return out


# ---------------------------------------------------------------- templates (CadQuery, mm, bottom on z=0)

def _rounded_slab(cq, w: float, h: float, t: float, r: float):
    slab = cq.Workplane("XY").box(w, h, t, centered=(True, True, False))
    return slab.edges("|Z").fillet(r) if r > 0.05 else slab


def nametag(text: str, width: float, height: float, thickness: float, font_size: float, border: float, hole: bool):
    import cadquery as cq

    r = min(3.0, height / 4)
    body = _rounded_slab(cq, width, height, thickness, r)
    if border > 0:
        outer = _rounded_slab(cq, width, height, _TEXT_RAISE_MM, r)
        inner = _rounded_slab(cq, width - 2 * border, height - 2 * border, _TEXT_RAISE_MM, max(r - border, 0.0))
        body = body.union(outer.cut(inner).translate((0, 0, thickness)))
    hole_zone = (_HOLE_D_MM + 5.0) if hole else 0.0
    avail_w = width - 2 * border - 4.0 - hole_zone
    avail_h = height - 2 * border - 3.0
    cx = hole_zone / 2
    txt = text.strip()
    if txt and avail_w > 2 and avail_h > 2:
        def make(size):
            return (cq.Workplane("XY").workplane(offset=thickness).center(cx, 0)
                    .text(txt, size, _TEXT_RAISE_MM, fontPath=_font_path(), halign="center", valign="center"))
        size = font_size
        letters = make(size)
        bb = letters.val().BoundingBox()
        fit = min(avail_w / max(bb.xlen, 1e-6), avail_h / max(bb.ylen, 1e-6))
        if fit < 1.0:
            size *= fit * 0.97
            letters = make(size)
        bb = letters.val().BoundingBox()
        letters = letters.translate((cx - bb.center.x, -bb.center.y, 0))  # centre the ink, not the metrics
        body = body.union(letters)
    if hole:
        x = -width / 2 + border + 2.0 + _HOLE_D_MM / 2 + 0.5
        cutter = cq.Workplane("XY").center(x, 0).circle(_HOLE_D_MM / 2).extrude(thickness + _TEXT_RAISE_MM + 1)
        body = body.cut(cutter.translate((0, 0, -0.5)))
    return body


def keychain_ring(outer_d: float, inner_d: float, thickness: float):
    import cadquery as cq

    if (outer_d - inner_d) / 2 < MIN_WALL_MM:
        raise CadError(f"keychain_ring wall {(outer_d - inner_d) / 2:.2f} mm < {MIN_WALL_MM} mm; raise outer_d or lower inner_d")
    return cq.Workplane("XY").circle(outer_d / 2).circle(inner_d / 2).extrude(thickness)


def holder(item_w: float, item_d: float, item_h: float, wall: float, clearance: float, angle_deg: float):
    import cadquery as cq

    iw, idp = item_w + 2 * clearance, item_d + 2 * clearance
    depth = min(max(item_h * 0.4, 8.0), 60.0)
    W, D, H = iw + 2 * wall, idp + 2 * wall, depth + wall
    # Cup in local frame: back-bottom edge on the X axis (y=0, z=0), cup spans y in [-D, 0].
    cup = cq.Workplane("XY").center(0, -D / 2).rect(W, D).extrude(H)
    pocket = cq.Workplane("XY").workplane(offset=wall).center(0, -D / 2).rect(iw, idp).extrude(H)
    cup = cup.cut(pocket)
    if angle_deg > 0:
        a = math.radians(angle_deg)
        cup = cup.rotate((0, 0, 0), (1, 0, 0), -angle_deg)  # top leans back (+Y), back-bottom edge stays on z=0
        wedge = (cq.Workplane("YZ").polyline([(0, 0), (-D * math.cos(a), 0), (-D * math.cos(a), D * math.sin(a))])
                 .close().extrude(W / 2, both=True))
        cup = cup.union(wedge)
    bb = cup.val().BoundingBox()
    return cup.translate((-bb.center.x, -bb.center.y, -bb.zmin))


def knob(d: float, h: float, shaft_d: float, shaft_flat: float, grip_ribs: int):
    import cadquery as cq

    if shaft_d + 2 * MIN_WALL_MM * 2 > d:
        raise CadError(f"knob d={d} too small for shaft_d={shaft_d}; need d >= shaft_d + {4 * MIN_WALL_MM}")
    if shaft_flat >= shaft_d / 2:
        raise CadError(f"shaft_flat {shaft_flat} must be < shaft_d/2 ({shaft_d / 2})")
    body = cq.Workplane("XY").circle(d / 2).extrude(h)
    if grip_ribs > 0:
        rib_r = max(0.8, min(1.5, math.pi * d / grip_ribs / 4))
        ribs = cq.Workplane("XY").polarArray(d / 2, 0, 360, grip_ribs).circle(rib_r).extrude(h)
        body = body.union(ribs)
    depth = h - max(2.0, MIN_WALL_MM)
    r = shaft_d / 2
    shaft = cq.Workplane("XY").circle(r).extrude(depth)
    if shaft_flat > 0:
        chord = cq.Workplane("XY").center(0, (r - shaft_flat) + (shaft_flat + 1) / 2).rect(shaft_d + 2, shaft_flat + 1).extrude(depth)
        shaft = shaft.cut(chord)
    return body.cut(shaft.translate((0, 0, -0.01)))


def cable_clip(cable_d: float, count: int, base_w: float):
    import cadquery as cq

    base_t, wall, end = 2.0, 1.6, 8.0
    r_in = cable_d / 2 + 0.2
    r_out = r_in + wall
    pitch = 2 * r_out + 2.0
    length = count * pitch + 2 * end
    zc = base_t + r_in
    body = cq.Workplane("XY").box(length, base_w, base_t, centered=(True, True, False))
    for i in range(count):
        x = -length / 2 + end + pitch / 2 + i * pitch
        ring = cq.Workplane("XZ").center(x, zc).circle(r_out).circle(r_in).extrude(base_w / 2, both=True)
        slot = cq.Workplane("XY").workplane(offset=zc).center(x, 0).rect(0.75 * cable_d, base_w + 2).extrude(r_out + 1)
        body = body.union(ring.cut(slot))
    for sx in (-1, 1):
        body = body.cut(cq.Workplane("XY").center(sx * (length / 2 - end / 2), 0).circle(1.75).extrude(base_t + 1).translate((0, 0, -0.5)))
    return body


_BUILDERS = {"nametag": nametag, "keychain_ring": keychain_ring, "holder": holder, "knob": knob, "cable_clip": cable_clip}


def shape_to_trimesh(shape) -> trimesh.Trimesh:
    """Tessellate a CadQuery Workplane/Shape into a merged Trimesh (mm)."""
    import cadquery as cq

    if isinstance(shape, cq.Workplane):
        vals = [v for v in shape.vals() if isinstance(v, cq.Shape)]
        if not vals:
            raise CadError("result Workplane holds no solid")
        shape = vals[0] if len(vals) == 1 else cq.Compound.makeCompound(vals)
    verts, tris = shape.tessellate(0.02, 0.1)
    v = np.array([(p.x, p.y, p.z) for p in verts], dtype=float)
    mesh = trimesh.Trimesh(vertices=v, faces=np.array(tris, dtype=np.int64), process=True)
    mesh.fix_normals()  # OCC face orientation is not always consistent per triangle
    return mesh


def _finish_cad_mesh(mesh: trimesh.Trimesh, out_dir: Path, label: str) -> Artifact:
    mesh.merge_vertices()
    mesh.apply_translation([0, 0, -mesh.bounds[0][2]])  # rest on z=0 (bot code may not)
    if not mesh.is_watertight:
        raise CadError(f"{label}: solid is not watertight after tessellation")
    if max(mesh.extents) > BUILD_LIMIT_MM:
        raise CadError(f"{label}: bbox {np.round(mesh.extents, 1).tolist()} mm exceeds {BUILD_LIMIT_MM} mm build limit")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / "model.stl"
    mesh.export(str(raw), file_type="stl")
    return to_all_formats(raw, out_dir)


def build_template(name: str, params: dict, out_dir: Path) -> Artifact:
    p = _validate(name, params or {})
    try:
        shape = _BUILDERS[name](**p)
        if not shape.val().isValid():
            raise CadError(f"{name}: CadQuery produced an invalid solid for {p}")
        mesh = shape_to_trimesh(shape)
    except CadError:
        raise
    except Exception as e:  # OCC errors surface as generic exceptions
        raise CadError(f"{name} failed for {p}: {type(e).__name__}: {e}") from e
    return _finish_cad_mesh(mesh, Path(out_dir), name)


# ---------------------------------------------------------------- sandboxed CadQuery

# Runs via `python -I -c`: nothing from the cwd or PYTHONPATH lands on sys.path.
_CHILD = r'''
import json, resource, sys, traceback
code_path, out_stl, result_json, mem_bytes, cpu_s = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])

def done(obj):
    with open(result_json, "w") as f:
        json.dump(obj, f)

for lim, soft, hard in ((resource.RLIMIT_CPU, cpu_s, cpu_s + 5), (resource.RLIMIT_AS, mem_bytes, mem_bytes)):
    try:
        resource.setrlimit(lim, (soft, hard))
    except (ValueError, OSError):
        pass  # e.g. RLIMIT_AS is not enforceable on macOS; the wall-clock timeout still applies

import builtins, math
import cadquery as cq

_BLOCKED = ("socket.", "subprocess.", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork", "pty.")
def _audit(event, args):
    if event.startswith(_BLOCKED):
        raise PermissionError("blocked in sandbox: " + event)
sys.addaudithook(_audit)

_ALLOWED = {"cadquery", "math"}
_real_import = builtins.__import__
def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level != 0 or name.split(".")[0] not in _ALLOWED:
        raise ImportError("import of %r is not allowed in the CAD sandbox (only cadquery, math)" % name)
    return _real_import(name, globals, locals, fromlist, level)

_DENY = {"open", "exec", "eval", "compile", "input", "breakpoint", "exit", "quit", "help", "globals", "locals", "vars", "memoryview"}
safe = {k: getattr(builtins, k) for k in dir(builtins) if k not in _DENY}
safe["__import__"] = _guarded_import
g = {"__builtins__": safe, "__name__": "__cad__"}
try:
    with open(code_path) as f:
        src = f.read()
    exec(compile(src, "<cadquery>", "exec"), g)
    result = g.get("result")
    if result is None:
        raise NameError("the code must bind `result` to a cq.Workplane or cq.Shape")
    if isinstance(result, cq.Workplane):
        vals = [v for v in result.vals() if isinstance(v, cq.Shape)]
        if not vals:
            raise ValueError("`result` Workplane holds no shapes")
        shape = vals[0] if len(vals) == 1 else cq.Compound.makeCompound(vals)
    elif isinstance(result, cq.Shape):
        shape = result
    else:
        raise TypeError("`result` must be a cq.Workplane or cq.Shape, got %s" % type(result).__name__)
    if not shape.Solids():
        raise ValueError("`result` has no solids (only faces/wires?)")
    if not shape.isValid():
        raise ValueError("`result` is not a valid solid (self-intersecting or broken boolean?)")
    cq.exporters.export(shape, out_stl, exportType="STL", tolerance=0.02, angularTolerance=0.1)
    done({"ok": True})
except BaseException as e:
    tb = traceback.format_exc().strip().splitlines()
    done({"ok": False, "message": "%s: %s" % (type(e).__name__, e), "tail": "\n".join(tb[-12:])[-1500:]})
'''


def run_cadquery(code: str, out_dir: Path, timeout_s: int = 90) -> Artifact:
    out_dir = Path(out_dir)
    with tempfile.TemporaryDirectory(prefix="cq_sandbox_") as tmp:
        tmp_p = Path(tmp)
        (tmp_p / "code.py").write_text(code)
        raw, res = tmp_p / "raw.stl", tmp_p / "result.json"
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tmp, "TMPDIR": tmp, "LC_ALL": "C.UTF-8"}
        cmd = [sys.executable, "-I", "-c", _CHILD, "code.py", str(raw), str(res), str(SANDBOX_MEM_BYTES), str(timeout_s)]
        try:
            proc = subprocess.run(cmd, cwd=tmp, env=env, capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            raise CadError(f"CadQuery code timed out after {timeout_s} s") from None
        if not res.exists():
            tail = "\n".join((proc.stderr or "").strip().splitlines()[-12:])
            why = (f"CadQuery code hit the {timeout_s} s CPU time limit" if proc.returncode in (-24, -9)
                   else f"sandbox exited with code {proc.returncode}")
            raise CadError(why, tail)
        result = json.loads(res.read_text())
        if not result["ok"]:
            raise CadError(result["message"], result["tail"])
        mesh = trimesh.load(str(raw), force="mesh")
    return _finish_cad_mesh(mesh, out_dir, "run_cadquery")
