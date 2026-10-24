"""OrcaSlicer CLI slicing for a Bambu Lab A1 (0.4 nozzle, 0.20mm Standard, Generic PLA, Textured PEI)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import trimesh

from . import is_mock
from .types import SliceResult

PROFILES = Path(__file__).parent / "profiles"
MACHINE = PROFILES / "machine_a1_0.4.json"
PROCESS = PROFILES / "process_0.20mm_standard_a1.json"
FILAMENT = PROFILES / "filament_generic_pla_a1.json"
OUT_NAME = "model.gcode.3mf"
SLICE_TIMEOUT_S = 600
PLA_G_PER_CM3 = 1.24


class SlicerError(Exception):
    pass


def parse_slice_info(xml_text: str) -> tuple[int, float]:
    """(print_seconds, filament_grams) summed over plates of Metadata/slice_info.config."""
    root = ET.fromstring(xml_text)
    seconds, grams = 0.0, 0.0
    plates = root.findall("plate")
    if not plates:
        raise SlicerError("slice_info.config has no <plate>")
    for plate in plates:
        meta = {m.get("key"): m.get("value") for m in plate.findall("metadata")}
        seconds += float(meta.get("prediction") or 0)
        if meta.get("weight"):
            grams += float(meta["weight"])
        else:
            grams += sum(float(f.get("used_g") or 0) for f in plate.findall("filament"))
    return int(round(seconds)), round(grams, 2)


def read_gcode_3mf(path: Path) -> tuple[int, float]:
    with zipfile.ZipFile(path) as z:
        return parse_slice_info(z.read("Metadata/slice_info.config").decode())


def _orca_cmd(binary: str, stl: Path, out_dir: Path) -> list[str]:
    # No --orient: finish_for_print/CadQuery already rest the part flat on z=0 (keyring ring
    # included); Orca's auto-orient may tip it onto a worse face. --arrange centres it on the bed.
    cmd = [binary,
           "--load-settings", f"{MACHINE};{PROCESS}",
           "--load-filaments", str(FILAMENT),
           "--arrange", "1",
           "--slice", "0",
           "--outputdir", str(out_dir),
           "--export-3mf", OUT_NAME,
           str(stl)]
    if not os.environ.get("DISPLAY") and shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "-a", *cmd]
    return cmd


def _orca_env() -> dict[str, str]:
    """Environment for the slicer: ORCA_LD_LIBRARY_PATH (e.g. GL/GLU libs extracted from .debs
    on a host without root) is prepended to LD_LIBRARY_PATH for the slicer process only."""
    env = dict(os.environ)
    extra = os.environ.get("ORCA_LD_LIBRARY_PATH", "").strip()
    if extra:
        env["LD_LIBRARY_PATH"] = extra + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    return env


def _estimate(stl: Path, out_dir: Path) -> SliceResult:
    """Mock-mode estimate from geometry: 2 walls + 15% infill, ~6 mm^3/s effective, 4 min start-up."""
    mesh = trimesh.load(str(stl), force="mesh")
    vol = abs(float(mesh.volume)) / 1000.0 if mesh.is_watertight else float(mesh.convex_hull.volume) / 1000.0
    shell = min(vol, float(mesh.area) / 100.0 * 0.08)  # cm^2 x 0.8 mm of perimeters
    used_cm3 = shell + 0.15 * (vol - shell)
    grams = round(used_cm3 * PLA_G_PER_CM3 + 0.3, 2)
    seconds = int(240 + used_cm3 * 1000 / 6.0 + mesh.extents[2] / 0.2 * 1.5)
    gcode_3mf = out_dir / OUT_NAME
    info = (f'<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <plate>\n'
            f'    <metadata key="index" value="1"/>\n'
            f'    <metadata key="prediction" value="{seconds}"/>\n'
            f'    <metadata key="weight" value="{grams}"/>\n  </plate>\n</config>\n')
    with zipfile.ZipFile(gcode_3mf, "w") as z:
        z.writestr("Metadata/slice_info.config", info)
        z.writestr("Metadata/plate_1.gcode", "; MOCK ESTIMATE - not printable\n")
    (out_dir / "slice_result.json").write_text(json.dumps(
        {"estimate": True, "print_seconds": seconds, "filament_grams": grams, "gcode_3mf": str(gcode_3mf)}, indent=1))
    return SliceResult(gcode_3mf=gcode_3mf, print_seconds=seconds, filament_grams=grams)


def slice_model(stl: Path, out_dir: Path) -> SliceResult:
    stl, out_dir = Path(stl).resolve(), Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    binary = os.environ.get("ORCA_SLICER_BIN", "")
    if not binary or not Path(binary).exists():
        if is_mock():
            return _estimate(stl, out_dir)
        raise SlicerError(f"ORCA_SLICER_BIN {binary!r} not found and FACTORY_MOCK is not 1")
    gcode_3mf = out_dir / OUT_NAME
    gcode_3mf.unlink(missing_ok=True)
    try:
        proc = subprocess.run(_orca_cmd(binary, stl, out_dir), capture_output=True, text=True,
                              timeout=SLICE_TIMEOUT_S, env=_orca_env(), cwd=out_dir)  # Orca drops 00000.log in cwd
    except subprocess.TimeoutExpired:
        raise SlicerError(f"OrcaSlicer timed out after {SLICE_TIMEOUT_S} s") from None
    if proc.returncode != 0 or not gcode_3mf.exists():
        tail = "\n".join((proc.stderr + proc.stdout).strip().splitlines()[-15:])
        raise SlicerError(f"OrcaSlicer exited {proc.returncode}, no {OUT_NAME}:\n{tail}")
    seconds, grams = read_gcode_3mf(gcode_3mf)
    return SliceResult(gcode_3mf=gcode_3mf, print_seconds=seconds, filament_grams=grams)
