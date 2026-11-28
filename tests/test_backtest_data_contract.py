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


def test_read_only_backtest_does_not_require_runtime_leader(monkeypatch):
    from types import SimpleNamespace
    import main

    class Strategy:
        manifest = SimpleNamespace(id="engulfing_66_sma_5m", assets=("^NSEI",), account="nifty_5m")

        def data_request(self, symbol, *, period):
            return "5m", period

    class Registry:
        def get(self, key):
            assert key == "engulfing_66_sma_5m"
            return Strategy()

    metrics = SimpleNamespace(
        return_pct=0.0, max_drawdown_pct=0.0, sharpe=0.0, sortino=0.0,
        win_rate_pct=0.0, profit_factor=0.0, number_of_trades=0,
        average_trade=0.0, max_losing_streak=0, exposure_pct=0.0,
        risk_adjusted_performance=0.0, rating=0.0, rating_label="—", breakdown={},
    )
    result = SimpleNamespace(
        strategy="Engulf 66 SMA 5min", strategy_version="1.0.0", metrics=metrics,
        parameters={}, signals=[], trades=[], starting_account=100000.0,
    )
    frame = _ohlc(100, "5min", "2026-01-01")
    provenance = {"source": "test_cache", "age_seconds": 0.0}
    engine = SimpleNamespace(fetch=lambda *args, **kwargs: (kwargs["provenance"].update(provenance) or frame))
    monkeypatch.setattr(main, "_require_runtime_leader", lambda: pytest.fail("read-only backtest must not require the trading leader"))
    monkeypatch.setattr(main, "ensure_runtime", lambda: None)
    monkeypatch.setattr(main, "REGISTRY", Registry())
    monkeypatch.setattr(main, "SERVICE", SimpleNamespace(engine=engine))
    monkeypatch.setattr(main, "LIVE_ASSET_MAP", {"^NSEI": SimpleNamespace(label="NIFTY 50")})
    monkeypatch.setattr(main, "resolve_account", lambda *args, **kwargs: "nifty_5m")
    monkeypatch.setattr(main, "backtest_strategy", lambda *args, **kwargs: result)

    payload = main._backtest_payload("engulfing_66_sma_5m", "^NSEI", "5d")

    assert payload["ok"] is True
    assert payload["period"] == "5d"
    assert payload["data_interval"] == "5m"
    assert payload["candle_count"] == 100
