"""App, admin and file-URL auth."""
from __future__ import annotations

from fakes import ADMIN_HEADERS, APP_HEADERS, designed_order


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"ok": True, "mock": True, "printer_state": "IDLE"}


def test_app_routes_need_app_key_and_device(client, core):
    order = designed_order(core)
    oid = order["id"]
    routes = [("get", "/catalog", None), ("post", "/orders", {"product": "nametag"}), ("get", "/orders", None),
              ("get", f"/orders/{oid}", None), ("post", f"/orders/{oid}/messages", {"text": "hi"}),
              ("get", f"/orders/{oid}/stream", None), ("post", f"/orders/{oid}/accept", None),
              ("get", f"/orders/{oid}/camera.jpg", None), ("post", "/voice/token", {"order_id": oid}),
              ("post", f"/dev/pay/{oid}", None)]
    bad = [{}, {"X-Device-Id": "dev-1"}, {"X-App-Key": "test-app-key"},
           {"X-App-Key": "wrong", "X-Device-Id": "dev-1"}]
    for method, path, body in routes:
        for headers in bad:
            r = client.request(method.upper(), path, json=body, headers=headers)
            assert r.status_code == 401, (path, headers, r.status_code)


def test_orders_are_scoped_to_device(client, core):
    order = designed_order(core, device="dev-1")
    other = {"X-App-Key": "test-app-key", "X-Device-Id": "dev-2"}
    assert client.get(f"/orders/{order['id']}", headers=other).status_code == 404
    assert client.get("/orders", headers=other).json() == {"orders": []}
    assert [o["id"] for o in client.get("/orders", headers=APP_HEADERS).json()["orders"]] == [order["id"]]


def test_file_urls_need_signature_or_owner_headers(client, core):
    order = designed_order(core)
    name = order["files"]["glb"]
    assert client.get(f"/files/{order['id']}/{name}").status_code == 401
    assert client.get(f"/files/{order['id']}/{name}?sig=deadbeef").status_code == 401
    assert client.get(f"/files/{order['id']}/{name}?sig={core.file_sig(order)}").content == b"fake glb"
    assert client.get(f"/files/{order['id']}/{name}", headers=APP_HEADERS).status_code == 200
    assert client.get(f"/files/{order['id']}/..%2Fdb.sqlite?sig={core.file_sig(order)}").status_code == 404


def test_admin_routes_need_admin_key(client, core):
    for method, path, body in [("get", "/admin/state", None), ("post", "/admin/spool", {"colour": "red"}),
                               ("post", "/admin/bed-cleared", None), ("get", "/admin/human-tasks", None),
                               ("post", "/admin/human-tasks/1/done", None), ("post", "/admin/stock", {"colours": ["red"]})]:
        assert client.request(method.upper(), path, json=body).status_code == 401
        assert client.request(method.upper(), path, json=body, headers=APP_HEADERS).status_code == 401
    r = client.post("/admin/stock", json={"colours": ["white", "red"]}, headers=ADMIN_HEADERS)
    assert r.json() == {"colours_in_stock": ["white", "red"]}
    assert client.get("/admin/state", headers=ADMIN_HEADERS).json()["shop_state"]["colours_in_stock"] == ["white", "red"]


def test_catalog_and_voice_token(client, core):
    cat = client.get("/catalog", headers=APP_HEADERS).json()
    assert {p["id"] for p in cat["products"]} == {"keychain", "nametag", "fixit", "holder", "figurine"}
    assert next(p for p in cat["products"] if p["id"] == "nametag")["from_price_cents"] == 800
    assert cat["loaded_colour"] == "white"
    order = designed_order(core)
    tok = client.post("/voice/token", json={"order_id": order["id"]}, headers=APP_HEADERS).json()
    assert tok["conversation_token"].startswith("mock_") and tok["agent_id"] == "mock-agent"
