"""Regression coverage for transaction-level paper-trade/account settlement."""
from __future__ import annotations

import pytest

from db import DatabaseManager


def _database(tmp_path):
    database = DatabaseManager(str(tmp_path / "atomic-trades.db"))
    database.load_accounts(["nifty"], {"nifty": 100_000}, "2026-11-26")
    return database


def _trade(trade_id="trade-1", *, risk=2_000):
    return {
        "id": trade_id, "status": "OPEN", "account": "nifty",
        "symbol": "^NSEI", "planned_risk": risk, "entry": 100,
        "sl": 98, "tp": 104,
    }


def test_open_trade_and_account_reservation_are_one_transaction(tmp_path):
    db = _database(tmp_path)
    trade = _trade()
    outcome, account = db.open_trade_and_update_account(
        trade["id"], trade, "2026-11-26T10:00:00+05:30",
        account_name="nifty", planned_risk=2_000,
        reset_date="2026-11-26", daily_trade_limit=5,
        max_daily_planned_risk=10_000,
    )
    assert outcome == "CREATED"
    assert account["trades_today"] == 1
    assert account["planned_risk_used"] == 2_000
    assert db.load_trades("OPEN")[0]["id"] == trade["id"]


def test_open_trade_reservation_respects_database_limits(tmp_path):
    db = _database(tmp_path)
    db.save_account("nifty", balance=100_000, trades_today=5,
                    planned_risk_used=10_000, reset_date="2026-11-26")
    outcome, account = db.open_trade_and_update_account(
        "over-limit", _trade("over-limit"), "2026-11-26T10:00:00+05:30",
        account_name="nifty", planned_risk=2_000,
        reset_date="2026-11-26", daily_trade_limit=5,
        max_daily_planned_risk=10_000,
    )
    assert outcome == "LIMIT"
    assert account is None
    assert db.load_trades("OPEN") == []
    current = db.load_accounts(["nifty"], {"nifty": 100_000}, "2026-11-26")["nifty"]
    assert current["trades_today"] == 5
    assert current["planned_risk_used"] == 10_000


def test_close_trade_and_account_settlement_happen_once(tmp_path):
    db = _database(tmp_path)
    trade = _trade()
    db.open_trade_and_update_account(
        trade["id"], trade, "2026-11-26T10:00:00+05:30",
        account_name="nifty", planned_risk=2_000,
        reset_date="2026-11-26", daily_trade_limit=5,
        max_daily_planned_risk=10_000,
    )
    closed = {**trade, "status": "CLOSED", "pnl": 4_000}
    first, account = db.close_trade_and_settle_account(
        trade["id"], closed, "2026-11-26T10:30:00+05:30",
        account_name="nifty", pnl=4_000, planned_risk=2_000,
        reset_date="2026-11-26",
    )
    second, second_account = db.close_trade_and_settle_account(
        trade["id"], closed, "2026-11-26T10:31:00+05:30",
        account_name="nifty", pnl=4_000, planned_risk=2_000,
        reset_date="2026-11-26",
    )
    assert first is True
    assert second is False
    assert account["balance"] == 104_000
    assert account["planned_risk_used"] == 0
    assert second_account is None
    assert db.load_trades("OPEN") == []
    saved = db.load_trades("CLOSED")
    assert len(saved) == 1
    assert saved[0]["pnl"] == 4_000


def test_failed_account_settlement_rolls_trade_status_back(tmp_path):
    db = _database(tmp_path)
    trade = _trade()
    db.open_trade_and_update_account(
        trade["id"], trade, "2026-11-26T10:00:00+05:30",
        account_name="nifty", planned_risk=2_000,
        reset_date="2026-11-26", daily_trade_limit=5,
        max_daily_planned_risk=10_000,
    )
    with db._connect() as connection:
        connection.execute("""CREATE TRIGGER reject_account_settlement
            BEFORE UPDATE OF balance ON accounts
            BEGIN SELECT RAISE(ABORT, 'injected account write failure'); END""")
    with pytest.raises(Exception):
        db.close_trade_and_settle_account(
            trade["id"], {**trade, "status": "CLOSED", "pnl": 4_000},
            "2026-11-26T10:30:00+05:30", account_name="nifty",
            pnl=4_000, planned_risk=2_000, reset_date="2026-11-26",
        )
    assert len(db.load_trades("OPEN")) == 1
    account = db.load_accounts(["nifty"], {"nifty": 100_000}, "2026-11-26")["nifty"]
    assert account["balance"] == 100_000
    assert account["planned_risk_used"] == 2_000


def test_closing_previous_day_trade_does_not_reduce_new_day_risk(tmp_path):
    db = _database(tmp_path)
    trade = _trade()
    db.open_trade_and_update_account(
        trade["id"], trade, "2026-11-26T10:00:00+05:30",
        account_name="nifty", planned_risk=2_000,
        reset_date="2026-11-26", daily_trade_limit=5,
        max_daily_planned_risk=10_000,
    )
    # A new-day trade has already consumed today's risk budget.
    db.save_account("nifty", balance=100_000, trades_today=1,
                    planned_risk_used=2_000, reset_date="2026-11-27")
    closed, account = db.close_trade_and_settle_account(
        trade["id"], {**trade, "status": "CLOSED", "pnl": 4_000},
        "2026-11-27T10:30:00+05:30", account_name="nifty",
        pnl=4_000, planned_risk=2_000, reset_date="2026-11-27",
        reservation_date="2026-11-26",
    )
    assert closed is True
    assert account["balance"] == 104_000
    assert account["trades_today"] == 1
    assert account["planned_risk_used"] == 2_000
