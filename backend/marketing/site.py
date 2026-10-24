"""Calls to the Receipts site (Cloudflare Pages Functions): claims and the public events feed."""
from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger("marketing.site")


def _site() -> tuple[str, str]:
    return os.environ.get("SITE_URL", "").rstrip("/"), os.environ.get("SITE_ADMIN_TOKEN", "")


def post_event(agent: str, text: str, kind: str | None = None, client: httpx.Client | None = None) -> dict:
    """POST $SITE_URL/api/events {agent, text, kind?}. One line per meaningful action."""
    url, token = _site()
    body = {"agent": agent, "text": text[:280]}
    if kind:
        body["kind"] = kind
    if not url or not token:
        log.info("event (site not configured): %s", body)
        return {"ok": False, "skipped": "SITE_URL or SITE_ADMIN_TOKEN not set", "event": body}
    c = client or httpx.Client(timeout=15)
    r = c.post(f"{url}/api/events", json=body, headers={"authorization": f"Bearer {token}"})
    return {"ok": r.status_code < 300, "status": r.status_code}


def put_claim(claim: dict, client: httpx.Client | None = None) -> dict:
    """PUT $SITE_URL/api/claim/<slug> (Bearer admin token) with the claim JSON."""
    url, token = _site()
    if not url or not token:
        return {"ok": False, "skipped": "SITE_URL or SITE_ADMIN_TOKEN not set"}
    c = client or httpx.Client(timeout=30)
    r = c.put(f"{url}/api/claim/{claim['slug']}", json=claim, headers={"authorization": f"Bearer {token}"})
    return {"ok": r.status_code < 300, "status": r.status_code}
