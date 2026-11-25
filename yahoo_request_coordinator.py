"""Process-wide paced, priority-aware admission for Yahoo requests."""
from __future__ import annotations
import heapq
import itertools
import os
import threading
import time
from typing import Callable, TypeVar
T = TypeVar("T")

class YahooRequestCoordinator:
    def __init__(self, *, min_interval_seconds: float = 1.0, queue_timeout_seconds: float = 45.0):
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self.queue_timeout_seconds = max(0.1, float(queue_timeout_seconds))
        self._condition = threading.Condition()
        self._queue: list[tuple[int, int]] = []
        self._sequence = itertools.count()
        self._next_allowed_at = 0.0
        self._in_flight = False

    def run(self, callback: Callable[[], T], *, priority: int = 5) -> T:
        ticket = (int(priority), next(self._sequence))
        deadline = time.monotonic() + self.queue_timeout_seconds
        with self._condition:
            heapq.heappush(self._queue, ticket)
            while True:
                now = time.monotonic()
                if now >= deadline:
                    self._queue.remove(ticket)
                    heapq.heapify(self._queue)
                    self._condition.notify_all()
                    raise TimeoutError("Yahoo request admission queue timed out")
                if not self._in_flight and self._queue and self._queue[0] == ticket:
                    spacing = self._next_allowed_at - now
                    if spacing <= 0:
                        heapq.heappop(self._queue)
                        self._in_flight = True
                        self._next_allowed_at = now + self.min_interval_seconds
                        self._condition.notify_all()
                        break
                    self._condition.wait(timeout=min(spacing, deadline - now))
                else:
                    self._condition.wait(timeout=deadline - now)
        try:
            return callback()
        finally:
            with self._condition:
                self._in_flight = False
                self._condition.notify_all()

GLOBAL_YAHOO_COORDINATOR = YahooRequestCoordinator(
    min_interval_seconds=float(os.getenv("YAHOO_MIN_REQUEST_SPACING_SECONDS", "1.0")),
    queue_timeout_seconds=float(os.getenv("YAHOO_REQUEST_QUEUE_TIMEOUT_SECONDS", "45")),
)
