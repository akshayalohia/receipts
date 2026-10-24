"""Whop: one-time plan per quote, refunds, Standard Webhooks signature check.

The money path uses the REST API key server-side. Fulfilment happens only from the
verified `payment.succeeded` webhook (see app.py).

Checked against docs.whop.com (copies in runs/integ/docs/, fetched 2026-10-24):
- `POST /api/v1/plans` (api-reference/beta/plans/create-plan): Whop calls a plan a "variant";
  its id is `plan_...` and the response carries `purchase_url`. `title` is max 30 chars.
  `metadata` is "included in webhook payloads for payment and membership events".
- The iOS SDK buys exactly that id: `Checkout.shared.purchase(_ whopPlanId:)` (ios checkout
  reference), so `whop_variant_id` stores the `plan_` id.
- `POST /api/v1/payments/{id}/refund` (payments/refund-payment): empty body = full refund.
- Webhooks (developer/guides/webhooks): HMAC-SHA256 over `{webhook-id}.{webhook-timestamp}.{body}`,
  key = the `ws_...` secret exactly as Whop gave it, `webhook-signature: v1,<base64>`, 5 min tolerance.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Mapping, Protocol

import httpx

WHOP_API_BASE = "https://api.whop.com/api/v1"
WEBHOOK_TOLERANCE_S = 5 * 60
PLAN_TITLE_MAX = 30


class WhopClient(Protocol):
    def create_variant(self, *, order_id: str, price_cents: int, title: str) -> dict: ...
    def refund(self, *, payment_id: str) -> dict: ...


class MockWhop:
    """Offline stand-in: returns fake ids and a local purchase URL."""

    def __init__(self, base_url: str = "") -> None:
        self.base_url = base_url
        self.variants: dict[str, dict] = {}
        self.refunds: list[str] = []

    def create_variant(self, *, order_id: str, price_cents: int, title: str) -> dict:
        vid = "plan_mock_" + secrets.token_hex(5)
        v = {"id": vid, "purchase_url": f"{self.base_url}/dev/pay/{order_id}",
             "price_cents": price_cents, "title": title, "order_id": order_id}
        self.variants[vid] = v
        return v

    def refund(self, *, payment_id: str) -> dict:
        self.refunds.append(payment_id)
        return {"id": payment_id, "status": "refunded"}


class HttpWhop:
    def __init__(self, api_key: str, company_id: str, product_id: str,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.company_id = company_id
        self.product_id = product_id
        self._http = httpx.Client(base_url=WHOP_API_BASE, timeout=30, transport=transport,
                                  headers={"Authorization": f"Bearer {api_key}"})

    def create_variant(self, *, order_id: str, price_cents: int, title: str) -> dict:
        """One-time plan on WHOP_PRODUCT_ID; returns {id: "plan_...", purchase_url}."""
        body = {
            "account_id": self.company_id,          # optional with an account API key (it supplies its own)
            "product_id": self.product_id,
            "plan_type": "one_time",
            "release_method": "buy_now",
            "visibility": "hidden",                 # reachable only by its direct link / id, not on the product page
            "initial_price": round(price_cents / 100, 2),
            "currency": "usd",
            "title": title[:PLAN_TITLE_MAX],
            "description": f"Micro Factory order {order_id}",
            "metadata": {"order_id": order_id},
        }
        headers = {"Idempotency-Key": f"mf-plan-{order_id}-{price_cents}"}
        r = self._http.post("/plans", json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
        return {"id": data["id"], "purchase_url": data.get("purchase_url")}

    def refund(self, *, payment_id: str) -> dict:
        r = self._http.post(f"/payments/{payment_id}/refund", json={})
        r.raise_for_status()
        return r.json()


def make_whop(settings) -> WhopClient:
    if settings.mock or not settings.whop_api_key:
        return MockWhop(settings.public_base_url)
    return HttpWhop(settings.whop_api_key, settings.whop_company_id, settings.whop_product_id)


class WebhookError(Exception):
    pass


def _secret_bytes(secret: str) -> bytes:
    """HMAC key for a webhook secret.

    Whop (webhooks guide, "Verify without an SDK"): the key is the `ws_...` secret itself,
    used as given (don't strip the prefix, don't base64 it). A generic Standard Webhooks
    `whsec_<base64>` secret is decoded per that spec.
    """
    if secret.startswith("whsec_"):
        return base64.b64decode(secret[len("whsec_"):])
    return secret.encode()


def sign_webhook(secret: str, msg_id: str, timestamp: int | str, body: bytes) -> str:
    signed = f"{msg_id}.{timestamp}.".encode() + body
    digest = hmac.new(_secret_bytes(secret), signed, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


def verify_webhook(secret: str, headers: Mapping[str, str], body: bytes,
                   now: float | None = None) -> str:
    """Verify `webhook-id/-timestamp/-signature`; returns the webhook id or raises WebhookError."""
    if not secret:
        raise WebhookError("webhook secret not configured")
    lower = {k.lower(): v for k, v in headers.items()}
    msg_id = lower.get("webhook-id")
    ts = lower.get("webhook-timestamp")
    sig_header = lower.get("webhook-signature")
    if not (msg_id and ts and sig_header):
        raise WebhookError("missing webhook headers")
    try:
        ts_int = int(ts)
    except ValueError as e:
        raise WebhookError("bad timestamp") from e
    now = time.time() if now is None else now
    if abs(now - ts_int) > WEBHOOK_TOLERANCE_S:
        raise WebhookError("timestamp outside tolerance")
    expected = sign_webhook(secret, msg_id, ts, body).split(",", 1)[1]
    for part in sig_header.split():
        version, _, sig = part.partition(",")
        if version == "v1" and hmac.compare_digest(sig, expected):
            return msg_id
    raise WebhookError("signature mismatch")
