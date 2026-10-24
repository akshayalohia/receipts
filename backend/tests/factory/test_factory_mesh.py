import base64
import json

import httpx
import numpy as np
import pytest
import trimesh
from PIL import Image

from factory.mesh import (SAMPLE_MESH, MeshError, MeshyClient, combine, finish_for_print,
                          generate_from_images)


@pytest.fixture
def broken_stl(tmp_path):
    mesh = trimesh.load(str(SAMPLE_MESH))
    keep = np.ones(len(mesh.faces), bool)
    keep[np.random.default_rng(1).choice(len(mesh.faces), 40, replace=False)] = False  # 40 holes
    mesh.update_faces(keep)
    path = tmp_path / "broken.stl"
    mesh.export(str(path))
    assert not trimesh.load(str(path)).is_watertight
    return path


def test_generate_from_images_mock_returns_sample(tmp_path):
    img = tmp_path / "pet.jpg"
    Image.new("RGB", (32, 32), (120, 90, 60)).save(img)
    out = generate_from_images([img], tmp_path / "gen", prompt="my dog")
    assert out.exists() and out.suffix == ".stl"
    assert trimesh.load(str(out)).is_watertight


def test_finish_repairs_broken_mesh(tmp_path, broken_stl):
    a = finish_for_print(broken_stl, tmp_path / "out")
    assert a.watertight
    assert trimesh.load(str(a.stl)).is_watertight
    assert max(a.bbox_mm) <= 250


def test_finish_target_height_keyring_and_base(tmp_path):
    key = finish_for_print(SAMPLE_MESH, tmp_path / "key", target_height_mm=40, keyring=True)
    assert key.watertight and key.bbox_mm[2] == pytest.approx(40, abs=0.05)
    plain = finish_for_print(SAMPLE_MESH, tmp_path / "plain", target_height_mm=40)
    assert plain.watertight and key.volume_cm3 > plain.volume_cm3  # ring was unioned on
    based = finish_for_print(SAMPLE_MESH, tmp_path / "base", target_height_mm=70, add_base=True)
    assert based.watertight and based.bbox_mm[2] == pytest.approx(70, abs=0.05)
    bottom = trimesh.load(str(based.stl))
    on_bed = bottom.vertices[:, 2] < 1e-6
    assert np.ptp(bottom.vertices[on_bed][:, 0]) > 0.6 * bottom.extents[0]  # base gives a wide flat footprint


def test_finish_enforces_max_dim(tmp_path):
    big = trimesh.load(str(SAMPLE_MESH))
    big.apply_scale(10)  # ~540 mm long
    src = tmp_path / "big.stl"
    big.export(str(src))
    a = finish_for_print(src, tmp_path / "out")
    assert max(a.bbox_mm) <= 250 + 1e-6
    b = finish_for_print(src, tmp_path / "out2", max_dim_mm=100)
    assert max(b.bbox_mm) <= 100 + 1e-6


def test_combine_union_and_difference(tmp_path):
    a, b = tmp_path / "a.stl", tmp_path / "b.stl"
    trimesh.creation.box((20, 20, 20)).export(str(a))
    trimesh.creation.box((20, 20, 20), transform=trimesh.transformations.translation_matrix((10, 0, 0))).export(str(b))
    u = combine(a, b, tmp_path / "u")
    assert u.watertight and u.volume_cm3 == pytest.approx(12.0, rel=1e-3)
    d = combine(a, b, tmp_path / "d", op="difference")
    assert d.watertight and d.volume_cm3 == pytest.approx(4.0, rel=1e-3)
    with pytest.raises(MeshError):
        combine(a, b, tmp_path / "x", op="xor")


def _images(tmp_path, n=2):
    paths = []
    for i in range(n):
        p = tmp_path / f"view{i}.{'jpg' if i == 0 else 'png'}"
        Image.new("RGB", (16, 16), (40 * i, 80, 120)).save(p)
        paths.append(p)
    return paths


def test_meshy_client_against_mock_transport(tmp_path):
    stl_bytes = SAMPLE_MESH.read_bytes()
    calls, polls = [], iter([
        ({"id": "t1", "status": "PENDING", "progress": 0}, {"Retry-After": "2"}),
        ({"id": "t1", "status": "IN_PROGRESS", "progress": 60}, {}),
        ({"id": "t1", "status": "SUCCEEDED", "progress": 100,
          "model_urls": {"glb": "https://assets.meshy.ai/t1/model.glb?Expires=1",
                         "stl": "https://assets.meshy.ai/t1/model.stl?Expires=1"}}, {}),
    ])

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.method == "POST" and req.url.path == "/openapi/v1/multi-image-to-3d":
            return httpx.Response(202, json={"result": "t1"})
        if req.method == "GET" and req.url.path == "/openapi/v1/multi-image-to-3d/t1":
            body, headers = next(polls)
            return httpx.Response(200, json=body, headers=headers)
        if req.url.host == "assets.meshy.ai" and req.url.path == "/t1/model.stl":
            return httpx.Response(200, content=stl_bytes)
        return httpx.Response(404)

    slept = []
    client = MeshyClient("sk-test", transport=httpx.MockTransport(handler), sleep=slept.append)
    out = client.generate(_images(tmp_path), tmp_path / "gen")

    post = calls[0]
    assert post.headers["Authorization"] == "Bearer sk-test"
    body = json.loads(post.content)
    assert body["ai_model"] == "meshy-7.1" and body["should_texture"] is False
    assert len(body["image_urls"]) == 2
    assert body["image_urls"][0].startswith("data:image/jpeg;base64,")
    assert body["image_urls"][1].startswith("data:image/png;base64,")
    base64.b64decode(body["image_urls"][0].split(",", 1)[1])
    assert slept == [2, 5]  # Retry-After honoured, default 5 s otherwise
    download = calls[-1]
    assert download.url.host == "assets.meshy.ai" and "Authorization" not in download.headers
    assert out.name == "raw_mesh.stl" and out.read_bytes() == stl_bytes


def test_meshy_client_failed_task(tmp_path):
    def handler(req):
        if req.method == "POST":
            return httpx.Response(202, json={"result": "t2"})
        return httpx.Response(200, json={"id": "t2", "status": "FAILED", "task_error": {"message": "bad input"}})

    client = MeshyClient("k", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(MeshError, match="FAILED: bad input"):
        client.generate(_images(tmp_path, 1), tmp_path)


def test_meshy_client_rejects_too_many_images(tmp_path):
    client = MeshyClient("k", transport=httpx.MockTransport(lambda r: httpx.Response(500)), sleep=lambda s: None)
    with pytest.raises(MeshError, match="1-4 images"):
        client.create_task(_images(tmp_path, 5))
