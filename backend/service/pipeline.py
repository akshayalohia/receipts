"""The only module that touches BE1's `factory` package.

`factory` is imported lazily, so the service, MCP server and tests load without it.
Signatures mirror SPEC.md "BE1: factory library". Tests swap in a fake with
`set_pipeline(...)`; everything else calls `get_pipeline()`.
"""
from __future__ import annotations

import importlib
import threading
from pathlib import Path
from typing import Any, Protocol


class Pipeline(Protocol):
    def list_templates(self) -> list[dict]: ...
    def build_template(self, name: str, params: dict, out_dir: Path) -> Any: ...
    def run_cadquery(self, code: str, out_dir: Path, timeout_s: int = 90) -> Any: ...
    def generate_from_images(self, image_paths: list[Path], out_dir: Path, prompt: str | None = None) -> Path: ...
    def finish_for_print(self, src: Path, out_dir: Path, *, target_height_mm: float | None = None,
                         max_dim_mm: float = 250, add_base: bool = False, keyring: bool = False) -> Any: ...
    def combine(self, a: Path, b: Path, out_dir: Path, op: str = "union") -> Any: ...
    def to_all_formats(self, mesh_path: Path, out_dir: Path) -> Any: ...
    def slice_model(self, stl: Path, out_dir: Path) -> Any: ...
    def quote(self, s: Any, *, product: str, gen_cost_cents: int, queue_len: int,
              colour_loaded: bool, policy: dict | None = None) -> Any: ...
    def default_policy(self) -> dict: ...
    def load_policy(self, path: Path) -> dict: ...
    def save_policy(self, path: Path, policy: dict) -> dict: ...
    def get_printer(self) -> Any: ...
    def check_snapshot(self, jpeg: bytes) -> dict: ...


class FactoryPipeline:
    """Adapter over the real `factory` package (imported on first use)."""

    def __init__(self) -> None:
        self._printer = None
        self._lock = threading.Lock()

    @staticmethod
    def _mod(name: str):
        return importlib.import_module(f"factory.{name}")

    def list_templates(self) -> list[dict]:
        return self._mod("cad").list_templates()

    def build_template(self, name, params, out_dir):
        return self._mod("cad").build_template(name, params, Path(out_dir))

    def run_cadquery(self, code, out_dir, timeout_s=90):
        return self._mod("cad").run_cadquery(code, Path(out_dir), timeout_s=timeout_s)

    def generate_from_images(self, image_paths, out_dir, prompt=None):
        return self._mod("mesh").generate_from_images([Path(p) for p in image_paths], Path(out_dir), prompt=prompt)

    def finish_for_print(self, src, out_dir, *, target_height_mm=None, max_dim_mm=250,
                         add_base=False, keyring=False):
        return self._mod("mesh").finish_for_print(
            Path(src), Path(out_dir), target_height_mm=target_height_mm, max_dim_mm=max_dim_mm,
            add_base=add_base, keyring=keyring)

    def combine(self, a, b, out_dir, op="union"):
        return self._mod("mesh").combine(Path(a), Path(b), Path(out_dir), op=op)

    def to_all_formats(self, mesh_path, out_dir):
        return self._mod("convert").to_all_formats(Path(mesh_path), Path(out_dir))

    def slice_model(self, stl, out_dir):
        return self._mod("slicer").slice_model(Path(stl), Path(out_dir))

    def quote(self, s, *, product, gen_cost_cents, queue_len, colour_loaded, policy=None):
        return self._mod("pricing").quote(s, product=product, gen_cost_cents=gen_cost_cents,
                                          queue_len=queue_len, colour_loaded=colour_loaded, policy=policy)

    def default_policy(self) -> dict:
        return dict(self._mod("pricing").DEFAULT_POLICY)

    def load_policy(self, path):
        return self._mod("pricing").load_policy(Path(path))

    def save_policy(self, path, policy):
        return self._mod("pricing").save_policy(Path(path), policy)

    def get_printer(self):
        with self._lock:
            if self._printer is None:
                self._printer = self._mod("printer").get_printer()
            return self._printer

    def check_snapshot(self, jpeg):
        return self._mod("failure").check_snapshot(jpeg)


_pipeline: Pipeline | None = None


def get_pipeline() -> Pipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = FactoryPipeline()
    return _pipeline


def set_pipeline(pipeline: Pipeline | None) -> None:
    global _pipeline
    _pipeline = pipeline
