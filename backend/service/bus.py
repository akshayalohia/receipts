"""In-process event bus shared by the SSE stream, the MCP tools and the printer monitor.

publish() is thread-safe: each subscriber owns an asyncio.Queue on its own loop and
items are handed over with call_soon_threadsafe.
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BusEvent:
    order_id: str | None
    type: str
    data: dict = field(default_factory=dict)


class Subscription:
    def __init__(self, bus: "EventBus", order_id: str | None, loop: asyncio.AbstractEventLoop):
        self._bus = bus
        self.order_id = order_id
        self.loop = loop
        self.queue: asyncio.Queue[BusEvent] = asyncio.Queue()

    def wants(self, event: BusEvent) -> bool:
        return self.order_id is None or event.order_id == self.order_id

    async def get(self, timeout: float | None = None) -> BusEvent | None:
        try:
            return await asyncio.wait_for(self.queue.get(), timeout)
        except asyncio.TimeoutError:
            return None

    def close(self) -> None:
        self._bus._remove(self)


class EventBus:
    def __init__(self) -> None:
        self._subs: list[Subscription] = []
        self._lock = threading.Lock()

    def subscribe(self, order_id: str | None = None) -> Subscription:
        sub = Subscription(self, order_id, asyncio.get_running_loop())
        with self._lock:
            self._subs.append(sub)
        return sub

    def _remove(self, sub: Subscription) -> None:
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)

    def publish(self, order_id: str | None, type_: str, data: dict[str, Any]) -> None:
        event = BusEvent(order_id, type_, data)
        with self._lock:
            subs = [s for s in self._subs if s.wants(event)]
        for sub in subs:
            if sub.loop.is_closed():
                self._remove(sub)
                continue
            sub.loop.call_soon_threadsafe(sub.queue.put_nowait, event)
