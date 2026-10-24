"""Whop poll: idempotency by pay_ id, metadata -> order mapping, HTTP request shapes, refund."""
import json

import httpx
import pytest

from receipts.core import Pipeline
from receipts.models import NEEDS_REVIEW, PAID, REFUNDED, Settings
from receipts.slant import MockSlant
from receipts.whop import HttpWhop, MockWhop


def _pipeline(tmp_path, whop, events=None):
    def site(req: httpx.Request):
        if events is not None:
            events.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True})

    s = Settings(data_dir=tmp_path, mock=True, site_url="https://site.test", site_admin_token="tok")
    return Pipeline(s, whop=whop, slant=MockSlant(), site=httpx.Client(transport=httpx.MockTransport(site)))


def test_poll_is_idempotent_and_numbers_orders(tmp_path):
    p = _pipeline(tmp_path, MockWhop())
    first = p.poll_whop()
    assert [o.product for o in first] == ["tweet", "milestone", "fullcolour", "team"]  # open payment skipped
    assert [o.founding_number for o in first] == ["001", "002", "003", "004"]
    assert p.poll_whop() == []
    # a restarted worker on the same db does not duplicate either
    p2 = _pipeline(tmp_path, MockWhop())
    assert p2.poll_whop() == []
    assert len(p2.list_orders()) == 4
    p2.whop.payments.append({"id": "pay_late", "status": "paid", "substatus": "succeeded", "total": 49.0,
                             "created_at": "2026-10-24T15:00:00Z",
                             "metadata": {"product": "milestone", "colour": "red", "number": "100"}})
    late = p2.poll_whop()
    assert [o.seq for o in late] == [5] and late[0].number == "005"


def test_metadata_maps_to_order(tmp_path):
    p = _pipeline(tmp_path, MockWhop())
    o = {x.product: x for x in p.poll_whop()}["milestone"]
    assert o.payment_id == "pay_mock_milestone_0002"
    assert (o.status, o.colour, o.price_cents, o.amount_cents) == (PAID, "gold", 2799, 4900)
    assert o.order_ref == "SAMPLE02"
    assert o.email == "sample.buyer2@example.com"
    assert o.meta["number"] == "$10K MRR" and o.meta["label"] == "monthly recurring revenue"
    assert o.meta["ship_line2"] == "Unit 4" and o.meta["ship_zip"] == "97201"


def test_unknown_product_plan_fallback_and_non_us(tmp_path):
    pays = [
        {"id": "pay_a", "status": "paid", "total": 29, "created_at": "1", "plan": {"id": "plan_T"},
         "metadata": {"colour": "red"}},
        {"id": "pay_b", "status": "paid", "total": 29, "created_at": "2", "metadata": {"product": "mug"}},
        {"id": "pay_c", "status": "paid", "total": 29, "created_at": "3",
         "metadata": {"product": "tweet", "ship_country": "CA"}},
        {"id": "pay_d", "status": "paid", "substatus": "refunded", "total": 29, "created_at": "4",
         "metadata": {"product": "tweet"}},
        {"id": "ch_e", "status": "paid", "total": 29, "created_at": "5", "metadata": {"product": "tweet"}},
    ]
    p = _pipeline(tmp_path, MockWhop(pays))
    p.settings.plans = {"tweet": "plan_T"}
    got = {o.payment_id: o for o in p.poll_whop()}
    assert set(got) == {"pay_a", "pay_b", "pay_c"}
    assert got["pay_a"].product == "tweet" and got["pay_a"].status == PAID
    assert got["pay_b"].status == NEEDS_REVIEW
    assert got["pay_c"].status == NEEDS_REVIEW and "non-US" in got["pay_c"].note


def test_http_whop_lists_with_pagination_and_auth():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        assert req.headers["authorization"] == "Bearer wk_test"
        assert req.url.path == "/api/v1/payments"
        if "after" not in req.url.params:
            return httpx.Response(200, json={"data": [{"id": "pay_1", "status": "paid"}],
                                             "page_info": {"has_next_page": True, "end_cursor": "c1"}})
        assert req.url.params["after"] == "c1"
        return httpx.Response(200, json={"data": [{"id": "pay_2", "status": "paid"}],
                                         "page_info": {"has_next_page": False, "end_cursor": "c2"}})

    w = HttpWhop("wk_test", "biz_1", transport=httpx.MockTransport(handler))
    assert [p["id"] for p in w.list_payments()] == ["pay_1", "pay_2"]
    assert all(r.url.params["company_id"] == "biz_1" for r in seen)


def test_refund_calls_whop_and_marks_refunded(tmp_path):
    calls = []

    def handler(req: httpx.Request):
        calls.append(req)
        if req.method == "GET":
            return httpx.Response(200, json={"data": [
                {"id": "pay_r1", "status": "paid", "total": 29.0, "created_at": "1",
                 "metadata": {"product": "tweet", "colour": "black"}}], "page_info": {}})
        return httpx.Response(200, json={"id": "pay_r1", "substatus": "refunded"})

    events = []
    p = _pipeline(tmp_path, HttpWhop("wk", "biz", transport=httpx.MockTransport(handler)), events)
    (o,) = p.poll_whop()
    r = p.refund(o.seq)
    assert r.status == REFUNDED
    post = calls[-1]
    assert post.method == "POST" and post.url.path == "/api/v1/payments/pay_r1/refund"
    assert json.loads(post.content) == {}
    assert events[-1]["text"] == "Order #001 refunded"
    assert p.refund("#001").status == REFUNDED  # second refund is a no-op
    assert sum(1 for c in calls if c.method == "POST") == 1
    assert p.stats()["orders"] == 0 and p.stats()["refunded"] == 1


@pytest.mark.parametrize("pay,ok", [({"status": "paid"}, True), ({"substatus": "succeeded"}, True),
                                    ({"status": "open"}, False), ({"status": "paid", "substatus": "refunded"}, False)])
def test_is_paid(pay, ok):
    from receipts.whop import is_paid

    assert is_paid(pay) is ok
