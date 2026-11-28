# MULTIBOT2 — Pipeline & System Architecture

> Canonical reference for how data, signals, trades, notifications, persistence, and the dashboard work together in MULTIBOT2.

---

## 1. High-Level Architecture

MULTIBOT2 is a **single-process, multi-threaded Python runtime** (`main.py`) backed by **Supabase Postgres** in production (and local SQLite for development/tests).

### Leader Lease & Workers
To prevent duplicate scans or double Telegram messages during rolling deploys on Render:
1. `main.py` starts the WSGI HTTP server (`web_server`) immediately on `$PORT` so `/ping` and `/dashboard` stay responsive.
2. The main loop attempts to acquire a **Supabase Postgres runtime lease** (`runtime_leases` table, TTL `90s`, heartbeat `30s`, verification cache `15s`).
3. Only the **lease leader** starts the trading workers:
   - `scanner` (`scanner_loop`) — event-aligned strategy scans via `StrategyScheduler`
   - `monitor` (`monitor_loop`) — SL/TP monitoring via `TradeMonitor` (sleeps `120s` when `active_trades == 0`, otherwise `settings.monitor_interval_seconds`)
   - `summaries` (`summary_loop`) — daily/weekly summary delivery (polls every `60s`)
   - `telegram` (`telegram_commands`) — Telegram `getUpdates` command poller
   - `multibot2-reminders` (`ReminderService`) — overdue 1h signal reminder worker (polls every `60s`)

---

## 2. Market Data & CSV Candle Cache Pipeline

Yahoo Finance (`yfinance`) is the locked market-data provider. To minimize upstream rate limits and avoid Supabase egress for candle blobs, `YahooProvider` (`yahoo_provider.py`) uses a **4-tier lookup**:

1. **In-memory TTL cache** (`YF_TTL_BY_INTERVAL`: `1m=45s`, `30m=120s`, `1h=300s`, `4h=300s`, `1d=600s`).
2. **Optional persisted DB cache** (`persist_cache=False` in production runtime so Supabase `market_data_cache` is bypassed).
3. **CSV Baseline + Local Cache** (for `30m`, `1h`, `1d`):
   - Reads from `local_cache_dir` (`/tmp/multibot_candles` or `BOT_CANDLE_CACHE_DIR`) and `csv_dir` (`data/candles/` tracked in GitHub).
   - If the CSV is fresh within interval TTL, returns immediately (`source="csv_cache"`).
   - If stale, **tail-fetches only the delta** (`5d` or `1mo`) from Yahoo Finance, validates overlap (if close differs by `>0.5%`, assumes corporate split and re-downloads full period with stale fallback), merges, and saves to `local_cache_dir`.
   - A GitHub Actions workflow (`.github/workflows/sync-candles.yml`) runs `tools/sync_candle_csvs.py` Mon–Fri at `23:15 UTC` to keep `data/candles/` updated in Git.
4. **Stale Fallback & Backoff**:
   - Rate-limit errors trigger per-symbol and provider-wide exponential backoff (`120s` up to `1800s`), persisted in `app_config` (`yahoo_provider_backoff_v1`).
   - During backoff or transient fetch errors, `YahooProvider` serves `stale_fallback` within interval-bounded grace windows (`YAHOO_STALE_GRACE_BY_INTERVAL`).

---

## 3. Strategy & Signal Lifecycle Pipeline

Every strategy in `strategies/` (`adaptive_trend`, `sweep_v2`, `engulfing_66_sma`) implements the `Strategy` contract (`strategies/base.py`) and is discovered automatically by `strategies/registry.py`.

For each due strategy in `StrategyService.scan_and_dispatch()`:
1. **Market Session Gate (`market_sessions.py`)**: Skips closed markets (NSE `09:15–15:30 IST` weekdays minus `NSE_MARKET_HOLIDAYS`, COMEX Gold, Forex, 24/7 Crypto).
2. **News Gate (`news_gate.py`)**: If `/newspause` is enabled, pauses assets with a High-impact economic event within `±30m` and records `PAUSED_BY_NEWS`.
3. **Fetch & Evaluate (`strategy_engine.py`)**:
   - Fetches candles via `YahooProvider`.
   - `strategy.prepare_candles()` drops incomplete/forming candles and quarantines malformed OHLC rows (`sweep_engine.py` / `market_data.py`).
   - `strategy.generate_signal()` returns a canonical `Signal`.
4. **Persist Signal Event (`signal_lifecycle.py` + `db.py`)**:
   - Every evaluated signal gets a canonical `signal_key` (`strategy|SYMBOL|DIRECTION|timestamp`) and is recorded in `signal_events` before any filtering.
5. **Filter & Gate (`signal_gate.py`)**:
   - Non-directional -> `NON_DIRECTIONAL` (no trade, no Telegram).
   - Age `> 1h` after candle close -> `STALE` + `NOT_SENT_STALE` delivery audit (no Telegram bubble).
   - `signal_count >= 2` -> `DUPLICATE_LIMIT`; `signal_count == 1` -> `REMINDER_PENDING`.
   - Account daily limits reached -> `ACCOUNT_LIMIT`.
   - No valid SL/TP -> `NO_TRADE_PLAN`.
6. **Size & Notify (`trading.py` + `notification_service.py`)**:
   - Computes 1× leverage position size (`quantity_for_risk`) using the routed account (`resolve_account`: `macro`, `nifty`, `ny_session`, `sweep_4h`).
   - Delivers initial alert (`kind="SIGNAL"`) via `NotificationService.deliver()`.
   - Records send state (`send_count=1`, `reminder_due_at = now + 1h`) immediately after Telegram acceptance.
7. **Atomic Paper Trade Reservation (`db.py`)**:
   - `open_trade_and_update_account()` inserts the `OPEN` trade and updates `trades_today` / `planned_risk_used` in one SQL transaction.

---

## 4. Trade Monitor, Reminders & Notifications

- **Trade Monitor (`trade_monitor.py`)**:
  - Fetches `OPEN` trades once per cycle, looks up live `1m` price (`priority=0`), and settles at exact `SL` or `TP` via `close_trade_and_settle_account()` (conditional `WHERE status='OPEN'` prevents double settlement).
  - Sends `TRADE_CLOSED` notification and invalidates dashboard cache.
- **Reminders (`reminders.py`)**:
  - Queries `due_reminders()` (`send_count=1 AND reminder_sent=0 AND reminder_due_at <= now`), sends `kind="REMINDER"`, and marks `reminder_sent=1`.
- **Notification Gate (`notification_service.py`)**:
  - `_should_silence()` applies **only** to `kind == "SIGNAL"` so `REMINDER` and `TRADE_CLOSED` alerts are never silenced by the original signal's `DELIVERED` status.

---

## 5. Dashboard HTTP/WSGI & Bandwidth Design (`main.py` + `dashboard.py`)

- **Snapshot Caching**: `_build_dashboard_payload()` runs a single bundled DB read (`DB.dashboard_reads(..., signal_limit=150, scan_limit=30)`) and caches the snapshot for `180s`, invalidated immediately on scan completion or trade close.
- **Conditional Responses & Compression**:
  - `/api/dashboard` hashes payload **excluding `generated_at`** for `ETag`, returning `304 Not Modified` on unchanged polls.
  - Responses `>= 512` bytes are gzip-compressed when `Accept-Encoding: gzip` is present.
  - Static JS/CSS assets use `Cache-Control: public, max-age=3600`; HTML and `sw.js` use `no-store`.
