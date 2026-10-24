"""Breakout scoring (RECEIPTS-PLAN.md engine 1).

A post is a breakout when, within the last 6 h, either
  - likes >= 20 x the median likes of the author's recent posts, or
  - likes >= 1,000 and the author has fewer than 5,000 followers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median as _median

RATIO = 20
ABS_LIKES = 1000
SMALL_ACCOUNT = 5000
WINDOW_HOURS = 6
MIN_LIKES = 50          # ignore tiny posts even if 20x a near-zero median


@dataclass(frozen=True)
class Verdict:
    breakout: bool
    reason: str
    score: float          # likes / max(median, 1); used to rank leads


def median_likes(recent_likes: list[int]) -> float:
    return float(_median(recent_likes)) if recent_likes else 0.0


def score_post(likes: int, author_median: float, followers: int, created_at: datetime | None = None,
               now: datetime | None = None) -> Verdict:
    ratio = likes / max(author_median, 1.0)
    if created_at is not None:
        now = now or datetime.now(timezone.utc)
        if now - created_at > timedelta(hours=WINDOW_HOURS):
            return Verdict(False, "older than 6h", ratio)
    if likes >= ABS_LIKES and followers < SMALL_ACCOUNT:
        return Verdict(True, f"{likes} likes on a {followers}-follower account", ratio)
    if likes >= MIN_LIKES and author_median >= 0 and likes >= RATIO * max(author_median, 1.0):
        return Verdict(True, f"{likes} likes = {ratio:.0f}x the author's median {author_median:g}", ratio)
    return Verdict(False, "below thresholds", ratio)
