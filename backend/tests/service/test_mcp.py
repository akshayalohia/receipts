"""Factory MCP server: tool list, one call per tool group, pricing clamp, bearer auth."""
from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient
from fastmcp import Client

from fakes import designed_order
from mcp_server.server import ALL_TOOLS, build_mcp, mcp_http_app

SPEC_TOOLS = {
    "get_order", "list_templates", "build_template", "run_cadquery", "generate_mesh", "finish_mesh",
    "combine", "publish_design",
    "prepare_quote", "get_pricing_policy", "set_pricing_policy", "shop_metrics",
    "queue", "start_next_job", "printer_status", "pause_print", "resume_print", "cancel_print",
    "snapshot", "set_loaded_colour", "request_human",
    "list_orders", "refund", "financials",
    "post_customer_update", "log_decision",
}


def result(r):
    if isinstance(r.data, dict):
        return r.data
    if r.structured_content is not None:
        return r.structured_content
    return json.loads(r.content[0].text)


def run(core, fn):
    async def go():
        async with Client(build_mcp(core)) as c:
            return await fn(c)
    return asyncio.run(go())


def test_lists_every_spec_tool(core):
    names = run(core, lambda c: c.list_tools())
    assert {t.name for t in names} == SPEC_TOOLS == set(ALL_TOOLS)


def test_one_call_per_tool_group(core, pipeline):
    order = core.db.create_order("dev-1", "nametag", None)
    oid = order["id"]
    # photos for generate_mesh
    up = core.settings.upload_dir(oid)
    up.mkdir(parents=True)
    (up / "photo_1.jpg").write_bytes(b"\xff\xd8")

    async def calls(c):
        out = {}
        # design
        out["templates"] = result(await c.call_tool("list_templates", {"bot": "intake"}))
        built = result(await c.call_tool("build_template", {"order_id": oid, "name": "nametag",
                                                             "params": {"text": "HI"}, "bot": "intake"}))
        raw = result(await c.call_tool("generate_mesh", {"order_id": oid, "prompt": "a dog"}))
        out["raw"] = raw
        out["finished"] = result(await c.call_tool("finish_mesh", {"order_id": oid, "src": raw["artifact_id"],
                                                                   "keyring": True}))
        out["built"] = built
        out["publish_raw"] = result(await c.call_tool("publish_design", {"order_id": oid, "artifact_id": raw["artifact_id"],
                                                                         "summary": "x"}))
        out["published"] = result(await c.call_tool("publish_design", {"order_id": oid, "artifact_id": built["artifact_id"],
                                                                       "summary": "Name tag HI"}))
        # sales
        out["quote"] = result(await c.call_tool("prepare_quote", {"order_id": oid, "bot": "sales"}))
        out["metrics"] = result(await c.call_tool("shop_metrics", {}))
        # production
        out["queue"] = result(await c.call_tool("queue", {"bot": "production"}))
        out["start"] = result(await c.call_tool("start_next_job", {"bot": "production"}))
        out["human"] = result(await c.call_tool("request_human", {"kind": "spool_swap", "details": "load red",
                                                                  "bot": "production"}))
        # support / finance
        out["fin"] = result(await c.call_tool("financials", {"days": 1, "bot": "finance"}))
        out["orders"] = result(await c.call_tool("list_orders", {"status": "quoted"}))
        # shared
        out["update"] = result(await c.call_tool("post_customer_update", {"order_id": oid, "text": "Ready to view",
                                                                          "bot": "intake"}))
        out["decision"] = result(await c.call_tool("log_decision", {"decision": "hold price", "reason": "queue short",
                                                                    "bot": "sales"}))
        out["unknown"] = result(await c.call_tool("get_order", {"order_id": "ord_nope"}))
        return out

    out = run(core, calls)
    assert out["templates"]["templates"][0]["name"] == "nametag"
    assert set(out["built"]) == {"artifact_id", "bbox_mm", "watertight", "png_url"}
    assert out["built"]["png_url"].startswith(f"http://testserver/files/{oid}/art_")
    assert out["raw"]["watertight"] is False and out["finished"]["watertight"] is True
    assert out["publish_raw"]["ok"] is False and "watertight" in out["publish_raw"]["error"]
    assert out["published"]["version"] == 1
    assert out["quote"]["price_cents"] == 800      # 300 + 75 + 83 + 40 gen = 498 -> nametag floor
    assert out["metrics"]["queue_length"] == 0
    assert out["queue"]["jobs"] == [] and out["start"] == {"started": False, "reason": "queue is empty"}
    assert out["human"]["kind"] == "spool_swap" and out["human"]["status"] == "open"
    assert out["fin"]["paid_orders"] == 0 and out["fin"]["generation_cost_cents"] == 40
    assert [o["order_id"] for o in out["orders"]["orders"]] == [oid]
    assert out["unknown"] == {"ok": False, "error": "unknown order ord_nope"}

    o = core.db.get_order(oid)
    assert o["status"] == "quoted" and o["path"] == "hybrid" and o["gen_cost_cents"] == 40
    last = core.db.list_messages(oid)[-1]
    assert (last["role"], last["text"]) == ("agent", "Ready to view")
    decision = core.db.list_events(None, "decision")[-1]
    assert decision["actor"] == "sales" and decision["payload"] == {"decision": "hold price", "reason": "queue short"}
    calls = {(e["payload"]["tool"], e["actor"]) for e in core.db.list_events(type_="tool_call")}
    assert ("prepare_quote", "sales") in calls and ("generate_mesh", "unknown") in calls


def test_cadquery_errors_are_returned_to_the_bot(core, pipeline):
    order = core.db.create_order("dev-1", "fixit", None)

    class CadError(Exception):
        traceback_tail = "NameError: name 'cq' is not defined"

    def broken(code, out_dir, timeout_s=90):
        raise CadError("result was not bound")

    pipeline.run_cadquery = broken
    out = run(core, lambda c: c.call_tool("run_cadquery", {"order_id": order["id"], "code": "x = 1"}))
    data = result(out)
    assert data["ok"] is False and "result was not bound" in data["error"]
    assert data["traceback_tail"].startswith("NameError")


def test_set_pricing_policy_clamps_to_twenty_percent(core):
    async def calls(c):
        applied = result(await c.call_tool("set_pricing_policy", {
            "policy": {"per_gram_cents": 100, "base_cents": 1, "queue_threshold": 9,
                       "floors_cents": {"nametag": 5000, "figurine": 1400, "bogus": 1}, "bogus": 3},
            "reason": "test", "bot": "sales"}))
        current = result(await c.call_tool("get_pricing_policy", {}))
        return applied, current

    applied, current = run(core, calls)
    assert applied["per_gram_cents"] == 7          # 6 * 1.2 = 7.2 -> 7
    assert applied["base_cents"] == 240            # 300 * 0.8
    assert applied["queue_threshold"] == 2         # 2 * 1.2 = 2.4 -> 2
    assert applied["floors_cents"]["nametag"] == 960 and applied["floors_cents"]["figurine"] == 1400
    assert "bogus" not in applied and "bogus" not in applied["floors_cents"]
    assert applied["per_hour_cents"] == 250        # untouched keys keep their value
    assert current == applied
    ev = core.db.list_events(None, "pricing_policy")[-1]
    assert ev["actor"] == "sales" and ev["payload"]["reason"] == "test"

    # a second change is clamped against the default, not the already-moved value
    applied2 = run(core, lambda c: c.call_tool("set_pricing_policy", {"policy": {"per_gram_cents": 9},
                                                                      "reason": "again"}))
    assert result(applied2)["per_gram_cents"] == 7


def test_refund_cap_escalates_to_human(core):
    order = designed_order(core, product="figurine")
    core.prepare_quote(order["id"], "sales")
    core.db.update_order(order["id"], price_cents=2500)
    core.mark_paid(core.db.get_order(order["id"]), "pay_big", "whop")
    out = result(run(core, lambda c: c.call_tool("refund", {"order_id": order["id"], "reason": "broke", "bot": "support"})))
    assert out["refunded"] is False and out["escalated"] is True
    assert core.db.list_human_tasks(status="open", kind="qa")[0]["order_id"] == order["id"]
    assert core.whop.refunds == []

    small = designed_order(core)
    core.prepare_quote(small["id"], "sales")
    core.mark_paid(core.db.get_order(small["id"]), "pay_small", "whop")
    out = result(run(core, lambda c: c.call_tool("refund", {"order_id": small["id"], "reason": "wrong size"})))
    assert out == {"refunded": True, "amount_cents": 800}
    assert core.whop.refunds == ["pay_small"] and core.db.get_order(small["id"])["status"] == "refunded"


def test_http_transport_requires_bearer(core):
    with TestClient(mcp_http_app(core)) as c:
        assert c.post("/mcp", json={}).status_code == 401
        assert c.post("/mcp", json={}, headers={"Authorization": "Bearer wrong"}).status_code == 401
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "t", "version": "0"}}}
        r = c.post("/mcp", json=init, headers={"Authorization": "Bearer test-mcp-token",
                                               "Accept": "application/json, text/event-stream"})
        assert r.status_code == 200
