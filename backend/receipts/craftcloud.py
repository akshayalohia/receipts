"""Craftcloud v5 client (docs/vendor/craftcloud-openapi.json): price -> poll -> cheapest offer -> cart -> order.

The spec is partial. Steps it leaves unclear are marked TODO(craftcloud) and the live client is only
used with CRAFTCLOUD_LIVE=1 (see Settings.craftcloud_mock); otherwise MockCraftcloud runs.
"""
from __future__ import annotations

import os
import secrets
import time
from pathlib import Path

import httpx

# TODO(craftcloud): the spec has no `servers`/`host`; base URL assumed, override with CRAFTCLOUD_BASE_URL.
CRAFTCLOUD_API_BASE = os.environ.get("CRAFTCLOUD_BASE_URL", "https://api.craftcloud3d.com")

STATUS_MAP = {"ordered": "placed", "in_production": "printing", "shipped": "shipped", "received": "delivered",
              "blocked": "needs_review", "cancelled": "needs_review"}


class CraftcloudError(Exception):
    pass


def fullcolour_material_ids() -> list[str]:
    # TODO(craftcloud): the spec has no material catalogue, so which materialConfigIds are full colour
    # (HP MJF colour, PolyJet) has to be configured: CRAFTCLOUD_FULLCOLOUR_MATERIAL_IDS=id1,id2
    return [s.strip() for s in os.environ.get("CRAFTCLOUD_FULLCOLOUR_MATERIAL_IDS", "").split(",") if s.strip()]


def pick_cheapest(price: dict, material_ids: list[str] | None = None) -> dict | None:
    """Cheapest quote (+ cheapest shipping from the same vendor) among full-colour material configs.

    Returns {quoteId, vendorId, materialConfigId, shippingId, price_cents, shipping_cents} or None.
    """
    allowed = set(material_ids or [])
    ships_by_vendor: dict[str, dict] = {}
    for s in price.get("shippings") or []:
        cur = ships_by_vendor.get(s["vendorId"])
        if cur is None or s["price"] < cur["price"]:
            ships_by_vendor[s["vendorId"]] = s
    best = None
    for q in price.get("quotes") or []:
        if allowed and q["materialConfigId"] not in allowed:
            continue
        if q.get("currency", "USD") != "USD":
            continue
        ship = ships_by_vendor.get(q["vendorId"])
        if ship is None:
            continue
        total = q["price"] + ship["price"]
        if best is None or total < best[0]:
            best = (total, q, ship)
    if best is None:
        return None
    _, q, ship = best
    return {"quoteId": q["quoteId"], "vendorId": q["vendorId"], "materialConfigId": q["materialConfigId"],
            "shippingId": ship["shippingId"], "price_cents": int(round(q["price"] * 100)),
            "shipping_cents": int(round(ship["price"] * 100))}


def split_name(full: str) -> tuple[str, str]:
    parts = (full or "").strip().split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:]) or parts[0]


class HttpCraftcloud:
    def __init__(self, api_key: str, transport: httpx.BaseTransport | None = None,
                 sleep=time.sleep, base_url: str = CRAFTCLOUD_API_BASE):
        # TODO(craftcloud): the spec declares no security scheme; Bearer is an assumption.
        self._http = httpx.Client(base_url=base_url, timeout=60, transport=transport,
                                  headers={"Authorization": f"Bearer {api_key}"})
        self._sleep = sleep

    def _json(self, r: httpx.Response):
        if r.status_code >= 400:
            raise CraftcloudError(f"Craftcloud {r.request.method} {r.request.url.path} -> {r.status_code}: {r.text[:300]}")
        return r.json()

    def upload_model(self, path: Path) -> str:
        # TODO(craftcloud): v5 spec has no model upload endpoint (only modelIds in price requests).
        raise NotImplementedError("TODO(craftcloud): model upload endpoint is not in the v5 spec")

    def create_price(self, model_id: str, quantity: int = 1, material_ids: list[str] | None = None) -> str:
        body = {"currency": "USD", "countryCode": "US", "models": [{"modelId": model_id, "quantity": quantity}]}
        if material_ids:
            body["materialConfigIds"] = list(material_ids)
        return self._json(self._http.post("/v5/price", json=body))["priceId"]

    def poll_price(self, price_id: str, attempts: int = 30, interval_s: float = 2.0) -> dict:
        data = {}
        for _ in range(attempts):
            data = self._json(self._http.get(f"/v5/price/{price_id}"))
            if data.get("allComplete"):
                return data
            self._sleep(interval_s)
        return data  # partial prices: caller picks from what arrived

    def create_cart(self, quote_id: str, shipping_id: str, reference: str = "") -> dict:
        body = {"shippingIds": [shipping_id], "currency": "USD", "quotes": [{"id": quote_id}]}
        if reference:
            body["customerReference"] = reference[:128]
        return self._json(self._http.post("/v5/cart", json=body))

    def create_order(self, cart_id: str, *, email: str, ship: dict) -> dict:
        first, last = split_name(ship.get("name", ""))
        # TODO(craftcloud): phoneNumber is required but checkout collects none; we use our own contact
        # number (CRAFTCLOUD_CONTACT_PHONE). Billing should be the business; same-as-shipping until set.
        phone = os.environ.get("CRAFTCLOUD_CONTACT_PHONE", "0000000000")
        addr = {"firstName": first, "lastName": last, "address": ship.get("line1", ""),
                "addressLine2": ship.get("line2") or None, "city": ship.get("city", ""),
                "zipCode": ship.get("zip", ""), "stateCode": ship.get("state") or None, "countryCode": "US"}
        body = {"cartId": cart_id, "user": {
            "emailAddress": email,
            "shipping": {**addr, "phoneNumber": phone},
            "billing": {**addr, "phoneNumber": phone, "isCompany": False},
        }}
        # TODO(craftcloud): payment for the created order (/v5/payment/*) is not wired; confirm the
        # account's invoice/net30 terms with Craftcloud before going live.
        return self._json(self._http.post("/v5/order", json=body))

    def order_status(self, order_id: str) -> str:
        data = self._json(self._http.get(f"/v5/order/{order_id}/status"))
        latest = ""
        for part in data.get("status") or []:
            events = sorted(part.get("orderStatus") or [], key=lambda e: e.get("date", ""))
            if events:
                latest = events[-1]["type"]
        return latest


class MockCraftcloud:
    """Fake Craftcloud: one full-colour quote, fake ids, status advances per call."""

    FLOW = ["ordered", "in_production", "shipped", "received"]

    def __init__(self, price_cents: int = 3800, shipping_cents: int = 900):
        self.price_cents, self.shipping_cents = price_cents, shipping_cents
        self.orders: dict[str, int] = {}

    def upload_model(self, path: Path) -> str:
        return f"mockmodel-{secrets.token_hex(6)}"

    def create_price(self, model_id: str, quantity: int = 1, material_ids: list[str] | None = None) -> str:
        return f"mockprice-{secrets.token_hex(4)}"

    def poll_price(self, price_id: str, attempts: int = 30, interval_s: float = 2.0) -> dict:
        return {"allComplete": True, "quotes": [
            {"quoteId": "mockquote", "vendorId": "mockvendor", "modelId": "m", "materialConfigId": "mock-fullcolour",
             "price": self.price_cents / 100, "quantity": 1, "currency": "USD"}],
            "shippings": [{"shippingId": "00000000-0000-0000-0000-000000000000", "vendorId": "mockvendor",
                           "price": self.shipping_cents / 100, "currency": "USD", "type": "standard"}]}

    def create_cart(self, quote_id: str, shipping_id: str, reference: str = "") -> dict:
        return {"cartId": f"mockcart-{secrets.token_hex(4)}"}

    def create_order(self, cart_id: str, *, email: str, ship: dict) -> dict:
        oid = f"mockcc-{secrets.token_hex(6)}"
        self.orders[oid] = 0
        return {"orderId": oid, "orderNumber": oid.upper()}

    def order_status(self, order_id: str) -> str:
        step = self.orders.get(order_id, 0)
        self.orders[order_id] = min(step + 1, len(self.FLOW) - 1)
        return self.FLOW[step]
