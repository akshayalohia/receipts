"""Products, order status machine, Order / SupplierOrder records, env settings."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# docs/CONTRACT.md "Products" (single source of truth)
PRODUCTS: dict[str, dict] = {
    "tweet": {"name": "Tweet Trophy", "price_cents": 2099, "supplier": "slant", "qty": 1},
    "milestone": {"name": "Milestone Plaque", "price_cents": 2799, "supplier": "slant", "qty": 1},
    "fullcolour": {"name": "Full-Colour Receipt", "price_cents": 8900, "supplier": "craftcloud", "qty": 1},
    "team": {"name": "Team Pack", "price_cents": 15899, "supplier": "slant", "qty": 10},
}
COLOURS = ("black", "white", "red", "blue", "green", "gold")
FOUNDING_LIMIT = 100
MIN_MARGIN = 0.40
WHOP_FEE_PCT = 0.027
WHOP_FEE_FIXED_CENTS = 30

PAID, GENERATED, PLACED, PRINTING, SHIPPED, DELIVERED = "paid", "generated", "placed", "printing", "shipped", "delivered"
NEEDS_REVIEW, REFUNDED, FAILED = "needs_review", "refunded", "failed"
MAIN_FLOW = (PAID, GENERATED, PLACED, PRINTING, SHIPPED, DELIVERED)
STATUSES = MAIN_FLOW + (NEEDS_REVIEW, REFUNDED, FAILED)
ACTIVE_SUPPLIER = (PLACED, PRINTING, SHIPPED)

# Allowed moves. Supplier syncs may skip steps after `placed` (e.g. placed -> shipped).
TRANSITIONS: dict[str, set[str]] = {
    PAID: {GENERATED, NEEDS_REVIEW, REFUNDED, FAILED},
    GENERATED: {PLACED, NEEDS_REVIEW, REFUNDED, FAILED},
    PLACED: {PRINTING, SHIPPED, DELIVERED, NEEDS_REVIEW, REFUNDED, FAILED},
    PRINTING: {SHIPPED, DELIVERED, NEEDS_REVIEW, REFUNDED, FAILED},
    SHIPPED: {DELIVERED, NEEDS_REVIEW, REFUNDED},
    DELIVERED: {REFUNDED},
    NEEDS_REVIEW: {PAID, GENERATED, PLACED, REFUNDED, FAILED},  # operator approves / retries
    FAILED: {PAID, GENERATED, NEEDS_REVIEW, REFUNDED},          # retry
    REFUNDED: set(),
}


class InvalidTransition(ValueError):
    pass


def check_transition(current: str, new: str) -> None:
    if new not in STATUSES:
        raise InvalidTransition(f"unknown status {new!r}")
    if new not in TRANSITIONS.get(current, set()):
        raise InvalidTransition(f"cannot go from {current} to {new}")


def whop_fee_cents(price_cents: int) -> int:
    return round(price_cents * WHOP_FEE_PCT) + WHOP_FEE_FIXED_CENTS


def margin(price_cents: int, cost_cents: int, shipping_cents: int) -> float:
    if price_cents <= 0:
        return -1.0
    return (price_cents - cost_cents - shipping_cents - whop_fee_cents(price_cents)) / price_cents


@dataclass
class Order:
    seq: int
    payment_id: str
    product: str
    colour: str
    status: str
    price_cents: int
    amount_cents: int
    meta: dict = field(default_factory=dict)
    order_ref: str = ""
    email: str = ""
    file_path: str = ""
    supplier: str = ""
    supplier_order_id: str = ""
    supplier_status: str = ""
    cost_cents: int = 0
    shipping_cents: int = 0
    note: str = ""
    created_at: str = ""
    updated_at: str = ""

    @property
    def number(self) -> str:
        """Display number, e.g. "007"."""
        return f"{self.seq:03d}"

    @property
    def founding_number(self) -> str | None:
        return self.number if 1 <= self.seq <= FOUNDING_LIMIT else None

    @property
    def qty(self) -> int:
        return PRODUCTS.get(self.product, {}).get("qty", 1)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["number"] = self.number
        d["founding_number"] = self.founding_number
        return d


@dataclass
class SupplierOrder:
    supplier: str
    supplier_order_id: str
    cost_cents: int
    shipping_cents: int
    status: str = ""
    placed: bool = False
    raw: dict = field(default_factory=dict)


@dataclass
class Settings:
    data_dir: Path
    mock: bool
    whop_api_key: str = ""
    whop_company_id: str = ""
    slant_api_key: str = ""
    slant_platform_id: str = ""
    craftcloud_api_key: str = ""
    craftcloud_live: bool = False
    site_url: str = ""
    site_admin_token: str = ""
    plans: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ.get
        return cls(
            data_dir=Path(e("RECEIPTS_DATA", "data/receipts")),
            mock=e("RECEIPTS_MOCK", "") in ("1", "true", "yes"),
            whop_api_key=e("WHOP_API_KEY", ""),
            whop_company_id=e("WHOP_COMPANY_ID", ""),
            slant_api_key=e("SLANT_API_KEY", ""),
            slant_platform_id=e("SLANT_PLATFORM_ID", ""),
            craftcloud_api_key=e("CRAFTCLOUD_API_KEY", ""),
            craftcloud_live=e("CRAFTCLOUD_LIVE", "") == "1",
            site_url=e("SITE_URL", "").rstrip("/"),
            site_admin_token=e("SITE_ADMIN_TOKEN", ""),
            plans={k: e(f"PLAN_{k.upper()}", "") for k in PRODUCTS},
        )

    @property
    def whop_mock(self) -> bool:
        return self.mock or not (self.whop_api_key and self.whop_company_id)

    @property
    def slant_mock(self) -> bool:
        return self.mock or not (self.slant_api_key and self.slant_platform_id)

    @property
    def craftcloud_mock(self) -> bool:
        # TODO(craftcloud): the v5 spec has no model-upload endpoint, base URL or auth scheme, so the
        # live client stays opt-in (CRAFTCLOUD_LIVE=1) until those are confirmed with Craftcloud.
        return self.mock or not self.craftcloud_api_key or not self.craftcloud_live
