"""Hermes Agent API client (Runs API through the multiplexing gateway).

POST {HERMES_API_BASE}/p/<profile>/v1/runs  {"input", "session_id"}  -> {"run_id", "status"}
GET  {HERMES_API_BASE}/p/<profile>/v1/runs/{run_id}/events            -> SSE
Runs are profile-scoped, so the events/status routes also carry the /p/<profile> prefix.
Auth is bound to the routed profile: each profile has its own API_SERVER_KEY, derived
here as f"{HERMES_API_KEY}-{profile}" (fleet/bootstrap.sh writes the same value).

The docs name the event types (message.delta, tool.started, tool.completed, run.completed,
run.failed, run.cancelled, run.interrupted) but not every payload field, so parsing is
tolerant: the type comes from the SSE `event:` line or a JSON `event`/`type` field, and
delta text from `delta`/`text`/`content`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable

import httpx

TERMINAL = {"run.completed": "completed", "run.failed": "failed",
            "run.cancelled": "cancelled", "run.interrupted": "interrupted"}
DELTA_TYPES = {"message.delta", "assistant.delta"}


def profile_key(base_key: str, profile: str) -> str:
    return f"{base_key}-{profile}"


@dataclass
class RunResult:
    run_id: str
    status: str
    output: str


async def iter_sse(response: httpx.Response) -> AsyncIterator[tuple[str, dict]]:
    event_name, data_lines = "", []
    async for line in response.aiter_lines():
        if line == "":
            if data_lines:
                raw = "\n".join(data_lines)
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    data = {"text": raw}
                if not isinstance(data, dict):
                    data = {"value": data}
                yield event_name or data.get("event") or data.get("type") or "message", data
            event_name, data_lines = "", []
        elif line.startswith(":"):
            continue                      # keepalive comment
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())


def _text(data: dict) -> str:
    for key in ("delta", "text", "content"):
        if isinstance(data.get(key), str):
            return data[key]
    return ""


class HermesClient:
    def __init__(self, base_url: str, api_key: str, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.transport = transport

    def _headers(self, profile: str) -> dict:
        return {"Authorization": f"Bearer {profile_key(self.api_key, profile)}"}

    async def run(self, profile: str, input_text: str, session_id: str, *,
                  idempotency_key: str | None = None,
                  on_delta: Callable[[str], Awaitable[None]] | None = None) -> RunResult:
        prefix = f"{self.base_url}/p/{profile}/v1/runs"
        headers = self._headers(profile)
        timeout = httpx.Timeout(30.0, read=300.0)
        async with httpx.AsyncClient(timeout=timeout, transport=self.transport) as http:
            post_headers = dict(headers)
            if idempotency_key:
                post_headers["Idempotency-Key"] = idempotency_key
            r = await http.post(prefix, json={"input": input_text, "session_id": session_id},
                                headers=post_headers)
            r.raise_for_status()
            run_id = r.json()["run_id"]
            deltas: list[str] = []
            async with http.stream("GET", f"{prefix}/{run_id}/events", headers=headers) as resp:
                resp.raise_for_status()
                async for etype, data in iter_sse(resp):
                    if etype in DELTA_TYPES:
                        text = _text(data)
                        if text:
                            deltas.append(text)
                            if on_delta:
                                await on_delta(text)
                    elif etype in TERMINAL:
                        output = data.get("output")
                        if not isinstance(output, str):
                            output = "".join(deltas)
                        status = TERMINAL[etype]
                        if status != "completed" and not output:
                            output = str(data.get("error") or "")
                        return RunResult(run_id, status, output)
            # Stream closed without a terminal event: poll the run once.
            s = await http.get(f"{prefix}/{run_id}", headers=headers)
            s.raise_for_status()
            body = s.json()
            out = body.get("output") if isinstance(body.get("output"), str) else "".join(deltas)
            return RunResult(run_id, body.get("status", "unknown"), out)
