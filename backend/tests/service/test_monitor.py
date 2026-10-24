"""Printer monitor: FINISH -> done + bed_clear task; two bad snapshots -> pause."""
from __future__ import annotations

import asyncio

from fakes import designed_order
from service.monitor import PrinterMonitor


def _printing_order(core, pipeline):
    order = designed_order(core)
    core.prepare_quote(order["id"], "sales")
    core.mark_paid(core.db.get_order(order["id"]), "pay_1", "whop")
    result = core.start_next_job("production")
    assert result == {"started": True, "order_id": order["id"], "colour": "white"}
    assert pipeline.printer.calls[0] == ("start", order["id"])
    return core.db.get_order(order["id"])


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_finish_marks_done_and_requests_bed_clear(core, pipeline, hermes):
    order = _printing_order(core, pipeline)
    assert order["status"] == "printing" and core.db.get_state("bed_clear") is False

    async def scenario():
        monitor = PrinterMonitor(core)
        pipeline.printer.state, pipeline.printer.progress = "RUNNING", 50
        await monitor.tick()
        pipeline.printer.state, pipeline.printer.progress = "FINISH", 100
        await monitor.tick()
        await core.drain()

    asyncio.run(scenario())
    o = core.db.get_order(order["id"])
    assert o["status"] == "done"
    tasks = core.db.list_human_tasks(status="open")
    assert [(t["kind"], t["order_id"]) for t in tasks] == [("bed_clear", order["id"])]
    assert core.db.list_events(order["id"], "human_task")[0]["payload"]["kind"] == "bed_clear"
    assert core.db.get_state("printer_busy") is False and core.db.get_state("bed_clear") is False
    assert core.db.list_messages(order["id"])[-1]["text"] == "Your print is finished and ready for pickup."
    printer_events = core.db.list_events(order["id"], "printer")
    assert [e["payload"]["state"] for e in printer_events] == ["RUNNING", "FINISH"]
    prod = [r for r in hermes.runs if r["profile"] == "production"]
    assert len(prod) == 1 and "print_finished" in prod[0]["body"]["input"]

    # the next job only starts after a human clears the bed
    assert core.start_next_job("production")["started"] is False


def test_two_bad_snapshots_pause_the_print(core, pipeline, hermes):
    order = _printing_order(core, pipeline)
    pipeline.verdicts = ["ok", "spaghetti", "spaghetti"]
    clock = Clock()

    async def scenario():
        monitor = PrinterMonitor(core, clock=clock)
        await monitor.tick()                # check at t=1000: ok
        clock.t += 60
        await monitor.tick()                # 60 s later: no check due
        clock.t += 91
        await monitor.tick()                # t=1151: spaghetti (1 in a row)
        assert ("pause",) not in pipeline.printer.calls
        clock.t += 151
        await monitor.tick()                # t=1302: spaghetti (2 in a row) -> pause
        await core.drain()

    asyncio.run(scenario())
    assert ("pause",) in pipeline.printer.calls
    paused = core.db.list_events(order["id"], "print_paused")
    assert len(paused) == 1 and "spaghetti" in paused[0]["payload"]["reason"]
    checks = core.db.list_events(order["id"], "snapshot_check")
    assert [c["payload"]["verdict"] for c in checks] == ["ok", "spaghetti", "spaghetti"]
    prod = [r for r in hermes.runs if r["profile"] == "production"]
    assert len(prod) == 1 and "print_failure_suspected" in prod[0]["body"]["input"]
    assert (core.settings.order_dir(order["id"]) / "camera.jpg").read_bytes().startswith(b"\xff\xd8")


def test_one_bad_snapshot_does_not_pause(core, pipeline, hermes):
    _printing_order(core, pipeline)
    pipeline.verdicts = ["spaghetti", "ok", "spaghetti"]
    clock = Clock()

    async def scenario():
        monitor = PrinterMonitor(core, clock=clock)
        for _ in range(3):
            await monitor.tick()
            clock.t += 151

    asyncio.run(scenario())
    assert ("pause",) not in pipeline.printer.calls
