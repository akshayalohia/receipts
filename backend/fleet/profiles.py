"""Render the Receipts Hermes profiles from fleet/fleet.yaml.

  python3 profiles.py config <bot>     -> the profile's config.yaml on stdout
  python3 profiles.py cron             -> "<bot>\t<job-name>\t<schedule>\t<prompt>" lines
  python3 profiles.py engine <bot>     -> claude | codex
  python3 profiles.py bots             -> bot names, space separated

Hermes substitutes ${VAR} in config.yaml from the profile's .env (written by bootstrap.sh).
Runs inside the hermes image (python3 + pyyaml); no other imports.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ENGINES = {"claude", "codex"}
DISABLED_TOOLSETS = ["terminal", "file", "browser", "code_execution", "computer_use", "delegation", "cronjob"]


def load_fleet(path: Path = HERE / "fleet.yaml") -> dict[str, dict]:
    return yaml.safe_load(path.read_text())["bots"]


def render_config(bot: str, spec: dict) -> dict:
    return {
        "model": {"provider": "${FLEET_PROVIDER}", "default": "${FLEET_MODEL}"},
        "mcp_servers": {
            "receipts": {
                "url": "${RECEIPTS_MCP_URL}",
                "headers": {"Authorization": "Bearer ${MCP_TOKEN}", "X-Hermes-Profile": bot},
                "timeout": 300,
                "tools": {"include": list(spec["tools"]), "resources": False, "prompts": False},
            }
        },
        "platform_toolsets": {"api_server": ["receipts"], "cron": ["receipts"]},
        "agent": {"disabled_toolsets": list(DISABLED_TOOLSETS)},
    }


def main(argv: list[str]) -> int:
    fleet = load_fleet()
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "bots":
        print(" ".join(fleet))
    elif cmd == "config":
        sys.stdout.write(f"# Rendered from fleet/fleet.yaml by profiles.py; edit that file, not this one.\n")
        sys.stdout.write(yaml.safe_dump(render_config(argv[2], fleet[argv[2]]), sort_keys=False))
    elif cmd == "engine":
        print(fleet[argv[2]]["engine"])
    elif cmd == "cron":
        for bot, spec in fleet.items():
            prompt = " ".join(spec["prompt"].split())
            print(f"{bot}\trx-{bot}\t{spec['schedule']}\t{prompt}")
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
