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

# CONTRACT "Print geometry": plaques = slab 8 + raised 1; full colour = base 15 + panel 100. The tweet trophy is one
# piece: the 120 x 80 x 6 card standing at 75 deg in a 126 x 40 x 10 two-tier stand.
EXPECTED = {"tweet": (126, 40, 84.8), "milestone": (140, 100, 9), "team": (140, 100, 9), "fullcolour": (150, 30, 115)}


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
    if product == "tweet":
        assert "stand" not in files[product] and not (path.parent / "stand.stl").exists()  # one piece
        assert len(mesh.split(only_watertight=False)) == 1
        return
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


# ---------------------------------------------------------------- tweet trophy layout

def _avatar_png() -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (200, 200), (30, 40, 60))
    ImageDraw.Draw(img).ellipse((60, 30, 140, 120), fill=(230, 200, 170))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


TWEET_META = {"product": "tweet", "tweet_url": "https://x.com/sample_handle/status/1850000000000000001",
              "tweet_text": "Shipped it.", "name": "Sample Author", "label": "@sample_handle"}


def test_tweet_uses_real_counts_only():
    from receipts.tweet_card import build_card

    _, bare = build_card(TWEET_META)
    assert bare["counts"] == {} and bare["handle"] == "@sample_handle" and bare["avatar"] == "initial"
    _, full = build_card({**TWEET_META, "likes": "12,431", "replies": "312", "reposts": "1204", "views": "1218913",
                          "verified": "true"})
    assert full["counts"] == {"replies": "312", "reposts": "1,204", "likes": "12.4K", "views": "1.2M"}
    assert full["verified"] is True


def test_tweet_long_text_fits_and_strokes_are_printable():
    from manifold3d import JoinType

    from receipts.tweet_card import build_card, font

    _, info = build_card({**TWEET_META, "tweet_text": LONG_TWEET})
    assert info["cap"] >= 2.6 and not info["lines"][-1].endswith("…")
    f = font()
    for cap in (2.6, 2.8, 3.5):
        cs = f.line("Shipped the thing, and it shipped back.", cap, 0, 0)
        opened = cs.offset(-0.29, JoinType.Round).offset(0.29, JoinType.Round)
        assert opened.area() / cs.area() > 0.8, cap  # strokes survive a 0.58 mm opening


def test_tweet_avatar_relief_and_founding(tmp_path):
    files = generate_files("tweet", {**TWEET_META, "likes": "5"}, "black", "42", tmp_path, avatar_bytes=_avatar_png())
    assert files["info"]["avatar"] == "photo" and files["info"]["founding"] == "#042"
    mesh = trimesh.load(str(files["main"]), force="mesh")
    assert mesh.is_watertight and mesh.extents == pytest.approx(EXPECTED["tweet"], abs=1.0)
    plain = generate_files("tweet", {**TWEET_META, "likes": "5"}, "black", None, tmp_path / "plain")
    assert plain["info"]["avatar"] == "initial" and "founding" not in plain["info"]


def test_tweet_name_truncates_without_overflow():
    from receipts.tweet_card import build_card

    _, info = build_card({**TWEET_META, "name": "A Very Long Display Name That Would Run Into The X Logo Mark"})
    assert info["name"].endswith("…")
    _, info = build_card({**TWEET_META, "name": "Sample Author With A Long Name"})
    assert not info["name"].endswith("…")


def test_tweet_assets_fill_from_syndication(tmp_path):
    seen = []

    def handler(req: httpx.Request):
        seen.append(str(req.url))
        if req.url.host == "cdn.syndication.twimg.com":
            return httpx.Response(200, json={"conversation_count": 18, "user": {
                "is_blue_verified": True, "profile_image_url_https": "https://pbs.twimg.com/profile_images/1/a_normal.jpg"}})
        if req.url.host == "pbs.twimg.com":
            return httpx.Response(200, content=_avatar_png())
        return httpx.Response(404)

    s = Settings(data_dir=tmp_path, mock=False)
    p = Pipeline(s, whop=MockWhop([]), slant=object(), craftcloud=object(),
                 site=httpx.Client(transport=httpx.MockTransport(handler)))
    meta, avatar = p.tweet_assets({**TWEET_META, "likes": "7"})
    assert meta["avatar_url"].endswith("a_400x400.jpg") and meta["verified"] == "true" and meta["replies"] == "18"
    assert meta["likes"] == "7" and "reposts" not in meta and avatar
    # mock mode never touches the network
    p2 = Pipeline(Settings(data_dir=tmp_path / "m", mock=True), whop=MockWhop([]), slant=object(), craftcloud=object())
    assert p2.tweet_assets(TWEET_META) == (TWEET_META, None)
