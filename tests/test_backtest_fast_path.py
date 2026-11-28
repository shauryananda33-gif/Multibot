import numpy as np
import pandas as pd
import pytest

from strategies.adaptive_trend import AdaptiveTrendMomentum
from strategies.engulfing_66_sma import Engulfing66SMA


def _ohlc(periods, freq, start, *, seed=7):
    rng = np.random.default_rng(seed)
    index = pd.date_range(start, periods=periods, freq=freq, tz="Asia/Kolkata")
    close = 100 + np.cumsum(rng.normal(0.15, 1.2, periods))
    open_ = close + rng.normal(0, 0.5, periods)
    high = np.maximum(open_, close) + rng.uniform(0.1, 1.5, periods)
    low = np.minimum(open_, close) - rng.uniform(0.1, 1.5, periods)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=index)


@pytest.mark.parametrize(
    "strategy,symbol,frame",
    [
        (AdaptiveTrendMomentum(), "BTC-USD", _ohlc(260, "D", "2024-01-01")),
        (Engulfing66SMA(), "EURUSD=X", _ohlc(260, "h", "2024-01-01")),
    ],
)
def test_batch_backtest_signals_match_reference_prefix_evaluation(strategy, symbol, frame):
    """The fast path must be byte-for-byte equivalent to the old per-prefix path."""
    optimized = strategy.backtest_signals(symbol, frame)
    assert optimized is not None
    assert len(optimized) == len(frame)
    for i, now in enumerate(frame.index):
        reference = strategy.backtest_signal(symbol, frame.iloc[: i + 1], now=now)
        assert optimized[i] == reference
