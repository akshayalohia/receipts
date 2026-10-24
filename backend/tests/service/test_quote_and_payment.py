"""/accept -> prepare_quote (fake pipeline + mock Whop) -> quote event; Whop webhook handling."""
from __future__ import annotations

import json
import time

from fakes import APP_HEADERS, WEBHOOK_SECRET, designed_order
from service.whop import sign_webhook


def test_accept_prepares_quote_with_mock_whop(client, core, pipeline, hermes):
    order = designed_order(core)
    r = client.post(f"/orders/{order['id']}/accept", headers=APP_HEADERS)
    assert r.status_code == 202

    o = core.db.get_order(order["id"])
    assert o["status"] == "quoted"
    assert "slice_model" in pipeline.calls
    # fake quote: 300 base + 12.5 g * 6 + 1/3 h * 250 = 458 -> nametag floor 800
    assert o["price_cents"] == 800 and o["print_seconds"] == 1200 and o["filament_grams"] == 12.5
    variant = core.whop.variants[o["whop_variant_id"]]
    assert variant["title"] == f"Order {order['id']}" and variant["price_cents"] == 800
    assert o["whop_purchase_url"] == variant["purchase_url"]
    assert (core.settings.order_dir(order["id"]) / o["files"]["gcode_3mf"]).is_file()

    quote_events = core.db.list_events(order["id"], "quote")
    assert len(quote_events) == 1 and quote_events[0]["actor"] == "sales"
    assert quote_events[0]["payload"] == {"price_cents": 800, "print_seconds": 1200, "filament_grams": 12.5,
                                          "colour": "white", "whop_variant_id": o["whop_variant_id"]}
    assert hermes.profiles() == ["sales"]

    again = client.post(f"/orders/{order['id']}/accept", headers=APP_HEADERS)
    assert again.json()["status"] == "quoted" and len(core.whop.variants) == 1

    view = client.get(f"/orders/{order['id']}", headers=APP_HEADERS).json()
    assert view["quote"]["price_cents"] == 800 and view["files"]["usdz"].endswith(f"sig={core.file_sig(o)}")


def _webhook(client, payload: dict, *, secret=WEBHOOK_SECRET, ts=None, msg_id="msg_1"):
    body = json.dumps(payload).encode()
    ts = int(time.time()) if ts is None else ts
    headers = {"webhook-id": msg_id, "webhook-timestamp": str(ts),
               "webhook-signature": sign_webhook(secret, msg_id, ts, body),
               "content-type": "application/json"}
    return client.post("/webhooks/whop", content=body, headers=headers)


def _quoted(core):
    order = designed_order(core)
    core.prepare_quote(order["id"], "sales")
    return core.db.get_order(order["id"])


def test_signed_webhook_marks_paid_and_wakes_production(client, core, hermes):
    order = _quoted(core)
    payload = {"type": "payment.succeeded",
               "data": {"id": "pay_123", "plan": {"id": order["whop_variant_id"]}, "final_amount": 8.0}}

    r = _webhook(client, payload)
    assert r.status_code == 200 and r.json()["order_id"] == order["id"]
    o = core.db.get_order(order["id"])
    assert o["payment_id"] == "pay_123" and o["status"] == "queued" and o["queue_position"] == 1
    statuses = [e["payload"]["status"] for e in core.db.list_events(order["id"], "status")]
    assert statuses[-2:] == ["paid", "queued"]
    prod = [run for run in hermes.runs if run["profile"] == "production"]
    assert len(prod) == 1 and prod[0]["idempotency_key"] == "pay_123"
    assert "payment_succeeded" in prod[0]["body"]["input"]

    replay = _webhook(client, payload, msg_id="msg_2")         # same payment, redelivered
    assert replay.status_code == 200 and replay.json()["duplicate"] is True
    assert len([run for run in hermes.runs if run["profile"] == "production"]) == 1
    assert len([e for e in core.db.list_events(order["id"], "status") if e["payload"]["status"] == "paid"]) == 1


def test_webhook_rejects_bad_signature_and_stale_timestamp(client, core, hermes):
    order = _quoted(core)
    payload = {"type": "payment.succeeded", "data": {"id": "pay_9", "plan": {"id": order["whop_variant_id"]}}}

    assert _webhook(client, payload, secret="ws_wrong_secret").status_code == 401
    assert _webhook(client, payload, ts=int(time.time()) - 400).status_code == 401
    body = json.dumps(payload).encode()
    tampered = {"webhook-id": "msg_1", "webhook-timestamp": str(int(time.time())),
                "webhook-signature": sign_webhook(WEBHOOK_SECRET, "msg_1", int(time.time()), body + b" ")}
    assert client.post("/webhooks/whop", content=body, headers=tampered).status_code == 401
    assert client.post("/webhooks/whop", content=body).status_code == 401

    assert core.db.get_order(order["id"])["status"] == "quoted"
    assert hermes.runs == []


def test_webhook_secret_with_whsec_prefix():
    import base64
    from service.whop import WebhookError, verify_webhook
    secret = "whsec_" + base64.b64encode(b"raw-key-bytes").decode()
    body, ts = b'{"a":1}', int(time.time())
    headers = {"webhook-id": "m1", "webhook-timestamp": str(ts),
               "webhook-signature": "v1,bogus " + sign_webhook(secret, "m1", ts, body)}
    assert verify_webhook(secret, headers, body) == "m1"
    try:
        verify_webhook(secret, {**headers, "webhook-signature": "v1,bogus"}, body)
        raise AssertionError("expected WebhookError")
    except WebhookError:
        pass


def test_dev_pay_is_mock_only_shortcut(client, core, hermes):
    order = _quoted(core)
    r = client.post(f"/dev/pay/{order['id']}", headers=APP_HEADERS)
    assert r.status_code == 200
    assert core.db.get_order(order["id"])["status"] == "queued"
    assert [run["profile"] for run in hermes.runs] == ["production"]
    core.settings.mock = False
    assert client.post(f"/dev/pay/{order['id']}", headers=APP_HEADERS).status_code == 404
