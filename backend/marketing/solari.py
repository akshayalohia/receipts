"""Solari browser helper: drive a Solari cloud browser session with Playwright over CDP.

Used as the backup source for X advanced search and for pages with no API (Social Blade,
Product Hunt lists, checkout QA).

TODO(solari-sdk): the session-creation call below is a guess; confirm the endpoint, auth header
and response field against docs.getsolari.com. If Solari shows a CDP websocket URL in its
dashboard, set SOLARI_CDP_URL and the guess is skipped. Playwright is not in pyproject.toml;
add `playwright` there (owned by another run) before using this in the container.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

import httpx

SOLARI_API = os.environ.get("SOLARI_API_URL", "https://api.getsolari.com/v1")


def cdp_url() -> str:
    if os.environ.get("SOLARI_CDP_URL"):
        return os.environ["SOLARI_CDP_URL"]
    key = os.environ.get("SOLARI_API_KEY", "")
    if not key:
        raise RuntimeError("SOLARI_API_KEY not set")
    r = httpx.post(f"{SOLARI_API}/sessions", headers={"authorization": f"Bearer {key}"}, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("cdp_url") or data.get("connectUrl") or data["ws_url"]


@contextmanager
def browser_page():
    """with browser_page() as page: page.goto(...)"""
    from playwright.sync_api import sync_playwright  # lazy: optional dependency

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp_url())
        try:
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.new_page()
            yield page
        finally:
            browser.close()


def x_advanced_search_url(query: str) -> str:
    from urllib.parse import quote
    return f"https://x.com/search?q={quote(query)}&f=live"
