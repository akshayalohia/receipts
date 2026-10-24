"""Test doubles: a fake `factory` pipeline, a fake printer and a fake Hermes API."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import httpx

APP_HEADERS = {"X-App-Key": "test-app-key", "X-Device-Id": "dev-1"}
ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}
WEBHOOK_SECRET = "ws_test_secret_value"

DEFAULT_POLICY = {"base_cents": 300, "per_gram_cents": 6, "per_hour_cents": 250,
                  "queue_surcharge_cents": 200, "queue_threshold": 2, "colour_swap_cents": 200,
                  "floors_cents": {"nametag": 800, "fixit": 1000, "holder": 1200, "keychain": 1200,
                                   "figurine": 1500, "custom": 800}}


@dataclass
class Artifact:
    stl: Path
    glb: Path
    usdz: Path
    png: Path
    bbox_mm: tuple[float, float, float]
    watertight: bool
    volume_cm3: float


@dataclass
class SliceResult:
    gcode_3mf: Path
    print_seconds: int
    filament_grams: float


@dataclass
class Quote:
    price_cents: int
    print_seconds: int
    filament_grams: float
    breakdown: dict


@dataclass
class PrinterStatus:
    state: str
    progress_pct: int = 0
    remaining_min: int = 0
    layer: int = 0
    total_layers: int = 0
    job_name: str | None = None
    raw: dict = field(default_factory=dict)


class FakePrinter:
    def __init__(self) -> None:
        self.state = "IDLE"
        self.progress = 0
        self.calls: list[tuple] = []

    def start(self, gcode_3mf: Path, job_name: str) -> None:
        assert Path(gcode_3mf).is_file()
        self.calls.append(("start", job_name))
        self.state = "RUNNING"

    def status(self) -> PrinterStatus:
        return PrinterStatus(self.state, self.progress, 10, 5, 100)

    def pause(self) -> None:
        self.calls.append(("pause",))
        self.state = "PAUSE"

    def resume(self) -> None:
        self.calls.append(("resume",))
        self.state = "RUNNING"

    def stop(self) -> None:
        self.calls.append(("stop",))
        self.state = "IDLE"

    def snapshot_jpeg(self) -> bytes:
        return b"\xff\xd8fake-jpeg\xff\xd9"


def _artifact(out_dir: Path, watertight: bool = True) -> Artifact:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for ext in ("stl", "glb", "usdz", "png"):
        p = out_dir / f"model.{ext}"
        p.write_bytes(f"fake {ext}".encode())
        paths[ext] = p
    return Artifact(bbox_mm=(80.0, 25.0, 4.0), watertight=watertight, volume_cm3=6.5, **paths)


class FakePipeline:
    def __init__(self) -> None:
        self.printer = FakePrinter()
        self.verdicts: list[str] = []
        self.calls: list[str] = []

    def list_templates(self):
        return [{"name": "nametag", "title": "Name tag", "description": "Raised text plate",
                 "params": {"text": {"type": "string", "default": "NAME"}}}]

    def build_template(self, name, params, out_dir):
        self.calls.append(f"build_template:{name}")
        return _artifact(Path(out_dir))

    def run_cadquery(self, code, out_dir, timeout_s=90):
        self.calls.append("run_cadquery")
        return _artifact(Path(out_dir))

    def generate_from_images(self, image_paths, out_dir, prompt=None):
        self.calls.append("generate_from_images")
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        raw = Path(out_dir) / "raw.glb"
        raw.write_bytes(b"raw")
        return raw

    def finish_for_print(self, src, out_dir, *, target_height_mm=None, max_dim_mm=250, add_base=False, keyring=False):
        self.calls.append("finish_for_print")
        return _artifact(Path(out_dir))

    def combine(self, a, b, out_dir, op="union"):
        self.calls.append("combine")
        return _artifact(Path(out_dir))

    def to_all_formats(self, mesh_path, out_dir):
        return _artifact(Path(out_dir), watertight=False)

    def slice_model(self, stl, out_dir):
        self.calls.append("slice_model")
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        g = Path(out_dir) / "plate.gcode.3mf"
        g.write_bytes(b"gcode")
        return SliceResult(g, 1200, 12.5)

    def quote(self, s, *, product, gen_cost_cents, queue_len, colour_loaded, policy=None):
        p = policy or DEFAULT_POLICY
        cost = (p["base_cents"] + round(s.filament_grams * p["per_gram_cents"])
                + round(s.print_seconds / 3600 * p["per_hour_cents"]) + gen_cost_cents)
        price = max(p["floors_cents"].get(product, 800), cost)
        if not colour_loaded:
            price += p["colour_swap_cents"]
        return Quote(price, s.print_seconds, s.filament_grams, {"cost": cost, "price": price})

    def default_policy(self):
        return json.loads(json.dumps(DEFAULT_POLICY))

    def load_policy(self, path):
        return json.loads(Path(path).read_text())

    def save_policy(self, path, policy):            # no clamping here: the service must clamp
        Path(path).write_text(json.dumps(policy))
        return policy

    def get_printer(self):
        return self.printer

    def check_snapshot(self, jpeg):
        verdict = self.verdicts.pop(0) if self.verdicts else "ok"
        return {"verdict": verdict, "confidence": 0.9}


def designed_order(core, product: str = "nametag", device: str = "dev-1") -> dict:
    """An order with a published design (status review), built through the core tools."""
    order = core.db.create_order(device, product, None)
    art = core.build_template(order["id"], "nametag", {"text": "AKSHAYA"}, "intake")
    core.publish_design(order["id"], art["artifact_id"], "Name tag, 80 mm", "intake")
    return core.db.get_order(order["id"])


class FakeHermes:
    """httpx MockTransport handler mimicking /p/<profile>/v1/runs and its events stream."""

    def __init__(self) -> None:
        self.runs: list[dict] = []
        self.hooks: dict[str, Callable[[dict], None]] = {}
        self.replies: dict[str, list[str]] = {}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def profiles(self) -> list[str]:
        return [r["profile"] for r in self.runs]

    def handle(self, request: httpx.Request) -> httpx.Response:
        parts = request.url.path.strip("/").split("/")     # p/<profile>/v1/runs[/<id>/events]
        assert parts[0] == "p" and parts[2:4] == ["v1", "runs"], request.url.path
        profile = parts[1]
        if request.headers.get("authorization") != f"Bearer test-hermes-key-{profile}":
            return httpx.Response(401, json={"error": "bad key"})
        if request.method == "POST" and len(parts) == 4:
            body = json.loads(request.content)
            run_id = f"run_{len(self.runs) + 1}"
            self.runs.append({"profile": profile, "run_id": run_id, "body": body,
                              "idempotency_key": request.headers.get("idempotency-key")})
            if profile in self.hooks:
                self.hooks[profile](body)
            return httpx.Response(202, json={"run_id": run_id, "status": "started"})
        if request.method == "GET" and len(parts) == 6 and parts[5] == "events":
            pieces = self.replies.get(profile, ["On it."])
            frames = [": keepalive\n\n"]
            frames += [f"event: message.delta\ndata: {json.dumps({'delta': p})}\n\n" for p in pieces]
            frames.append("event: tool.started\ndata: {\"tool\": \"mcp__factory__get_order\"}\n\n")
            frames.append(f"event: run.completed\ndata: {json.dumps({'output': ''.join(pieces), 'completed': True})}\n\n")
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content="".join(frames).encode())
        return httpx.Response(404)
