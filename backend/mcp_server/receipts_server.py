"""Receipts MCP server + human post queue page (compose service `mcp`, port 8787).

  /mcp            streamable-HTTP MCP, `Authorization: Bearer $MCP_TOKEN` (the Hermes bots)
  /queue          human post queue page (published on 127.0.0.1:8787 only)
  /queue.json     same items as JSON
  /health         liveness

Receipts functions come from BACKEND-ORDERS' `receipts` package (docs/CONTRACT.md); it is
imported lazily so tests can stub it via sys.modules. Every marketing key lives in this
container; the bots only hold MCP_TOKEN.
"""
from __future__ import annotations

import dataclasses
import hmac
import importlib
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from marketing import db_path
from marketing import site as site_api
from marketing.ads import AdsLedger
from marketing.claims import attach_og, build_claim, claim_url
from marketing.exa_client import ExaClient
from marketing.leads import LeadStore
from marketing.post_queue import QueueStore, render_queue_html
from marketing.scout import find_breakouts, find_milestones
from marketing.x_client import XClient, post_mention_reply

PORT = int(os.environ.get("MCP_PORT", "8787"))


def _receipts():
    return importlib.import_module("receipts")


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if hasattr(value, "__dict__") and not isinstance(value, (str, int, float, bool)):
        return _jsonable({k: v for k, v in vars(value).items() if not k.startswith("_")})
    return value


def _order_id(order: dict) -> str | None:
    for key in ("id", "order_id", "order_ref", "pay_id"):
        if order.get(key):
            return str(order[key])
    return None


class Tools:
    """Plain functions behind the MCP tools (tested directly)."""

    def __init__(self, path: Path | str | None = None, x: XClient | None = None, exa: ExaClient | None = None):
        path = path or db_path()
        self.leads = LeadStore(path)
        self.queue = QueueStore(path)
        self.ads = AdsLedger(path)
        self.x = x or XClient()
        self.exa = exa or ExaClient()

    def event(self, agent: str, text: str, kind: str | None = None) -> dict:
        try:
            return site_api.post_event(agent, text, kind)
        except Exception as e:  # never fail a tool because the feed is down
            return {"ok": False, "error": str(e)}

    # ---- receipts ---------------------------------------------------------
    def list_orders(self, status: str | None = None) -> dict:
        return {"orders": _jsonable(_receipts().list_orders(status))}

    def order_status(self, order_id: str) -> dict:
        for o in _jsonable(_receipts().list_orders(None)):
            if _order_id(o) == order_id or order_id in {str(o.get(k)) for k in ("id", "order_id", "order_ref", "pay_id")}:
                return {"ok": True, "order": o}
        return {"ok": False, "error": f"order {order_id} not found"}

    def refund(self, order_id: str, reason: str, agent: str) -> dict:
        result = _jsonable(_receipts().refund(order_id))
        self.event(agent, f"Refunded order {order_id}: {reason}"[:200], "refund")
        return {"ok": True, "result": result}

    def stats(self) -> dict:
        try:
            base = _jsonable(_receipts().stats())
        except Exception as e:
            base = {"error": f"receipts.stats failed: {e}"}
        return {"receipts": base, "leads_by_source": self.leads.counts_by_source(),
                "queue": self.queue.counts(), "ads": self.ads.status()}

    # ---- marketing --------------------------------------------------------
    def find_breakouts(self, hours: int = 6) -> dict:
        return find_breakouts(self.x, self.leads, hours=min(max(hours, 1), 6))

    def find_milestones(self, sources: list[str] | None = None) -> dict:
        return find_milestones(self.exa, self.leads, sources)

    def list_leads(self, status: str | None = "new", limit: int = 20) -> dict:
        return {"leads": self.leads.list(status, min(limit, 100))}

    def create_claim(self, handle: str, product: str = "tweet", colour: str = "black", lead_id: int | None = None,
                     tweet_url: str | None = None, text: str | None = None, likes: int | None = None,
                     number: str | None = None, label: str | None = None, name: str | None = None,
                     date: str | None = None, agent: str = "designer") -> dict:
        claim = build_claim(handle, product, colour, tweet_url=tweet_url, text=text, likes=likes, number=number,
                            label=label, name=name, date=date)
        put = site_api.put_claim(attach_og(claim))
        url = claim_url(os.environ.get("SITE_URL", ""), claim["slug"])
        if lead_id is not None:
            self.leads.set_status(lead_id, "designed", slug=claim["slug"], claim_url=url)
        if put.get("ok"):
            self.event(agent, f"Built a {product} trophy claim page for @{claim['handle']}", "claim")
        return {"ok": bool(put.get("ok")), "slug": claim["slug"], "claim_url": url, "claim": claim, "site": put}

    def queue_reply(self, text: str, agent: str, kind: str = "reply", target_url: str | None = None,
                    claim_url: str | None = None, lead_id: int | None = None) -> dict:
        res = self.queue.add(kind, agent, text, target_url=target_url, claim_url=claim_url, lead_id=lead_id)
        if lead_id is not None and not res["duplicate"]:
            self.leads.set_status(lead_id, "queued")
        return res

    def ads_status(self) -> dict:
        return self.ads.status()

    def ads_draft(self, channel: str, campaign: str, daily_usd: float, note: str, agent: str) -> dict:
        res = self.ads.draft(channel, campaign, daily_usd, note, agent)
        if res["ok"]:
            self.queue.add("ads_move", agent, f"{channel} / {campaign}: set daily budget to ${res['daily_usd']:.2f}. {note}")
            self.event(agent, f"Drafted {channel} budget ${res['daily_usd']:.2f}/day for {campaign}", "ads")
        return res

    def reply_to_mention(self, tweet_id: str, mention_text: str, text: str) -> dict:
        return post_mention_reply(text, tweet_id, mention_text, os.environ.get("X_BRAND_HANDLE", "receipts"),
                                  trigger="mention")


TOOL_NAMES = ["list_orders", "order_status", "refund", "stats", "find_breakouts", "find_milestones", "list_leads",
              "create_claim", "queue_reply", "post_event", "ads_status", "ads_draft", "reply_to_mention"]


def build_mcp(tools: Tools):
    import anyio
    from fastmcp import FastMCP
    from fastmcp.server.dependencies import get_http_headers

    mcp = FastMCP("receipts")

    def who(bot: str | None) -> str:
        if bot:
            return bot
        try:
            return get_http_headers().get("x-hermes-profile") or "unknown"
        except Exception:
            return "unknown"

    async def run(fn, *args, **kwargs):
        try:
            return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))
        except Exception as e:  # errors go back to the bot so it can adjust
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    @mcp.tool
    async def list_orders(status: str | None = None) -> dict:
        """Receipts orders, optionally by status (e.g. needs_review)."""
        return await run(tools.list_orders, status)

    @mcp.tool
    async def order_status(order_id: str) -> dict:
        """One order with its supplier status."""
        return await run(tools.order_status, order_id)

    @mcp.tool
    async def refund(order_id: str, reason: str, bot: str | None = None) -> dict:
        """Refund an order through Whop and post an event."""
        return await run(tools.refund, order_id, reason, who(bot))

    @mcp.tool
    async def stats() -> dict:
        """Revenue/orders (receipts.stats), leads per source, queue counts, ads budget."""
        return await run(tools.stats)

    @mcp.tool
    async def find_breakouts(hours: int = 6) -> dict:
        """Search X for breakout posts in the last <=6 h; new leads go to the lead store (deduped)."""
        return await run(tools.find_breakouts, hours)

    @mcp.tool
    async def find_milestones(sources: list[str] | None = None) -> dict:
        """Exa searches: linkedin, youtube, producthunt, show_hn, github, devpost. Deduped leads."""
        return await run(tools.find_milestones, sources)

    @mcp.tool
    async def list_leads(status: str | None = "new", limit: int = 20) -> dict:
        """Leads by status: new, designed, queued (null = all)."""
        return await run(tools.list_leads, status, limit)

    @mcp.tool
    async def create_claim(handle: str, product: str = "tweet", colour: str = "black", lead_id: int | None = None,
                           tweet_url: str | None = None, text: str | None = None, likes: int | None = None,
                           number: str | None = None, label: str | None = None, name: str | None = None,
                           date: str | None = None, bot: str | None = None) -> dict:
        """Build a claim (product tweet|milestone), render its og image, PUT it to the site."""
        return await run(tools.create_claim, handle, product, colour, lead_id, tweet_url, text, likes, number,
                         label, name, date, who(bot))

    @mcp.tool
    async def queue_reply(text: str, kind: str = "reply", target_url: str | None = None,
                          claim_url: str | None = None, lead_id: int | None = None, bot: str | None = None) -> dict:
        """Put a draft in the HUMAN post queue (kind reply|email|x_post|terac_task|note). Never posts."""
        return await run(tools.queue_reply, text, who(bot), kind, target_url, claim_url, lead_id)

    @mcp.tool
    async def post_event(text: str, kind: str | None = None, bot: str | None = None) -> dict:
        """One-line public event for the challenge page feed."""
        return await run(tools.event, who(bot), text, kind)

    @mcp.tool
    async def ads_status() -> dict:
        """Today's drafted ad budgets vs the hard daily cap."""
        return await run(tools.ads_status)

    @mcp.tool
    async def ads_draft(channel: str, campaign: str, daily_usd: float, note: str = "", bot: str | None = None) -> dict:
        """Draft a budget for whop_ads|x_ads campaign (0 = kill). Rejected above the daily cap."""
        return await run(tools.ads_draft, channel, campaign, daily_usd, note, who(bot))

    @mcp.tool
    async def reply_to_mention(tweet_id: str, mention_text: str, text: str) -> dict:
        """Auto-reply ONLY to a '@brand print this' mention (needs X_AUTOREPLY_MENTIONS=1)."""
        return await run(tools.reply_to_mention, tweet_id, mention_text, text)

    return mcp


def _allowed_origin(origin: str | None) -> bool:
    if not origin:
        return True     # plain form posts from curl / same-origin without the header
    return origin in {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}


def build_app(tools: Tools | None = None, token: str | None = None):
    from starlette.requests import Request
    from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

    tools = tools or Tools()
    token = os.environ.get("MCP_TOKEN", "") if token is None else token
    mcp = build_mcp(tools)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request):
        return JSONResponse({"ok": True})

    @mcp.custom_route("/queue", methods=["GET"])
    async def queue_page(request: Request):
        return HTMLResponse(render_queue_html(tools.queue.list("pending")))

    @mcp.custom_route("/queue.json", methods=["GET"])
    async def queue_json(request: Request):
        return JSONResponse(tools.queue.list(request.query_params.get("status") or "pending"))

    @mcp.custom_route("/queue/{item_id:int}/posted", methods=["POST"])
    async def mark_posted(request: Request):
        if not _allowed_origin(request.headers.get("origin")):
            return JSONResponse({"error": "bad origin"}, status_code=403)
        tools.queue.mark_posted(int(request.path_params["item_id"]))
        return RedirectResponse("/queue", status_code=303)

    return McpBearer(mcp.http_app(path="/mcp"), token)


class McpBearer:
    """Bearer token on /mcp only; the queue page is protected by binding to 127.0.0.1."""

    def __init__(self, app, token: str):
        self.app = app
        self.expected = f"Bearer {token}".encode() if token else None

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/mcp"):
            auth = dict(scope.get("headers") or []).get(b"authorization", b"")
            if self.expected is None or not hmac.compare_digest(auth, self.expected):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body", "body": json.dumps({"detail": "bearer token required"}).encode()})
                return
        await self.app(scope, receive, send)


def main() -> None:
    import uvicorn
    uvicorn.run(build_app(), host=os.environ.get("MCP_HOST", "0.0.0.0"), port=PORT)


if __name__ == "__main__":
    main()
