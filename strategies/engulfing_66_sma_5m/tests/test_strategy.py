from __future__ import annotations

import pandas as pd

from config import IST_TIMEZONE, NIFTY_SYMBOLS, resolve_account, LIVE_ASSET_MAP
from db import DatabaseManager
from strategies.engulfing_66_sma_5m import create_strategy
from strategy_service import StrategyService
from strategies.registry import discover_strategies


def test_engulfing_66_sma_5m_contract_and_routing():
    st = create_strategy()
    assert st.manifest.id == "engulfing_66_sma_5m"
    assert st.manifest.name == "Engulf 66 SMA 5min"
    assert st.manifest.assets == NIFTY_SYMBOLS
    assert st.manifest.timeframes == ("5m",)
    assert st.manifest.account == "nifty_5m"
    assert st.data_request("^NSEI") == ("5m", "5d")
    assert st.manifest.parameters["max_trades_per_asset"]["default"] == 10
    now = pd.Timestamp("2026-11-28T10:00:00+05:30")
    assert resolve_account("engulfing_66_sma_5m", LIVE_ASSET_MAP["^NSEI"], now, "nifty_5m") == "nifty_5m"
    assert resolve_account("engulfing_66_sma_5m", LIVE_ASSET_MAP["^NSEBANK"], now, "nifty_5m") == "nifty_5m"


def test_5m_drops_forming_candle_before_close():
    st = create_strategy()
    idx = pd.date_range("2026-11-28 09:15", periods=4, freq="5min", tz=IST_TIMEZONE)
    frame = pd.DataFrame(
        {"open": [100, 101, 102, 103], "high": [102, 103, 104, 105], "low": [99, 100, 101, 102], "close": [101, 102, 103, 104]},
        index=idx,
    )
    # At 09:32 IST, the 09:30 candle (idx[-1]) has not closed (closes at 09:35).
    prepared = st.prepare_candles("^NSEI", frame, now=pd.Timestamp("2026-11-28 09:32:00+05:30"))
    assert len(prepared) == 3
    assert prepared.index[-1] == idx[2]


def test_per_asset_daily_trade_cap_blocks_11th_trade_but_records_signal(tmp_path):
    db = DatabaseManager(str(tmp_path / "cap.db"))
    today = pd.Timestamp("2026-11-28 10:00:00+05:30")
    for i in range(10):
        db.open_trade_and_update_account(
            f"t_{i}", {"id": f"t_{i}", "symbol": "^NSEI", "account": "nifty_5m", "opened_at": today.isoformat()},
            today.isoformat(), account_name="nifty_5m", planned_risk=2000.0,
            reset_date=today.date().isoformat(), daily_trade_limit=20, max_daily_planned_risk=40000.0,
        )
    assert db.count_trades_today("nifty_5m", "^NSEI", today.date().isoformat()) == 10
    assert db.count_trades_today("nifty_5m", "^NSEBANK", today.date().isoformat()) == 0
    service = StrategyService(registry=discover_strategies(), database=db)
    sig = create_strategy().generate_signal("^NSEI", pd.DataFrame(), now=today)
    # Build a directional signal manually to verify dispatch cap
    from strategies.base import Signal
    directional = Signal("Engulf 66 SMA 5min", "1.0.0", "^NSEI", "BUY", today - pd.Timedelta(minutes=5), "5M", "BULLISH_ENGULFING_AT_66_SMA", 24000.0, 23950.0, 24100.0)
    res = service.dispatch("engulfing_66_sma_5m", "^NSEI", directional, current_price=24000.0, now=today, send=False)
    assert res.reason == "ASSET_DAILY_LIMIT"
    assert res.signal_id is not None
