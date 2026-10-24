"""Scout jobs: X breakouts and Exa milestone searches, written to the lead store with dedupe."""
from __future__ import annotations

from datetime import datetime, timezone

from marketing.exa_client import MILESTONE_QUERIES, ExaClient
from marketing.leads import LeadStore
from marketing.scoring import MIN_LIKES, median_likes, score_post
from marketing.x_client import XClient

# Win-shaped posts. X v2 recent search has no min_faves operator, so likes are filtered after.
BREAKOUT_QUERIES = [
    '("just hit" OR "we hit" OR "crossed" OR "milestone") (followers OR subscribers OR MRR OR stars OR users) -is:retweet -is:reply lang:en',
    '("first sale" OR "first $" OR "made my first" OR "launched today" OR "we won") -is:retweet -is:reply lang:en',
    '("got the job" OR "got promoted" OR "accepted to" OR "finally did it") -is:retweet -is:reply lang:en',
]


def _parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def find_breakouts(x: XClient, store: LeadStore, queries: list[str] | None = None, hours: int = 6,
                   max_authors: int = 25) -> dict:
    medians: dict[str, float] = {}
    new_ids, seen, errors = [], 0, []
    for q in queries or BREAKOUT_QUERIES:
        try:
            res = x.recent_search(q, hours=hours)
        except Exception as e:  # rate limits etc. go back to the bot
            errors.append(str(e))
            continue
        users = {u["id"]: u for u in res.get("includes", {}).get("users", [])}
        for t in res.get("data", []):
            seen += 1
            likes = t.get("public_metrics", {}).get("like_count", 0)
            if likes < MIN_LIKES:
                continue
            user = users.get(t["author_id"], {})
            followers = user.get("public_metrics", {}).get("followers_count", 0)
            if t["author_id"] not in medians:
                if len(medians) >= max_authors:
                    continue
                try:
                    tl = x.user_tweets(t["author_id"])
                    recent = [p["public_metrics"]["like_count"] for p in tl.get("data", []) if p["id"] != t["id"]]
                except Exception as e:
                    errors.append(str(e))
                    recent = []
                medians[t["author_id"]] = median_likes(recent)
            v = score_post(likes, medians[t["author_id"]], followers, _parse_time(t.get("created_at")),
                           datetime.now(timezone.utc))
            if not v.breakout:
                continue
            handle = user.get("username", "")
            lead_id = store.add("x", f"https://x.com/{handle}/status/{t['id']}", handle=handle,
                                title=t.get("text", "")[:120], score=v.score, external_id=t["id"],
                                data={"text": t.get("text", ""), "likes": likes, "followers": followers,
                                      "author_median": medians[t["author_id"]], "name": user.get("name"),
                                      "created_at": t.get("created_at"), "reason": v.reason})
            if lead_id:
                new_ids.append(lead_id)
    return {"new_leads": new_ids, "posts_seen": seen, "errors": errors[:5]}


def find_milestones(exa: ExaClient, store: LeadStore, sources: list[str] | None = None) -> dict:
    new_ids, errors = [], []
    for source, query, domains in MILESTONE_QUERIES:
        if sources and source not in sources:
            continue
        try:
            results = exa.search(query, include_domains=domains)
        except Exception as e:
            errors.append(f"{source}: {e}")
            continue
        for r in results:
            if not r.get("url"):
                continue
            lead_id = store.add(source, r["url"], handle=r.get("author"), title=r.get("title"),
                                data={"text": (r.get("text") or "")[:600], "published": r.get("publishedDate")})
            if lead_id:
                new_ids.append(lead_id)
    return {"new_leads": new_ids, "errors": errors[:5]}
