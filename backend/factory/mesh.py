"""Organic meshes: Meshy multi-image-to-3D, print finishing (repair/orient/scale/base/keyring), booleans."""
from __future__ import annotations

import base64
import io
import logging
import os
import shutil
import time
from pathlib import Path

import httpx
import numpy as np
import trimesh
from manifold3d import Manifold, Mesh as MMesh

from . import is_mock
from .convert import load_mesh, to_all_formats
from .types import Artifact

log = logging.getLogger(__name__)

BUILD_LIMIT_MM = 250.0
MIN_WALL_MM = 1.2
MAX_THIN_FRACTION = 0.10  # refuse if more than 10% of sampled surface is thinner than MIN_WALL_MM
BASE_MM = 2.5
SAMPLE_MESH = Path(__file__).parent / "assets" / "sample_pet.stl"
MOCK_DELAY_S = 0.5


class MeshError(Exception):
    pass


# ---------------------------------------------------------------- Meshy (https://docs.meshy.ai/api/multi-image-to-3d)

class MeshyClient:
    """Multi-Image to 3D: POST /openapi/v1/multi-image-to-3d, poll GET .../{id}, download model_urls.

    Mesh only: `should_texture: false`. Model: `meshy-7.1` (the docs' newest for this endpoint).
    The endpoint has no geometry prompt (texture_prompt needs should_texture), so `prompt` is not sent.
    """

    BASE_URL = "https://api.meshy.ai"
    AI_MODEL = "meshy-7.1"
    MAX_WAIT_S = 60 * 60  # docs: wait at least 60 min from created_at before giving up
    _MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}

    def __init__(self, api_key: str, *, transport: httpx.BaseTransport | None = None,
                 sleep=time.sleep, base_url: str = BASE_URL):
        self._http = httpx.Client(base_url=base_url, transport=transport, timeout=60.0,
                                  headers={"Authorization": f"Bearer {api_key}"})
        self._sleep = sleep

    def _data_uri(self, path: Path) -> str:
        path = Path(path)
        mime = self._MIME.get(path.suffix.lower())
        data = path.read_bytes()
        if mime is None:  # e.g. HEIC/other: re-encode to JPEG if Pillow can read it
            from PIL import Image

            try:
                buf = io.BytesIO()
                Image.open(path).convert("RGB").save(buf, "JPEG", quality=92)
            except Exception as e:
                raise MeshError(f"unsupported image {path.name}: {e}") from e
            data, mime = buf.getvalue(), "image/jpeg"
        if len(data) > 20 * 1024 * 1024:
            raise MeshError(f"{path.name} is over Meshy's 20 MB per-image limit")
        return f"data:{mime};base64,{base64.b64encode(data).decode()}"

    def create_task(self, image_paths: list[Path]) -> str:
        if not 1 <= len(image_paths) <= 4:
            raise MeshError(f"Meshy takes 1-4 images, got {len(image_paths)}")
        body = {
            "image_urls": [self._data_uri(p) for p in image_paths],
            "ai_model": self.AI_MODEL,
            "should_texture": False,
            "target_formats": ["stl", "glb"],
        }
        for _ in range(4):
            r = self._http.post("/openapi/v1/multi-image-to-3d", json=body)
            if r.status_code == 429:  # 4xx: no task was created, so retrying is safe
                self._sleep(int(r.headers.get("Retry-After", 5)))
                continue
            if r.status_code >= 400:
                raise MeshError(f"Meshy create failed {r.status_code}: {r.text[:300]}")
            return r.json()["result"]
        raise MeshError("Meshy create rate-limited (429) 4 times")

    def wait(self, task_id: str) -> dict:
        start = time.monotonic()
        while time.monotonic() - start < self.MAX_WAIT_S:
            try:
                r = self._http.get(f"/openapi/v1/multi-image-to-3d/{task_id}")
            except httpx.TransportError:
                self._sleep(5)  # the task is unaffected by our network; never re-create it
                continue
            if r.status_code == 429 or r.status_code >= 500:
                self._sleep(int(r.headers.get("Retry-After", 5)))
                continue
            if r.status_code >= 400:
                raise MeshError(f"Meshy get task {task_id} failed {r.status_code}: {r.text[:300]}")
            task = r.json()
            status = task.get("status")
            if status == "SUCCEEDED":
                return task
            if status in ("FAILED", "CANCELED"):
                msg = (task.get("task_error") or {}).get("message", "")
                raise MeshError(f"Meshy task {task_id} {status}: {msg}")
            self._sleep(int(r.headers.get("Retry-After", 5)))
        raise MeshError(f"Meshy task {task_id} still running after {self.MAX_WAIT_S} s")

    def download(self, task: dict, out_dir: Path) -> Path:
        urls = task.get("model_urls") or {}
        fmt = next((f for f in ("stl", "glb") if urls.get(f)), None)
        if fmt is None:
            raise MeshError(f"Meshy task {task.get('id')} has no stl/glb in model_urls")
        req = self._http.build_request("GET", urls[fmt])
        del req.headers["Authorization"]  # signed asset URL; a second auth mechanism makes S3/CDNs refuse
        r = self._http.send(req, follow_redirects=True)
        if r.status_code >= 400:
            raise MeshError(f"Meshy download failed {r.status_code}")
        out = Path(out_dir) / f"raw_mesh.{fmt}"
        out.write_bytes(r.content)
        return out

    def generate(self, image_paths: list[Path], out_dir: Path) -> Path:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        task_id = self.create_task(image_paths)
        log.info("meshy task %s created", task_id)
        return self.download(self.wait(task_id), out_dir)


def generate_from_images(image_paths: list[Path], out_dir: Path, prompt: str | None = None) -> Path:
    key = os.environ.get("MESHY_API_KEY", "")
    out_dir = Path(out_dir)
    if is_mock() or not key:
        out_dir.mkdir(parents=True, exist_ok=True)
        time.sleep(MOCK_DELAY_S)
        out = out_dir / "raw_mesh.stl"
        shutil.copyfile(SAMPLE_MESH, out)
        return out
    return MeshyClient(key).generate([Path(p) for p in image_paths], out_dir)


# ---------------------------------------------------------------- manifold helpers

def _to_manifold(mesh: trimesh.Trimesh) -> Manifold:
    m = Manifold(MMesh(vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
                       tri_verts=np.asarray(mesh.faces, dtype=np.uint32)))
    if m.is_empty():
        raise MeshError(f"mesh is not a valid manifold ({m.status()})")
    return m


def _from_manifold(m: Manifold) -> trimesh.Trimesh:
    mm = m.to_mesh()
    return trimesh.Trimesh(vertices=np.asarray(mm.vert_properties)[:, :3], faces=np.asarray(mm.tri_verts))


def _repair(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """trimesh -> pymeshlab -> manifold3d, stopping as soon as it is a valid closed manifold."""
    mesh.merge_vertices()
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
    trimesh.repair.fill_holes(mesh)
    trimesh.repair.fix_normals(mesh)
    if not mesh.is_watertight:
        import pymeshlab

        ms = pymeshlab.MeshSet()
        ms.add_mesh(pymeshlab.Mesh(vertex_matrix=mesh.vertices, face_matrix=mesh.faces))
        ms.meshing_remove_duplicate_vertices()
        ms.meshing_remove_duplicate_faces()
        ms.meshing_repair_non_manifold_edges()
        ms.meshing_repair_non_manifold_vertices()
        ms.meshing_close_holes(maxholesize=max(30, len(mesh.faces) // 10))
        cm = ms.current_mesh()
        mesh = trimesh.Trimesh(vertices=cm.vertex_matrix(), faces=cm.face_matrix())
        trimesh.repair.fix_normals(mesh)
    if not mesh.is_watertight:
        raise MeshError("could not repair the mesh into a closed solid")
    return _from_manifold(_to_manifold(mesh))


def _orient(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Most probable stable resting pose, preferring poses that keep the model roughly upright."""
    transforms, probs = trimesh.poses.compute_stable_poses(mesh)
    if len(transforms) == 0:
        return mesh
    up = np.array([0.0, 0.0, 1.0])
    upright = [i for i, T in enumerate(transforms) if (T[:3, :3] @ up) @ up > np.cos(np.radians(45))]
    best = max(upright or range(len(transforms)), key=lambda i: probs[i])
    mesh.apply_transform(transforms[best])
    return mesh


def _footprint(mesh: trimesh.Trimesh, height: float = 1.0) -> np.ndarray:
    v = mesh.vertices
    pts = v[v[:, 2] <= v[:, 2].min() + height][:, :2]
    return pts if len(pts) >= 3 else v[:, :2]


def _thin_fraction(mesh: trimesh.Trimesh, samples: int = 400) -> float:
    pts, idx = trimesh.sample.sample_surface(mesh, samples, seed=0)
    normals = mesh.face_normals[idx]
    origins = pts - normals * 1e-3
    locs, ray_idx, _ = mesh.ray.intersects_location(origins, -normals, multiple_hits=True)
    if len(ray_idx) == 0:
        return 0.0
    d = np.linalg.norm(locs - origins[ray_idx], axis=1)
    thick = np.full(samples, np.inf)
    np.minimum.at(thick, ray_idx, np.where(d > 1e-3, d, np.inf))
    return float(np.mean(thick < MIN_WALL_MM))


def _keyring_mesh() -> tuple[trimesh.Trimesh, float]:
    from .cad import _TEMPLATES, keychain_ring, shape_to_trimesh

    defaults = {k: v["default"] for k, v in _TEMPLATES["keychain_ring"]["params"].items()}
    return shape_to_trimesh(keychain_ring(**defaults)), defaults["outer_d"] / 2


def finish_for_print(src: Path, out_dir: Path, *, target_height_mm: float | None = None,
                     max_dim_mm: float = 250, add_base: bool = False, keyring: bool = False) -> Artifact:
    max_dim = min(float(max_dim_mm), BUILD_LIMIT_MM)
    try:
        mesh = _repair(load_mesh(src))
    except ValueError as e:
        raise MeshError(str(e)) from e
    mesh = _orient(mesh)
    mesh.apply_translation(-np.array([*mesh.bounds.mean(axis=0)[:2], mesh.bounds[0][2]]))

    base_h = BASE_MM - 0.5 if add_base else 0.0  # base overlaps the model by 0.5 mm
    if target_height_mm:
        model_h = float(target_height_mm) - base_h
        if model_h <= 2:
            raise MeshError(f"target_height_mm {target_height_mm} is too small")
        mesh.apply_scale(model_h / mesh.extents[2])
    if max(mesh.extents) > max_dim:
        mesh.apply_scale(max_dim / max(mesh.extents))
    h = float(mesh.extents[2])
    cut = min(0.6, 0.02 * h)
    mesh.apply_scale((h + cut) / h)  # pre-stretch so the height after the bottom trim is still h

    # Flat bottom: trim a thin slice so the part sits on a real contact patch, not on points.
    solid = _to_manifold(mesh).trim_by_plane([0.0, 0.0, 1.0], cut).translate([0.0, 0.0, -cut])

    if add_base:
        fp = _footprint(_from_manifold(solid), 2.0)
        lo, hi = fp.min(axis=0), fp.max(axis=0)
        c, r = (lo + hi) / 2, (hi - lo) / 2 * np.sqrt(2) + 2.0  # ellipse circumscribing the footprint box
        base = Manifold.cylinder(BASE_MM, 1.0, 1.0, 96).scale([r[0], r[1], 1.0]).translate([c[0], c[1], 0.0])
        solid = base + solid.translate([0.0, 0.0, base_h])

    if keyring:
        ring, r_out = _keyring_mesh()
        fp = _footprint(_from_manifold(solid), 1.0)
        x_min = fp[:, 0].min()
        y = float(fp[fp[:, 0] < x_min + 2.0][:, 1].mean())
        solid = solid + _to_manifold(ring).translate([x_min - r_out + 2.0, y, 0.0])

    out = _from_manifold(solid)
    if max(out.extents) > max_dim:
        out.apply_scale(max_dim / max(out.extents))
    out.apply_translation(-np.array([*out.bounds.mean(axis=0)[:2], out.bounds[0][2]]))

    if not out.is_watertight:
        raise MeshError("finished mesh is not watertight")
    thin = _thin_fraction(out)
    if thin > MAX_THIN_FRACTION:
        raise MeshError(f"{thin:.0%} of the surface is thinner than {MIN_WALL_MM} mm; make it bigger")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stl = out_dir / "model.stl"
    out.export(str(stl), file_type="stl")
    return to_all_formats(stl, out_dir)


def combine(a: Path, b: Path, out_dir: Path, op: str = "union") -> Artifact:
    ops = {"union": lambda x, y: x + y, "difference": lambda x, y: x - y, "intersection": lambda x, y: x ^ y}
    if op not in ops:
        raise MeshError(f"op must be one of {sorted(ops)}")
    ma, mb = _to_manifold(_repair(load_mesh(a))), _to_manifold(_repair(load_mesh(b)))
    out = _from_manifold(ops[op](ma, mb))
    if len(out.faces) == 0:
        raise MeshError(f"{op} produced an empty solid")
    if not out.is_watertight:
        raise MeshError(f"{op} result is not watertight")
    if max(out.extents) > BUILD_LIMIT_MM:
        raise MeshError(f"{op} result {np.round(out.extents, 1).tolist()} mm exceeds {BUILD_LIMIT_MM} mm")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stl = out_dir / "model.stl"
    out.export(str(stl), file_type="stl")
    return to_all_formats(stl, out_dir)
