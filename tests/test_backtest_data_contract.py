import numpy as np
import pandas as pd
import pytest

from strategies.engulfing_66_sma import Engulfing66SMA
from strategies.engulfing_66_sma_5m import Engulfing66SMA5m
from yahoo_provider import YahooProvider


def _ohlc(periods, freq, start):
    rng = np.random.default_rng(19)
    index = pd.date_range(start, periods=periods, freq=freq, tz="Asia/Kolkata")
    close = 100 + np.cumsum(rng.normal(0.1, 1.0, periods))
    open_ = close + rng.normal(0, 0.4, periods)
    high = np.maximum(open_, close) + rng.uniform(0.1, 1.0, periods)
    low = np.minimum(open_, close) - rng.uniform(0.1, 1.0, periods)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=index)


@pytest.mark.parametrize("period", ["5d", "1mo", "30d", "60d"])
def test_5m_strategy_preserves_supported_requested_history(period):
    assert Engulfing66SMA5m().data_request("^NSEI", period=period) == ("5m", period)


@pytest.mark.parametrize("period", ["90d", "1y", "2y", "unknown"])
def test_5m_strategy_rejects_unsupported_history_instead_of_silently_using_5d(period):
    with pytest.raises(ValueError, match="5-minute Yahoo backtests support"):
        Engulfing66SMA5m().data_request("^NSEI", period=period)


def test_5m_backtest_signals_report_5m_timeframe():
    strategy = Engulfing66SMA5m()
    signals = strategy.backtest_signals("^NSEI", _ohlc(260, "5min", "2026-01-01"))
    assert signals
    assert {signal.timeframe for signal in signals} == {"5M"}


def test_hourly_engulf_backtest_signals_keep_hourly_timeframe():
    strategy = Engulfing66SMA()
    signals = strategy.backtest_signals("EURUSD=X", _ohlc(260, "1h", "2026-01-01"))
    assert signals
    assert {signal.timeframe for signal in signals} == {"1H"}


def test_yahoo_csv_cache_supports_five_minute_candles():
    assert "5m" in YahooProvider._CSV_INTERVALS
