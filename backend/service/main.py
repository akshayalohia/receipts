"""Run the HTTP API (:8080) and the MCP server (:9000/mcp) in one process.

One process so the SSE stream, the MCP tools and the printer monitor share the
in-process event bus and the SQLite connection.
    python -m service.main
"""
from __future__ import annotations

import asyncio
import logging

import uvicorn

from mcp_server.server import mcp_http_app
from service.app import create_app
from service.config import Settings
from service.core import Core


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    core = Core(Settings.from_env())
    api = uvicorn.Server(uvicorn.Config(create_app(core), host="0.0.0.0", port=8080))
    mcp = uvicorn.Server(uvicorn.Config(mcp_http_app(core), host="0.0.0.0", port=9000))
    await asyncio.gather(api.serve(), mcp.serve())


if __name__ == "__main__":
    asyncio.run(main())
