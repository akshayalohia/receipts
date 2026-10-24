import numpy as np
import pytest
import trimesh
from PIL import Image

from factory.convert import load_mesh, to_all_formats


@pytest.fixture
def box_artifact(tmp_path, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)  # rendering must not need a display
    src = tmp_path / "box.stl"
    box = trimesh.creation.box((40, 20, 10))
    box.apply_translation((0, 0, 5))  # resting on z=0
    box.export(str(src))
    return to_all_formats(src, tmp_path / "out")


def test_artifact_fields(box_artifact):
    a = box_artifact
    assert a.bbox_mm == pytest.approx((40, 20, 10))
    assert a.watertight and a.volume_cm3 == pytest.approx(8.0)
    assert [p.name for p in (a.stl, a.glb, a.usdz, a.png)] == ["model.stl", "model.glb", "model.usdz", "model.png"]


def test_usdz_true_physical_scale(box_artifact):
    from pxr import Usd, UsdGeom, UsdShade

    stage = Usd.Stage.Open(str(box_artifact.usdz))
    assert UsdGeom.GetStageMetersPerUnit(stage) == pytest.approx(1.0)  # geometry stored in metres
    assert UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y
    assert stage.GetDefaultPrim().GetPath().pathString == "/Model"
    mesh = UsdGeom.Mesh(stage.GetPrimAtPath("/Model/Geom"))
    pts = np.array(mesh.GetPointsAttr().Get())
    size_m = pts.max(axis=0) - pts.min(axis=0)
    size_mm = size_m * UsdGeom.GetStageMetersPerUnit(stage) * 1000
    # Y-up: USD x = X, USD y = Z (height), USD z = -Y
    assert size_mm == pytest.approx((40, 10, 20), abs=1e-3)
    assert pts[:, 1].min() == pytest.approx(0.0, abs=1e-6)  # sits on the floor in AR
    assert UsdShade.MaterialBindingAPI(mesh.GetPrim()).ComputeBoundMaterial()[0]


def test_glb_is_metres_y_up_and_round_trips(box_artifact):
    raw = trimesh.load(str(box_artifact.glb), force="mesh")
    assert raw.extents == pytest.approx((0.040, 0.010, 0.020), abs=1e-6)
    assert load_mesh(box_artifact.glb).extents == pytest.approx((40, 20, 10), abs=1e-3)


def test_png_render_headless(box_artifact):
    with Image.open(box_artifact.png) as im:
        assert im.size == (800, 800)
        colours = im.convert("RGB").getcolors(maxcolors=1_000_000)
    assert colours is not None and len(colours) > 20  # an actual shaded render, not a blank canvas
