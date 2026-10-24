"""Mesh format conversion: STL (mm) + GLB + USDZ + PNG preview.

Internal convention everywhere in `factory`: millimetres, Z up, model resting on z=0.
"""
from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np
import trimesh

from .types import Artifact

# glTF is metres, Y up. (x, y, z)_zup -> (x, z, -y)_yup is a proper rotation (det +1).
_ZUP_TO_YUP = np.array([[1.0, 0, 0], [0, 0, 1.0], [0, -1.0, 0]])
PLA_RGB = (0.36, 0.55, 0.85)
PNG_PX = 800
_RENDER_MAX_FACES = 40_000


def load_mesh(path: Path) -> trimesh.Trimesh:
    """Load any mesh file as one Trimesh in mm, Z up. GLB/GLTF are read as metres, Y up (glTF spec)."""
    path = Path(path)
    mesh = trimesh.load(str(path), force="mesh")
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ValueError(f"no triangle mesh in {path.name}")
    if path.suffix.lower() in (".glb", ".gltf"):
        mesh.vertices = (mesh.vertices @ _ZUP_TO_YUP) * 1000.0  # inverse rotation = transpose
    return mesh


def to_all_formats(mesh_path: Path, out_dir: Path) -> Artifact:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mesh = load_mesh(mesh_path)
    stl, glb, usdz, png = (out_dir / f"model.{ext}" for ext in ("stl", "glb", "usdz", "png"))
    mesh.export(str(stl), file_type="stl")
    _write_glb(mesh, glb)
    _write_usdz(mesh, usdz)
    _render_png(mesh, png)
    ext = mesh.extents
    return Artifact(
        stl=stl, glb=glb, usdz=usdz, png=png,
        bbox_mm=(round(float(ext[0]), 3), round(float(ext[1]), 3), round(float(ext[2]), 3)),
        watertight=bool(mesh.is_watertight),
        volume_cm3=round(abs(float(mesh.volume)) / 1000.0, 3) if mesh.is_watertight else 0.0,
    )


def _write_glb(mesh: trimesh.Trimesh, path: Path) -> None:
    m = trimesh.Trimesh(vertices=(mesh.vertices @ _ZUP_TO_YUP.T) * 0.001, faces=mesh.faces, process=False)
    m.visual = trimesh.visual.ColorVisuals(m, face_colors=[int(c * 255) for c in PLA_RGB] + [255])
    m.export(str(path), file_type="glb")


def _write_usdz(mesh: trimesh.Trimesh, path: Path) -> None:
    # Scale decision: geometry is converted to METRES and the stage says metersPerUnit = 1.0, upAxis = Y.
    # Metres are RealityKit's native unit and AR Quick Look honours metersPerUnit, so the model shows
    # at true physical size. (The alternative, mm + metersPerUnit 0.001, was not used.)
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdUtils, Vt

    shaded = mesh.smooth_shaded  # splits vertices at sharp edges so CAD edges stay crisp
    pts = ((shaded.vertices @ _ZUP_TO_YUP.T) * 0.001).astype(np.float32)
    nrm = (shaded.vertex_normals @ _ZUP_TO_YUP.T).astype(np.float32)
    faces = np.asarray(shaded.faces, dtype=np.int32)
    with tempfile.TemporaryDirectory(prefix="usd_") as tmp:
        usdc = Path(tmp) / "model.usdc"
        stage = Usd.Stage.CreateNew(str(usdc))
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        root = UsdGeom.Xform.Define(stage, "/Model")
        stage.SetDefaultPrim(root.GetPrim())
        geom = UsdGeom.Mesh.Define(stage, "/Model/Geom")
        geom.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(pts))
        geom.CreateNormalsAttr(Vt.Vec3fArray.FromNumpy(nrm))
        geom.SetNormalsInterpolation(UsdGeom.Tokens.vertex)
        geom.CreateFaceVertexCountsAttr(Vt.IntArray.FromNumpy(np.full(len(faces), 3, dtype=np.int32)))
        geom.CreateFaceVertexIndicesAttr(Vt.IntArray.FromNumpy(faces.ravel()))
        geom.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        geom.CreateExtentAttr(Vt.Vec3fArray([Gf.Vec3f(*map(float, lo)), Gf.Vec3f(*map(float, hi))]))
        mat = UsdShade.Material.Define(stage, "/Model/Materials/PLA")
        shader = UsdShade.Shader.Define(stage, "/Model/Materials/PLA/Surface")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*PLA_RGB))
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.6)
        shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
        mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
        UsdShade.MaterialBindingAPI.Apply(geom.GetPrim()).Bind(mat)
        stage.GetRootLayer().Save()
        if path.exists():
            path.unlink()
        if not UsdUtils.CreateNewARKitUsdzPackage(Sdf.AssetPath(str(usdc)), str(path)):
            raise RuntimeError("USDZ packaging failed")


def _decimate(mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh:
    import pymeshlab

    ms = pymeshlab.MeshSet()
    ms.add_mesh(pymeshlab.Mesh(vertex_matrix=mesh.vertices, face_matrix=mesh.faces))
    ms.meshing_decimation_quadric_edge_collapse(targetfacenum=target_faces, preservenormal=True)
    m = ms.current_mesh()
    return trimesh.Trimesh(vertices=m.vertex_matrix(), faces=m.face_matrix())


def _render_png(mesh: trimesh.Trimesh, path: Path) -> None:
    """Headless 3/4-view shaded render with matplotlib's Agg canvas (no display, no GPU)."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    m = _decimate(mesh, _RENDER_MAX_FACES) if len(mesh.faces) > _RENDER_MAX_FACES else mesh
    elev, azim = math.radians(25), math.radians(-60)
    eye = np.array([math.cos(elev) * math.cos(azim), math.cos(elev) * math.sin(azim), math.sin(elev)])
    front = m.face_normals @ eye > 0  # back-face culling keeps matplotlib's painter sort clean
    faces, normals = m.faces[front], m.face_normals[front]
    light = np.array([0.35, -0.55, 0.75])
    light /= np.linalg.norm(light)
    shade = 0.3 + 0.7 * np.clip(normals @ light, 0.0, 1.0)
    colours = np.column_stack([np.outer(shade, PLA_RGB), np.ones(len(shade))])

    fig = Figure(figsize=(PNG_PX / 100, PNG_PX / 100), dpi=100, facecolor="#f3f4f6")
    FigureCanvasAgg(fig)
    ax = fig.add_axes((0, 0, 1, 1), projection="3d")
    ax.set_facecolor("#f3f4f6")
    # edges painted in the face colour hide the anti-aliasing seams between triangles
    ax.add_collection3d(Poly3DCollection(m.vertices[faces], facecolors=colours, edgecolors=colours, linewidths=0.3))
    lo, hi = m.bounds
    ext = np.maximum(hi - lo, (hi - lo).max() * 0.05)
    centre = (lo + hi) / 2
    ax.set_xlim(centre[0] - ext[0] / 2, centre[0] + ext[0] / 2)
    ax.set_ylim(centre[1] - ext[1] / 2, centre[1] + ext[1] / 2)
    ax.set_zlim(centre[2] - ext[2] / 2, centre[2] + ext[2] / 2)
    ax.set_box_aspect(tuple(ext), zoom=0.85)
    ax.view_init(elev=math.degrees(elev), azim=math.degrees(azim))
    ax.set_axis_off()
    fig.savefig(str(path), dpi=100, facecolor=fig.get_facecolor())
