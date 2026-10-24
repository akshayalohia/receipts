"""Receipts order pipeline (docs/CONTRACT.md "Backend"). Public functions used by the fleet / MCP server.

RECEIPTS_MOCK=1, or missing keys, fakes Whop / Slant / Craftcloud; the CadQuery generators always run for real.
"""
from __future__ import annotations

from pathlib import Path

from .models import PRODUCTS, STATUSES, Order, Settings, SupplierOrder

_pipeline = None


def get_pipeline():
    """Process-wide pipeline built from the environment on first use."""
    global _pipeline
    if _pipeline is None:
        from .core import Pipeline

        _pipeline = Pipeline(Settings.from_env())
    return _pipeline


def set_pipeline(p) -> None:
    """Swap the process-wide pipeline (tests, or a caller with custom clients). None = rebuild from env."""
    global _pipeline
    _pipeline = p


def _order(order_or_id) -> Order:
    if isinstance(order_or_id, Order):
        return order_or_id
    o = get_pipeline().store.find(order_or_id)
    if o is None:
        raise KeyError(f"order {order_or_id} not found")
    return o


def poll_whop() -> list[Order]:
    return get_pipeline().poll_whop()


def generate(order) -> Path:
    return get_pipeline().generate(_order(order))


def place(order) -> SupplierOrder:
    return get_pipeline().place(_order(order))


def sync_status() -> list[Order]:
    return get_pipeline().sync_status()


def refund(order_id) -> Order:
    return get_pipeline().refund(order_id)


def list_orders(status: str | None = None) -> list[Order]:
    return get_pipeline().list_orders(status)


def stats() -> dict:
    return get_pipeline().stats()


__all__ = ["PRODUCTS", "STATUSES", "Order", "SupplierOrder", "generate", "get_pipeline", "list_orders", "place",
           "poll_whop", "refund", "set_pipeline", "stats", "sync_status"]
