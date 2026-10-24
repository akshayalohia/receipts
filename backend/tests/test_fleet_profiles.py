"""Fleet profiles render with required fields; compose isolation; MCP tools with a stubbed receipts."""
from __future__ import annotations

import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml

from fleet.profiles import load_fleet, render_config
from mcp_server.receipts_server import TOOL_NAMES, Tools, build_app

BACKEND = Path(__file__).resolve().parents[1]
FLEET = BACKEND / "fleet"
DEPLOY = BACKEND / "deploy"
BOTS = {"ceo", "scout", "designer", "closer", "ads", "production", "hiring", "finance"}
CLAUDE_BOTS = {"ceo", "closer", "designer"}


def test_fleet_bots_and_engines():
    fleet = load_fleet()
    assert set(fleet) == BOTS
    for bot, spec in fleet.items():
        assert spec["engine"] == ("claude" if bot in CLAUDE_BOTS else "codex"), bot
        assert spec["schedule"] and spec["prompt"].strip()
    assert fleet["ceo"]["schedule"] == "every 1h" and fleet["scout"]["schedule"] == "every 10m"


@pytest.mark.parametrize("bot", sorted(BOTS))
def test_profile_renders(bot):
    spec = load_fleet()[bot]
    cfg = yaml.safe_load(yaml.safe_dump(render_config(bot, spec)))
    assert cfg["model"] == {"provider": "${FLEET_PROVIDER}", "default": "${FLEET_MODEL}"}
    srv = cfg["mcp_servers"]["receipts"]
    assert srv["url"] == "${RECEIPTS_MCP_URL}"
    assert srv["headers"] == {"Authorization": "Bearer ${MCP_TOKEN}", "X-Hermes-Profile": bot}
    include = srv["tools"]["include"]
    assert include and set(include) <= set(TOOL_NAMES), set(include) - set(TOOL_NAMES)
    assert "receipts" in cfg["platform_toolsets"]["cron"]
    assert {"terminal", "file", "browser"} <= set(cfg["agent"]["disabled_toolsets"])
    soul = (FLEET / bot / "SOUL.md").read_text()
    assert soul.startswith("# ") and len(soul.splitlines()) <= 60
    for tool in include:
        assert tool in soul or tool in spec["prompt"], f"{bot}: {tool} not explained"


def test_role_rules():
    fleet = load_fleet()
    every = {t for spec in fleet.values() for t in spec["tools"]}
    assert every == set(TOOL_NAMES), set(TOOL_NAMES) - every
    assert "refund" in fleet["production"]["tools"] and all(
        "refund" not in s["tools"] for b, s in fleet.items() if b != "production")
    assert fleet["ads"]["tools"].count("ads_draft") == 1 and "ads_draft" not in fleet["ceo"]["tools"]
    assert "reply_to_mention" in fleet["closer"]["tools"]
    assert "create_claim" in fleet["designer"]["tools"] and "find_breakouts" in fleet["scout"]["tools"]
    assert "x_post" in fleet["ceo"]["prompt"]


def test_profiles_cli_and_bootstrap():
    out = subprocess.run([sys.executable, str(FLEET / "profiles.py"), "cron"], capture_output=True, text=True,
                         check=True).stdout.strip().splitlines()
    assert len(out) == len(BOTS) and all(len(line.split("\t")) == 4 for line in out)
    cfg = subprocess.run([sys.executable, str(FLEET / "profiles.py"), "config", "scout"], capture_output=True,
                         text=True, check=True).stdout
    assert yaml.safe_load(cfg)["mcp_servers"]["receipts"]["headers"]["X-Hermes-Profile"] == "scout"
    script = (FLEET / "bootstrap.sh").read_text()
    assert "exec hermes gateway run" in script and 'hermes profile create "$p" --no-alias' in script
    sh = shutil.which("sh")
    if sh:
        subprocess.run([sh, "-n", str(FLEET / "bootstrap.sh")], check=True)


# ---- compose isolation ---------------------------------------------------
@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load((DEPLOY / "docker-compose.yml").read_text())


def test_compose_isolation(compose):
    services = compose["services"]
    assert set(services) == {"receipts-worker", "mcp", "hermes"}
    assert set(compose["volumes"]) == {"receipts-data", "hermes-home"}
    assert compose["networks"]["internal"]["internal"] is True
    for name, svc in services.items():
        assert svc["read_only"] is True, name
        assert any(t.startswith("/tmp") for t in svc["tmpfs"]), name
        assert svc["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in svc["security_opt"], name
        assert svc["user"] and not svc["user"].startswith("0"), name
        assert not svc.get("privileged") and "network_mode" not in svc, name
        for vol in svc.get("volumes", []):
            src = vol.split(":")[0]
            assert src in compose["volumes"], f"{name}: {vol} is not a named volume"
            assert "docker.sock" not in vol
        for port in svc.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name}: {port}"
    assert services["receipts-worker"]["command"] == ["python", "-m", "receipts.worker"]
    assert services["mcp"]["ports"] == ["127.0.0.1:8787:8787"]
    assert "internal" in services["hermes"]["networks"] and "internal" in services["mcp"]["networks"]
    hermes_env = services["hermes"]["environment"]
    assert not any(k.startswith(("WHOP_", "SLANT_", "CRAFTCLOUD_", "X_", "EXA_", "SITE_")) for k in hermes_env)
    assert hermes_env["RECEIPTS_MCP_URL"] == "http://mcp:8787/mcp"
    text = (DEPLOY / "docker-compose.yml").read_text()
    for gone in ("mosquitto", "cloudflared", "ELEVENLABS", "PRINTER_"):
        assert gone not in text
    hermes_df = (DEPLOY / "Dockerfile.hermes").read_text()
    assert "@anthropic-ai/claude-code" in hermes_df and "@openai/codex" in hermes_df and "USER 10000" in hermes_df
    assert "USER 10001" in (DEPLOY / "Dockerfile.receipts").read_text()


# ---- MCP tools + queue page with a stubbed receipts package ---------------
@pytest.fixture
def tools(tmp_path, monkeypatch):
    calls = []
    fake = types.ModuleType("receipts")
    fake.list_orders = lambda status=None: [{"id": "o1", "status": status or "placed", "product": "tweet"}]
    fake.refund = lambda order_id: calls.append(order_id) or {"refunded": order_id}
    fake.stats = lambda: {"revenue_cents": 2900, "orders": 1}
    monkeypatch.setitem(sys.modules, "receipts", fake)
    monkeypatch.delenv("SITE_URL", raising=False)
    monkeypatch.delenv("SITE_ADMIN_TOKEN", raising=False)
    t = Tools(tmp_path / "m.db")
    t.calls = calls
    return t


def test_tools_with_stubbed_receipts(tools):
    assert tools.list_orders("needs_review")["orders"][0]["status"] == "needs_review"
    assert tools.order_status("o1")["ok"] and not tools.order_status("zz")["ok"]
    assert tools.refund("o1", "supplier rejected", "production")["ok"] and tools.calls == ["o1"]
    assert tools.stats()["receipts"]["revenue_cents"] == 2900
    lead = tools.leads.add("x", "https://x.com/maya/status/9", handle="maya")
    claim = tools.create_claim("maya", "tweet", lead_id=lead, text="we hit 10k", likes=3000)
    assert claim["ok"] is False and claim["site"]["skipped"]            # no SITE_URL: not PUT
    assert tools.leads.get(lead)["status"] == "designed"
    assert tools.queue_reply("Congrats", "closer", lead_id=lead, claim_url=claim["claim_url"])["ok"]
    assert tools.leads.get(lead)["status"] == "queued"
    assert tools.ads_draft("x_ads", "boost", 60, "", "ads")["ok"] is False
    assert tools.ads_draft("x_ads", "boost", 25, "best post", "ads")["ok"]
    assert {i["kind"] for i in tools.queue.list()} == {"reply", "ads_move"}


def test_app_auth_and_queue_page(tools):
    from starlette.testclient import TestClient

    tools.queue.add("reply", "closer", "hello there", target_url="https://x.com/a/status/1")
    client = TestClient(build_app(tools, token="secret"))
    assert client.post("/mcp", json={}).status_code == 401
    assert client.post("/mcp", json={}, headers={"authorization": "Bearer nope"}).status_code == 401
    page = client.get("/queue")
    assert page.status_code == 200 and "hello there" in page.text
    item = client.get("/queue.json").json()[0]
    assert client.post(f"/queue/{item['id']}/posted", headers={"origin": "https://evil.example"}).status_code == 403
    r = client.post(f"/queue/{item['id']}/posted", follow_redirects=False)
    assert r.status_code == 303 and client.get("/queue.json").json() == []
