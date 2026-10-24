"""Breakout scoring, lead dedupe, post queue, claim payloads, ads cap, X auto-post guard."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest

from marketing.ads import AdsLedger, daily_cap_usd
from marketing.claims import CLAIM_KEYS, PRODUCTS, attach_og, build_claim, validate_claim
from marketing.leads import LeadStore, lead_key
from marketing.post_queue import QueueStore, render_queue_html
from marketing.scoring import score_post
from marketing.scout import find_breakouts
from marketing import x_client


# ---- breakout scoring ---------------------------------------------------
def test_ratio_breakout():
    assert score_post(2000, 50, 100_000).breakout            # 40x median
    assert not score_post(900, 50, 100_000).breakout         # 18x, big account


def test_small_account_breakout():
    assert score_post(1000, 900, 4999).breakout
    assert not score_post(1000, 900, 5000).breakout
    assert not score_post(999, 900, 10).breakout


def test_window_and_floor():
    now = datetime.now(timezone.utc)
    assert not score_post(5000, 10, 100, now - timedelta(hours=7), now).breakout
    assert score_post(5000, 10, 100, now - timedelta(hours=5), now).breakout
    assert not score_post(30, 0, 100).breakout               # 30x a zero median, but tiny


class FakeX:
    def __init__(self):
        self.timeline_calls = 0

    def recent_search(self, q, hours=6):
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return {"data": [
            {"id": "1", "author_id": "a", "text": "we hit 10k MRR", "created_at": now,
             "public_metrics": {"like_count": 3000}},
            {"id": "2", "author_id": "b", "text": "meh", "created_at": now, "public_metrics": {"like_count": 120}},
        ], "includes": {"users": [
            {"id": "a", "username": "maya", "name": "Maya", "public_metrics": {"followers_count": 20000}},
            {"id": "b", "username": "big", "name": "Big", "public_metrics": {"followers_count": 900000}},
        ]}}

    def user_tweets(self, uid):
        self.timeline_calls += 1
        likes = [40, 60, 50] if uid == "a" else [100, 200, 150]
        return {"data": [{"id": f"{uid}{i}", "public_metrics": {"like_count": n}} for i, n in enumerate(likes)]}


def test_find_breakouts_writes_deduped_leads(tmp_path):
    store, x = LeadStore(tmp_path / "m.db"), FakeX()
    first = find_breakouts(x, store, queries=["q1", "q2"])
    assert len(first["new_leads"]) == 1                     # same post from two queries -> one lead
    lead = store.get(first["new_leads"][0])
    assert lead["handle"] == "maya" and lead["data"]["likes"] == 3000 and lead["source"] == "x"
    assert x.timeline_calls == 2                            # author medians cached across queries
    assert find_breakouts(x, store, queries=["q1"])["new_leads"] == []


# ---- leads --------------------------------------------------------------
def test_lead_key_normalises_x_urls():
    assert lead_key("https://twitter.com/Maya/status/123?s=20") == lead_key("https://x.com/maya/status/123/")
    assert lead_key("https://www.producthunt.com/posts/foo/") == "producthunt.com/posts/foo"


def test_lead_dedupe(tmp_path):
    store = LeadStore(tmp_path / "m.db")
    a = store.add("x", "https://x.com/maya/status/9", handle="maya")
    assert a is not None
    assert store.add("x", "https://twitter.com/MAYA/status/9?t=1") is None
    assert store.add("linkedin", "https://linkedin.com/posts/abc") is not None
    store.set_status(a, "designed", claim_url="https://s/c/maya-1")
    assert store.list("designed")[0]["data"]["claim_url"] == "https://s/c/maya-1"
    assert store.counts_by_source() == {"x": 1, "linkedin": 1}


# ---- post queue ---------------------------------------------------------
def test_queue_store_and_page(tmp_path):
    q = QueueStore(tmp_path / "m.db")
    r = q.add("reply", "closer", "Congrats! <b>yours</b>", target_url="https://x.com/maya/status/9",
              claim_url="https://s/c/maya", lead_id=1)
    assert r == {"ok": True, "id": r["id"], "duplicate": False}
    assert q.add("reply", "closer", "second draft", lead_id=1)["duplicate"] is True
    q.add("x_post", "ceo", "Hour 3: $420 of $2,000")
    page = render_queue_html(q.list())
    assert "&lt;b&gt;yours&lt;/b&gt;" in page and "<b>yours" not in page
    assert "Open post" in page and "Copy" in page and "Mark posted" in page and "https://s/c/maya" in page
    assert q.mark_posted(r["id"]) and not q.mark_posted(r["id"])
    assert [i["kind"] for i in q.list()] == ["x_post"]
    with pytest.raises(ValueError):
        q.add("dm", "closer", "x")


def test_search_triggered_replies_never_autopost(monkeypatch):
    monkeypatch.setenv("X_AUTOREPLY_MENTIONS", "1")
    monkeypatch.setenv("X_USER_TOKEN", "t")
    res = x_client.post_mention_reply("hi", "1", "@receipts print this", "receipts", trigger="search")
    assert res["ok"] is False
    res = x_client.post_mention_reply("hi", "1", "@receipts nice", "receipts", trigger="mention")
    assert res["ok"] is False
    monkeypatch.setenv("X_AUTOREPLY_MENTIONS", "0")
    res = x_client.post_mention_reply("hi", "1", "@receipts print this", "receipts", trigger="mention")
    assert res["ok"] is False and "X_AUTOREPLY_MENTIONS" in res["error"]
    assert x_client.is_print_request("lol @Receipts  print this please", "receipts")


# ---- claims -------------------------------------------------------------
def test_tweet_claim_shape():
    c = build_claim("@maya", "tweet", "gold", tweet_url="https://x.com/maya/status/9", text="x" * 400,
                    likes=3000, name="Maya", date="Oct 24, 2026")
    validate_claim(c)
    assert set(c) <= CLAIM_KEYS and c["handle"] == "maya" and c["price_cents"] == PRODUCTS["tweet"] == 2900
    assert len(c["text"]) == 280 and c["slug"].startswith("maya-")
    with_og = attach_og(c)
    validate_claim(with_og)
    assert base64.b64decode(with_og["og_image_b64"])[:8] == b"\x89PNG\r\n\x1a\n"


def test_milestone_claim_and_errors():
    c = build_claim("dev", "milestone", number="10000 STARS!", label="GITHUB STARS")
    assert c["price_cents"] == 4900 and len(c["number"]) == 10 and "tweet_url" not in c
    assert attach_og(c)["og_image_b64"]
    for kwargs in ({"product": "fullcolour"}, {"colour": "pink", "text": "a"}, {"product": "tweet"},
                   {"product": "milestone"}):
        with pytest.raises(ValueError):
            build_claim("dev", **kwargs)


# ---- ads cap ------------------------------------------------------------
def test_ads_cap_default_and_env(monkeypatch, tmp_path):
    monkeypatch.delenv("ADS_DAILY_CAP_USD", raising=False)
    assert daily_cap_usd() == 50
    monkeypatch.setenv("ADS_DAILY_CAP_USD", "20")
    assert AdsLedger(tmp_path / "m.db").cap == 20


def test_ads_cap_enforced(tmp_path):
    ads = AdsLedger(tmp_path / "m.db", cap_usd=50)
    assert ads.draft("whop_ads", "retarget", 30)["ok"]
    assert ads.draft("x_ads", "boost", 20)["ok"]
    over = ads.draft("x_ads", "boost2", 0.01)
    assert not over["ok"] and "cap" in over["error"]
    assert ads.draft("whop_ads", "retarget", 35)["ok"] is False          # raising an existing one
    assert ads.draft("whop_ads", "retarget", 10)["ok"]                    # lowering frees room
    assert ads.draft("x_ads", "boost2", 20)["ok"]
    assert ads.draft("x_ads", "boost", -5)["ok"] is False
    assert ads.draft("meta", "x", 1)["ok"] is False
    st = ads.status()
    assert st["planned_usd"] == 50 and st["remaining_usd"] == 0 and st["planned_usd"] <= st["cap_usd"]
