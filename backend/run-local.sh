#!/bin/sh
# Run the factory service without Docker, in mock mode: API on :8080, MCP on :9000/mcp
# (one process, like the Docker image). Stop with Ctrl-C.
#   sh backend/run-local.sh
# First run creates backend/.venv with uv (Python 3.12). Any variable below can be
# overridden from the environment, e.g. FACTORY_MOCK=0 PRINTER_IP=... sh backend/run-local.sh
set -eu
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    uv venv --python 3.12 .venv
    uv pip install --python .venv/bin/python -r pyproject.toml
fi

export FACTORY_MOCK="${FACTORY_MOCK:-1}"
export FACTORY_DATA="${FACTORY_DATA:-$PWD/data}"
export APP_SHARED_SECRET="${APP_SHARED_SECRET:-dev}"   # app's X-App-Key
export ADMIN_KEY="${ADMIN_KEY:-dev}"                   # X-Admin-Key for /admin/*
export MCP_TOKEN="${MCP_TOKEN:-dev}"                   # bearer for :9000/mcp
export HERMES_API_KEY="${HERMES_API_KEY:-dev}"
export HERMES_API_BASE="${HERMES_API_BASE:-http://127.0.0.1:8642}"   # chat needs a Hermes gateway here

# Real slicing when OrcaSlicer is extracted in tools/orca (Linux); otherwise mock mode
# prices from a volume estimate. ORCA_LD_LIBRARY_PATH: GL/GLU libs extracted from .debs.
if [ -z "${ORCA_SLICER_BIN:-}" ] && [ -x ../tools/orca/squashfs-root/AppRun ]; then
    export ORCA_SLICER_BIN="$(cd ../tools/orca/squashfs-root && pwd)/AppRun"
fi
if [ -z "${ORCA_LD_LIBRARY_PATH:-}" ] && [ -d ../tools/libs/root/usr/lib/x86_64-linux-gnu ]; then
    export ORCA_LD_LIBRARY_PATH="$(cd ../tools/libs/root/usr/lib/x86_64-linux-gnu && pwd)"
fi

echo "[run-local] mock=$FACTORY_MOCK data=$FACTORY_DATA slicer=${ORCA_SLICER_BIN:-estimate}"
exec .venv/bin/python -m service.main
