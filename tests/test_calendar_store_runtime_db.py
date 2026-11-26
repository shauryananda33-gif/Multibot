from calendar_store import CalendarStore
from db import DatabaseManager


def test_calendar_store_uses_injected_runtime_database(tmp_path):
    database = DatabaseManager(str(tmp_path / "shared-runtime.db"))
    store = CalendarStore(database=database)
    assert store.database is database

    first = [{"id": "event-1", "title": "Initial event"}]
    second = [{"id": "event-2", "title": "Updated event"}]
    store.save_week("thisweek", "2026-11-23", first)
    store.save_week("thisweek", "2026-11-23", second)

    cached, fetched_at = store.load_week("thisweek", "2026-11-23")
    assert cached == second
    assert fetched_at


def test_calendar_attempt_upsert_uses_composite_key(tmp_path):
    database = DatabaseManager(str(tmp_path / "calendar-attempts.db"))
    store = CalendarStore(database=database)

    store.save_attempt("thisweek", "2026-11-23", "first failure")
    store.save_attempt("thisweek", "2026-11-23", "latest failure")

    recent = store.load_attempt_recent("thisweek", "2026-11-23", minutes=30)
    assert recent is not None
    assert recent[1] == "latest failure"
