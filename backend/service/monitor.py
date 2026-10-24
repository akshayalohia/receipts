"""Printer monitor (SPEC: "Printer monitor (background task in service)").

While the printer is busy: poll status every 5 s and emit `printer` events; every 150 s
run check_snapshot; two bad verdicts in a row -> pause + event + production run.
On FINISH -> order `done`, bed_clear human task, customer notice, production run.
"""
from __future__ import annotations

import asyncio
import logging
import time

from .core import Core

log = logging.getLogger("factory.monitor")
BAD_VERDICTS = {"spaghetti", "detached", "empty_bed"}


class PrinterMonitor:
    def __init__(self, core: Core, clock=time.monotonic) -> None:
        self.core = core
        self.clock = clock
        self.bad_streak = 0
        self.last_snapshot_at: float | None = None
        self.last_state: str | None = None
        self.paused_for_failure = False

    async def run(self) -> None:
        while True:
            try:
                if self.core.db.get_state("printer_busy"):
                    await self.tick()
            except Exception:  # keep monitoring through transient printer/vision errors
                log.exception("printer monitor tick failed")
            await asyncio.sleep(self.core.settings.printer_poll_s)

    async def tick(self) -> None:
        core = self.core
        status = await asyncio.to_thread(lambda: core.pipeline.get_printer().status())
        order = core._printing_order()
        oid = order["id"] if order else None
        core.emit(oid, "system", "printer",
                  {"state": status.state, "progress_pct": status.progress_pct,
                   "remaining_min": status.remaining_min},
                  persist=status.state != self.last_state)
        self.last_state = status.state

        if status.state == "FINISH":
            await self._finished(order)
        elif status.state == "FAILED":
            await self._failed(order)
        elif status.state == "RUNNING":
            await self._maybe_check_snapshot(order)

    async def _maybe_check_snapshot(self, order: dict | None) -> None:
        now = self.clock()
        if self.last_snapshot_at is not None and now - self.last_snapshot_at < self.core.settings.snapshot_every_s:
            return
        self.last_snapshot_at = now
        core = self.core
        jpeg = await asyncio.to_thread(lambda: core.pipeline.get_printer().snapshot_jpeg())
        core.save_snapshot(jpeg)
        verdict = await asyncio.to_thread(core.pipeline.check_snapshot, jpeg)
        oid = order["id"] if order else None
        core.db.add_event(oid, "system", "snapshot_check", verdict)
        if verdict.get("verdict") in BAD_VERDICTS:
            self.bad_streak += 1
        else:
            self.bad_streak = 0
        if self.bad_streak >= 2 and not self.paused_for_failure:
            await asyncio.to_thread(core.pause_print, f"failure check: {verdict.get('verdict')} twice in a row",
                                    "system")
            self.paused_for_failure = True
            self.bad_streak = 0
            core.spawn(core.wake("production", "print_failure_suspected", oid))

    def _reset_job(self) -> None:
        self.bad_streak = 0
        self.last_snapshot_at = None
        self.paused_for_failure = False

    async def _finished(self, order: dict | None) -> None:
        core = self.core
        core.db.set_state("printer_busy", False)
        self._reset_job()
        if order is None:
            return
        core.set_status(order["id"], "done", "system")
        core.request_human("bed_clear", f"Print for {order['id']} finished: remove the part and clear the bed.",
                           order["id"], "system")
        core.add_message(order["id"], "agent", "Your print is finished and ready for pickup.")
        core.spawn(core.wake("production", "print_finished", order["id"]))

    async def _failed(self, order: dict | None) -> None:
        core = self.core
        core.db.set_state("printer_busy", False)
        self._reset_job()
        if order is None:
            return
        core.set_status(order["id"], "failed", "system")
        core.request_human("bed_clear", f"Print for {order['id']} failed: clear the bed and check the printer.",
                           order["id"], "system")
        core.spawn(core.wake("production", "print_failed", order["id"]))
