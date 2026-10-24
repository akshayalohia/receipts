"""Ads budget ledger with a hard daily cap (ADS_DAILY_CAP_USD, default 50).

The ads bot only *drafts* campaigns and budget moves; a human applies them in Whop Ads / X Ads
(TODO(ads-oauth): both APIs need human OAuth, so nothing here calls them). A draft that would
push the sum of today's per-channel daily budgets above the cap is rejected, never clamped silently.
"""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

CHANNELS = {"whop_ads", "x_ads"}
DEFAULT_CAP_USD = 50.0


def daily_cap_usd() -> float:
    try:
        cap = float(os.environ.get("ADS_DAILY_CAP_USD", DEFAULT_CAP_USD))
    except ValueError:
        cap = DEFAULT_CAP_USD
    return max(cap, 0.0)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class AdsLedger:
    def __init__(self, path: Path | str, cap_usd: float | None = None):
        self.path = str(path)
        self.cap = daily_cap_usd() if cap_usd is None else float(cap_usd)
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS ads_moves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                channel TEXT NOT NULL,
                campaign TEXT NOT NULL,
                daily_usd REAL NOT NULL,
                note TEXT,
                agent TEXT,
                created_at REAL NOT NULL)""")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _budgets(self, c: sqlite3.Connection, day: str) -> dict[tuple[str, str], float]:
        """Latest daily budget per (channel, campaign) for the day."""
        out: dict[tuple[str, str], float] = {}
        for r in c.execute("SELECT channel, campaign, daily_usd FROM ads_moves WHERE day=? ORDER BY id", (day,)):
            out[(r["channel"], r["campaign"])] = r["daily_usd"]
        return out

    def status(self, day: str | None = None) -> dict:
        day = day or _today()
        with self._conn() as c:
            budgets = self._budgets(c, day)
        total = round(sum(budgets.values()), 2)
        return {"day": day, "cap_usd": self.cap, "planned_usd": total,
                "remaining_usd": round(max(self.cap - total, 0.0), 2),
                "campaigns": [{"channel": ch, "campaign": cp, "daily_usd": v} for (ch, cp), v in budgets.items()],
                "live_apis": False, "todo": "TODO(ads-oauth): a human applies drafts in Whop Ads / X Ads"}

    def draft(self, channel: str, campaign: str, daily_usd: float, note: str = "", agent: str = "ads",
              day: str | None = None) -> dict:
        """Set campaign's daily budget (0 = pause/kill). Rejected if today's total would exceed the cap."""
        if channel not in CHANNELS:
            return {"ok": False, "error": f"channel must be one of {sorted(CHANNELS)}"}
        try:
            daily_usd = round(float(daily_usd), 2)
        except (TypeError, ValueError):
            return {"ok": False, "error": "daily_usd must be a number"}
        if daily_usd < 0 or daily_usd != daily_usd:
            return {"ok": False, "error": "daily_usd must be >= 0"}
        day = day or _today()
        with self._conn() as c:
            budgets = self._budgets(c, day)
            budgets[(channel, campaign)] = daily_usd
            total = round(sum(budgets.values()), 2)
            if total > self.cap + 1e-9:
                return {"ok": False, "error": f"over daily cap: total would be ${total:.2f} > cap ${self.cap:.2f}",
                        "cap_usd": self.cap}
            c.execute("INSERT INTO ads_moves (day, channel, campaign, daily_usd, note, agent, created_at)"
                      " VALUES (?,?,?,?,?,?,?)", (day, channel, campaign, daily_usd, note, agent, time.time()))
        return {"ok": True, "channel": channel, "campaign": campaign, "daily_usd": daily_usd,
                "planned_usd": total, "cap_usd": self.cap}
