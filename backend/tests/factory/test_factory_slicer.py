import json
import os
import shutil
import zipfile
from pathlib import Path

import pytest

from factory.slicer import FILAMENT, MACHINE, PROCESS, SlicerError, parse_slice_info, read_gcode_3mf, slice_model

# Read at collection time, before the autouse `offline` fixture clears it.
ORIGINAL_ORCA_BIN = os.environ.get("ORCA_SLICER_BIN", "")
REPO_ROOT = Path(__file__).resolve().parents[3]

SLICE_INFO = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header><header_item key="X-BBL-Client-Type" value="slicer"/></header>
  <plate>
    <metadata key="index" value="1"/>
    <metadata key="prediction" value="1534"/>
    <metadata key="weight" value="6.12"/>
    <filament id="1" type="PLA" color="#FFFFFF" used_m="2.05" used_g="6.12"/>
  </plate>
  <plate>
    <metadata key="index" value="2"/>
    <metadata key="prediction" value="66"/>
    <filament id="1" type="PLA" color="#FFFFFF" used_m="0.3" used_g="0.88"/>
  </plate>
</config>
"""


def test_parse_slice_info_sums_plates():
    assert parse_slice_info(SLICE_INFO) == (1600, 7.0)


def test_profiles_are_flattened_a1():
    machine, process, filament = (json.loads(p.read_text()) for p in (MACHINE, PROCESS, FILAMENT))
    for prof in (machine, process, filament):
        assert "inherits" not in prof
    assert machine["printer_model"] == "Bambu Lab A1" and machine["nozzle_diameter"] == ["0.4"]
    assert machine["curr_bed_type"] == "Textured PEI Plate" and process["curr_bed_type"] == "Textured PEI Plate"
    assert process["layer_height"] == "0.2"
    assert "" in process["compatible_printers"] and "" in filament["compatible_printers"]
    assert filament["filament_type"] == ["PLA"]


def test_mock_estimate(nametag_artifact, tmp_path):
    s = slice_model(nametag_artifact.stl, tmp_path)
    assert 240 < s.print_seconds < 3 * 3600
    assert 1 < s.filament_grams < 50
    side = json.loads((tmp_path / "slice_result.json").read_text())
    assert side["estimate"] is True and side["print_seconds"] == s.print_seconds
    assert read_gcode_3mf(s.gcode_3mf) == (s.print_seconds, s.filament_grams)
    with zipfile.ZipFile(s.gcode_3mf) as z:
        assert "Metadata/plate_1.gcode" in z.namelist()


def test_no_slicer_outside_mock_mode_raises(nametag_artifact, tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_MOCK", "0")
    with pytest.raises(SlicerError, match="ORCA_SLICER_BIN"):
        slice_model(nametag_artifact.stl, tmp_path)


def _orca_bin() -> str | None:
    for cand in (ORIGINAL_ORCA_BIN, str(REPO_ROOT / "tools/orca/squashfs-root/AppRun")):
        if cand and Path(cand).exists():
            return cand
    return None


def _orca_libs() -> str:
    """ORCA_LD_LIBRARY_PATH, else the GL/GLU/mspack libs extracted from .debs into tools/libs/."""
    local = REPO_ROOT / "tools/libs/root/usr/lib/x86_64-linux-gnu"
    return os.environ.get("ORCA_LD_LIBRARY_PATH", "") or (str(local) if local.is_dir() else "")


@pytest.fixture(scope="module")
def keychain_artifact(tmp_path_factory):
    from factory.mesh import SAMPLE_MESH, finish_for_print

    return finish_for_print(SAMPLE_MESH, tmp_path_factory.mktemp("keychain"), target_height_mm=40, keyring=True)


@pytest.mark.skipif(_orca_bin() is None, reason="OrcaSlicer not found (set ORCA_SLICER_BIN or extract into tools/orca/)")
@pytest.mark.parametrize("model", ["nametag", "keychain"])
def test_real_orca_slice(model, request, tmp_path, monkeypatch):
    stl = request.getfixturevalue(f"{model}_artifact").stl
    monkeypatch.setenv("ORCA_SLICER_BIN", _orca_bin())
    monkeypatch.setenv("ORCA_LD_LIBRARY_PATH", _orca_libs())
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # Orca writes its config dir under HOME
    try:
        s = slice_model(stl, tmp_path)
    except SlicerError as e:
        if "missing host" in str(e):  # the AppImage's own preflight: host lacks GL/WebKit system libraries
            pytest.skip(f"OrcaSlicer AppImage cannot start on this host: {' '.join(str(e).splitlines()[1:3])}")
        if not os.environ.get("DISPLAY") and not shutil.which("xvfb-run"):
            pytest.skip(f"OrcaSlicer CLI failed on this display-less host without xvfb-run: {e}")
        raise
    assert 300 < s.print_seconds < 4 * 3600 and 1 < s.filament_grams < 60
    with zipfile.ZipFile(s.gcode_3mf) as z:
        assert "Metadata/plate_1.gcode" in z.namelist()
        assert b"; printer_model = Bambu Lab A1" in z.read("Metadata/plate_1.gcode")
    assert not (tmp_path / "slice_result.json").exists()  # real slice, not an estimate
    print(f"real slice {model}: {s.print_seconds} s, {s.filament_grams} g")
