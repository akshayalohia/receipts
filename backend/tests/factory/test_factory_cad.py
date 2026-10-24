import pytest

from factory.cad import CadError, build_template, list_templates, run_cadquery

A1_BUILD_MM = 256.0

CASES = {
    "nametag": [
        {},
        {"text": "AKSHAYA", "width": 120, "height": 30, "font_size": 20, "border": 0, "hole": False},
        {"text": "Jo", "width": 40, "height": 15, "thickness": 2, "font_size": 30, "border": 2.5},
        {"text": "A VERY LONG NAME TAG", "width": 60, "height": 20},  # font auto-shrinks to fit
    ],
    "keychain_ring": [{}, {"outer_d": 20, "inner_d": 12, "thickness": 4}, {"outer_d": 7, "inner_d": 4, "thickness": 1.5}],
    "holder": [
        {},
        {"item_w": 75, "item_d": 12, "item_h": 150, "angle_deg": 15},
        {"item_w": 10, "item_d": 10, "item_h": 10, "wall": 1.2, "clearance": 0, "angle_deg": 30},
        {"item_w": 200, "item_d": 200, "item_h": 240, "wall": 6, "clearance": 3},
    ],
    "knob": [{}, {"d": 50, "h": 25, "shaft_d": 8, "shaft_flat": 0, "grip_ribs": 0},
             {"d": 12, "h": 8, "shaft_d": 4, "shaft_flat": 0.5, "grip_ribs": 24}],
    "cable_clip": [{}, {"cable_d": 3, "count": 4, "base_w": 8}, {"cable_d": 20, "count": 2, "base_w": 40}],
}


def test_list_templates_schema():
    templates = {t["name"]: t for t in list_templates()}
    assert set(templates) == set(CASES)
    for t in templates.values():
        assert t["title"] and t["description"]
        props = t["params"]["properties"]
        assert props and all("default" in p for p in props.values())
    assert templates["nametag"]["params"]["properties"]["width"]["unit"] == "mm"


@pytest.mark.parametrize("name,params", [(n, p) for n, ps in CASES.items() for p in ps])
def test_template_builds_printable_solid(tmp_path, name, params):
    a = build_template(name, params, tmp_path)
    assert a.watertight
    assert all(0 < d <= A1_BUILD_MM for d in a.bbox_mm), a.bbox_mm
    assert a.volume_cm3 > 0
    for f in (a.stl, a.glb, a.usdz, a.png):
        assert f.exists() and f.stat().st_size > 0


def test_template_dimensions_follow_params(tmp_path):
    tag = build_template("nametag", {"width": 90, "height": 28, "thickness": 3}, tmp_path / "tag")
    assert tag.bbox_mm[0] == pytest.approx(90, abs=0.05)
    assert tag.bbox_mm[1] == pytest.approx(28, abs=0.05)
    assert tag.bbox_mm[2] == pytest.approx(4, abs=0.05)  # plate + 1 mm raised text/border
    ring = build_template("keychain_ring", {"outer_d": 12, "thickness": 3}, tmp_path / "ring")
    assert ring.bbox_mm[0] == pytest.approx(12, abs=0.05) and ring.bbox_mm[2] == pytest.approx(3, abs=0.01)
    cup = build_template("holder", {}, tmp_path / "cup")  # 60x30 item + 2*0.5 clearance + 2*2 wall
    assert cup.bbox_mm == pytest.approx((65, 35, 34), abs=0.05)


@pytest.mark.parametrize("name,params,match", [
    ("teapot", {}, "unknown template"),
    ("nametag", {"width": 500}, "between"),
    ("nametag", {"colour": "red"}, "unknown params"),
    ("knob", {"grip_ribs": 2.5}, "whole number"),
    ("keychain_ring", {"outer_d": 8, "inner_d": 7}, "wall"),
    ("knob", {"d": 10, "shaft_d": 8}, "too small"),
])
def test_template_bad_params_raise_cad_error(tmp_path, name, params, match):
    with pytest.raises(CadError, match=match):
        build_template(name, params, tmp_path)


def test_run_cadquery_success(tmp_path):
    code = "import cadquery as cq\nresult = cq.Workplane('XY').box(20, 10, 5).faces('>Z').workplane().hole(3)\n"
    a = run_cadquery(code, tmp_path)
    assert a.watertight
    assert a.bbox_mm == pytest.approx((20, 10, 5), abs=0.01)
    assert a.png.exists() and a.usdz.exists()


def test_run_cadquery_error_has_traceback_tail(tmp_path):
    code = "import cadquery as cq\n\nresult = cq.Workplane('XY').bocks(1, 2, 3)\n"
    with pytest.raises(CadError) as ei:
        run_cadquery(code, tmp_path)
    assert "bocks" in ei.value.message
    assert '"<cadquery>", line 3' in ei.value.traceback_tail


def test_run_cadquery_requires_result(tmp_path):
    with pytest.raises(CadError, match="result"):
        run_cadquery("import cadquery as cq\nshape = cq.Workplane().box(1, 1, 1)\n", tmp_path)


def test_run_cadquery_blocks_other_imports(tmp_path):
    with pytest.raises(CadError, match="not allowed"):
        run_cadquery("import os\nresult = None\n", tmp_path)


def test_run_cadquery_blocks_sockets_even_after_import_escape(tmp_path):
    # The import allowlist is best effort; the audit hook still stops network use.
    code = (
        "import cadquery as cq\n"
        "b = cq.__builtins__\n"
        "imp = b['__import__'] if isinstance(b, dict) else b.__import__\n"
        "imp('socket').socket()\n"
    )
    with pytest.raises(CadError, match="blocked in sandbox: socket"):
        run_cadquery(code, tmp_path)


def test_run_cadquery_time_limit(tmp_path):
    with pytest.raises(CadError, match="time limit|timed out"):
        run_cadquery("while True:\n    pass\n", tmp_path, timeout_s=5)


def test_run_cadquery_memory_limit(tmp_path):
    with pytest.raises(CadError, match="MemoryError"):
        run_cadquery("x = bytearray(8 * 1024**3)\n", tmp_path)
