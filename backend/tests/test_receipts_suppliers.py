"""Slant 3D v2 and Craftcloud v5 request shapes, checked against docs/vendor/*.json (stubbed transport)."""
import json
from pathlib import Path

import httpx
import pytest

from receipts import core
from receipts.craftcloud import HttpCraftcloud, MockCraftcloud, pick_cheapest
from receipts.models import NEEDS_REVIEW, PLACED, PRINTING, SHIPPED, Settings
from receipts.slant import HttpSlant
from receipts.whop import MockWhop

VENDOR = Path(__file__).parents[2] / "docs" / "vendor"
SLANT = json.loads((VENDOR / "slant3d-openapi.json").read_text())
CRAFT = json.loads((VENDOR / "craftcloud-openapi.json").read_text())
FIXTURE = json.loads((Path(__file__).parents[1] / "receipts" / "fixtures" / "mock_payments.json").read_text())
FILE_ID = "6f1c2c1e-0b7a-4c55-9d7e-2b1f0c3d4e5f"
UUID = "20106a2d-1fc5-4a04-8393-6139e5803dfd"


def _resolve(spec, schema):
    while "$ref" in schema:
        node = spec
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        schema = node
    return schema


def check(spec, schema, value, path="$"):
    """Minimal schema check: required keys, no unknown keys when additionalProperties is false, types."""
    schema = _resolve(spec, schema)
    if "allOf" in schema:
        for s in schema["allOf"]:
            check(spec, s, value, path)
        return
    t = schema.get("type")
    if t == "object" or "properties" in schema:
        assert isinstance(value, dict), f"{path}: expected object"
        for k in schema.get("required", []):
            assert k in value, f"{path}: missing required {k!r}"
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(props)
            assert not extra, f"{path}: unknown keys {extra}"
        for k, v in value.items():
            if k in props:
                check(spec, props[k], v, f"{path}.{k}")
    elif t == "array":
        assert isinstance(value, list), f"{path}: expected array"
        for i, v in enumerate(value):
            check(spec, schema.get("items", {}), v, f"{path}[{i}]")
    elif t == "string" or t == ["string", "null"]:
        assert isinstance(value, str) or (value is None and isinstance(t, list)), f"{path}: expected string"
        if "enum" in schema:
            assert value in schema["enum"], f"{path}: {value!r} not in enum"
    elif t == "integer":
        assert isinstance(value, int), f"{path}: expected integer"
    elif t == "boolean":
        assert isinstance(value, bool), f"{path}: expected boolean"


def slant_body_schema(path, method):
    return SLANT["paths"][path][method]["requestBody"]["content"]["application/json"]["schema"]


def craft_body_schema(path, method):
    return next(p["schema"] for p in CRAFT["paths"][path][method]["parameters"] if p["in"] == "body")


def ok(data, status=200):
    return httpx.Response(status, json={"success": True, "message": "ok", "data": data})


class SlantStub:
    def __init__(self, printing="6.50", delivery="5.50"):
        self.reqs: list[httpx.Request] = []
        self.printing, self.delivery = printing, delivery
        self.n = 0

    def __call__(self, req: httpx.Request):
        self.reqs.append(req)
        p = req.url.path
        if req.url.host == "s3.test":
            return httpx.Response(200)
        assert req.headers["authorization"] == "Bearer sl-test"
        if p == "/v2/api/files/direct-upload":
            check(SLANT, slant_body_schema("/files/direct-upload", "post"), json.loads(req.content))
            self.n += 1
            return ok({"presignedUrl": f"https://s3.test/up/{self.n}", "key": f"k{self.n}",
                       "filePlaceholder": {"publicFileServiceId": FILE_ID, "name": json.loads(req.content)["name"]}})
        if p == "/v2/api/files/confirm-upload":
            check(SLANT, slant_body_schema("/files/confirm-upload", "post"), json.loads(req.content))
            return ok({"publicFileServiceId": FILE_ID})
        if p == "/v2/api/filaments":
            return ok([{"publicId": "fil-petg-red", "name": "PETG Red", "provider": "x", "profile": "PETG",
                        "color": "red", "hexValue": "#ff0000", "available": True}])
        if p == "/v2/api/orders" and req.method == "POST":
            check(SLANT, slant_body_schema("/orders", "post"), json.loads(req.content))
            return ok({"order": {"publicId": "SLANT_ABC123", "status": "DRAFT", "printingCost": self.printing,
                                 "deliveryCost": self.delivery}}, 201)
        if p == "/v2/api/orders/SLANT_ABC123" and req.method == "POST":
            assert not req.content
            return ok({"order": {"publicId": "SLANT_ABC123", "status": "PAID"}})
        if p == "/v2/api/orders/SLANT_ABC123" and req.method == "DELETE":
            return ok({})
        if p == "/v2/api/orders/SLANT_ABC123" and req.method == "GET":
            return ok({"order": {"publicId": "SLANT_ABC123", "status": "SHIPPED"}})
        return httpx.Response(404, json={"success": False, "message": f"no route {req.method} {p}"})


def _pipeline(tmp_path, *, slant=None, cc=None, payment):
    s = Settings(data_dir=tmp_path, mock=True)
    return core.Pipeline(s, whop=MockWhop([payment]), slant=slant, craftcloud=cc,
                         site=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))))


def _generated(p, tmp_path):
    (o,) = p.poll_whop()
    d = p.order_dir(o)
    d.mkdir(parents=True)
    (d / "tweet_card.stl").write_bytes(b"solid card\nendsolid card\n")
    (d / "stand.stl").write_bytes(b"solid stand\nendsolid stand\n")
    o = p.store.update(o.seq, file_path=str(d / "tweet_card.stl"))
    return p.set_status(o, "generated")


def test_slant_full_flow_request_shapes(tmp_path):
    stub = SlantStub()
    slant = HttpSlant("sl-test", "11111111-2222-3333-4444-555555555555", transport=httpx.MockTransport(stub))
    pay = {**FIXTURE[0], "metadata": {**FIXTURE[0]["metadata"], "colour": "red"}}
    p = _pipeline(tmp_path, slant=slant, payment=pay)
    o = _generated(p, tmp_path)
    so = p.place(o)
    assert so.placed and so.supplier_order_id == "SLANT_ABC123"
    assert (so.cost_cents, so.shipping_cents) == (650, 550)
    order = p.store.get(o.seq)
    assert order.status == PLACED
    paths = [(r.method, r.url.host, r.url.path) for r in stub.reqs]
    assert paths[0] == ("GET", "slant3dapi.com", "/v2/api/filaments")
    assert stub.reqs[0].url.params["profile"] == "PETG" and stub.reqs[0].url.params["color"] == "red"
    assert paths.count(("POST", "slant3dapi.com", "/v2/api/files/direct-upload")) == 2
    puts = [r for r in stub.reqs if r.url.host == "s3.test"]
    assert len(puts) == 2 and all(r.method == "PUT" and "authorization" not in r.headers for r in puts)
    assert puts[0].content.startswith(b"solid card")
    # confirm-upload echoes the exact placeholder
    conf = [json.loads(r.content) for r in stub.reqs if r.url.path.endswith("/confirm-upload")]
    assert conf[0] == {"filePlaceholder": {"publicFileServiceId": FILE_ID, "name": "tweet_card.stl"}}
    draft = json.loads(next(r.content for r in stub.reqs if r.url.path == "/v2/api/orders"))
    assert draft["platformId"] == "11111111-2222-3333-4444-555555555555"
    assert draft["customer"]["details"]["address"]["country"] == "US"
    assert draft["items"][0] == {"type": "PRINT", "quantity": 1, "publicFileServiceId": FILE_ID,
                                 "filamentId": "fil-petg-red"}
    # process after the margin check, then status sync
    assert ("POST", "slant3dapi.com", "/v2/api/orders/SLANT_ABC123") in paths
    (synced,) = p.sync_status()
    assert synced.status == SHIPPED


def test_slant_margin_guard_does_not_process(tmp_path):
    stub = SlantStub(printing="19.00", delivery="6.00")
    slant = HttpSlant("sl-test", "11111111-2222-3333-4444-555555555555", transport=httpx.MockTransport(stub))
    p = _pipeline(tmp_path, slant=slant, payment=FIXTURE[0])
    o = _generated(p, tmp_path)
    assert not p.place(o).placed
    assert p.store.get(o.seq).status == NEEDS_REVIEW
    methods = [(r.method, r.url.path) for r in stub.reqs if r.url.path == "/v2/api/orders/SLANT_ABC123"]
    assert methods == [("DELETE", "/v2/api/orders/SLANT_ABC123")]


class CraftStub:
    def __init__(self):
        self.reqs: list[httpx.Request] = []
        self.polls = 0

    def __call__(self, req: httpx.Request):
        self.reqs.append(req)
        p, body = req.url.path, (json.loads(req.content) if req.content else None)
        assert req.headers["authorization"] == "Bearer cc-test"
        if p == "/v5/price" and req.method == "POST":
            check(CRAFT, craft_body_schema("/v5/price", "post"), body)
            return httpx.Response(201, json={"priceId": UUID})
        if p == f"/v5/price/{UUID}":
            self.polls += 1
            q = lambda qid, vendor, mat, price: {  # noqa: E731
                "quoteId": qid, "vendorId": vendor, "modelId": "model123", "materialConfigId": mat, "price": price,
                "quantity": 1, "currency": "USD", "productionTimeFast": 5, "productionTimeSlow": 9, "scale": 1,
                "priceInclVat": price}
            s = lambda sid, vendor, price: {  # noqa: E731
                "shippingId": sid, "vendorId": vendor, "name": "UPS Ground", "deliveryTime": "3-5", "price": price,
                "currency": "USD", "type": "standard", "carrier": "UPS"}
            return httpx.Response(200, json={
                "expiresAt": 1, "allComplete": self.polls >= 2, "printingServiceComplete": {}, "minimumProductionPrice": {},
                "quotes": [q("q-pla", "cheapvendor", "mat-pla", 5.0), q("q-fc-a", "vendora", "mat-fullcolour", 30.0),
                           q("q-fc-b", "vendorb", "mat-fullcolour", 26.0)],
                "shippings": [s("11111111-1111-1111-1111-111111111111", "vendora", 8.0),
                              s("22222222-2222-2222-2222-222222222222", "vendorb", 15.0),
                              s("33333333-3333-3333-3333-333333333333", "vendorb", 11.0)]})
        if p == "/v5/cart":
            check(CRAFT, craft_body_schema("/v5/cart", "post"), body)
            return httpx.Response(201, json={"cartId": "cart-1"})
        if p == "/v5/order":
            check(CRAFT, craft_body_schema("/v5/order", "post"), body)
            return httpx.Response(201, json={"orderId": UUID, "orderNumber": "CC-1", "amounts": {}})
        if p == f"/v5/order/{UUID}/status":
            return httpx.Response(200, json={"orderNumber": "CC-1", "estDeliveryTime": {}, "status": [
                {"vendorId": "vendorb", "cancelled": False, "orderStatus": [
                    {"type": "ordered", "date": "2026-10-24"}, {"type": "in_production", "date": "2026-10-25"}]}]})
        return httpx.Response(404)


def test_craftcloud_flow_request_shapes(tmp_path, monkeypatch):
    monkeypatch.setenv("CRAFTCLOUD_FULLCOLOUR_MATERIAL_IDS", "mat-fullcolour")
    stub = CraftStub()
    cc = HttpCraftcloud("cc-test", transport=httpx.MockTransport(stub), sleep=lambda s: None,
                        base_url="https://cc.test")
    monkeypatch.setattr(cc, "upload_model", lambda path: "model123")  # TODO(craftcloud): no upload endpoint in spec
    p = _pipeline(tmp_path, cc=cc, payment=FIXTURE[2])
    (o,) = p.poll_whop()
    zp = p.order_dir(o) / "receipt_fullcolour.zip"
    zp.parent.mkdir(parents=True)
    zp.write_bytes(b"PK")
    o = p.set_status(p.store.update(o.seq, file_path=str(zp)), "generated")
    so = p.place(o)
    # cheapest full-colour quote + shipping: vendorb 26 + 11 = 37 beats vendora 30 + 8 = 38; PLA ignored
    assert so.placed and (so.cost_cents, so.shipping_cents) == (2600, 1100)
    price_req = json.loads(stub.reqs[0].content)
    assert price_req == {"currency": "USD", "countryCode": "US", "models": [{"modelId": "model123", "quantity": 1}],
                         "materialConfigIds": ["mat-fullcolour"]}
    assert stub.polls == 2
    cart = json.loads(next(r.content for r in stub.reqs if r.url.path == "/v5/cart"))
    assert cart["quotes"] == [{"id": "q-fc-b"}] and cart["shippingIds"] == ["33333333-3333-3333-3333-333333333333"]
    order = json.loads(next(r.content for r in stub.reqs if r.url.path == "/v5/order"))
    assert order["cartId"] == "cart-1" and order["user"]["shipping"]["countryCode"] == "US"
    assert order["user"]["shipping"]["stateCode"] == "TX"
    assert p.store.get(o.seq).status == PLACED
    (synced,) = p.sync_status()
    assert synced.status == PRINTING


def test_craftcloud_upload_is_todo():
    with pytest.raises(NotImplementedError):
        HttpCraftcloud("k").upload_model(Path("x.zip"))


def test_pick_cheapest_none_without_shipping():
    assert pick_cheapest({"quotes": [{"quoteId": "q", "vendorId": "v", "materialConfigId": "m", "price": 1.0}],
                          "shippings": []}) is None
    assert MockCraftcloud().poll_price("x")["allComplete"]
