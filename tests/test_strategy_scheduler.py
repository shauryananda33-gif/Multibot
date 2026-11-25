import pandas as pd
import pytest

from strategy_scheduler import StrategyScheduler
from strategies.base import StrategyManifest


class StubStrategy:
    def __init__(self, schedule, timeframes):
        self.manifest = StrategyManifest(
            id="stub",
            name="Stub",
            version="1.0.0",
            description="",
            assets=("BTC-USD",),
            timeframes=timeframes,
            schedule=schedule,
            parameters={},
        )


def test_completed_candle_uses_declared_timeframe():
    scheduler = StrategyScheduler()
    assert scheduler.interval_seconds(StubStrategy("completed_candle", ("1h",))) == 3600
    assert scheduler.interval_seconds(StubStrategy("completed_candle", ("1d",))) == 86400


def test_completed_candle_requires_one_timeframe():
    with pytest.raises(ValueError, match="exactly one timeframe"):
        StrategyScheduler().interval_seconds(
            StubStrategy("completed_candle", ("1h", "4h"))
        )


def test_completed_candle_rejects_invalid_timeframe():
    with pytest.raises(ValueError, match="Unsupported strategy timeframe"):
        StrategyScheduler().interval_seconds(StubStrategy("completed_candle", ("bad",)))


def test_canonical_sweep_waits_for_configured_completed_candle_event():
    scheduler = StrategyScheduler()
    strategy = StubStrategy("canonical_sweep_schedule", ("1h", "4h"))
    start = pd.Timestamp("2026-11-25T10:00:00+05:30")
    assert scheduler.is_due(strategy, start) is True
    assert scheduler.seconds_until_next_due(strategy, start) == 15 * 60
    assert scheduler.is_due(strategy, start + pd.Timedelta(minutes=14)) is False
    due = start + pd.Timedelta(minutes=15)
    assert scheduler.is_due(strategy, due) is True
    assert scheduler.is_due(strategy, due + pd.Timedelta(seconds=30)) is False


def test_canonical_sweep_keeps_global_schedule_active_on_weekends():
    scheduler = StrategyScheduler()
    strategy = StubStrategy("canonical_sweep_schedule", ("1h", "4h"))
    start = pd.Timestamp("2026-11-28T00:00:00+05:30")  # Saturday
    assert scheduler.is_due(strategy, start) is True
    assert scheduler.seconds_until_next_due(strategy, start) == 5 * 60 + 30 * 60
