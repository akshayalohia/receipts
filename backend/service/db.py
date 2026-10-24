"""SQLite store. Schema per SPEC.md "SQLite (service/db.py)".

One connection guarded by a lock: the FastAPI app, the MCP server and the printer
monitor run in one process and may call in from worker threads.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

ORDER_STATUSES = (
    "draft", "designing", "review", "quoted", "paid", "queued", "printing",
    "done", "picked_up", "failed", "refunded", "cancelled",
)
PAID_STATUSES = ("paid", "queued", "printing", "done", "picked_up")
JSON_ORDER_COLS = ("params", "files", "bbox_mm")

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    status TEXT NOT NULL,
    product TEXT NOT NULL,
    path TEXT,
    params TEXT,
    colour TEXT,
    design_version INTEGER NOT NULL DEFAULT 0,
    files TEXT,
    bbox_mm TEXT,
    print_seconds INTEGER,
    filament_grams REAL,
    price_cents INTEGER,
    gen_cost_cents INTEGER NOT NULL DEFAULT 0,
    whop_variant_id TEXT,
    whop_purchase_url TEXT,
    payment_id TEXT,
    queue_position INTEGER,
    eta TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_device ON orders(device_id);
CREATE INDEX IF NOT EXISTS orders_variant ON orders(whop_variant_id);
CREATE UNIQUE INDEX IF NOT EXISTS orders_payment ON orders(payment_id);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'agent', 'system')),
    text TEXT NOT NULL,
    media TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_order ON messages(order_id);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT,
    actor TEXT NOT NULL,
    type TEXT NOT NULL,
    payload TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS events_order ON events(order_id);
CREATE TABLE IF NOT EXISTS human_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ('bed_clear', 'spool_swap', 'qa', 'pickup', 'other')),
    order_id TEXT,
    details TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
    assignee TEXT NOT NULL DEFAULT 'teammate' CHECK (assignee IN ('teammate', 'terac')),
    created_at REAL NOT NULL,
    done_at REAL
);
CREATE TABLE IF NOT EXISTS shop_state (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

DEFAULT_SHOP_STATE = {
    "loaded_colour": "white",
    "colours_in_stock": ["white", "black", "red", "blue"],
    "printer_busy": False,
    "bed_clear": True,
}


def new_order_id() -> str:
    return "ord_" + secrets.token_hex(6)


class DB:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            for key, value in DEFAULT_SHOP_STATE.items():
                self._conn.execute(
                    "INSERT OR IGNORE INTO shop_state(key, value) VALUES (?, ?)",
                    (key, json.dumps(value)),
                )

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    def _x(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, args)
            return cur.lastrowid

    # ---- orders -------------------------------------------------------------
    @staticmethod
    def _order(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        for col in JSON_ORDER_COLS:
            d[col] = json.loads(d[col]) if d[col] else ({} if col != "bbox_mm" else None)
        return d

    def create_order(self, device_id: str, product: str, colour: str | None) -> dict:
        now = time.time()
        oid = new_order_id()
        self._x(
            "INSERT INTO orders(id, device_id, status, product, params, colour, files, created_at, updated_at)"
            " VALUES (?, ?, 'draft', ?, '{}', ?, '{}', ?, ?)",
            (oid, device_id, product, colour, now, now),
        )
        return self.get_order(oid)

    def get_order(self, order_id: str) -> dict | None:
        rows = self._q("SELECT * FROM orders WHERE id = ?", (order_id,))
        return self._order(rows[0] if rows else None)

    def update_order(self, order_id: str, **fields: Any) -> dict:
        if not fields:
            return self.get_order(order_id)
        sets, args = [], []
        for key, value in fields.items():
            if key in JSON_ORDER_COLS and value is not None:
                value = json.dumps(value)
            sets.append(f"{key} = ?")
            args.append(value)
        sets.append("updated_at = ?")
        args.append(time.time())
        args.append(order_id)
        self._x(f"UPDATE orders SET {', '.join(sets)} WHERE id = ?", tuple(args))
        return self.get_order(order_id)

    def list_orders(self, *, device_id: str | None = None, status: str | list[str] | None = None) -> list[dict]:
        sql, args = "SELECT * FROM orders WHERE 1=1", []
        if device_id is not None:
            sql += " AND device_id = ?"
            args.append(device_id)
        if status:
            statuses = [status] if isinstance(status, str) else list(status)
            sql += f" AND status IN ({','.join('?' * len(statuses))})"
            args.extend(statuses)
        sql += " ORDER BY created_at ASC"
        return [self._order(r) for r in self._q(sql, tuple(args))]

    def find_order_by_variant(self, variant_id: str) -> dict | None:
        rows = self._q("SELECT * FROM orders WHERE whop_variant_id = ?", (variant_id,))
        return self._order(rows[0] if rows else None)

    def find_order_by_payment(self, payment_id: str) -> dict | None:
        rows = self._q("SELECT * FROM orders WHERE payment_id = ?", (payment_id,))
        return self._order(rows[0] if rows else None)

    # ---- messages -----------------------------------------------------------
    def add_message(self, order_id: str, role: str, text: str, media: list | None = None) -> int:
        return self._x(
            "INSERT INTO messages(order_id, role, text, media, created_at) VALUES (?, ?, ?, ?, ?)",
            (order_id, role, text, json.dumps(media or []), time.time()),
        )

    def list_messages(self, order_id: str) -> list[dict]:
        out = []
        for r in self._q("SELECT * FROM messages WHERE order_id = ? ORDER BY id", (order_id,)):
            d = dict(r)
            d["media"] = json.loads(d["media"]) if d["media"] else []
            out.append(d)
        return out

    # ---- events -------------------------------------------------------------
    def add_event(self, order_id: str | None, actor: str, type_: str, payload: dict | None) -> int:
        return self._x(
            "INSERT INTO events(order_id, actor, type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
            (order_id, actor, type_, json.dumps(payload or {}), time.time()),
        )

    def list_events(self, order_id: str | None = None, type_: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM events WHERE 1=1", []
        if order_id is not None:
            sql += " AND order_id = ?"
            args.append(order_id)
        if type_ is not None:
            sql += " AND type = ?"
            args.append(type_)
        out = []
        for r in self._q(sql + " ORDER BY id", tuple(args)):
            d = dict(r)
            d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
            out.append(d)
        return out

    # ---- human tasks --------------------------------------------------------
    def add_human_task(self, kind: str, details: str, order_id: str | None = None,
                       assignee: str = "teammate") -> dict:
        tid = self._x(
            "INSERT INTO human_tasks(kind, order_id, details, assignee, created_at) VALUES (?, ?, ?, ?, ?)",
            (kind, order_id, details, assignee, time.time()),
        )
        return self.get_human_task(tid)

    def get_human_task(self, task_id: int) -> dict | None:
        rows = self._q("SELECT * FROM human_tasks WHERE id = ?", (task_id,))
        return dict(rows[0]) if rows else None

    def list_human_tasks(self, status: str | None = None, kind: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM human_tasks WHERE 1=1", []
        if status:
            sql += " AND status = ?"
            args.append(status)
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        return [dict(r) for r in self._q(sql + " ORDER BY id", tuple(args))]

    def finish_human_task(self, task_id: int) -> dict | None:
        self._x("UPDATE human_tasks SET status = 'done', done_at = ? WHERE id = ? AND status = 'open'",
                (time.time(), task_id))
        return self.get_human_task(task_id)

    # ---- shop state ---------------------------------------------------------
    def get_state(self, key: str | None = None) -> Any:
        if key is None:
            return {r["key"]: json.loads(r["value"]) for r in self._q("SELECT key, value FROM shop_state")}
        rows = self._q("SELECT value FROM shop_state WHERE key = ?", (key,))
        return json.loads(rows[0]["value"]) if rows else DEFAULT_SHOP_STATE.get(key)

    def set_state(self, key: str, value: Any) -> None:
        self._x("INSERT INTO shop_state(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, json.dumps(value)))
