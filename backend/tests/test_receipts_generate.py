"""Generators write non-empty valid STL / OBJ zip files whose bounding boxes match docs/CONTRACT.md (±1 mm)."""
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
import trimesh

from receipts.core import Pipeline
from receipts.generate import generate_files, obj_zip_extents, placeholder_png
from receipts.models import FAILED, GENERATED, Settings
from receipts.whop import MockWhop

FIXTURE = json.loads((Path(__file__).parents[1] / "receipts" / "fixtures" / "mock_payments.json").read_text())
META = {p["metadata"]["product"]: p["metadata"] for p in FIXTURE[:4]}
LONG_TWEET = ("Shipped it. " * 30)[:280]

# CONTRACT "Print geometry": slab + raised text (tweet 6 + 0.8, plaques 8 + 1); full colour = base 15 + panel 100.
EXPECTED = {"tweet": (120, 80, 6.8), "milestone": (140, 100, 9), "team": (140, 100, 9), "fullcolour": (150, 30, 115)}


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    out = {}
    for product, meta in META.items():
        if product == "tweet":
            meta = {**meta, "tweet_text": LONG_TWEET}
        d = tmp_path_factory.mktemp(product)
        out[product] = generate_files(product, meta, meta["colour"], "007", d, image_bytes=placeholder_png())
    return out


@pytest.mark.parametrize("product", ["tweet", "milestone", "team"])
def test_stl_bbox_matches_contract(files, product):
    path = files[product]["main"]
    assert path.suffix == ".stl" and path.stat().st_size > 10_000
    mesh = trimesh.load(str(path), force="mesh")
    assert mesh.is_watertight and mesh.volume > 0
    assert mesh.extents == pytest.approx(EXPECTED[product], abs=1.0)
    # raised text exists above the slab top
    assert mesh.bounds[1][2] > EXPECTED[product][2] - 0.2
    stand = trimesh.load(str(files[product]["stand"]), force="mesh")
    assert stand.is_watertight and stand.volume > 0


def test_fullcolour_zip(files):
    path = files["fullcolour"]["main"]
    assert path.suffix == ".zip" and path.stat().st_size > 1000
    with zipfile.ZipFile(path) as z:
        assert set(z.namelist()) == {"model.obj", "model.mtl", "screenshot.png"}
        obj, mtl = z.read("model.obj").decode(), z.read("model.mtl").decode()
        from PIL import Image

        img = Image.open(io.BytesIO(z.read("screenshot.png")))
        assert img.size[0] * 2 == img.size[1] * 3
    assert "mtllib model.mtl" in obj and "usemtl screen" in obj and "vt 1 1" in obj
    assert "map_Kd screenshot.png" in mtl
    assert obj_zip_extents(path) == pytest.approx(EXPECTED["fullcolour"], abs=1.0)


def test_fullcolour_fetches_screenshot_from_site(tmp_path):
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        if req.url.path == "/api/admin/upload/up123":
            return httpx.Response(200, content=placeholder_png(), headers={"content-type": "image/png"})
        return httpx.Response(200, json={"ok": True})

    s = Settings(data_dir=tmp_path, mock=False, site_url="https://site.test", site_admin_token="tok")
    pay = {**FIXTURE[2], "metadata": {**FIXTURE[2]["metadata"], "upload_id": "up123"}}
    p = Pipeline(s, whop=MockWhop([pay]), slant=object(), craftcloud=object(),
                 site=httpx.Client(transport=httpx.MockTransport(handler)))
    (o,) = p.poll_whop()
    path = p.generate(o)
    assert path.exists() and p.store.get(o.seq).status == GENERATED
    up = [r for r in seen if r.method == "GET"]
    assert up and up[0].headers["authorization"] == "Bearer tok"


def test_fullcolour_without_screenshot_fails_when_live(tmp_path):
    s = Settings(data_dir=tmp_path, mock=False)
    pay = {**FIXTURE[2], "metadata": {k: v for k, v in FIXTURE[2]["metadata"].items() if k != "upload_id"}}
    p = Pipeline(s, whop=MockWhop([pay]), slant=object(), craftcloud=object())
    (o,) = p.poll_whop()
    with pytest.raises(Exception):
        p.generate(o)
    assert p.store.get(o.seq).status == FAILED
