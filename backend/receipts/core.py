"""Order pipeline: Whop poll -> print file -> supplier quote/margin guard -> place -> status sync."""
from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import craftcloud as cc
from .generate import GenerationError, generate_files, placeholder_png
from .models import (ACTIVE_SUPPLIER, COLOURS, DELIVERED, FAILED, GENERATED, MIN_MARGIN, NEEDS_REVIEW, PAID,
                     PLACED, PRINTING, PRODUCTS, REFUNDED, SHIPPED, Order, Settings, SupplierOrder, margin,
                     whop_fee_cents)
from .slant import STATUS_MAP as SLANT_STATUS, HttpSlant, MockSlant, usd_to_cents
from .store import Store
from .whop import HttpWhop, MockWhop, is_paid

log = logging.getLogger("receipts")

_EVENT_TEXT = {
    PAID: "Order #{n} paid: {product}",
    GENERATED: "Order #{n} print file ready",
    PRINTING: "Order #{n} is printing",
    SHIPPED: "Order #{n} shipped",
    DELIVERED: "Order #{n} delivered",
    REFUNDED: "Order #{n} refunded",
}


def event_text(order: Order, status: str, note: str = "") -> str:
    """Event line for the public feed. Never includes customer names, emails or addresses."""
    n = order.number
    if status == PLACED:
        return (f"Order #{n} sent to the full-colour print shop" if order.supplier == "craftcloud"
                else f"Order #{n} sent to the print farm")
    if status == NEEDS_REVIEW:
        return f"Order #{n} needs review" + (f": {note}" if note else "")
    if status == FAILED:
        return f"Order #{n} failed" + (f": {note[:120]}" if note else "")
    name = PRODUCTS.get(order.product, {}).get("name", order.product)
    return _EVENT_TEXT.get(status, "Order #{n}: {status}").format(n=n, product=name, status=status)


class Pipeline:
    def __init__(self, settings: Settings, *, store: Store | None = None, whop=None, slant=None, craftcloud=None,
                 site: httpx.Client | None = None):
        self.settings = settings
        self.store = store or Store(Path(settings.data_dir) / "receipts.db")
        self.whop = whop or (MockWhop() if settings.whop_mock
                             else HttpWhop(settings.whop_api_key, settings.whop_company_id))
        self.slant = slant or (MockSlant() if settings.slant_mock
                               else HttpSlant(settings.slant_api_key, settings.slant_platform_id))
        self.craftcloud = craftcloud or (cc.MockCraftcloud() if settings.craftcloud_mock
                                         else cc.HttpCraftcloud(settings.craftcloud_api_key))
        self.site = site or httpx.Client(timeout=15)

    # ------------------------------------------------------------ events / status

    def post_event(self, text: str, kind: str = "order") -> bool:
        log.info("event: %s", text)
        if not (self.settings.site_url and self.settings.site_admin_token):
            return False
        try:
            r = self.site.post(f"{self.settings.site_url}/api/events",
                               json={"agent": "production", "text": text, "kind": kind},
                               headers={"Authorization": f"Bearer {self.settings.site_admin_token}"})
            return r.status_code < 300
        except httpx.HTTPError as e:
            log.warning("event post failed: %s", e)
            return False

    def set_status(self, order: Order, status: str, note: str = "") -> Order:
        new, _prev = self.store.set_status(order.seq, status, note)
        if status in (NEEDS_REVIEW, FAILED):
            log.warning("order #%s -> %s: %s", new.number, status, note)
        self.post_event(event_text(new, status, note), kind="alert" if status in (NEEDS_REVIEW, FAILED) else "order")
        return new

    # ------------------------------------------------------------ Whop

    def order_fields(self, payment: dict) -> dict:
        """Map a Whop payment (+ checkout metadata) to order columns."""
        meta = {k: str(v) for k, v in (payment.get("metadata") or {}).items() if v not in (None, "")}
        product = meta.get("product", "")
        if product not in PRODUCTS:
            plan_id = (payment.get("plan") or {}).get("id", "")
            product = next((k for k, v in self.settings.plans.items() if v and v == plan_id), product)
        colour = meta.get("colour", "black").lower()
        total = payment.get("usd_total", payment.get("total", payment.get("final_amount")))
        price = PRODUCTS.get(product, {}).get("price_cents", 0)
        amount = usd_to_cents(total) if total is not None else price
        email = meta.get("ship_email") or (payment.get("user") or {}).get("email", "") or ""
        note, status = "", PAID
        if product not in PRODUCTS:
            status, note = NEEDS_REVIEW, "unknown product in payment metadata"
        elif colour not in COLOURS:
            status, note = NEEDS_REVIEW, f"unknown colour {colour[:20]}"
        elif (meta.get("ship_country") or "US").upper() not in ("US", "USA"):
            status, note = NEEDS_REVIEW, "non-US shipping address"
        return {"payment_id": payment["id"], "product": product or "unknown", "colour": colour, "status": status,
                "price_cents": price, "amount_cents": amount, "meta": meta, "order_ref": meta.get("order_ref", ""),
                "email": email, "note": note}

    def poll_whop(self) -> list[Order]:
        new: list[Order] = []
        payments = sorted(self.whop.list_payments(), key=lambda p: p.get("created_at") or "")
        for p in payments:
            pid = p.get("id", "")
            if not pid.startswith("pay_") or not is_paid(p) or self.store.has_payment(pid):
                continue
            fields = self.order_fields(p)
            order = self.store.insert(**fields)
            if order is None:
                continue
            self.post_event(event_text(order, PAID))
            if order.status == NEEDS_REVIEW:
                self.post_event(event_text(order, NEEDS_REVIEW, order.note), kind="alert")
            new.append(order)
        return new

    # ------------------------------------------------------------ print files

    def order_dir(self, order: Order) -> Path:
        return Path(self.settings.data_dir) / "files" / order.number

    def fetch_screenshot(self, upload_id: str) -> bytes | None:
        s = self.settings
        if upload_id and s.site_url and s.site_admin_token:
            r = self.site.get(f"{s.site_url}/api/admin/upload/{upload_id}",
                              headers={"Authorization": f"Bearer {s.site_admin_token}"})
            if r.status_code == 200 and r.content:
                return r.content
            log.warning("screenshot %s: HTTP %s", upload_id, r.status_code)
        return placeholder_png() if s.mock else None

    def tweet_assets(self, meta: dict) -> tuple[dict, bytes | None]:
        """Best effort, live mode only: fill what /make previewed but checkout metadata does not carry (avatar,
        verified, reply count) from X's public syndication JSON, and fetch the avatar image. Never invents a
        value: anything missing stays missing and the card simply leaves it out."""
        if self.settings.mock:
            return meta, None
        meta = dict(meta)
        mt = re.search(r"/status(?:es)?/(\d+)", meta.get("tweet_url", ""))
        if mt and not meta.get("avatar_url"):
            tid = mt.group(1)
            token = re.sub(r"(0+|\.)", "", _base36((int(tid) / 1e15) * math.pi)) or "a"
            try:
                r = self.site.get("https://cdn.syndication.twimg.com/tweet-result",
                                  params={"id": tid, "lang": "en", "token": token}, timeout=10)
                data = r.json() if r.status_code == 200 else {}
                user = data.get("user") or {}
                av = user.get("profile_image_url_https") or ""
                if isinstance(av, str) and av.startswith("https://pbs.twimg.com/"):
                    meta["avatar_url"] = re.sub(r"_normal(\.\w+)$", r"_400x400\1", av)
                if "verified" not in meta and (user.get("is_blue_verified") is True or user.get("verified") is True):
                    meta["verified"] = "true"
                cc_ = data.get("conversation_count")
                if not meta.get("replies") and isinstance(cc_, int) and cc_ >= 0:
                    meta["replies"] = str(cc_)
            except Exception as e:  # noqa: BLE001 - extras are optional
                log.warning("tweet extras %s: %s", tid, e)
        avatar = None
        url = meta.get("avatar_url", "")
        if url and urlparse(url).scheme == "https" and urlparse(url).hostname in ("pbs.twimg.com", "abs.twimg.com"):
            try:
                r = self.site.get(url, timeout=10)
                if r.status_code == 200 and r.content:
                    avatar = r.content
            except Exception as e:  # noqa: BLE001
                log.warning("avatar %s: %s", url, e)
        return meta, avatar

    def generate(self, order: Order) -> Path:
        image = self.fetch_screenshot(order.meta.get("upload_id", "")) if order.product == "fullcolour" else None
        meta, avatar = self.tweet_assets(order.meta) if order.product == "tweet" else (order.meta, None)
        try:
            files = generate_files(order.product, meta, order.colour, order.founding_number,
                                   self.order_dir(order), image_bytes=image, avatar_bytes=avatar)
        except GenerationError as e:
            self.set_status(order, FAILED, f"print file: {e}")
            raise
        order = self.store.update(order.seq, file_path=str(files["main"]))
        if order.status == PAID:
            self.set_status(order, GENERATED)
        return files["main"]

    # ------------------------------------------------------------ suppliers

    def _ship(self, order: Order) -> dict:
        m = order.meta
        return {"name": m.get("ship_name", ""), "line1": m.get("ship_line1", ""), "line2": m.get("ship_line2", ""),
                "city": m.get("ship_city", ""), "state": m.get("ship_state", ""), "zip": m.get("ship_zip", ""),
                "country": "US"}

    def _guard(self, order: Order, cost: int, ship: int) -> tuple[bool, str]:
        price = order.amount_cents or order.price_cents
        mg = margin(price, cost, ship)
        msg = (f"margin {mg:.0%} below {MIN_MARGIN:.0%} (cost ${cost / 100:.2f} + shipping ${ship / 100:.2f}"
               f" + Whop fee ${whop_fee_cents(price) / 100:.2f} on ${price / 100:.2f})")
        return mg >= MIN_MARGIN, msg

    def place(self, order: Order) -> SupplierOrder:
        """Quote, check margin, then place. Below 40% margin: needs_review, nothing placed."""
        if order.status != GENERATED:
            raise ValueError(f"order #{order.number} is {order.status}, expected generated")
        sup = PRODUCTS[order.product]["supplier"]
        order = self.store.update(order.seq, supplier=sup)
        ship = self._ship(order)
        missing = [k for k in ("name", "line1", "city", "state", "zip") if not ship[k]]
        if missing or not order.email:
            self.set_status(order, NEEDS_REVIEW, "shipping details incomplete")
            return SupplierOrder(sup, "", 0, 0, "", placed=False)
        try:
            return self._place_slant(order, ship) if sup == "slant" else self._place_craftcloud(order, ship)
        except Exception as e:
            self.set_status(self.store.get(order.seq), FAILED, f"{sup}: {type(e).__name__}: {e}"[:200])
            raise

    def _place_slant(self, order: Order, ship: dict) -> SupplierOrder:
        files = self.order_dir(order)
        main = Path(order.file_path)
        stand = files / "stand.stl"
        owner = f"receipts-{order.number}"
        fil = self.slant.filament_id(order.colour)
        items = []
        for path in (main, stand):
            if not path.exists():
                continue
            fid = self.slant.upload_file(path, owner_id=owner)
            item = {"type": "PRINT", "quantity": order.qty, "publicFileServiceId": fid}
            if fil:
                item["filamentId"] = fil
            items.append(item)
        draft = self.slant.draft_order(items=items, email=order.email, address={
            "name": ship["name"], "line1": ship["line1"], **({"line2": ship["line2"]} if ship["line2"] else {}),
            "city": ship["city"], "state": ship["state"], "zip": ship["zip"], "country": "US"}, owner_id=owner)
        oid = draft["publicId"]
        cost, ship_c = usd_to_cents(draft.get("printingCost")), usd_to_cents(draft.get("deliveryCost"))
        order = self.store.update(order.seq, supplier_order_id=oid, cost_cents=cost, shipping_cents=ship_c,
                                  supplier_status=draft.get("status", "DRAFT"))
        ok, msg = self._guard(order, cost, ship_c)
        if not ok:
            try:
                self.slant.cancel_order(oid)
            except Exception as e:  # draft stays unprocessed either way
                log.warning("cancel draft %s failed: %s", oid, e)
            self.set_status(order, NEEDS_REVIEW, msg)
            return SupplierOrder("slant", oid, cost, ship_c, "DRAFT", placed=False, raw=draft)
        done = self.slant.process_order(oid)
        order = self.store.update(order.seq, supplier_status=done.get("status", ""))
        self.set_status(order, PLACED)
        return SupplierOrder("slant", oid, cost, ship_c, done.get("status", ""), placed=True, raw=done)

    def _place_craftcloud(self, order: Order, ship: dict) -> SupplierOrder:
        c = self.craftcloud
        mats = cc.fullcolour_material_ids()
        model_id = c.upload_model(Path(order.file_path))
        price_id = c.create_price(model_id, order.qty, mats or None)
        best = cc.pick_cheapest(c.poll_price(price_id), mats)
        if best is None:
            self.set_status(order, NEEDS_REVIEW, "no full-colour offer for a US address")
            return SupplierOrder("craftcloud", "", 0, 0, "", placed=False)
        cost, ship_c = best["price_cents"], best["shipping_cents"]
        order = self.store.update(order.seq, cost_cents=cost, shipping_cents=ship_c)
        ok, msg = self._guard(order, cost, ship_c)
        if not ok:
            self.set_status(order, NEEDS_REVIEW, msg)
            return SupplierOrder("craftcloud", "", cost, ship_c, "", placed=False, raw=best)
        cart = c.create_cart(best["quoteId"], best["shippingId"], reference=f"receipts-{order.number}")
        res = c.create_order(cart["cartId"], email=order.email, ship=ship)
        order = self.store.update(order.seq, supplier_order_id=res["orderId"], supplier_status="ordered")
        self.set_status(order, PLACED)
        return SupplierOrder("craftcloud", res["orderId"], cost, ship_c, "ordered", placed=True, raw=res)

    def sync_status(self) -> list[Order]:
        changed: list[Order] = []
        for order in self.store.list():
            if order.status not in ACTIVE_SUPPLIER or not order.supplier_order_id:
                continue
            try:
                if order.supplier == "slant":
                    raw = self.slant.get_order(order.supplier_order_id).get("status", "")
                    new = SLANT_STATUS.get(raw, "")
                else:
                    raw = self.craftcloud.order_status(order.supplier_order_id)
                    new = cc.STATUS_MAP.get(raw, "")
            except Exception as e:
                log.warning("sync #%s failed: %s", order.number, e)
                continue
            if raw != order.supplier_status:
                order = self.store.update(order.seq, supplier_status=raw)
            if not new or new == order.status:
                continue
            if new in (PLACED, PRINTING, SHIPPED, DELIVERED) and _rank(new) < _rank(order.status):
                continue  # never move backwards on a stale supplier status
            note = f"supplier status {raw}" if new == NEEDS_REVIEW else ""
            changed.append(self.set_status(order, new, note))
        return changed

    # ------------------------------------------------------------ refunds / queries

    def refund(self, order_id) -> Order:
        order = self.store.find(order_id)
        if order is None:
            raise KeyError(f"order {order_id} not found")
        if order.status == REFUNDED:
            return order
        self.whop.refund(order.payment_id)
        # TODO(refund): cancel an in-flight supplier order (Slant DELETE /orders/{id}) once the policy is set.
        return self.set_status(order, REFUNDED)

    def list_orders(self, status: str | None = None) -> list[Order]:
        return self.store.list(status)

    def stats(self) -> dict:
        orders = self.store.list()
        live = [o for o in orders if o.status != REFUNDED]
        by_status: dict[str, int] = {}
        by_product: dict[str, int] = {}
        for o in orders:
            by_status[o.status] = by_status.get(o.status, 0) + 1
        for o in live:
            by_product[o.product] = by_product.get(o.product, 0) + 1
        revenue = sum(o.amount_cents or o.price_cents for o in live)
        placed = [o for o in live if o.status in (PLACED, PRINTING, SHIPPED, DELIVERED)]
        cost = sum(o.cost_cents + o.shipping_cents for o in placed)
        fees = sum(whop_fee_cents(o.amount_cents or o.price_cents) for o in live)
        return {"orders": len(live), "revenue_cents": revenue, "refunded": by_status.get(REFUNDED, 0),
                "founding_left": max(0, 100 - self.store.max_seq()), "by_status": by_status,
                "by_product": by_product, "supplier_cost_cents": cost, "whop_fees_cents": fees,
                "gross_margin_cents": revenue - cost - fees}

    # ------------------------------------------------------------ one worker pass

    def run_once(self) -> dict:
        new = self.poll_whop()
        generated = placed = 0
        for o in self.store.list(PAID):
            try:
                self.generate(o)
                generated += 1
            except Exception as e:
                log.error("generate #%s: %s", o.number, e)
                cur = self.store.get(o.seq)
                if cur.status == PAID:
                    self.set_status(cur, FAILED, f"print file: {type(e).__name__}")
        for o in self.store.list(GENERATED):
            try:
                if self.place(o).placed:
                    placed += 1
            except Exception as e:
                log.error("place #%s: %s", o.number, e)
        synced = self.sync_status()
        return {"new": len(new), "generated": generated, "placed": placed, "synced": len(synced)}


def _rank(status: str) -> int:
    order = (PAID, GENERATED, PLACED, PRINTING, SHIPPED, DELIVERED)
    return order.index(status) if status in order else -1


def _base36(x: float) -> str:
    """JS Number.prototype.toString(36) for a positive float (integer part + up to 12 fraction digits)."""
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    ip, fp = int(x), x - int(x)
    out = ""
    while True:
        ip, r = divmod(ip, 36)
        out = digits[r] + out
        if not ip:
            break
    if fp:
        out += "."
        for _ in range(12):
            fp *= 36
            d = int(fp)
            out += digits[d]
            fp -= d
            if not fp:
                break
    return out
