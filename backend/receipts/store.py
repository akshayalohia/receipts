"""SQLite store at $RECEIPTS_DATA/receipts.db. One row per Whop payment (idempotent by pay_ id)."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .models import Order, check_transition

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id TEXT NOT NULL UNIQUE,
    order_ref TEXT NOT NULL DEFAULT '',
    product TEXT NOT NULL,
    colour TEXT NOT NULL,
    status TEXT NOT NULL,
    price_cents INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL,
    meta TEXT NOT NULL DEFAULT '{}',
    email TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL DEFAULT '',
    supplier TEXT NOT NULL DEFAULT '',
    supplier_order_id TEXT NOT NULL DEFAULT '',
    supplier_status TEXT NOT NULL DEFAULT '',
    cost_cents INTEGER NOT NULL DEFAULT 0,
    shipping_cents INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS status_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seq INTEGER NOT NULL,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    ts TEXT NOT NULL
);
"""
_FIELDS = ("payment_id", "order_ref", "product", "colour", "status", "price_cents", "amount_cents", "meta",
           "email", "file_path", "supplier", "supplier_order_id", "supplier_status", "cost_cents",
           "shipping_cents", "note", "created_at", "updated_at")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._db.executescript(_SCHEMA)

    @staticmethod
    def _row(r: sqlite3.Row | None) -> Order | None:
        if r is None:
            return None
        d = dict(r)
        d["meta"] = json.loads(d["meta"] or "{}")
        return Order(**d)

    def has_payment(self, payment_id: str) -> bool:
        return self._db.execute("SELECT 1 FROM orders WHERE payment_id=?", (payment_id,)).fetchone() is not None

    def insert(self, *, payment_id: str, product: str, colour: str, status: str, price_cents: int,
               amount_cents: int, meta: dict, order_ref: str = "", email: str = "", note: str = "") -> Order | None:
        """Insert a new order; returns None if the payment was already recorded."""
        now = _now()
        with self._lock:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO orders (payment_id, order_ref, product, colour, status, price_cents,"
                " amount_cents, meta, email, note, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (payment_id, order_ref, product, colour, status, price_cents, amount_cents,
                 json.dumps(meta), email, note, now, now))
            if cur.rowcount == 0:
                return None
            seq = cur.lastrowid
            self._db.execute("INSERT INTO status_log (seq, from_status, to_status, note, ts) VALUES (?,?,?,?,?)",
                             (seq, "", status, note, now))
        return self.get(seq)

    def get(self, seq: int) -> Order | None:
        return self._row(self._db.execute("SELECT * FROM orders WHERE seq=?", (seq,)).fetchone())

    def find(self, key) -> Order | None:
        """Look up by seq (int / "7" / "#007"), pay_ id, or order_ref."""
        s = str(key).strip().lstrip("#")
        if s.isdigit():
            return self.get(int(s))
        r = self._db.execute("SELECT * FROM orders WHERE payment_id=? OR order_ref=? ORDER BY seq LIMIT 1",
                             (s, s)).fetchone()
        return self._row(r)

    def list(self, status: str | None = None) -> list[Order]:
        if status:
            rows = self._db.execute("SELECT * FROM orders WHERE status=? ORDER BY seq", (status,)).fetchall()
        else:
            rows = self._db.execute("SELECT * FROM orders ORDER BY seq").fetchall()
        return [self._row(r) for r in rows]

    def update(self, seq: int, **fields) -> Order:
        bad = set(fields) - set(_FIELDS) - {"status"}
        if bad or "status" in fields:
            raise ValueError(f"use set_status for status; unknown fields {sorted(bad)}")
        if "meta" in fields:
            fields["meta"] = json.dumps(fields["meta"])
        fields["updated_at"] = _now()
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._db.execute(f"UPDATE orders SET {cols} WHERE seq=?", (*fields.values(), seq))
        return self.get(seq)

    def set_status(self, seq: int, status: str, note: str = "") -> tuple[Order, str]:
        """Validated status change; returns (order, previous_status)."""
        with self._lock:
            cur = self._db.execute("SELECT status FROM orders WHERE seq=?", (seq,)).fetchone()
            if cur is None:
                raise KeyError(f"order {seq} not found")
            prev = cur["status"]
            check_transition(prev, status)
            now = _now()
            self._db.execute("UPDATE orders SET status=?, note=?, updated_at=? WHERE seq=?", (status, note, now, seq))
            self._db.execute("INSERT INTO status_log (seq, from_status, to_status, note, ts) VALUES (?,?,?,?,?)",
                             (seq, prev, status, note, now))
        return self.get(seq), prev

    def history(self, seq: int) -> list[dict]:
        rows = self._db.execute("SELECT from_status, to_status, note, ts FROM status_log WHERE seq=? ORDER BY id",
                                (seq,)).fetchall()
        return [dict(r) for r in rows]

    def max_seq(self) -> int:
        r = self._db.execute("SELECT MAX(seq) AS m FROM orders").fetchone()
        return r["m"] or 0
