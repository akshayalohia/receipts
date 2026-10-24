"""Factory MCP server: the tools the Hermes bots use (SPEC.md "MCP server").

Streamable HTTP on :9000/mcp behind a bearer token (MCP_TOKEN). Every call logs an
`events` row attributed to the calling bot: the `bot` argument if given, else the
`X-Hermes-Profile` header each profile sends (fleet/*/config.yaml).
Per-profile whitelists live in fleet/<profile>/config.yaml (mcp_servers.factory.tools.include).
"""
from __future__ import annotations

import hmac
import json
from functools import partial
from typing import Any

import anyio
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers

from service.core import Core, ShopError

TOOL_GROUPS = {
    "design": ["get_order", "list_templates", "build_template", "run_cadquery", "generate_mesh",
               "finish_mesh", "combine", "publish_design"],
    "sales": ["prepare_quote", "get_pricing_policy", "set_pricing_policy", "shop_metrics"],
    "production": ["queue", "start_next_job", "printer_status", "pause_print", "resume_print",
                   "cancel_print", "snapshot", "set_loaded_colour", "request_human"],
    "support_finance": ["list_orders", "refund", "financials"],
    "shared": ["post_customer_update", "log_decision"],
}
ALL_TOOLS = [t for group in TOOL_GROUPS.values() for t in group]


def build_mcp(core: Core) -> FastMCP:
    mcp = FastMCP("factory")

    def caller(bot: str | None) -> str:
        return bot or get_http_headers().get("x-hermes-profile") or "unknown"

    def short(value: Any) -> Any:
        text = json.dumps(value, default=str)
        return json.loads(text) if len(text) <= 300 else text[:300] + "..."

    async def call(tool: str, bot: str | None, order_id: str | None, fn, *args, **kwargs) -> Any:
        actor = caller(bot)
        args_log = {"args": [short(a) for a in args], "kwargs": {k: short(v) for k, v in kwargs.items()}}
        core.db.add_event(order_id, actor, "tool_call", {"tool": tool, **args_log})
        try:
            return await anyio.to_thread.run_sync(partial(fn, *args, **kwargs))
        except ShopError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # pipeline errors (e.g. CadError) go back to the bot so it can retry
            core.db.add_event(order_id, actor, "tool_error", {"tool": tool, "error": str(e)})
            return {"ok": False, "error": f"{type(e).__name__}: {e}",
                    "traceback_tail": getattr(e, "traceback_tail", None)}

    # ---- design -------------------------------------------------------------
    @mcp.tool
    async def get_order(order_id: str, bot: str | None = None) -> dict:
        """Order details, recent chat, photo paths and the current design/quote."""
        def run():
            order = core.require_order(order_id)
            view = core.order_view(order)
            view["messages"] = [{"role": m["role"], "text": m["text"]} for m in core.db.list_messages(order_id)[-20:]]
            view["photo_paths"] = [str(p) for p in core.photos(order_id)]
            return view
        return await call("get_order", bot, order_id, run)

    @mcp.tool
    async def list_templates(bot: str | None = None) -> dict:
        """Parametric templates (nametag, keychain_ring, holder, knob, cable_clip) with params in mm."""
        return await call("list_templates", bot, None, lambda: {"templates": core.list_templates()})

    @mcp.tool
    async def build_template(order_id: str, name: str, params: dict, bot: str | None = None) -> dict:
        """Build a template design. Returns {artifact_id, bbox_mm, watertight, png_url}."""
        actor = caller(bot)
        return await call("build_template", bot, order_id, core.build_template, order_id, name, params, actor)

    @mcp.tool
    async def run_cadquery(order_id: str, code: str, bot: str | None = None) -> dict:
        """Run CadQuery code that binds `result` (units mm). Errors come back so you can fix and retry."""
        actor = caller(bot)
        return await call("run_cadquery", bot, order_id, core.run_cadquery, order_id, code, actor)

    @mcp.tool
    async def generate_mesh(order_id: str, prompt: str | None = None, bot: str | None = None) -> dict:
        """Organic 3D mesh from the order's photos (Meshy). Usually needs finish_mesh before publishing."""
        actor = caller(bot)
        return await call("generate_mesh", bot, order_id, core.generate_mesh, order_id, prompt, actor)

    @mcp.tool
    async def finish_mesh(order_id: str, src: str, target_height_mm: float | None = None,
                          add_base: bool = False, keyring: bool = False, bot: str | None = None) -> dict:
        """Repair, scale, orient and optionally add a base or keyring loop to artifact `src`."""
        actor = caller(bot)
        return await call("finish_mesh", bot, order_id, core.finish_mesh, order_id, src, actor,
                          target_height_mm=target_height_mm, add_base=add_base, keyring=keyring)

    @mcp.tool
    async def combine(order_id: str, a: str, b: str, bot: str | None = None) -> dict:
        """Union two artifacts (e.g. a mesh and a CadQuery ring)."""
        actor = caller(bot)
        return await call("combine", bot, order_id, core.combine, order_id, a, b, actor)

    @mcp.tool
    async def publish_design(order_id: str, artifact_id: str, summary: str, bot: str | None = None) -> dict:
        """Show an artifact to the customer: saves files, bumps design_version, status review."""
        actor = caller(bot)
        return await call("publish_design", bot, order_id, core.publish_design, order_id, artifact_id, summary, actor)

    # ---- sales --------------------------------------------------------------
    @mcp.tool
    async def prepare_quote(order_id: str, bot: str | None = None) -> dict:
        """Slice, price with the current policy, create the Whop one-time variant; status quoted."""
        actor = caller(bot)
        return await call("prepare_quote", bot, order_id, core.prepare_quote, order_id, actor)

    @mcp.tool
    async def get_pricing_policy(bot: str | None = None) -> dict:
        """Current pricing policy (cents)."""
        return await call("get_pricing_policy", bot, None, core.get_policy)

    @mcp.tool
    async def set_pricing_policy(policy: dict, reason: str, bot: str | None = None) -> dict:
        """Change pricing; every value is clamped to ±20% of the default. Returns the applied policy."""
        actor = caller(bot)
        return await call("set_pricing_policy", bot, None, core.set_policy, policy, reason, actor)

    @mcp.tool
    async def shop_metrics(bot: str | None = None) -> dict:
        """Queue length, orders and payments in the last 24 h, conversion, average price."""
        return await call("shop_metrics", bot, None, core.shop_metrics)

    # ---- production ---------------------------------------------------------
    @mcp.tool
    async def queue(bot: str | None = None) -> dict:
        """Paid jobs waiting, what is printing, loaded colour, bed_clear."""
        return await call("queue", bot, None, core.queue)

    @mcp.tool
    async def start_next_job(bot: str | None = None) -> dict:
        """Start the next job. Refuses unless bed is clear, printer IDLE/FINISH and colour matches."""
        actor = caller(bot)
        return await call("start_next_job", bot, None, core.start_next_job, actor)

    @mcp.tool
    async def printer_status(bot: str | None = None) -> dict:
        """Printer state, progress and remaining minutes."""
        return await call("printer_status", bot, None, core.printer_status)

    @mcp.tool
    async def pause_print(reason: str, bot: str | None = None) -> dict:
        """Pause the current print."""
        actor = caller(bot)
        return await call("pause_print", bot, None, core.pause_print, reason, actor)

    @mcp.tool
    async def resume_print(bot: str | None = None) -> dict:
        """Resume a paused print."""
        actor = caller(bot)
        return await call("resume_print", bot, None, core.resume_print, actor)

    @mcp.tool
    async def cancel_print(reason: str, bot: str | None = None) -> dict:
        """Stop the current print; the order is marked failed and a bed_clear task is created."""
        actor = caller(bot)
        return await call("cancel_print", bot, None, core.cancel_print, reason, actor)

    @mcp.tool
    async def snapshot(bot: str | None = None) -> dict:
        """Take a printer camera snapshot; returns its URL (JPEG) and server path."""
        actor = caller(bot)
        return await call("snapshot", bot, None, core.snapshot, actor)

    @mcp.tool
    async def set_loaded_colour(colour: str, bot: str | None = None) -> dict:
        """Record which spool is loaded (only after a human confirms the swap)."""
        actor = caller(bot)
        return await call("set_loaded_colour", bot, None, core.set_loaded_colour, colour, actor)

    @mcp.tool
    async def request_human(kind: str, details: str, order_id: str | None = None, bot: str | None = None) -> dict:
        """Ask a human: kind is bed_clear, spool_swap, qa, pickup or other."""
        actor = caller(bot)
        return await call("request_human", bot, order_id, core.request_human, kind, details, order_id, actor)

    # ---- support / finance --------------------------------------------------
    @mcp.tool
    async def list_orders(status: str | None = None, bot: str | None = None) -> dict:
        """Orders, optionally filtered by status."""
        return await call("list_orders", bot, None, lambda: {"orders": core.list_orders(status)})

    @mcp.tool
    async def refund(order_id: str, reason: str, bot: str | None = None) -> dict:
        """Refund via Whop up to $20; larger amounts open a qa task for a human instead."""
        actor = caller(bot)
        return await call("refund", bot, order_id, core.refund, order_id, reason, actor)

    @mcp.tool
    async def financials(days: int = 1, bot: str | None = None) -> dict:
        """Revenue, Whop fees, filament ($0.02/g) and generation cost, margin, in cents."""
        return await call("financials", bot, None, core.financials, days)

    # ---- shared -------------------------------------------------------------
    @mcp.tool
    async def post_customer_update(order_id: str, text: str, bot: str | None = None) -> dict:
        """Send the customer a chat message (shows live in the app)."""
        actor = caller(bot)
        return await call("post_customer_update", bot, order_id, core.post_customer_update, order_id, text, actor)

    @mcp.tool
    async def log_decision(decision: str, reason: str, order_id: str | None = None, bot: str | None = None) -> dict:
        """Record a decision and why. Call for every non-trivial decision."""
        actor = caller(bot)
        return await call("log_decision", bot, order_id, core.log_decision, order_id, decision, reason, actor)

    return mcp


class BearerAuth:
    """ASGI wrapper: every HTTP request must carry `Authorization: Bearer <MCP_TOKEN>`."""

    def __init__(self, app, token: str) -> None:
        self.app = app
        self.expected = f"Bearer {token}".encode() if token else None

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            auth = dict(scope.get("headers") or []).get(b"authorization", b"")
            if self.expected is None or not hmac.compare_digest(auth, self.expected):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"),
                                        (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body", "body": b'{"detail":"bearer token required"}'})
                return
        await self.app(scope, receive, send)


def mcp_http_app(core: Core):
    return BearerAuth(build_mcp(core).http_app(path="/mcp"), core.settings.mcp_token)
