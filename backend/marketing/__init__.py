"""Receipts marketing tools used by the Hermes fleet through the MCP server.

Everything with an API key runs inside the `mcp` container; the bots only hold MCP_TOKEN.
All stores share one sqlite file: $RECEIPTS_DATA/marketing.db (see `db_path`).
"""
from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    path = Path(os.environ.get("RECEIPTS_DATA", "./data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "marketing.db"
