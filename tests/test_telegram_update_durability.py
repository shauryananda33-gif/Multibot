from db import DatabaseManager


def test_telegram_update_offset_survives_database_recreation(tmp_path):
    path = str(tmp_path / "telegram.db")
    first = DatabaseManager(path)
    assert first.telegram_update_offset() == 0
    assert first.claim_telegram_update(7001, "2026-11-26T10:00:00+05:30")
    first.complete_telegram_update(7001, 7002, "2026-11-26T10:00:01+05:30")

    restarted = DatabaseManager(path)
    assert restarted.telegram_update_offset() == 7002
    assert restarted.claim_telegram_update(7001, "2026-11-26T10:01:00+05:30") is False


def test_incomplete_telegram_update_is_replayed_after_restart(tmp_path):
    path = str(tmp_path / "telegram-pending.db")
    first = DatabaseManager(path)
    assert first.claim_telegram_update(8001, "2026-11-26T10:00:00+05:30")

    restarted = DatabaseManager(path)
    assert restarted.telegram_update_offset() == 0
    assert restarted.claim_telegram_update(8001, "2026-11-26T10:05:00+05:30") is True
    restarted.complete_telegram_update(8001, 8002, "2026-11-26T10:05:01+05:30")
    assert restarted.telegram_update_offset() == 8002


def test_telegram_poll_offset_never_moves_backwards(tmp_path):
    database = DatabaseManager(str(tmp_path / "telegram-monotonic.db"))
    assert database.claim_telegram_update(9001, "2026-11-26T10:00:00+05:30")
    database.complete_telegram_update(9001, 9002, "2026-11-26T10:00:01+05:30")
    assert database.claim_telegram_update(9002, "2026-11-26T10:00:02+05:30")
    database.complete_telegram_update(9002, 9003, "2026-11-26T10:00:03+05:30")
    assert database.telegram_update_offset() == 9003
