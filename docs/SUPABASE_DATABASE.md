# Supabase Postgres setup for MULTIBOT2

MULTIBOT2 uses Supabase Postgres as its durable production database. It does
not use the Supabase REST API key as a database connection and no longer
requires Turso/libSQL.

## 1. Apply the database migration

The versioned schema is in
supabase/migrations/20261125000000_initial_multibot_schema.sql. Apply it to
the Multibot Supabase project before deploying the application. The migration
creates a private multibot schema, all runtime tables, indexes and access
restrictions. It intentionally creates no tables in the exposed public schema.

## 2. Configure Render

Add this secret environment variable to the Multibot web service:

- SUPABASE_DB_URL: Supabase Postgres Session pooler connection string (port
  5432), copied from the project's Connect dialog. Use the session pooler for
  a persistent Render service on IPv4 networks. Replace the password
  placeholder with the database password; do not commit this value.

Keep existing SUPABASE_URL / SUPABASE_KEY only if another feature actually
uses the Supabase Data API. They are not used by this persistence adapter.
Never use a publishable/anon key or service-role API key as the Postgres
password.

The app uses SSL and sets its search path to multibot,public. The database
role in the connection string must own the schema (the standard Supabase
postgres database user does). Do not use transaction-pooler mode for this
long-running worker.

## 3. Local development

Without PORT and without SUPABASE_DB_URL, the project continues using SQLite
at BOT_STATE_DB_PATH (or /tmp/workspace/multibot2_state.db). This is for
local development and tests only. Render sets PORT; if the Supabase
connection is missing, startup fails closed instead of silently using the
ephemeral filesystem.

Install and run:

    pip install -e ".[test]"
    python -m compileall -q .
    pytest
    python main.py

For an integration test against a non-production Supabase development project,
set SUPABASE_DB_URL locally after applying the migration.

## 4. Runtime safety

The existing atomic Postgres lease remains the single-leader guard. Only the
process that owns the unexpired lease may start scanners, trade monitoring,
reminders and Telegram polling. A database outage therefore fails closed for
trading; it must never fall back to per-container SQLite in production.

The migration stores account state, trades, signals, delivery history, scan
history, market-data cache, calendar cache, app configuration and the runtime
lease in the private schema. It does not import historical state from Turso.
The connected Supabase project currently has no existing public app tables or
migration history, so this establishes the initial schema.
