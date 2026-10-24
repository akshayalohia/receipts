"""order create -> photo upload -> message -> fake Hermes run -> agent message + SSE events,
then /accept -> quote event on the same stream. Runs a real uvicorn server on 127.0.0.1."""
from __future__ import annotations

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from fakes import APP_HEADERS
from service.app import create_app


@pytest.fixture
def live_url(core):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(core, start_monitor=False), log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.02)
    assert server.started
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


def read_events(lines, until, timeout=10.0) -> list[tuple[str, dict]]:
    events, name, deadline = [], None, time.time() + timeout
    for line in lines:
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:") and name:
            events.append((name, json.loads(line[5:])))
            if until(events):
                return events
            name = None
        assert time.time() < deadline, f"timed out; got {events}"
    return events


def test_message_runs_intake_and_streams(core, hermes, live_url):
    def intake_hook(body):                       # what the intake bot would do through MCP tools
        oid = body["session_id"]
        art = core.build_template(oid, "nametag", {"text": "AKSHAYA"}, "intake")
        core.publish_design(oid, art["artifact_id"], "Blue name tag, 80 x 25 mm", "intake")

    hermes.hooks["intake"] = intake_hook
    hermes.replies["intake"] = ["Here is your ", "name tag."]

    with httpx.Client(base_url=live_url, headers=APP_HEADERS, timeout=10) as http:
        order = http.post("/orders", json={"product": "nametag"}).json()
        oid = order["id"]
        assert order["status"] == "draft"

        up = http.post(f"/orders/{oid}/photos",
                       files=[("files[]", ("tag.jpg", b"\xff\xd8jpeg", "image/jpeg"))])
        assert up.status_code == 200 and len(up.json()["urls"]) == 1
        assert http.get(up.json()["urls"][0].replace("http://testserver", live_url),
                        headers={}).content == b"\xff\xd8jpeg"     # signed URL, no headers

        with http.stream("GET", f"/orders/{oid}/stream") as stream:
            lines = stream.iter_lines()
            assert next(lines) == ": connected"
            r = http.post(f"/orders/{oid}/messages",
                          json={"text": "AKSHAYA, bold", "colour": "blue",
                                "measurements": [{"label": "width", "mm": 80}]})
            assert r.status_code == 202 and "message_id" in r.json()
            events = read_events(lines, lambda ev: any(n == "message" and d["role"] == "agent" for n, d in ev))

            types = [n for n, _ in events]
            assert ("message", {"role": "user", "text": "AKSHAYA, bold\nMeasurements: width 80 mm\nColour: blue"}) in events
            assert ("status", {"status": "designing"}) in events
            assert ("status", {"status": "review"}) in events
            design = next(d for n, d in events if n == "design")
            assert design["version"] == 1 and design["bbox_mm"] == [80.0, 25.0, 4.0]
            assert "".join(d["text"] for n, d in events if n == "agent_delta") == "Here is your name tag."
            assert events[-1] == ("message", {"role": "agent", "text": "Here is your name tag."})
            assert types.index("design") < types.index("message", types.index("agent_delta"))

            acc = http.post(f"/orders/{oid}/accept")
            assert acc.status_code == 202
            events = read_events(lines, lambda ev: any(n == "quote" for n, _ in ev))
            quote = next(d for n, d in events if n == "quote")
            assert quote["colour"] == "blue" and quote["whop_variant_id"].startswith("plan_mock_")

    run = hermes.runs[0]
    assert run["profile"] == "intake" and run["body"]["session_id"] == oid
    assert "AKSHAYA, bold" in run["body"]["input"] and "width = 80.0 mm" in run["body"]["input"]
    assert "photo_1.jpg" in run["body"]["input"]
    assert hermes.profiles() == ["intake", "sales"]           # /accept wakes the sales bot

    final = core.db.get_order(oid)
    assert final["status"] == "quoted" and final["colour"] == "blue"
    roles = [m["role"] for m in core.db.list_messages(oid)]
    assert roles == ["user", "agent"]
