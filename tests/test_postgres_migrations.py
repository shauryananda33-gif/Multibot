"""Disposable PostgreSQL migration and production-adapter integration tests."""
import os
from pathlib import Path

import pytest

URL = os.getenv("MULTIBOT_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not URL, reason="disposable PostgreSQL URL not configured")


def test_versioned_migrations_and_supabase_repository_operations(monkeypatch, tmp_path):
    import psycopg

    root = Path(__file__).resolve().parents[1]
    with psycopg.connect(URL, autocommit=True) as connection:
        # Supabase provides this event-trigger function. The migration only
        # revokes untrusted execution; a stub makes stock PostgreSQL suitable.
        connection.execute("""
            CREATE OR REPLACE FUNCTION public.rls_auto_enable()
            RETURNS event_trigger LANGUAGE plpgsql AS $$
            BEGIN
                NULL;
            END;
            $$
        """)
        for migration in sorted((root / "supabase" / "migrations").glob("*.sql")):
            connection.execute(migration.read_text(encoding="utf-8"))

        tables = {
            row[0] for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='multibot'"
            ).fetchall()
        }
        required = {
            "accounts", "trades", "forex_calendar_week_cache",
            "forex_calendar_attempts", "runtime_leases", "telegram_updates",
            "telegram_poll_state", "multibot_migrations",
        }
        assert required <= tables
        rls = {
            row[0] for row in connection.execute(
                "SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='multibot' AND c.relrowsecurity"
            ).fetchall()
        }
        assert {"telegram_updates", "telegram_poll_state"} <= rls

    import supabase_db
    monkeypatch.setattr(supabase_db, "SUPABASE_DB_URL", URL)
    database = supabase_db.DatabaseManager(str(tmp_path / "unused.db"))
    try:
        accounts = database.load_accounts(["macro"], {"macro": 100000}, "2026-11-26")
        assert accounts["macro"]["balance"] == 100000

        opened, account = database.open_trade_and_update_account(
            "integration-trade-1",
            {"id": "integration-trade-1", "account": "macro", "status": "OPEN"},
            "2026-11-26T10:00:00+05:30",
            account_name="macro", planned_risk=2000, reset_date="2026-11-26",
            daily_trade_limit=20, max_daily_planned_risk=10000,
        )
        assert opened == "CREATED"
        assert account["planned_risk_used"] == 2000

        closed, settled = database.close_trade_and_settle_account(
            "integration-trade-1",
            {"id": "integration-trade-1", "account": "macro", "status": "CLOSED"},
            "2026-11-26T11:00:00+05:30",
            account_name="macro", pnl=250, planned_risk=2000,
            reset_date="2026-11-26", reservation_date="2026-11-26",
        )
        assert closed is True
        assert settled["balance"] == 100250
        assert settled["planned_risk_used"] == 0
        assert database.telegram_update_offset() == 0
        assert database.claim_telegram_update(123456, "2026-11-26T11:00:00+05:30")
        database.complete_telegram_update(123456, 123457, "2026-11-26T11:00:01+05:30")
        assert database.telegram_update_offset() == 123457
    finally:
        database.close()
