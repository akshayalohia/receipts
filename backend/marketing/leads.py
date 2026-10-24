"""Lead store: sqlite, deduped by a normalised key (one lead per post / page)."""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit

_STATUS_RE = re.compile(r"^/[^/]+/status(?:es)?/(\d+)")


def lead_key(url: str, source: str = "", external_id: str | None = None) -> str:
    """x.com/a/status/1?s=20 and twitter.com/A/status/1 give the same key."""
    if external_id:
        return f"{source}:{external_id}"
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.").removeprefix("mobile.")
    if host in {"twitter.com", "x.com"}:
        m = _STATUS_RE.match(parts.path)
        if m:
            return f"x:status:{m.group(1)}"
        host = "x.com"
    path = parts.path.rstrip("/").lower() if host == "x.com" else parts.path.rstrip("/")
    return f"{host}{path}"


class LeadStore:
    def __init__(self, path: Path | str):
        self.path = str(path)
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                source TEXT NOT NULL,
                url TEXT NOT NULL,
                handle TEXT,
                title TEXT,
                data TEXT NOT NULL DEFAULT '{}',
                score REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'new',
                created_at REAL NOT NULL)""")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def add(self, source: str, url: str, handle: str | None = None, title: str | None = None,
            data: dict | None = None, score: float = 0.0, external_id: str | None = None) -> int | None:
        """Insert a lead; returns its id, or None if it was already known."""
        key = lead_key(url, source, external_id)
        with self._conn() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO leads (key, source, url, handle, title, data, score, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (key, source, url, handle, title, json.dumps(data or {}), score, time.time()))
            return cur.lastrowid if cur.rowcount else None

    def get(self, lead_id: int) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        return _row(row) if row else None

    def list(self, status: str | None = None, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            if status:
                rows = c.execute("SELECT * FROM leads WHERE status=? ORDER BY score DESC, id DESC LIMIT ?",
                                 (status, limit)).fetchall()
            else:
                rows = c.execute("SELECT * FROM leads ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [_row(r) for r in rows]

    def set_status(self, lead_id: int, status: str, **extra) -> None:
        with self._conn() as c:
            row = c.execute("SELECT data FROM leads WHERE id=?", (lead_id,)).fetchone()
            if row is None:
                raise KeyError(lead_id)
            data = {**json.loads(row["data"]), **extra}
            c.execute("UPDATE leads SET status=?, data=? WHERE id=?", (status, json.dumps(data), lead_id))

    def counts_by_source(self) -> dict[str, int]:
        with self._conn() as c:
            return {r[0]: r[1] for r in c.execute("SELECT source, COUNT(*) FROM leads GROUP BY source")}


def _row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["data"] = json.loads(out["data"])
    return out
