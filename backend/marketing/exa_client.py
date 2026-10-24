"""Exa search client (EXA_API_KEY): POST https://api.exa.ai/search with `contents`."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import httpx

API = "https://api.exa.ai"

# Milestone sources (RECEIPTS-PLAN.md engines 2-4). Each: (source, query, include_domains).
MILESTONE_QUERIES: list[tuple[str, str, list[str] | None]] = [
    ("linkedin", '"thrilled to announce" new role OR promotion OR raised OR launched', ["linkedin.com"]),
    ("youtube", "thank you 1k subscribers OR 10k subscribers OR 50k subscribers milestone video", ["youtube.com"]),
    ("producthunt", "Product Hunt top product of the day today", ["producthunt.com"]),
    ("show_hn", "Show HN", ["news.ycombinator.com"]),
    ("github", "repository just crossed 1,000 stars OR 10,000 stars on GitHub", None),
    ("devpost", "hackathon winners announced this weekend", ["devpost.com"]),
]


class ExaClient:
    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None):
        self.api_key = api_key if api_key is not None else os.environ.get("EXA_API_KEY", "")
        self.http = client or httpx.Client(timeout=30)

    def search(self, query: str, num_results: int = 10, days: int = 2,
               include_domains: list[str] | None = None, text_chars: int = 600) -> list[dict]:
        if not self.api_key:
            raise RuntimeError("EXA_API_KEY not set")
        start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        body: dict = {"query": query, "type": "auto", "numResults": num_results,
                      "startPublishedDate": start, "contents": {"text": {"maxCharacters": text_chars}}}
        if include_domains:
            body["includeDomains"] = include_domains
        r = self.http.post(f"{API}/search", json=body, headers={"x-api-key": self.api_key})
        r.raise_for_status()
        return r.json().get("results", [])
