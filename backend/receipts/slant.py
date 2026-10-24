"""Slant 3D v2 client (docs/vendor/slant3d-openapi.json).

x-agent-hints followed: Bearer auth; presigned direct upload + REQUIRED confirm-upload; platformId on
every request that takes one; order workflow upload -> draft order -> process order; 100 req/min.
"""
from __future__ import annotations

import secrets
import time
from pathlib import Path

import httpx

SLANT_API_BASE = "https://slant3dapi.com/v2/api"

# Slant order status -> our status ("" = no change from `placed`).
STATUS_MAP = {
    "DRAFT": "", "PAID": "placed", "QUEUED": "placed", "IN_REVIEW": "placed",
    "PRINTING": "printing", "ITEMS_ON_SHELF": "printing", "POST_PROCESSING": "printing",
    "COMPLETED": "printing", "AWAITING_SHIPMENT": "printing",
    "SHIPPED": "shipped", "DELIVERED": "delivered",
    "CANCELED": "needs_review", "PAYMENT_ERROR": "needs_review",
}


def usd_to_cents(v) -> int:
    try:
        return int(round(float(v or 0) * 100))
    except (TypeError, ValueError):
        return 0


class SlantError(Exception):
    pass


class HttpSlant:
    def __init__(self, api_key: str, platform_id: str, transport: httpx.BaseTransport | None = None,
                 upload_transport: httpx.BaseTransport | None = None):
        self.platform_id = platform_id
        self._http = httpx.Client(base_url=SLANT_API_BASE, timeout=60, transport=transport,
                                  headers={"Authorization": f"Bearer {api_key}"})
        # Presigned S3 URL: no API auth header.
        self._s3 = httpx.Client(timeout=120, transport=upload_transport or transport)
        self._filaments: dict[str, str] = {}

    def _data(self, r: httpx.Response):
        if r.status_code >= 400:
            raise SlantError(f"Slant {r.request.method} {r.request.url.path} -> {r.status_code}: {r.text[:300]}")
        body = r.json()
        if body.get("success") is False:
            raise SlantError(f"Slant {r.request.url.path}: {body.get('message')}")
        return body.get("data")

    def upload_file(self, path: Path, owner_id: str = "") -> str:
        """direct-upload -> PUT to presigned URL -> confirm-upload. Returns publicFileServiceId."""
        path = Path(path)
        req = {"name": path.name, "platformId": self.platform_id}
        if owner_id:
            req["ownerId"] = owner_id
        data = self._data(self._http.post("/files/direct-upload", json=req))
        put = self._s3.put(data["presignedUrl"], content=path.read_bytes())
        if put.status_code >= 300:
            raise SlantError(f"presigned upload failed: {put.status_code}")
        conf = self._data(self._http.post("/files/confirm-upload", json={"filePlaceholder": data["filePlaceholder"]}))
        return conf["publicFileServiceId"]

    def filament_id(self, colour: str) -> str | None:
        """PETG in the colour (plan says PETG), falling back to PLA; None = Slant default (PLA Black)."""
        if colour in self._filaments:
            return self._filaments[colour]
        fid = None
        for profile in ("PETG", "PLA"):
            data = self._data(self._http.get("/filaments", params={"profile": profile, "color": colour})) or []
            avail = [f for f in data if f.get("available", True)]
            if avail:
                fid = avail[0]["publicId"]
                break
        self._filaments[colour] = fid
        return fid

    def draft_order(self, *, items: list[dict], email: str, address: dict, owner_id: str = "") -> dict:
        body = {"platformId": self.platform_id,
                "customer": {"details": {"email": email, "address": address}},
                "items": items}
        if owner_id:
            body["ownerId"] = owner_id
        return self._data(self._http.post("/orders", json=body))["order"]

    def process_order(self, public_id: str) -> dict:
        return self._data(self._http.post(f"/orders/{public_id}"))["order"]

    def cancel_order(self, public_id: str) -> None:
        self._data(self._http.delete(f"/orders/{public_id}"))

    def get_order(self, public_id: str) -> dict:
        return self._data(self._http.get(f"/orders/{public_id}"))["order"]


class MockSlant:
    """Fake Slant: fake ids, fixed per-item costs, status advances one step per get_order()."""

    COST_PER_ITEM = {"card": 650, "plaque": 980, "stand": 120}
    SHIPPING_CENTS = 550
    FLOW = ["PAID", "PRINTING", "SHIPPED", "DELIVERED"]

    def __init__(self, cost_override_cents: int | None = None):
        self.cost_override_cents = cost_override_cents
        self.files: dict[str, str] = {}
        self.orders: dict[str, dict] = {}
        self.processed: list[str] = []
        self.cancelled: list[str] = []

    def upload_file(self, path: Path, owner_id: str = "") -> str:
        fid = f"mockfile-{secrets.token_hex(6)}"
        self.files[fid] = Path(path).name
        return fid

    def filament_id(self, colour: str) -> str | None:
        return f"mock-filament-{colour}"

    def draft_order(self, *, items: list[dict], email: str, address: dict, owner_id: str = "") -> dict:
        cost = 0
        for it in items:
            name = self.files.get(it.get("publicFileServiceId", ""), "")
            kind = "stand" if "stand" in name else ("card" if "tweet" in name else "plaque")
            cost += self.COST_PER_ITEM[kind] * it.get("quantity", 1)
        if self.cost_override_cents is not None:
            cost = self.cost_override_cents
        oid = f"SLANT_MOCK{secrets.token_hex(4).upper()}"
        o = {"publicId": oid, "status": "DRAFT", "printingCost": f"{cost / 100:.2f}",
             "deliveryCost": f"{self.SHIPPING_CENTS / 100:.2f}", "items": items, "_step": -1,
             "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        self.orders[oid] = o
        return dict(o)

    def process_order(self, public_id: str) -> dict:
        o = self.orders[public_id]
        o["status"], o["_step"] = "PAID", 0
        self.processed.append(public_id)
        return dict(o)

    def cancel_order(self, public_id: str) -> None:
        self.orders[public_id]["status"] = "CANCELED"
        self.cancelled.append(public_id)

    def get_order(self, public_id: str) -> dict:
        o = self.orders.get(public_id)
        if o is None:
            return {"publicId": public_id, "status": "QUEUED"}
        if o["_step"] >= 0 and o["_step"] < len(self.FLOW) - 1:
            o["_step"] += 1
            o["status"] = self.FLOW[o["_step"]]
        return dict(o)
