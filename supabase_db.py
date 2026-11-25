"""Supabase Postgres persistence with SQLite retained for local development.

Production uses a private PostgreSQL schema through Supabase's session pooler.
Local development continues to use the established SQLite implementation.
"""
from __future__ import annotations

import os
import re
import time
import threading

from db import DatabaseManager as _SQLiteDatabaseManager
from db import DatabaseError

SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL", "").strip()


def _translate_sql(sql: str) -> str:
    """Translate the small SQLite dialect surface used by the inherited DB API."""
    statement = str(sql).strip()
    match = re.match(
        r"^INSERT\s+OR\s+(IGNORE|REPLACE)\s+INTO\s+([A-Za-z_][A-Za-z0-9_.]*)"
        r"(\s*\([^)]*\))?\s*(.*)$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        mode, table, column_clause, remainder = match.groups()
        if mode.upper() == "IGNORE":
            statement = f"INSERT INTO {table}{column_clause or ''} {remainder} ON CONFLICT DO NOTHING"
        else:
            if not column_clause:
                raise DatabaseError("PostgreSQL INSERT OR REPLACE requires an explicit column list")
            columns = [item.strip().strip('"') for item in column_clause.strip()[1:-1].split(",")]
            if not columns:
                raise DatabaseError("PostgreSQL INSERT OR REPLACE has no columns")
            key = columns[0]
            updates = columns[1:]
            if updates:
                action = ", ".join(f'"{column}" = EXCLUDED."{column}"' for column in updates)
                conflict = f'ON CONFLICT ("{key}") DO UPDATE SET {action}'
            else:
                conflict = f'ON CONFLICT ("{key}") DO NOTHING'
            statement = f"INSERT INTO {table}{column_clause} {remainder} {conflict}"

    statement = re.sub(
        r"json_extract\(\s*payload\s*,\s*'\$\.account'\s*\)",
        "(payload::jsonb ->> 'account')",
        statement,
        flags=re.IGNORECASE,
    )
    return re.sub(r"(?<!%)\?", "%s", statement)


class _PostgresConnection:
    """Connection context with sqlite-like execute() and deterministic close."""

    def __init__(self, connection):
        self._connection = connection

    def execute(self, sql, parameters=()):
        try:
            return self._connection.execute(_translate_sql(sql), tuple(parameters or ()))
        except Exception as exc:
            raise DatabaseError(f"Supabase Postgres query failed: {exc}") from exc

    def executemany(self, sql, seq_of_parameters):
        try:
            cursor = self._connection.cursor()
            cursor.executemany(_translate_sql(sql), seq_of_parameters)
            return cursor
        except Exception as exc:
            raise DatabaseError(f"Supabase Postgres batch query failed: {exc}") from exc

    def commit(self):
        try:
            self._connection.commit()
        except Exception as exc:
            raise DatabaseError(f"Supabase Postgres commit failed: {exc}") from exc

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            self.commit() if exc_type is None else self.rollback()
        finally:
            self.close()
        return False


class DatabaseManager(_SQLiteDatabaseManager):
    """Use Supabase Postgres in Render and SQLite for local development."""

    _TRANSIENT_POSTGRES_MARKERS = (
        "connection reset", "connection closed", "server closed the connection",
        "connection is closed", "broken pipe", "timed out", "timeout",
        "temporarily unavailable", "could not translate host name",
        "name or service not known", "network is unreachable", "connection refused",
        "ssl syscall", "too many connections", "database system is starting up",
        "deadlock detected", "could not serialize access",
    )

    def __init__(self, path=None):
        self.path = path or os.getenv("BOT_STATE_DB_PATH", "/tmp/workspace/multibot2_state.db")
        self.supabase_enabled = bool(SUPABASE_DB_URL)
        self.turso_enabled = self.supabase_enabled  # legacy flag: shared durable DB is enabled
        self._health_check_lock = threading.Lock()
        self._health_check_at = 0.0
        self._health_check_result = None

        if self.supabase_enabled:
            self._initialize()
        elif os.getenv("PORT"):
            # Never silently fall back to Render's ephemeral filesystem.
            self._missing_supabase_configuration = True
        else:
            self._missing_supabase_configuration = False
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            _SQLiteDatabaseManager._initialize(self)

    def _connect(self):
        if not self.supabase_enabled:
            import sqlite3
            connection = sqlite3.connect(self.path, timeout=30)
            connection.row_factory = sqlite3.Row
            return connection
        try:
            import psycopg
            from psycopg.rows import dict_row
            connection = psycopg.connect(
                SUPABASE_DB_URL,
                connect_timeout=10,
                sslmode="require",
                application_name="multibot2",
                options="-c search_path=multibot,public",
                prepare_threshold=None,
                row_factory=dict_row,
            )
            return _PostgresConnection(connection)
        except Exception as exc:
            raise DatabaseError(f"Supabase Postgres connection failed: {exc}") from exc

    def _initialize(self):
        """Fail fast when the versioned Supabase migration has not been applied."""
        expected = set(self._TABLES) | {"multibot_migrations", "runtime_leases"}
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='multibot' AND table_name = ANY(%s)",
                (list(expected),),
            ).fetchall()
        found = {row["table_name"] for row in rows}
        missing = sorted(expected - found)
        if missing:
            raise DatabaseError(
                "Supabase schema is incomplete. Apply the repository migration "
                "supabase/migrations/20261125000000_initial_multibot_schema.sql; "
                f"missing tables: {', '.join(missing)}"
            )

    @classmethod
    def _is_retryable_turso_error(cls, exc):
        message = str(exc).lower()
        return any(marker in message for marker in cls._TRANSIENT_POSTGRES_MARKERS)

    @staticmethod
    def is_transient_database_error(exc):
        message = str(exc).lower()
        return any(marker in message for marker in DatabaseManager._TRANSIENT_POSTGRES_MARKERS)

    def _retry_turso_operation(self, operation, *, operation_name="database operation", attempts=3):
        """Retry only idempotent operations already designated by their callers."""
        attempts = max(1, int(attempts))
        for attempt in range(attempts):
            try:
                return operation()
            except Exception as exc:
                if not self.supabase_enabled or not self._is_retryable_turso_error(exc):
                    raise
                if attempt + 1 >= attempts:
                    raise DatabaseError(
                        f"Supabase Postgres {operation_name} failed after {attempts} attempts: {exc}"
                    ) from exc
                time.sleep(0.2 * (2 ** attempt))

    def market_data_cache_health(self):
        if not self.supabase_enabled:
            return {"enabled": False, "remote": False, "reason": "LOCAL_SQLITE"}
        return super().market_data_cache_health()
