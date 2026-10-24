"""Whop payments: list paid payments (poll) and refund. Mock reads a synthetic fixture."""
from __future__ import annotations

import json
from pathlib import Path

import httpx

WHOP_API_BASE = "https://api.whop.com/api/v1"
FIXTURE = Path(__file__).parent / "fixtures" / "mock_payments.json"
PAID_STATUSES = {"paid", "succeeded"}


def is_paid(p: dict) -> bool:
    if (p.get("substatus") or "") in ("refunded", "partially_refunded", "failed"):
        return False
    return (p.get("status") in PAID_STATUSES) or (p.get("substatus") in PAID_STATUSES)


class HttpWhop:
    def __init__(self, api_key: str, company_id: str, transport: httpx.BaseTransport | None = None):
        self.company_id = company_id
        self._http = httpx.Client(base_url=WHOP_API_BASE, timeout=30, transport=transport,
                                  headers={"Authorization": f"Bearer {api_key}"})

    def list_payments(self, max_pages: int = 20) -> list[dict]:
        """All payments for the company (newest first per Whop), following page_info cursors."""
        out: list[dict] = []
        params: dict = {"company_id": self.company_id, "first": 100}
        for _ in range(max_pages):
            r = self._http.get("/payments", params=params)
            r.raise_for_status()
            body = r.json()
            out.extend(body.get("data") or [])
            info = body.get("page_info") or {}
            if not info.get("has_next_page") or not info.get("end_cursor"):
                break
            params = {**params, "after": info["end_cursor"]}
        return out

    def refund(self, payment_id: str) -> dict:
        # Empty body = full refund (backend/service/whop.py, Whop payments/refund-payment).
        r = self._http.post(f"/payments/{payment_id}/refund", json={})
        r.raise_for_status()
        return r.json()


class MockWhop:
    """Fake Whop: returns the fixture payments (synthetic buyers, example addresses)."""

    def __init__(self, payments: list[dict] | None = None):
        self.payments = payments if payments is not None else json.loads(FIXTURE.read_text())
        self.refunds: list[str] = []

    def list_payments(self, max_pages: int = 20) -> list[dict]:
        return [dict(p) for p in self.payments]

    def refund(self, payment_id: str) -> dict:
        self.refunds.append(payment_id)
        return {"id": payment_id, "status": "paid", "substatus": "refunded"}
