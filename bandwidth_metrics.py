"""Low-overhead outbound traffic accounting for Render bandwidth investigations.

Yahoo's yfinance adapter exposes parsed candles rather than raw HTTP bodies, so
its inbound byte figure is explicitly an estimate. urllib adapters record the
actual encoded request body and response body bytes they read. This is
observability only: counters are in-memory and never affect trading decisions.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict

logger = logging.getLogger("multibot2.bandwidth")

_LOG_INTERVAL_SECONDS = 900.0
_lock = threading.Lock()
_totals = defaultdict(lambda: {
    "requests": 0,
    "outbound_bytes": 0,
    "inbound_bytes": 0,
    "estimated_inbound_bytes": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "queue_admissions": 0,
    "queue_timeouts": 0,
    "queue_wait_ms": 0,
})
_window_started = time.monotonic()


def record(
    component: str,
    *,
    outbound_bytes: int = 0,
    inbound_bytes: int = 0,
    estimated_inbound_bytes: int = 0,
    requests: int = 1,
    cache_hits: int = 0,
    cache_misses: int = 0,
    queue_admissions: int = 0,
    queue_timeouts: int = 0,
    queue_wait_ms: int = 0,
) -> None:
    """Record bytes observed at an adapter boundary; never raises to callers."""
    global _window_started
    try:
        values = {
            "requests": max(0, int(requests)),
            "outbound_bytes": max(0, int(outbound_bytes)),
            "inbound_bytes": max(0, int(inbound_bytes)),
            "estimated_inbound_bytes": max(0, int(estimated_inbound_bytes)),
            "cache_hits": max(0, int(cache_hits)),
            "cache_misses": max(0, int(cache_misses)),
            "queue_admissions": max(0, int(queue_admissions)),
            "queue_timeouts": max(0, int(queue_timeouts)),
            "queue_wait_ms": max(0, int(queue_wait_ms)),
        }
        with _lock:
            bucket = _totals[str(component)]
            for key, value in values.items():
                bucket[key] += value
            now = time.monotonic()
            if now - _window_started < _LOG_INTERVAL_SECONDS:
                return
            snapshot = {name: dict(stats) for name, stats in _totals.items()}
            _totals.clear()
            elapsed = max(1.0, now - _window_started)
            _window_started = now
        _log_snapshot(snapshot, elapsed)
    except Exception:
        # Instrumentation must never interrupt scans, monitoring, or alerts.
        logger.debug("Bandwidth metric recording failed", exc_info=True)


def snapshot() -> dict:
    """Return a copy of counters accumulated since process start/window reset."""
    with _lock:
        return {name: dict(stats) for name, stats in _totals.items()}


def flush(*, force: bool = False) -> bool:
    """Write the current window to Render logs; useful for graceful shutdown/tests."""
    global _window_started
    with _lock:
        now = time.monotonic()
        if not force and now - _window_started < _LOG_INTERVAL_SECONDS:
            return False
        if not _totals:
            _window_started = now
            return False
        snapshot_data = {name: dict(stats) for name, stats in _totals.items()}
        _totals.clear()
        elapsed = max(1.0, now - _window_started)
        _window_started = now
    _log_snapshot(snapshot_data, elapsed)
    return True


def _log_snapshot(data: dict, elapsed: float) -> None:
    totals = {
        key: sum(item[key] for item in data.values())
        for key in ("requests", "outbound_bytes", "inbound_bytes", "estimated_inbound_bytes",
                    "cache_hits", "cache_misses", "queue_admissions", "queue_timeouts", "queue_wait_ms")
    }
    logger.info(
        "Bandwidth usage window | duration_seconds=%d requests=%d outbound_bytes=%d "
        "inbound_bytes_observed=%d inbound_bytes_estimated=%d cache_hits=%d cache_misses=%d "
        "queue_admissions=%d queue_timeouts=%d queue_wait_ms=%d components=%s",
        int(elapsed),
        totals["requests"],
        totals["outbound_bytes"],
        totals["inbound_bytes"],
        totals["estimated_inbound_bytes"],
        totals["cache_hits"],
        totals["cache_misses"],
        totals["queue_admissions"],
        totals["queue_timeouts"],
        totals["queue_wait_ms"],
        data,
    )
