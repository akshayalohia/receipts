"""Margin guard, status transitions, event posting (stubbed HTTP), sync, stats, worker pass."""
import json

import httpx
import pytest

import receipts
from receipts import core
from receipts.craftcloud import MockCraftcloud
from receipts.models import (DELIVERED, GENERATED, NEEDS_REVIEW, PAID, PLACED, PRINTING, REFUNDED, SHIPPED,
                             InvalidTransition, Settings, check_transition, margin, whop_fee_cents)
from receipts.slant import MockSlant
from receipts.whop import MockWhop

PII = ("Sample Buyer", "sample.buyer", "Example St", "Example Ave", "Example Blvd", "Example Rd", "62701", "97201")


class Site:
    def __init__(self):
        self.requests: list[httpx.Request] = []

    def __call__(self, req: httpx.Request):
        self.requests.append(req)
        return httpx.Response(201, json={"ok": True})

    @property
    def events(self):
        return [json.loads(r.content) for r in self.requests if r.url.path == "/api/events"]


@pytest.fixture
def fake_files(monkeypatch):
    """Pipeline tests don't need real CAD (covered in test_receipts_generate); write tiny stand-ins."""
    def fake(product, meta, colour, founding, out_dir, image_bytes=None, avatar_bytes=None):
        out_dir.mkdir(parents=True, exist_ok=True)
        name = {"fullcolour": "receipt_fullcolour.zip", "tweet": "tweet_trophy.stl"}.get(product, f"{product}_card.stl")
        main = out_dir / name
        main.write_bytes(b"solid x\nendsolid x\n")
        res = {"main": main}
        if product not in ("fullcolour", "tweet"):  # the tweet trophy is one piece (card + stand)
            (out_dir / "stand.stl").write_bytes(b"solid s\nendsolid s\n")
            res["stand"] = out_dir / "stand.stl"
        return res

    monkeypatch.setattr(core, "generate_files", fake)


def make(tmp_path, site=None, slant=None, cc=None, payments=None):
    site = site or Site()
    s = Settings(data_dir=tmp_path, mock=True, site_url="https://site.test", site_admin_token="admin-tok")
    p = core.Pipeline(s, whop=MockWhop(payments), slant=slant or MockSlant(), craftcloud=cc or MockCraftcloud(),
                      site=httpx.Client(transport=httpx.MockTransport(site)))
    return p, site


def test_margin_math():
    assert whop_fee_cents(2900) == 108  # 2.7% + $0.30
    assert margin(2900, 1000, 500) == pytest.approx((2900 - 1608) / 2900)


def test_transitions():
    for a, b in [(PAID, GENERATED), (GENERATED, PLACED), (PLACED, PRINTING), (PRINTING, SHIPPED),
                 (SHIPPED, DELIVERED), (PLACED, SHIPPED), (GENERATED, NEEDS_REVIEW), (NEEDS_REVIEW, PLACED),
                 (DELIVERED, REFUNDED)]:
        check_transition(a, b)
    for a, b in [(DELIVERED, PRINTING), (PAID, PLACED), (REFUNDED, PAID), (SHIPPED, PLACED), (PAID, "lost")]:
        with pytest.raises(InvalidTransition):
            check_transition(a, b)


def test_store_rejects_invalid_and_logs_history(tmp_path, fake_files):
    p, _ = make(tmp_path)
    o = p.poll_whop()[0]
    with pytest.raises(InvalidTransition):
        p.set_status(o, DELIVERED)
    p.generate(o)
    assert [h["to_status"] for h in p.store.history(o.seq)] == [PAID, GENERATED]


def test_happy_path_events_and_sync(tmp_path, fake_files):
    p, site = make(tmp_path)
    tweet = p.poll_whop()[0]
    p.generate(tweet)
    so = p.place(p.store.get(tweet.seq))
    assert so.placed and so.supplier == "slant" and so.supplier_order_id.startswith("SLANT_")
    o = p.store.get(tweet.seq)
    assert o.status == PLACED and o.cost_cents == 650 and o.shipping_cents == 550  # one-piece trophy 6.50 (mock)
    assert p.slant.processed == [so.supplier_order_id]
    seen = []
    for _ in range(4):
        seen += [x.status for x in p.sync_status() if x.seq == tweet.seq]
    assert seen == [PRINTING, SHIPPED, DELIVERED]
    texts = [e["text"] for e in site.events]
    assert "Order #001 sent to the print farm" in texts
    assert "Order #001 paid: Tweet Trophy" in texts and "Order #001 delivered" in texts
    assert all(e["agent"] == "production" for e in site.events)
    assert all(r.headers["authorization"] == "Bearer admin-tok" for r in site.requests)
    blob = json.dumps(site.events)
    assert not any(s in blob for s in PII), "events must not carry customer names or addresses"


def test_margin_guard_slant_blocks_order(tmp_path, fake_files):
    p, site = make(tmp_path, slant=MockSlant(cost_override_cents=2000))
    o = p.poll_whop()[0]
    p.generate(o)
    so = p.place(p.store.get(o.seq))
    o = p.store.get(o.seq)
    assert not so.placed and o.status == NEEDS_REVIEW and "margin" in o.note
    assert p.slant.processed == [] and p.slant.cancelled == [so.supplier_order_id]
    assert any(e["text"].startswith("Order #001 needs review: margin") and e["kind"] == "alert" for e in site.events)


def test_margin_guard_craftcloud(tmp_path, fake_files):
    p, _ = make(tmp_path, cc=MockCraftcloud(price_cents=6000, shipping_cents=1200))
    fc = [o for o in p.poll_whop() if o.product == "fullcolour"][0]
    p.generate(fc)
    so = p.place(p.store.get(fc.seq))
    assert not so.placed and p.store.get(fc.seq).status == NEEDS_REVIEW
    assert p.craftcloud.orders == {}


def test_craftcloud_mock_places_and_event_wording(tmp_path, fake_files):
    p, site = make(tmp_path)
    fc = [o for o in p.poll_whop() if o.product == "fullcolour"][0]
    p.generate(fc)
    assert p.place(p.store.get(fc.seq)).placed
    assert "Order #003 sent to the full-colour print shop" in [e["text"] for e in site.events]


def test_missing_shipping_needs_review(tmp_path, fake_files):
    pay = [{"id": "pay_x", "status": "paid", "total": 29, "created_at": "1",
            "metadata": {"product": "tweet", "colour": "black"}}]
    p, _ = make(tmp_path, payments=pay)
    (o,) = p.poll_whop()
    p.generate(o)
    assert not p.place(p.store.get(o.seq)).placed
    assert p.store.get(o.seq).status == NEEDS_REVIEW


def test_event_post_skipped_without_site(tmp_path):
    s = Settings(data_dir=tmp_path, mock=True)
    calls = []
    p = core.Pipeline(s, whop=MockWhop([]), slant=MockSlant(), craftcloud=MockCraftcloud(),
                      site=httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(r))))
    assert p.post_event("Order #001 shipped") is False and calls == []


def test_worker_pass_and_public_api(tmp_path, fake_files):
    p, _ = make(tmp_path)
    receipts.set_pipeline(p)
    try:
        r = p.run_once()
        # Craftcloud's first status is "ordered" (= still placed); the three Slant orders move to printing
        assert r == {"new": 4, "generated": 4, "placed": 4, "synced": 3}
        assert len(receipts.list_orders(PRINTING)) == 3 and len(receipts.list_orders(PLACED)) == 1
        st = receipts.stats()
        assert st["orders"] == 4 and st["revenue_cents"] == 2900 + 4900 + 8900 + 24900
        assert st["founding_left"] == 96 and st["by_product"]["team"] == 1
        assert st["gross_margin_cents"] == st["revenue_cents"] - st["supplier_cost_cents"] - st["whop_fees_cents"]
        team = [o for o in receipts.list_orders() if o.product == "team"][0]
        items = p.slant.orders[team.supplier_order_id]["items"]
        assert all(i["quantity"] == 10 for i in items)
        assert receipts.refund(team.seq).status == REFUNDED
    finally:
        receipts.set_pipeline(None)
