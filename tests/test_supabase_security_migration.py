from pathlib import Path

def test_private_schema_security_migration_enables_rls_for_all_tables():
    root = Path(__file__).resolve().parents[1]
    path = root / "supabase" / "migrations" / "20261126000000_multibot_security_and_request_coordination.sql"
    source = path.read_text(encoding="utf-8")
    expected = {
        "accounts", "trades", "signals", "signal_events", "deliveries",
        "scan_runs", "scan_error_alerts", "market_data_cache",
        "forex_calendar_week_cache", "forex_calendar_attempts",
        "multibot_migrations", "app_config", "runtime_leases",
    }
    for table in expected:
        assert f"ALTER TABLE multibot.{table} ENABLE ROW LEVEL SECURITY;" in source
    assert "REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM PUBLIC, anon, authenticated;" in source
    assert "CREATE POLICY" not in source
