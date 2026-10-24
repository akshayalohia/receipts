"""Human post queue: every drafted reply / post / email waits here for a person to send it.

Search-triggered auto-replies get X accounts banned, so the bots never post them; a human
opens http://127.0.0.1:8787/queue, copies the text, opens the target post and marks it posted.
"""
from __future__ import annotations

import html
import json
import sqlite3
import time
from pathlib import Path

KINDS = {"reply", "email", "x_post", "ads_move", "terac_task", "note"}


class QueueStore:
    def __init__(self, path: Path | str):
        self.path = str(path)
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS post_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                agent TEXT NOT NULL,
                text TEXT NOT NULL,
                target_url TEXT,
                claim_url TEXT,
                lead_id INTEGER,
                meta TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at REAL NOT NULL,
                posted_at REAL)""")
            # One draft per lead and kind (the closer may run twice on the same lead).
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS post_queue_lead_kind"
                      " ON post_queue(lead_id, kind) WHERE lead_id IS NOT NULL")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def add(self, kind: str, agent: str, text: str, target_url: str | None = None,
            claim_url: str | None = None, lead_id: int | None = None, meta: dict | None = None) -> dict:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {sorted(KINDS)}")
        text = text.strip()
        if not text:
            raise ValueError("text is empty")
        with self._conn() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO post_queue (kind, agent, text, target_url, claim_url, lead_id, meta, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (kind, agent, text, target_url, claim_url, lead_id, json.dumps(meta or {}), time.time()))
            if cur.rowcount:
                return {"ok": True, "id": cur.lastrowid, "duplicate": False}
            row = c.execute("SELECT id FROM post_queue WHERE lead_id=? AND kind=?", (lead_id, kind)).fetchone()
            return {"ok": True, "id": row["id"], "duplicate": True}

    def list(self, status: str | None = "pending", limit: int = 200) -> list[dict]:
        with self._conn() as c:
            if status:
                rows = c.execute("SELECT * FROM post_queue WHERE status=? ORDER BY id DESC LIMIT ?",
                                 (status, limit)).fetchall()
            else:
                rows = c.execute("SELECT * FROM post_queue ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(r), "meta": json.loads(r["meta"])} for r in rows]

    def mark_posted(self, item_id: int) -> bool:
        with self._conn() as c:
            cur = c.execute("UPDATE post_queue SET status='posted', posted_at=? WHERE id=? AND status='pending'",
                            (time.time(), item_id))
            return bool(cur.rowcount)

    def counts(self) -> dict[str, int]:
        with self._conn() as c:
            return {f"{r[0]}:{r[1]}": r[2] for r in
                    c.execute("SELECT kind, status, COUNT(*) FROM post_queue GROUP BY kind, status")}


_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Receipts post queue</title>
<style>
body{{font:15px/1.45 system-ui,sans-serif;margin:0 auto;max-width:860px;padding:16px;color:#18181b;background:#fafafa}}
h1{{font-size:20px}} .item{{background:#fff;border:1px solid #e4e4e7;border-radius:8px;padding:12px;margin:10px 0}}
.meta{{color:#52525b;font-size:13px}} pre{{white-space:pre-wrap;font:inherit;margin:8px 0}}
button,a.btn{{font:inherit;padding:6px 12px;border-radius:6px;border:1px solid #18181b;background:#18181b;color:#fff;
cursor:pointer;text-decoration:none;display:inline-block;margin-right:6px}} button.ghost{{background:#fff;color:#18181b}}
</style></head><body><h1>Post queue ({count} pending)</h1>
<p class="meta">Copy, open the post, reply from the brand account, then Mark posted. Nothing here posts automatically.</p>
{items}
<script>
document.querySelectorAll('[data-copy]').forEach(b=>b.onclick=()=>{{
  navigator.clipboard.writeText(document.getElementById('t'+b.dataset.copy).innerText);b.textContent='Copied';}});
</script></body></html>"""


def render_queue_html(items: list[dict]) -> str:
    blocks = []
    for it in items:
        i = int(it["id"])
        target = it.get("target_url") or ""
        claim = it.get("claim_url") or ""
        links = ""
        if target:
            links += f'<a class="btn" href="{html.escape(target)}" target="_blank" rel="noopener">Open post</a>'
        blocks.append(
            f'<div class="item"><div class="meta">#{i} {html.escape(it["kind"])} by {html.escape(it["agent"])}'
            + (f' &middot; target: <a href="{html.escape(target)}" target="_blank" rel="noopener">{html.escape(target)}</a>' if target else "")
            + (f' &middot; claim: <a href="{html.escape(claim)}" target="_blank" rel="noopener">{html.escape(claim)}</a>' if claim else "")
            + f'</div><pre id="t{i}">{html.escape(it["text"])}</pre>'
            f'<button data-copy="{i}">Copy</button>{links}'
            f'<form method="post" action="/queue/{i}/posted" style="display:inline">'
            f'<button class="ghost" type="submit">Mark posted</button></form></div>')
    return _PAGE.format(count=len(items), items="\n".join(blocks) or "<p>Nothing waiting.</p>")
