"""End-to-end order flow, offline.

The real service (API + MCP server in one event loop, as in service/main.py) runs on
127.0.0.1 with the real `factory` library in mock mode: Meshy, Whop, printer and vision are
mocked; CadQuery, mesh finishing, format conversion and (when OrcaSlicer is present) slicing
are real. Hermes is a stub that completes every run at once; the test plays the bots by
calling the MCP tools over streamable HTTP in the order the bots would.

Nametag: order -> message -> build_template -> publish_design -> /accept -> quote (slicer
numbers) -> signed payment.succeeded webhook -> queued. Keychain: order -> photos -> message
-> generate_mesh (mock Meshy) -> finish_mesh(keyring) -> publish_design -> /accept -> paid.
Then production: start_next_job -> MockPrinter to FINISH -> bed_clear task -> start refused
-> admin bed-cleared -> the next queued job starts and finishes.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import io
import json
import os
import socket
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from mcp_server.server import mcp_http_app
from service.app import create_app
from service.config import Settings
from service.core import Core
from service.hermes import HermesClient
from service.pipeline import FactoryPipeline

REPO = Path(__file__).resolve().parents[3]
APP_KEY, ADMIN_KEY, MCP_TOKEN, HERMES_KEY = "e2e-app-key", "e2e-admin-key", "e2e-mcp-token", "e2e-hermes"
WEBHOOK_SECRET = "ws_e2e_" + "0123456789abcdef" * 4
APP_HEADERS = {"X-App-Key": APP_KEY, "X-Device-Id": "e2e-device"}
ADMIN_HEADERS = {"X-Admin-Key": ADMIN_KEY}
EXTERNAL_KEYS = ("MESHY_API_KEY", "GEMINI_API_KEY", "PRINTER_IP", "PRINTER_SERIAL", "PRINTER_ACCESS_CODE")
ORCA_BIN = os.environ.get("ORCA_SLICER_BIN") or str(REPO / "tools/orca/squashfs-root/AppRun")
_LOCAL_LIBS = REPO / "tools/libs/root/usr/lib/x86_64-linux-gnu"
ORCA_LIBS = os.environ.get("ORCA_LD_LIBRARY_PATH") or (str(_LOCAL_LIBS) if _LOCAL_LIBS.is_dir() else "")
REAL_SLICER = Path(ORCA_BIN).exists()
MOCK_PRINT_SECONDS = 3.0
STATUS_FLOW = ["designing", "review", "quoted", "paid", "queued", "printing", "done"]
MAGIC = {"usdz": b"PK", "glb": b"glTF", "png": b"\x89PNG"}


class StubHermes:
    """Stands in for the Hermes gateway: every run completes at once with "On it."."""

    def __init__(self) -> None:
        self.runs: list[tuple[str, str]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        profile = request.url.path.strip("/").split("/")[1]           # /p/<profile>/v1/runs[...]
        if request.method == "POST":
            self.runs.append((profile, json.loads(request.content)["session_id"]))
            return httpx.Response(202, json={"run_id": f"run_{len(self.runs)}", "status": "started"})
        frames = ('event: message.delta\ndata: {"delta": "On it."}\n\n'
                  'event: run.completed\ndata: {"output": "On it."}\n\n')
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=frames.encode())


@dataclass
class Shop:
    core: Core
    api_url: str
    mcp_url: str
    hermes: StubHermes


def _listen() -> socket.socket:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    return sock


@pytest.fixture
def shop(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_MOCK", "1")
    for key in EXTERNAL_KEYS:
        monkeypatch.delenv(key, raising=False)
    if REAL_SLICER:
        monkeypatch.setenv("ORCA_SLICER_BIN", ORCA_BIN)
        monkeypatch.setenv("ORCA_LD_LIBRARY_PATH", ORCA_LIBS)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))           # Orca writes its config under HOME
    else:
        monkeypatch.delenv("ORCA_SLICER_BIN", raising=False)
    from factory import printer
    monkeypatch.setattr(printer, "_printer", printer.MockPrinter(job_seconds=MOCK_PRINT_SECONDS))

    api_sock, mcp_sock = _listen(), _listen()
    api_url = f"http://127.0.0.1:{api_sock.getsockname()[1]}"
    settings = Settings(mock=True, data_dir=tmp_path / "data", public_base_url=api_url,
                        app_shared_secret=APP_KEY, admin_key=ADMIN_KEY, whop_webhook_secret=WEBHOOK_SECRET,
                        hermes_api_base="http://hermes.test", hermes_api_key=HERMES_KEY, mcp_token=MCP_TOKEN,
                        printer_poll_s=0.2, snapshot_every_s=1.0)
    hermes = StubHermes()
    core = Core(settings, pipeline=FactoryPipeline(),
                hermes=HermesClient(settings.hermes_api_base, HERMES_KEY, transport=httpx.MockTransport(hermes.handle)))
    api = uvicorn.Server(uvicorn.Config(create_app(core), log_level="warning", timeout_graceful_shutdown=1))
    mcp = uvicorn.Server(uvicorn.Config(mcp_http_app(core), log_level="warning", timeout_graceful_shutdown=1))

    async def serve_both():
        await asyncio.gather(api.serve(sockets=[api_sock]), mcp.serve(sockets=[mcp_sock]))

    thread = threading.Thread(target=lambda: asyncio.run(serve_both()), daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not (api.started and mcp.started) and time.time() < deadline:
        time.sleep(0.05)
    assert api.started and mcp.started
    yield Shop(core, api_url, f"http://127.0.0.1:{mcp_sock.getsockname()[1]}/mcp", hermes)
    api.should_exit = mcp.should_exit = True
    thread.join(15)


class Stream:
    """Reads /orders/{id}/stream on a thread until the bed_clear task after the print."""

    def __init__(self, api_url: str, order_id: str) -> None:
        self.events: list[tuple[str, dict]] = []
        self._cv = threading.Condition()
        self._connected = threading.Event()
        threading.Thread(target=self._run, args=(api_url, order_id), daemon=True).start()
        assert self._connected.wait(10), "SSE stream did not connect"

    def _run(self, api_url: str, order_id: str) -> None:
        with httpx.Client(base_url=api_url, headers=APP_HEADERS, timeout=httpx.Timeout(10, read=120)) as http:
            with http.stream("GET", f"/orders/{order_id}/stream") as resp:
                name = None
                for line in resp.iter_lines():
                    if line == ": connected":
                        self._connected.set()
                    elif line.startswith("event:"):
                        name = line[6:].strip()
                    elif line.startswith("data:") and name:
                        data = json.loads(line[5:])
                        with self._cv:
                            self.events.append((name, data))
                            self._cv.notify_all()
                        if name == "human_task" and data.get("kind") == "bed_clear":
                            return
                        name = None

    def wait(self, predicate, timeout: float = 120) -> list[tuple[str, dict]]:
        with self._cv:
            ok = self._cv.wait_for(lambda: predicate(self.events), timeout)
        assert ok, f"timed out; events so far: {self.events}"
        return self.events

    def wait_event(self, name: str, timeout: float = 120) -> dict:
        self.wait(lambda evs: any(n == name for n, _ in evs), timeout)
        return next(d for n, d in self.events if n == name)

    def wait_status(self, status: str, timeout: float = 120) -> None:
        self.wait(lambda evs: ("status", {"status": status}) in evs, timeout)

    def statuses(self) -> list[str]:
        return [d["status"] for n, d in self.events if n == "status"]


def mcp(shop: Shop, profile: str, tool: str, **args) -> dict:
    """One MCP tool call as the given Hermes profile (bearer + X-Hermes-Profile, like fleet/*/config.yaml)."""
    async def call():
        transport = StreamableHttpTransport(shop.mcp_url, headers={"Authorization": f"Bearer {MCP_TOKEN}",
                                                                    "X-Hermes-Profile": profile})
        async with Client(transport) as client:
            r = await client.call_tool(tool, args)
        if isinstance(r.data, dict):
            return r.data
        return r.structured_content if r.structured_content is not None else json.loads(r.content[0].text)

    out = asyncio.run(call())
    assert out.get("ok") is not False, f"{tool} failed: {out}"
    return out


def pay_with_signed_webhook(http: httpx.Client, order: dict, payment_id: str) -> httpx.Response:
    """payment.succeeded shaped like Whop's webhook guide, signed per its 'Verify without an SDK' recipe."""
    body = json.dumps({
        "id": f"msg_{payment_id}", "type": "payment.succeeded", "api_version": "v1",
        "api_version_date": "2026-08-14", "timestamp": "2026-10-24T12:00:00.000Z", "account_id": "biz_e2e",
        "data": {"id": payment_id, "status": "paid", "substatus": "succeeded", "currency": "usd",
                 "total": order["price_cents"] / 100, "plan": {"id": order["whop_variant_id"]},
                 "metadata": {"order_id": order["id"]}},
    }).encode()
    msg_id, ts = f"msg_{payment_id}", str(int(time.time()))
    digest = hmac.new(WEBHOOK_SECRET.encode(), f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()
    headers = {"webhook-id": msg_id, "webhook-timestamp": ts, "content-type": "application/json",
               "webhook-signature": "v1," + base64.b64encode(digest).decode()}
    return http.post("/webhooks/whop", content=body, headers=headers)


def check_design_downloads(design: dict) -> None:
    for key, magic in MAGIC.items():
        r = httpx.get(design[key], timeout=30)                    # signed URL: no app headers needed
        assert r.status_code == 200 and r.content.startswith(magic), (key, r.status_code, r.content[:8])


def check_quote(shop: Shop, order_id: str, quote: dict) -> dict:
    order = shop.core.db.get_order(order_id)
    slice_dir = shop.core.settings.order_dir(order_id) / f"slice_v{order['design_version']}"
    if REAL_SLICER:
        from factory.slicer import read_gcode_3mf
        assert not (slice_dir / "slice_result.json").exists(), "expected a real OrcaSlicer slice, got the estimate"
        assert read_gcode_3mf(slice_dir / "model.gcode.3mf") == (quote["print_seconds"], quote["filament_grams"])
    assert 300 < quote["print_seconds"] < 4 * 3600 and 1 < quote["filament_grams"] < 60
    assert quote["whop_variant_id"].startswith("plan_") and quote["whop_variant_id"] == order["whop_variant_id"]
    assert order["status"] == "quoted" and order["price_cents"] >= 800
    print(f"{order['product']}: {'real slice' if REAL_SLICER else 'estimate'} {quote['print_seconds']} s, "
          f"{quote['filament_grams']} g, {order['price_cents']} cents")
    return order


def jpeg_bytes() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (180, 120, 60)).save(buf, "JPEG")
    return buf.getvalue()


def test_nametag_and_keychain_orders_end_to_end(shop):
    http = httpx.Client(base_url=shop.api_url, headers=APP_HEADERS, timeout=30)
    admin = httpx.Client(base_url=shop.api_url, headers=ADMIN_HEADERS, timeout=30)

    # ---- nametag: parametric template ------------------------------------------------
    tag = http.post("/orders", json={"product": "nametag"}).json()
    tid = tag["id"]
    assert tag["status"] == "draft"
    tag_stream = Stream(shop.api_url, tid)
    r = http.post(f"/orders/{tid}/messages", json={"text": "A desk name tag that says AKSHAYA", "colour": "white"})
    assert r.status_code == 202
    assert "nametag" in {t["name"] for t in mcp(shop, "intake", "list_templates")["templates"]}
    art = mcp(shop, "intake", "build_template", order_id=tid, name="nametag", params={"text": "AKSHAYA"})
    assert art["watertight"] is True and art["bbox_mm"][0] > 20
    mcp(shop, "intake", "publish_design", order_id=tid, artifact_id=art["artifact_id"], summary="White name tag")
    design = tag_stream.wait_event("design")
    assert design["version"] == 1
    check_design_downloads(design)
    detail = http.get(f"/orders/{tid}").json()
    assert detail["status"] == "review" and detail["files"]["usdz"] == design["usdz"]

    assert http.post(f"/orders/{tid}/accept").status_code == 202
    tag_order = check_quote(shop, tid, tag_stream.wait_event("quote", timeout=600))
    r = pay_with_signed_webhook(http, tag_order, "pay_e2e_tag")
    assert r.status_code == 200 and r.json()["order_id"] == tid
    tag_stream.wait_status("queued")

    # ---- keychain: photos -> mock Meshy -> finish_mesh with keyring ---------------------
    key = http.post("/orders", json={"product": "keychain"}).json()
    kid = key["id"]
    key_stream = Stream(shop.api_url, kid)
    up = http.post(f"/orders/{kid}/photos", files=[("files[]", ("pet.jpg", jpeg_bytes(), "image/jpeg"))])
    assert up.status_code == 200 and len(up.json()["urls"]) == 1
    r = http.post(f"/orders/{kid}/messages", json={"text": "My dog as a keychain", "colour": "white"})
    assert r.status_code == 202
    raw = mcp(shop, "intake", "generate_mesh", order_id=kid)
    done = mcp(shop, "intake", "finish_mesh", order_id=kid, src=raw["artifact_id"], target_height_mm=40, keyring=True)
    assert done["watertight"] is True and max(done["bbox_mm"]) <= 60
    mcp(shop, "intake", "publish_design", order_id=kid, artifact_id=done["artifact_id"], summary="Dog keychain, 40 mm")
    check_design_downloads(key_stream.wait_event("design"))
    assert http.post(f"/orders/{kid}/accept").status_code == 202
    key_order = check_quote(shop, kid, key_stream.wait_event("quote", timeout=600))
    assert pay_with_signed_webhook(http, key_order, "pay_e2e_key").json()["order_id"] == kid
    key_stream.wait_status("queued")
    assert [j["order_id"] for j in mcp(shop, "production", "queue")["jobs"]] == [tid, kid]

    # ---- production: first job, FINISH, bed_clear gate, next job -------------------------
    first = mcp(shop, "production", "start_next_job")
    assert first["started"] is True and first["order_id"] == tid
    assert mcp(shop, "production", "start_next_job")["started"] is False      # bed no longer clear
    tag_stream.wait_event("human_task", timeout=MOCK_PRINT_SECONDS + 60)
    tasks = admin.get("/admin/human-tasks", params={"status": "open"}).json()["tasks"]
    assert [(t["kind"], t["order_id"]) for t in tasks] == [("bed_clear", tid)]
    blocked = mcp(shop, "production", "start_next_job")
    assert blocked["started"] is False and "bed" in blocked["reason"]
    assert admin.post("/admin/bed-cleared").json() == {"bed_clear": True}
    assert admin.get("/admin/human-tasks", params={"status": "open"}).json()["tasks"] == []
    second = mcp(shop, "production", "start_next_job")
    assert second["started"] is True and second["order_id"] == kid
    key_stream.wait_event("human_task", timeout=MOCK_PRINT_SECONDS + 60)

    # ---- what the app saw on each SSE stream -------------------------------------------
    for oid, stream in ((tid, tag_stream), (kid, key_stream)):
        assert stream.statuses() == STATUS_FLOW, (oid, stream.statuses())
        names = [n for n, _ in stream.events]
        assert names.index("design") < names.index("quote") < names.index("human_task")
        printer = [d for n, d in stream.events if n == "printer"]
        assert printer and printer[-1]["state"] == "FINISH" and printer[-1]["progress_pct"] == 100
        assert ("human_task", "bed_clear") in [(n, d.get("kind")) for n, d in stream.events]
        assert ("message", {"role": "agent", "text": "On it."}) in stream.events
        assert shop.core.db.get_order(oid)["status"] == "done"
    assert {p for p, _ in shop.hermes.runs} >= {"intake", "sales", "production"}
    assert admin.get("/admin/state").json()["shop_state"]["bed_clear"] is False   # second part still on the bed
