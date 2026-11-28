# MULTIBOT2 — Change Log & Session Context Anchor

> **Rule for future sessions:** Always read this file first before starting work so context, architectural decisions, recent fixes, and pending manual steps are never lost. Update this file whenever code, docs, or infrastructure changes are made.

---

## 2026-11-28 (Session 3b) — Live Dashboard & UX/UI Max Audit

### Summary
- Audited live deployment `https://multibot-3hsb.onrender.com/` (desktop `1440×900` + mobile `390×844` + all 3 themes + all Tools settings).
- Saved full report to **[docs/UI_UX_MAX_AUDIT.md](file:///C:/Users/Vivek/.gemini/antigravity/scratch/Multibot/docs/UI_UX_MAX_AUDIT.md)**.
- Key bugs found for next fix pass: `dashboard-live-wiring.js` `₹` prefix on Forex Entry, `app.js`/`dashboard.html` missing `nifty_5m` label & `Engulf 66 SMA 5min` in Locked Rules, `notifications.js` missing `.active` class on event chips & `[REDACTED]` prefill, `Engulfing66SMA5m.data_request()` ignoring `period="30d"` in Backtest, and `Save`/`+ New`/`Reset` UX on read-only public dashboard.

---

## 2026-11-28 (Session 3) — `Engulf 66 SMA 5min` + Dedicated `nifty_5m` Account

### Summary
- Added `engulfing_66_sma_5m` (`Engulf 66 SMA 5min`) for `^NSEI` and `^NSEBANK` on `5m` completed candles (`period="5d"`).
- Added dedicated `nifty_5m` account (`₹100,000` capital, `₹2,000` risk, `1:2` target = `₹4,000`, `daily_trade_limit=20`).
- Added editable per-asset daily trade cap (`max_trades_per_asset=10`): all signals still generate and record in `signal_events`, while trades above 10/asset/day return `ASSET_DAILY_LIMIT`.

### Files Changed & Blast Radius
1. **[strategies/engulfing_66_sma/strategy.py](file:///C:/Users/Vivek/.gemini/antigravity/scratch/Multibot/strategies/engulfing_66_sma/strategy.py)**: Parameterized `_timeframe_label` and `_candle_delta` on `Engulfing66SMA` so `5m` subclasses cleanly without duplicating indicator/signal logic.
2. **[strategies/engulfing_66_sma_5m/strategy.py](file:///C:/Users/Vivek/.gemini/antigravity/scratch/Multibot/strategies/engulfing_66_sma_5m/strategy.py)** & **[\_\_init\_\_.py](file:///C:/Users/Vivek/.gemini/antigravity/scratch/Multibot/strategies/engulfing_66_sma_5m/__init__.py)**: New strategy package; `assets=NIFTY_SYMBOLS`, `timeframes=("5m",)`, `account="nifty_5m"`, `max_trades_per_asset=10`.
3. **[strategies/registry.py](file:///C:/Users/Vivek/.gemini/antigravity/scratch/Multibot/strategies/registry.py)**: Added `"engulfing_66_sma_5m"` to `BUILTIN_STRATEGY_IDS`.
4. **[config.py](file:///C:/Users/Vivek/.gemini/antigravity/scratch/Multibot/config.py)**: Added `"nifty_5m": 20` to `DEFAULT_ACCOUNT_TRADE_LIMITS` & `BUILTIN_ACCOUNT_NAMES`, plus `RoutingRule("nifty_5m", ("engulfing_66_sma_5m",))` at the top of `ACCOUNT_ROUTING`.
5. **[bot_settings.py](file:///C:/Users/Vivek/.gemini/antigravity/scratch/Multibot/bot_settings.py)**: Added `_merge_new_builtins()` in `load()` so existing Supabase `bot_settings` rows inherit `nifty_5m` without resetting operator edits.
6. **[yahoo_provider.py](file:///C:/Users/Vivek/.gemini/antigravity/scratch/Multibot/yahoo_provider.py)**: Added `"5m": 45.0` to `YF_TTL_BY_INTERVAL` and `"5m": 1800.0` to `YAHOO_STALE_GRACE_BY_INTERVAL`.
7. **[db.py](file:///C:/Users/Vivek/.gemini/antigravity/scratch/Multibot/db.py)**, **[strategy_service.py](file:///C:/Users/Vivek/.gemini/antigravity/scratch/Multibot/strategy_service.py)**, **[signal_lifecycle.py](file:///C:/Users/Vivek/.gemini/antigravity/scratch/Multibot/signal_lifecycle.py)**: Added `count_trades_today()`, `ASSET_DAILY_LIMIT` gate (records signal, blocks >10 trades/asset/day), and `TERMINAL`/`actionable` handling.
8. **Tests & Docs**: Updated `tests/test_config.py`, `tests/test_account_limits.py`, `tests/test_account_routing.py`, `AI_REBUILD_SPEC.md`, `README.md`; added `strategies/engulfing_66_sma_5m/tests/test_strategy.py`.

---

## 2026-11-28 (Session 2) — Bug Fixes, Docs Sync, Skills & Context Anchor

### Summary
- Installed `caveman` and `ponytail` skills globally in `C:\Users\Vivek\.gemini\config\skills\`.
- Audited core pipeline code line-by-line and fixed 4 bugs.
- Updated `release_notes.py`, `WHATS_NEW.md`, `README.md`, and created `docs/architecture/PIPELINE_AND_ARCHITECTURE.md`.

### Code Changes & Blast Radius
1. **[main.py](file:///C:/Users/Vivek/.gemini/antigravity/scratch/Multibot/main.py) (`_scan_error_entries`)**:
   - **Fix:** Moved `detail = ...` assignment above `if is_market:` (previously raised `UnboundLocalError` before `detail` was defined, silently swallowing all `MARKET_DATA_ERROR` Telegram alerts in `_notify_scan()`).
   - **Affects:** Scan error Telegram notifications (`MSG-SCAN-ERROR-V1`).
   - **Test added:** `tests/test_main.py::test_scan_error_entries_formats_market_data_error`.
2. **[main.py](file:///C:/Users/Vivek/.gemini/antigravity/scratch/Multibot/main.py) (`_handle_command` `/test`)**:
   - **Fix:** Checked `frame is not None and not frame.empty` instead of `is not None` so an empty DataFrame no longer reports Yahoo Finance as healthy.
   - **Affects:** Telegram `/test` command only.
3. **[trade_monitor.py](file:///C:/Users/Vivek/.gemini/antigravity/scratch/Multibot/trade_monitor.py) (`monitor_once`)**:
   - **Fix:** Changed `row.get("opened_at", row.get("signal_ts"))` to `row.get("opened_at") or row.get("signal_ts")` and converted to `Asia/Kolkata` before `.date().isoformat()` (prevents `NaTType` crash when `opened_at` is `None` and prevents UTC/IST date mismatch on `reservation_date`).
   - **Affects:** Paper trade closing & daily risk settlement in `close_trade_and_settle_account()`.
4. **[yahoo_provider.py](file:///C:/Users/Vivek/.gemini/antigravity/scratch/Multibot/yahoo_provider.py) (`fetch`)**:
   - **Fix:** Wrapped split/corporate-action full re-download in `try/except (YahooRequestQueueTimeout, YahooDataError)` with `_stale(key)` fallback.
   - **Affects:** CSV merge path when overlapping bars differ by >0.5%.

### Documentation Changes
- **[docs/architecture/PIPELINE_AND_ARCHITECTURE.md](file:///C:/Users/Vivek/.gemini/antigravity/scratch/Multibot/docs/architecture/PIPELINE_AND_ARCHITECTURE.md)**: Created canonical pipeline & architecture reference.
- **[README.md](file:///C:/Users/Vivek/.gemini/antigravity/scratch/Multibot/README.md)**: Updated architecture diagram (3 strategies + CSV cache), repository structure, and What's New section.
- **[release_notes.py](file:///C:/Users/Vivek/.gemini/antigravity/scratch/Multibot/release_notes.py)** & **[WHATS_NEW.md](file:///C:/Users/Vivek/.gemini/antigravity/scratch/Multibot/WHATS_NEW.md)**: Updated v3.5.0 release highlights (kept `APP_VERSION = "3.5.0"` to preserve `test_version_consistency.py`).

---

## 2026-11-28 (Session 1, Commit `aef8399`) — Silence Bug, CSV Cache & Bandwidth Cuts

### Summary
- Fixed `NotificationService.deliver()` silencing `REMINDER` and `TRADE_CLOSED` alerts (caused 43,294 silent `MSG-REMINDER-V1` rows in `multibot.deliveries` and 13 overdue reminders).
- Added GitHub CSV candle baseline + incremental Yahoo delta fetch (`yahoo_provider.py`, `tools/sync_candle_csvs.py`, `.github/workflows/sync-candles.yml`, `data/candles/.gitkeep`).
- Reduced Render (5 GB/mo) & Supabase free-tier bandwidth: `SNAPSHOT_CACHE_TTL_SECONDS=180`, `SIGNAL_HISTORY_LIMIT=150`, ETag ignoring `generated_at`, gzip `>=512B`, static `max-age=3600`, `persist_cache=False`, `monitor_loop` 120s idle sleep, `ReminderService` 60s interval, lease heartbeat 30s/90s.
- Synced `docs/API.md`, `docs/RENDER_ONLY_DEPLOYMENT.md`, `docs/SUPABASE_DATABASE.md`, `MANIFEST.txt`, `market_data.py`, `supabase_db.py`, `app.js`.

---

## Pending / Operational Notes
- **Render & GitHub:** Push local commits to `origin/main` so Render deploys the Session 2 fixes.
- **Candle CSV Baselines:** Run `python tools/sync_candle_csvs.py` locally (or trigger **Sync Candle CSVs** in GitHub Actions) to populate `data/candles/`.
- **Pytest:** Run `python -m pytest -x -q` in an environment with Python + dependencies installed (`pytest` is not available in the local Windows agent shell).
