"""Engulf 66 SMA 5min strategy for NIFTY and BANKNIFTY."""
from __future__ import annotations

import pandas as pd

from config import NIFTY_SYMBOLS
from strategies.base import StrategyManifest
from strategies.engulfing_66_sma.strategy import Engulfing66SMA


class Engulfing66SMA5m(Engulfing66SMA):
    """Closed-candle 5m engulfing entries around a 66-period SMA on NSE indices."""

    _timeframe_label = "5M"
    _candle_delta = pd.Timedelta(minutes=5)

    manifest = StrategyManifest(
        id="engulfing_66_sma_5m",
        name="Engulf 66 SMA 5min",
        version="1.0.0",
        description=(
            "5-minute bullish/bearish engulfing entries near a 66 SMA on "
            "NIFTY 50 and BANK NIFTY with ATR body, slope, confirmation and cooldown filters."
        ),
        assets=NIFTY_SYMBOLS,
        timeframes=("5m",),
        schedule="completed_candle",
        account="nifty_5m",
        capabilities=("signal", "fixed_sl", "fixed_tp", "backtest"),
        parameters={
            **Engulfing66SMA.manifest.parameters,
            "timeframe": {
                "type": "select",
                "options": ["5m"],
                "default": "5m",
                "editable": False,
            },
            "max_trades_per_asset": {"type": "integer", "min": 1, "max": 100, "default": 10},
        },
    )

    def data_request(self, symbol: str, *, period: str = "5d") -> tuple[str, str]:
        return "5m", period if period in {"5d", "1mo", "30d", "60d"} else "5d"


def create_strategy() -> Engulfing66SMA5m:
    return Engulfing66SMA5m()
