-- Durable Telegram update acknowledgement and replay protection.
-- Existing migrations are immutable; this is additive for already-provisioned projects.
CREATE TABLE IF NOT EXISTS multibot.telegram_updates (
    update_id BIGINT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'COMPLETED')),
    received_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS multibot.telegram_poll_state (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    next_offset BIGINT NOT NULL,
    updated_at TEXT NOT NULL
);
ALTER TABLE multibot.telegram_updates ENABLE ROW LEVEL SECURITY;
ALTER TABLE multibot.telegram_poll_state ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON ALL TABLES IN SCHEMA multibot FROM PUBLIC, anon, authenticated;
