"""X API v2 client: recent search, user lookup, user timeline (app bearer X_BEARER_TOKEN).

Posting: search-triggered replies are NEVER automated (X bans them); they go to the human post
queue. The only automated post is a reply to a mention asking "@<brand> print this", and only when
X_AUTOREPLY_MENTIONS=1 and a user-context token X_USER_TOKEN is set.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

import httpx

API = "https://api.x.com/2"
TWEET_FIELDS = "public_metrics,created_at,author_id,conversation_id,lang"
USER_FIELDS = "public_metrics,username,name,verified"


class XError(RuntimeError):
    pass


class XClient:
    def __init__(self, bearer: str | None = None, client: httpx.Client | None = None):
        self.bearer = bearer if bearer is not None else os.environ.get("X_BEARER_TOKEN", "")
        self.http = client or httpx.Client(timeout=20)

    def _get(self, path: str, params: dict) -> dict:
        if not self.bearer:
            raise XError("X_BEARER_TOKEN not set")
        r = self.http.get(f"{API}{path}", params=params, headers={"authorization": f"Bearer {self.bearer}"})
        if r.status_code == 429:
            raise XError(f"rate limited until {r.headers.get('x-rate-limit-reset')}")
        if r.status_code >= 400:
            raise XError(f"X {path} {r.status_code}: {r.text[:200]}")
        return r.json()

    def recent_search(self, query: str, hours: int = 6, max_results: int = 100) -> dict:
        start = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return self._get("/tweets/search/recent", {
            "query": query, "start_time": start, "max_results": max(10, min(max_results, 100)),
            "tweet.fields": TWEET_FIELDS, "expansions": "author_id", "user.fields": USER_FIELDS,
            "sort_order": "relevancy"})

    def user_by_username(self, username: str) -> dict:
        return self._get(f"/users/by/username/{username.lstrip('@')}", {"user.fields": USER_FIELDS})

    def user_tweets(self, user_id: str, max_results: int = 20) -> dict:
        return self._get(f"/users/{user_id}/tweets", {
            "max_results": max(5, min(max_results, 100)), "exclude": "retweets,replies",
            "tweet.fields": TWEET_FIELDS})

    def mentions(self, user_id: str, since_id: str | None = None) -> dict:
        params = {"tweet.fields": TWEET_FIELDS, "expansions": "author_id,referenced_tweets.id",
                  "user.fields": USER_FIELDS}
        if since_id:
            params["since_id"] = since_id
        return self._get(f"/users/{user_id}/mentions", params)


def autoreply_enabled() -> bool:
    return os.environ.get("X_AUTOREPLY_MENTIONS") == "1" and bool(os.environ.get("X_USER_TOKEN"))


def is_print_request(text: str, brand: str) -> bool:
    brand = re.escape(brand.lstrip("@"))
    return re.search(rf"@{brand}\b.*\bprint\s+this\b", text, re.I | re.S) is not None


def post_mention_reply(text: str, in_reply_to: str, mention_text: str, brand: str,
                       trigger: str, client: httpx.Client | None = None) -> dict:
    """Reply to a "@brand print this" mention. Refuses every other trigger."""
    if trigger != "mention":
        return {"ok": False, "error": "auto-posting is only allowed for mention-triggered replies; queue it instead"}
    if not is_print_request(mention_text, brand):
        return {"ok": False, "error": "mention does not ask to 'print this'"}
    if not autoreply_enabled():
        return {"ok": False, "error": "X_AUTOREPLY_MENTIONS=1 and X_USER_TOKEN required"}
    c = client or httpx.Client(timeout=20)
    r = c.post(f"{API}/tweets", json={"text": text, "reply": {"in_reply_to_tweet_id": in_reply_to}},
               headers={"authorization": f"Bearer {os.environ['X_USER_TOKEN']}"})
    return {"ok": r.status_code < 300, "status": r.status_code}
