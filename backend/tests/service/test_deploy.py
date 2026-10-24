"""Static checks of deploy/ and fleet/ for the Receipts stack (Docker is not available on the build host)."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from fleet.profiles import load_fleet

BACKEND = Path(__file__).resolve().parents[2]
DEPLOY = BACKEND / "deploy"
FLEET = BACKEND / "fleet"
SERVICES = {"receipts-worker", "mcp", "hermes"}
PROFILES = {"ceo", "scout", "designer", "closer", "ads", "production", "hiring", "finance"}
HERMES_BIN = "/opt/hermes/.venv/bin/hermes"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load((DEPLOY / "docker-compose.yml").read_text())


def test_compose_services_and_isolation(compose):
    services = compose["services"]
    assert set(services) == SERVICES
    for name, svc in services.items():
        assert svc["read_only"] is True, name
        assert any(t.startswith("/tmp") for t in svc["tmpfs"]), name
        assert svc["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in svc["security_opt"], name
        uid = str(svc["user"]).split(":")[0]
        assert uid.isdigit() and int(uid) >= 1000, f"{name}: user {svc['user']}"
        assert not svc.get("privileged") and "network_mode" not in svc and "pid" not in svc, name
        for vol in svc.get("volumes", []):
            src = vol.split(":")[0]
            assert src in compose["volumes"], f"{name}: {vol} is not a named volume"
        for port in svc.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name}: {port}"
        for dep in svc.get("depends_on", []):
            assert dep in services, f"{name} depends on unknown {dep}"
    assert services["hermes"]["user"] == "10000:10000"
    assert compose["networks"]["internal"]["internal"] is True


def test_hermes_service(compose):
    hermes = compose["services"]["hermes"]
    assert hermes["build"] == {"context": "..", "dockerfile": "deploy/Dockerfile.hermes"}
    assert hermes["entrypoint"] == ["sh", "/opt/fleet/bootstrap.sh"] and hermes["command"] == []
    assert hermes["volumes"] == ["hermes-home:/opt/data"] and "ports" not in hermes
    env = hermes["environment"]
    assert env["HERMES_HOME"] == "/opt/data" and env["HOME"].startswith("/opt/data/")
    assert env["CLAUDE_PROVIDER"] == "${CLAUDE_PROVIDER:-anthropic}"
    assert env["CODEX_PROVIDER"] == "${CODEX_PROVIDER:-openai-codex}"
    assert env["CODEX_MODEL"] == "${CODEX_MODEL:-gpt-5.5}"
    for bot in PROFILES:
        assert f"{bot.upper()}_MODEL" in env


def test_dockerfile_hermes():
    text = (DEPLOY / "Dockerfile.hermes").read_text()
    assert re.search(r"^FROM nousresearch/hermes-agent:latest$", text, re.M)
    assert not re.search(r"pip install[^\n]*hermes", text), "Hermes is not pip-installable"
    assert "hermes-src" not in text
    assert "@anthropic-ai/claude-code" in text and "@openai/codex" in text
    assert "COPY fleet /opt/fleet" in text and "python3-yaml" in text
    assert re.search(r"^USER 10000:10000$", text, re.M)
    assert 'CMD ["sh", "/opt/fleet/bootstrap.sh"]' in text
    assert (DEPLOY / "Dockerfile.hermes.dockerignore").read_text().split()[:2] == ["*", "!fleet"]


def test_env_example():
    env = (DEPLOY / ".env.example").read_text()
    values = dict(re.findall(r"^([A-Z][A-Z0-9_]+)=(\S*)", env, re.M))
    assert values["CLAUDE_PROVIDER"] == "anthropic" and values["CODEX_PROVIDER"] == "openai-codex"
    assert values["CODEX_MODEL"] == "gpt-5.5" and values["CLAUDE_MODEL"]
    assert "HERMES_REPO" not in values and "MCP_TOKEN" in values
    for bot in PROFILES:
        assert f"{bot.upper()}_MODEL" in values


def test_receipts_profiles():
    fleet = load_fleet()
    assert set(fleet) == PROFILES
    for bot in PROFILES:
        assert (FLEET / bot / "SOUL.md").is_file(), bot


def test_bootstrap_script():
    script = (FLEET / "bootstrap.sh").read_text()
    assert f'HERMES_BIN="${{HERMES_BIN:-{HERMES_BIN}}}"' in script
    assert 'hermes() { "$HERMES_BIN" "$@"; }' in script
    assert 'hermes profile create "$p" --no-alias' in script
    assert script.rstrip().endswith("exec hermes gateway run")
    assert 'CODEX_MODEL="${CODEX_MODEL:-gpt-5.5}"' in script
    sh = shutil.which("sh")
    if sh:
        subprocess.run([sh, "-n", str(FLEET / "bootstrap.sh")], check=True)
