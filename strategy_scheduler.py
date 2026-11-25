"""Manifest scheduler with event-aligned wakeups for live strategies."""
from __future__ import annotations

import pandas as pd

from config import (
    BTC_SWEEP_HOURS_IST,
    GOLD_SWEEP_HOURS_IST,
    FOREX_SWEEP_HOURS_IST,
    NSE_INDEX_SWEEP_HOURS_IST,
    SWEEP_MINUTE_GLOBAL,
    SWEEP_MINUTE_NSE,
    IST_TIMEZONE,
)

SCHEDULES = {
    "canonical_sweep_schedule": {"type": "canonical_sweep"},
    "daily_completed_candle": {"type": "interval", "seconds": 86400},
}


def _timeframe_seconds(timeframe: str) -> int:
    """Convert a manifest timeframe into seconds for generic polling."""
    value = str(timeframe or "").strip().lower()
    if not value:
        raise ValueError("Completed-candle schedule requires a timeframe")
    units = {"m": 60, "h": 3600, "d": 86400, "w": 7 * 86400}
    try:
        amount = int(value[:-1])
        multiplier = units[value[-1]]
    except (KeyError, ValueError):
        raise ValueError(f"Unsupported strategy timeframe: {timeframe!r}") from None
    if amount <= 0:
        raise ValueError(f"Invalid strategy timeframe: {timeframe!r}")
    return amount * multiplier


def _canonical_events(start: pd.Timestamp, end: pd.Timestamp):
    """Yield configured completed Sweep candle times in the IST timezone.

    Global 4H assets (including 24/7 BTC) use their configured start hours
    plus four hours. NSE indices close on the following hour; NSE stocks use
    the configured 4H and 2H session closes. Events are generated from config,
    not from a fixed polling interval.
    """
    start = pd.Timestamp(start).tz_convert(IST_TIMEZONE)
    end = pd.Timestamp(end).tz_convert(IST_TIMEZONE)
    first_day = start.normalize() - pd.Timedelta(days=1)
    last_day = end.normalize() + pd.Timedelta(days=1)

    global_end_hours = {
        (hour + 4) % 24
        for hours in (BTC_SWEEP_HOURS_IST, GOLD_SWEEP_HOURS_IST, FOREX_SWEEP_HOURS_IST)
        for hour in hours
    }
    nse_index_end_hours = {(hour + 1) % 24 for hour in NSE_INDEX_SWEEP_HOURS_IST}

    day = first_day
    while day <= last_day:
        # BTC is 24/7, so global events remain active every calendar day.
        for hour in sorted(global_end_hours):
            event = day + pd.Timedelta(hours=hour, minutes=SWEEP_MINUTE_GLOBAL)
            if start < event <= end:
                yield event

        # NSE schedules are weekdays only. Exchange holidays are still
        # rejected by the market-session gate before any trading decision.
        if day.weekday() < 5:
            for hour in sorted(nse_index_end_hours | {13, 15}):
                event = day + pd.Timedelta(hours=hour, minutes=SWEEP_MINUTE_NSE)
                if start < event <= end:
                    yield event
        day += pd.Timedelta(days=1)


class StrategyScheduler:
    def __init__(self):
        self._last = {}

    def interval_seconds(self, strategy):
        schedule = strategy.manifest.schedule
        if isinstance(schedule, dict):
            if schedule.get("type") != "interval":
                raise ValueError(f"Unsupported schedule type for {strategy.manifest.id}: {schedule!r}")
            seconds = int(schedule.get("seconds", 0))
        elif str(schedule) == "completed_candle":
            timeframes = tuple(strategy.manifest.timeframes or ())
            if len(timeframes) != 1:
                raise ValueError(
                    f"Strategy {strategy.manifest.id} uses completed_candle and must declare exactly one timeframe"
                )
            seconds = _timeframe_seconds(timeframes[0])
        else:
            spec = SCHEDULES.get(str(schedule))
            if spec is None:
                raise ValueError(
                    f"Strategy {strategy.manifest.id} uses unknown schedule {schedule!r}; "
                    "add it to SCHEDULES or use {'type':'interval','seconds':N}."
                )
            if spec["type"] == "canonical_sweep":
                # Retain the legacy nominal interval for callers that display
                # schedule metadata; scanner_loop uses seconds_until_next_due.
                return 60
            seconds = int(spec["seconds"])
        if seconds <= 0:
            raise ValueError(f"Invalid schedule interval for {strategy.manifest.id}")
        return seconds

    def is_due(self, strategy, now):
        key = strategy.manifest.id
        current = pd.Timestamp(now)
        if current.tzinfo is None:
            raise ValueError("Scheduler timestamps must be timezone-aware")
        current = current.tz_convert(IST_TIMEZONE)
        schedule = strategy.manifest.schedule
        is_canonical = (
            not isinstance(schedule, dict)
            and str(schedule) in SCHEDULES
            and SCHEDULES[str(schedule)]["type"] == "canonical_sweep"
        )
        last = self._last.get(key)
        if last is None:
            self._last[key] = current
            return True
        if is_canonical:
            due_events = sorted(_canonical_events(last, current))
            if not due_events:
                return False
            self._last[key] = due_events[-1]
            return True
        if (current - last).total_seconds() >= self.interval_seconds(strategy):
            self._last[key] = current
            return True
        return False

    def seconds_until_next_due(self, strategy, now):
        """Seconds until this strategy's next eligible scan; never busy-poll."""
        current = pd.Timestamp(now)
        if current.tzinfo is None:
            raise ValueError("Scheduler timestamps must be timezone-aware")
        current = current.tz_convert(IST_TIMEZONE)
        key = strategy.manifest.id
        last = self._last.get(key)
        if last is None:
            return 0.0
        schedule = strategy.manifest.schedule
        is_canonical = (
            not isinstance(schedule, dict)
            and str(schedule) in SCHEDULES
            and SCHEDULES[str(schedule)]["type"] == "canonical_sweep"
        )
        if is_canonical:
            # If a configured event elapsed while the previous scan was
            # running, return immediately so is_due() can consume it.
            overdue = sorted(_canonical_events(last, current))
            if overdue:
                return 0.0
            horizon = current + pd.Timedelta(days=8)
            next_events = sorted(_canonical_events(current, horizon))
            return max(0.0, (next_events[0] - current).total_seconds()) if next_events else 3600.0
        return max(0.0, self.interval_seconds(strategy) - (current - last).total_seconds())
