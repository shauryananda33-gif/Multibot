# Multibot — Repository Audit and Restructure Plan

**Audit baseline:** `main` at `ca84c9f2285c1463a1f2e26e443d123dc1b1769b`  
**Audit branch:** `audit/repository-structure-plan`  
**Scope:** read-only repository audit plus this planning document. No application code, strategy rules, database rows, or deployment settings have been changed.

## 1. Executive summary

The repository has **157 tracked files (about 2.48 MB)**:

| Area | Files |
|---|---:|
| Repository root | 62 |
| Tests | 54 |
| Documentation | 21 |
| Strategy packages | 11 |
| Tooling | 5 |
| Supabase migrations/schema | 3 |
| GitHub Actions | 1 |
| **Total** | **157** |

The main structural issue is not merely that many Python modules live in the root. The repository currently contains multiple competing descriptions of the system:

- Production runtime persistence is Supabase Postgres through `supabase_db.py`.
- `db.py`, several tests, the architecture report and multiple documents still describe Turso/libSQL as the production database.
- `CalendarStore` independently constructs the old `db.DatabaseManager`, so its production cache is not using the Supabase manager used by the trading runtime.
- `schema.sql` and `supabase/schema.sql` are old schema snapshots; versioned Supabase migrations are the production schema source.
- The live Render service settings do not match the checked-in Render Blueprint.
- The dependency graph in `report_builder.py` lists only five source paths while claiming to describe the dashboard server's imports.
- The test suite is large, but several persistence tests assert the old Turso implementation rather than the deployed Supabase path.

There are also correctness and reliability issues in the runtime call graph. The highest-risk ones are trade/account persistence, the Yahoo rate-limit classification seen in production, API-triggered Yahoo work outside the runtime leader guard, calendar-cache persistence, strategy scheduling, and a mismatch between advertised and implemented trailing-stop behaviour.

**Recommendation:** do not start by moving files. First make the dependency contracts explicit, then make one integrated, dependency-aware change set with the file moves, import updates, runtime corrections, test replacements and documentation updates together. Keep the existing Render entrypoint and external dashboard-hosting contract intact.

## 2. Non-negotiable behaviour boundaries

The implementation plan must preserve, unless separately authorised:

- Strategy entry conditions, indicators, parameters, candle interpretation and signal identity.
- Instrument mapping, including Gold remaining on the existing `GC=F` instrument until a separate decision is made.
- Account routing, starting balances, risk budgets, daily trade limits and position sizing.
- Initial stop-loss/take-profit calculations and the existing paper-trading model.
- Existing notification content and signal-delivery semantics, except for explicitly approved error/incident handling.
- Existing market-session and closed-candle safety rules.
- The single active runtime-leader model.

The audit identifies a trailing-stop contract discrepancy. It does **not** authorise enabling or changing trailing stops. That would change trade behaviour and needs an explicit decision.

The work should be one coherent PR, not a sequence of partial migrations that leave the repository between incompatible architectures.

## 3. Current runtime and dependency map

### Runtime startup and orchestration

- Render starts `main.py`.
- `main.py` constructs the Supabase database manager, global runtime state, strategy registry, Yahoo provider, strategy service, trade monitor, notification service, calendar service and WSGI application.
- The runtime leader lease is stored in Supabase Postgres.
- The leader starts scanner, trade-monitor, summary and optional Telegram polling workers.
- Every Render process can still serve HTTP while in standby. The leader guard protects the worker scan path, but not every API-triggered data-fetch path.

### Strategy execution

- `strategies/registry.py` discovers strategy packages.
- `strategies/base.py` defines the strategy and signal contract.
- `strategy_engine.py` obtains data through `yahoo_provider.py` and prepares/evaluates candles.
- `strategy_service.py` owns the live scan, signal lifecycle, account routing, notification and trade acceptance path.
- `strategy_scheduler.py` decides when strategy cycles run.
- `trading.py` owns account, risk and trade-plan calculations.
- `trade_monitor.py` monitors open paper trades and settles them.
- `backtest.py` simulates historical trades.

### Market data

- `yahoo_provider.py` owns Yahoo fetching, cache, stale fallback and cooldown.
- `yahoo_request_coordinator.py` provides a process-wide priority queue and request admission.
- `candles.py`, `market_data.py`, `market_sessions.py` and `sweep_engine.py` own candle validation, market sessions and Sweep preparation.
- `bandwidth_metrics.py` records process-local application-level traffic estimates.
- The request coordinator is process-local, not a cross-process/global Yahoo limiter.

### Persistence

- `supabase_db.py` provides the production psycopg connection pool and Postgres adapter.
- `db.py` contains shared database operations plus the old SQLite/Turso connection implementation.
- The production database schema is created by the two versioned files in `supabase/migrations/`.
- Bot settings, notification channels, accounts, trades, signals, scan history, cache and runtime lease are intended to use the shared database.
- The calendar cache currently bypasses the production database manager.
- Summary delivery state is written to a local JSON file.

### HTTP and dashboard

- `main.py` owns WSGI routes, runtime orchestration, dashboard snapshots, Telegram command polling and worker lifecycle.
- `dashboard.py` serializes dashboard data.
- `dashboard.html`, `app.js`, `dashboard-live-wiring.js`, `notifications.js`, `appearance.js`, three CSS files, `manifest.webmanifest`, `sw.js` and `app-icon.svg` form the frontend.
- The browser polls every 30 seconds. The current repository client sends `If-None-Match`; the server returns a bodyless 304 when the ETag matches. The server snapshot cache is 35 seconds.
- Production logs containing `/api/dashboard?t=...` do not match the current `app.js`, which does not append a timestamp cache-buster. That points to an older/different client bundle or another caller; it does not by itself prove the current ETag implementation is broken.
- `_redirects` describes a separate Netlify-style static frontend that proxies API paths to the custom domain. The exact external hosting and custom-domain mapping must be confirmed before changing the frontend's directory or proxy destination.

## 4. Verified findings and required treatment

Severity is about correctness and production risk, not cosmetic priority.

| Priority | Finding | Evidence / affected files | Required treatment |
|---|---|---|---|
| Critical | Trade opening and closing are not atomic with account-ledger updates. | `strategy_service.py`, `trade_monitor.py`, `trading.py`, `db.py`, `supabase_db.py`. Entry saves trade and account separately. Exit mutates the in-memory account before separate trade/account writes. | Add idempotent transaction-level open/close operations. Update shared in-memory account state only after commit. Add failure-injection and retry tests. |
| Critical | Trade monitor and strategy dispatch share account state without one shared lock. | `StrategyService` has its own RLock; `TradeMonitor` has no matching lock and mutates the same accounts dictionary. | Use a shared account-state coordination boundary and database-side atomic updates. Test concurrent close/open operations. |
| High | Production Yahoo rate-limit log can be classified as an empty response. | `yahoo_provider.py`; production showed `YFRateLimitError` followed by `scope=symbol reason=empty_response`. Current tests distinguish raised rate-limit exceptions from generic empty frames, but do not simulate yfinance logging a rate-limit error while returning an empty DataFrame. | Capture explicit yfinance rate-limit diagnostics or use a provider path that exposes the exception. Only explicit 429/rate-limit evidence should trigger provider-wide cooldown. Preserve queue-timeout and generic-empty-response distinctions. Persist and restore the provider-wide cooldown. |
| High | Stale compatible cache can return the wrong history window. | `yahoo_provider.py`: `_compatible_cached` checks coverage and trims; `_compatible_stale` accepts another period without equivalent coverage validation or trimming. | Require the stale frame to cover the requested window and return the correct window. Do not silently substitute a shorter or longer history that can change indicator values. Add shorter/longer-period stale-fallback tests. |
| High | HTTP backtest and Sweep diagnostic endpoints can fetch Yahoo data without requiring runtime leadership. | `main.py`: `_backtest_payload` and `_sweep_diagnostic_payload` call `SERVICE.engine.fetch` directly. The HTTP server runs in standby processes too. The strategy service's runtime guard is not invoked by these direct engine fetches. | Make data-fetching API paths leader-aware or route them through a shared, explicitly admitted data-fetch service. Prevent standby processes from creating independent Yahoo traffic. |
| High | Calendar cache does not use the production Supabase database manager. | `main.py` constructs `NEWS=NewsService()`; `news.py` constructs `CalendarStore`; `calendar_store.py` imports and constructs `db.DatabaseManager`. Render Blueprint has `SUPABASE_DB_URL`, not Turso settings. | Inject the production database into CalendarStore. Update its composite-key upserts for SQLite/Postgres compatibility. Remove redundant mirror writes only after confirming migration compatibility. |
| High | Hot-added assets can appear in the configured scan list but be rejected by the already-loaded strategy manifest. | `config.py`, `bot_settings.py`, `strategies/*/strategy.py`, `strategy_service.py`, `main.py`. The test named “actually receives signals” only checks account routing; another test checks `assets_for_strategy()`, not a hot add after registry creation and a complete scan. | Make the runtime asset contract dynamic or rebuild the registry safely on accepted settings changes. Update scan, diagnostic, backtest and registry symbol checks consistently. Add a test that adds an asset after service/registry startup and runs the actual scan path. |
| High | Generic completed-candle schedules are intervals from the previous scan, not wall-clock candle-close events. | `strategy_scheduler.py`: `completed_candle` uses timeframe seconds since last execution; `daily_completed_candle` is a 24-hour interval. Only Sweep uses configured canonical events. Existing scheduler tests encode interval behaviour. | Define event-aligned completion schedules for the relevant markets/timeframes, preserving closed-candle gates. Add restart, late-start, market-session and missed-event tests. |
| High | Adaptive Trend advertises an ATR trailing stop, but live monitoring and backtesting use the stored fixed SL/TP and do not apply the trailing policy. | `strategies/adaptive_trend/strategy.py`, `trading.py`, `trade_monitor.py`, `backtest.py`. The policy is stored in the trade plan, but no trailing-stop update path exists in the monitor or simulator. | Treat as a documented strategy-contract discrepancy. Do not implement until the desired trailing behaviour is explicitly approved and specified. |
| High | Optional news gate currency mapping does not match configured market names/symbols. | `news_gate.py`, `config.py`. Runtime market values include `Crypto`, `Gold`, `Forex`; map keys use `CRYPTO`, `COMMODITY`, `GOLD`, and an unused `ETH-USD`. `GC=F` has no explicit currency mapping. | Derive currency exposure from canonical AssetConfig/symbol data. For FX pairs consider both currencies. Add tests for NSE, crypto, gold and every Forex pair before enabling the gate. |
| High | Persistence failure after Telegram delivery is not counted as a scan error. | `strategy_service.py` returns `SENT_PERSISTENCE_FAILED`; `main.py` counts only market-data and Telegram failures in scan error totals/alerts. | Add explicit failure categories and make persistence failures visible in scan status, logs and incident alerts without marking an already delivered Telegram signal as unsent. |
| High | Dashboard/API authentication is optional by default, and the checked-in Render Blueprint does not declare the token. | `main.py`: absent `DASHBOARD_API_TOKEN` means admin guard passes; same-origin checks allow requests without Origin/Referer. `render.yaml` omits the token. | Confirm the live Render secret is configured. Make the deployment requirement explicit in the Blueprint/docs while retaining local-development convenience. Do not expose secret values in repository files. |
| Medium | Calendar/summary/runtime state has mixed durability. | `calendar_store.py`, `main.py`, `strategy_scheduler.py`, `telegram_commands`. Calendar uses local SQLite; summary watermark is a local JSON file; scheduler state and Telegram update offset are process-local. | Classify each state as intentionally ephemeral or durable. Persist calendar and summary idempotency state where cross-restart guarantees are required. |
| Medium | Health endpoint reports ONLINE without checking database/runtime readiness. | `main.py` `/api/health` exposes status/keepalive, while actual database readiness is checked elsewhere. Live Render service has no configured health-check path despite `render.yaml` specifying `/ping`. | Separate liveness from readiness and align the Render health-check contract. Do not make health checks trigger market-data requests. |
| Medium | Telegram polling comment says opt-in but code defaults it on. | `main.py` `_telegram_command_polling_enabled()` defaults `TELEGRAM_COMMAND_POLLING` to `true`; production logs showed 409 conflicts. | Make the setting/comment/default consistent and document the single-consumer requirement. Do not disable command handling without confirming the user's intended Telegram workflow. |
| Medium | Database adapter has legacy names and duplicate commit opportunities. | `supabase_db.py` wraps Postgres connections; inherited methods in `db.py` call explicit commits, while Postgres context exit also commits unconditionally. | Make transaction completion idempotent and avoid redundant commits. Rename generic retry/remote concepts away from Turso while retaining only deliberate compatibility APIs. Add tests for explicit commit followed by context exit. |
| Medium | Settings include apparently unused controls. | `config.py`: `scan_interval_seconds` and `dashboard_api_url` have no runtime consumers; generic schedule is manifest-driven and the JS uses `window.DASHBOARD_API_URL`. | Remove dead settings or wire them to an explicit contract. Do not leave environment variables that appear to control production but have no effect. |
| Medium | Legacy candle-building functions remain beside the active candle/sweep path. | `market_data.py` includes minute-to-hour and global-hourly builders; runtime use is concentrated in strict validation/quarantine and Sweep preparation. | Confirm every helper's production caller. Move genuinely legacy builders into an explicit compatibility/research module or remove only after test/reference review. Correct stale “19 asset” comments; built-in universe is 25 plus operator-added assets. |
| Medium | Dependency resolution is not reproducible across Render and CI. | `requirements.txt` and `pyproject.toml` duplicate broad version ranges; Render currently installs requirements while CI installs the project extras. No lock file. | Choose one canonical dependency declaration and lock the resolved runtime set, especially yfinance/pandas. Keep Render and CI installing the same versions. |
| Medium | Render Blueprint differs from the live service configuration. | Live Render service reports `pip install -r requirements.txt`, `python3 main.py`, empty healthCheckPath; `render.yaml` says `pip install -e .`, `python main.py`, `/ping`, service name `multibot2`. | Reconcile Blueprint with live service settings. Confirm external cron and dashboard host before applying changes. |
| Medium | Documentation and tests encode contradictory persistence architectures. | `docs/API.md`, `docs/LOCKED_RULES.md`, `MANIFEST.txt`, `AI_CONTEXT.md`, `AI_REBUILD_SPEC.md`, `tests/test_schema_parity.py`, `tests/test_dashboard_wiring_audit.py`, `tests/test_scan_history_persistence.py`, `tests/test_durable_app_config.py`. | Make Supabase migrations and adapter the authoritative contract. Replace source-text assertions about Turso with tests of the actual production adapter/migrations. Archive historical Turso material rather than silently rewriting incident history. |
| Medium | Two old schema snapshots are not the deployed schema source. | Root `schema.sql` and `supabase/schema.sql` differ; production schema is in versioned migrations. Current schema-parity test checks `db.py`, not migration parity. | Keep migrations authoritative. Archive/remove stale snapshots only after all rebuild-kit/docs references are updated. Add migration validation. |
| Medium | API documentation and health semantics are stale. | `docs/API.md` is checked for route coverage but still describes the old database label/contract. `/api/health` is a liveness/keepalive endpoint, not a DB readiness check. | Regenerate/update the API contract from the current route implementation and test semantic fields, not only route names. |
| Medium | Frontend deployment/version may be out of sync with the current repository. | Current `app.js` uses ETag and no timestamp query; production logs show `?t=`. `_redirects` describes Netlify-to-custom-domain proxying, while Render also serves the same static files. | Verify the actual frontend host, deploy branch, custom-domain destination and served JS version. Keep one authoritative frontend bundle and one documented API origin. |
| Low | Root contains historical audit/rebuild documents and a misleading partial dependency graph. | `report_builder.py` lists only five graph paths; several old UI/Turso/rebuild docs conflict with current code. | Move the report generator to tooling, regenerate the graph from imports, and archive historical reports under clearly named archive folders. |
| Low | Static CSS has a large multi-layer cascade. | `styles.css` ~147 KB, `foundation.css` ~90 KB, `appearance-overrides.css` ~133 KB. Repeated selectors exist across layers and media queries. | Do not bulk-delete duplicate selectors. First define ownership per layer, use the existing visual/mutation guards, then consolidate proven superseded rules. |
| Low | The architecture HTML is a large generated artifact. | `docs/architecture/multibot2-architecture.html` is roughly 819 KB and served at `/architecture`; JSON companion is separate. | Decide whether HTML is generated from a source model. Keep the route working; avoid treating generated HTML as the canonical dependency graph. |

## 5. Specific dependency and correctness notes

### Trade/account ledger

Opening a trade currently performs separate writes for the trade row and account balance. Closing a trade does the same. A partial failure can leave the trade ledger and account ledger disagreeing. The monitor also mutates the in-memory account before either write is confirmed. If a trade-close write fails and the trade remains OPEN, the next monitor cycle can settle the same trade again using the already-mutated in-memory account.

The fix must be transaction-level and idempotent:
- Open: atomically record the accepted trade and reserve/update the account's daily risk state.
- Close: atomically transition only an OPEN trade to CLOSED and settle the account once.
- Update in-memory account state only after a successful transaction.
- Use one shared account coordination boundary across scanner and monitor.
- Add injected failures for first write, commit, retry and concurrent close/open cases.

### Yahoo rate-limit and cache contract

The generic empty-frame test is correct to avoid turning every empty response into a provider-wide cooldown. The missing case is the observed yfinance behaviour: the library logs a typed rate-limit diagnostic and returns an empty frame rather than propagating that exception to the caller.

The tests need to cover:
- Raised `YFRateLimitError` / HTTP 429.
- Logged `YFRateLimitError` plus empty DataFrame.
- Empty DataFrame with no rate-limit diagnostic.
- Queue admission timeout.
- Provider-wide cooldown persistence/restart.
- Stale cache coverage and requested-window trimming.
- A successful unrelated request must not accidentally erase a still-relevant provider cooldown unless that is the intended recovery contract.

### Runtime leader boundary

The scanner path checks runtime leadership, but the backtest and Sweep diagnostic API helpers fetch through the engine directly. Since standby processes still serve HTTP, those requests can issue Yahoo traffic through a separate process-local coordinator. Calendar API fetches can similarly run from a process-local CalendarService.

The leader boundary must cover every endpoint that can initiate upstream market-data work, not just background worker loops.

### Scheduling

Sweep V2 has configured event-aligned scheduling. The generic `completed_candle` schedule is currently an elapsed interval from the last scan; daily completed-candle scheduling is 24 hours from the last scan. The candle-preparation layer may prevent use of an incomplete candle, but that does not make the scan time itself aligned to candle completion.

The new scheduler tests must cover hourly NSE closes, global-market boundaries, daily completion, late startup, restart, missed events, weekends/holidays and market-session gating.

### Strategy feature contract

Adaptive Trend declares a trailing-stop capability and exposes a trailing policy. The policy is persisted into the trade row, but the monitor and backtest simulator only check the original SL/TP. Do not silently implement a new trail. First agree on the exact ATR reference, update cadence, monotonic stop rule, gap handling, exit price, restart persistence and backtest parity.

### Calendar persistence and news gate

Calendar tables exist in the Supabase migration, but the production CalendarStore is constructed with the old database manager. Wiring it to Supabase requires replacing composite-key `INSERT OR REPLACE` statements with explicit `ON CONFLICT(feed_key, week_start) DO UPDATE` statements; the current Postgres compatibility translator assumes a single conflict key and cannot safely infer this composite key.

News-gate mappings must use canonical market/symbol data. Current mapping only correctly covers BTC/USD and NSE/INR. Gold and Forex market names do not match the fallback keys.

## 6. Proposed repository structure

The intended layout is domain-oriented. The root `main.py` remains the Render entrypoint. The strategy plugin directory remains discoverable by the registry. The frontend remains compatible with the external static-hosting contract until that host is verified.

    main.py                         # thin deployment entrypoint
    startup.py                      # documented compatibility launcher
    multibot/
      config/                       # settings, assets, routing, operator config
      runtime/                      # lifecycle, leader lease, worker orchestration
      dashboard/                    # WSGI/API routes, snapshot, serializers
      market_data/                  # Yahoo provider, coordinator, cache, candles,
                                    # sessions, validation, Sweep preparation
      persistence/                  # repository contract, SQLite, Supabase Postgres
      strategies/                   # base contract, registry integration, service,
                                    # engine and scheduler
      trading/                      # account state, risk, trade monitor, backtest
      signals/                      # identity, freshness and lifecycle
      notifications/                # Telegram, channels, delivery, reminders
      calendar/                     # calendar service, store and news gate
      telemetry/                    # bandwidth and operational metrics
    strategies/                     # shipped/dropped-in strategy plugin packages
    web/                            # frontend source if external host is configured
    docs/
      architecture/
      operations/
      strategy/
      design/
      reference/
      archive/
    tests/
      unit/
      integration/
      contracts/
      frontend/
      regression/
    tools/
    supabase/
      migrations/                   # sole authoritative production schema history

### Important migration constraints

- Do not move static assets out of the current publish root until the Netlify/static-host publish directory and redirects are explicitly confirmed. If moved to `web/`, add and verify the corresponding hosting configuration in the same PR.
- Keep `main.py` as the stable Render command target.
- Update all absolute imports, dynamic strategy discovery, packaging metadata, test imports, rebuild-kit file lists, API static routes and external redirects in the same change set.
- Do not leave a half-migrated state with some modules importing root names and others importing package names.
- If compatibility imports are required, keep thin wrappers only for real public entrypoints; do not preserve dozens of duplicate implementation modules.

## 7. File-by-file inventory

The following inventory accounts for every tracked path in the baseline tree. “Keep” means retain the behaviour/source; it does not mean the file cannot move into its target domain.

### Root files (62)

| File | Purpose | Planned treatment |
|---|---|---|
| `.gitignore` | Python/build/cache/local-state exclusions | Keep; review generated audit/build artifacts. |
| `AI_CONTEXT.md` | AI project context and source-reading order | Keep at root; update current Supabase/runtime architecture and known risks. |
| `AI_REBUILD_SPEC.md` | Full reconstruction contract | Keep as reference; update file inventory, migrations, runtime and strategy contracts. |
| `AUDIT_DESIGN_ROUND2.md` | Historical dashboard design audit | Archive under docs/archive/design. |
| `DASHBOARD_AUDIT_REPORTS.txt` | Historical dashboard audit reports | Archive; do not treat as current contract. |
| `DESIGN.md` | Design-system reference | Move to docs/design and reconcile with current CSS layers. |
| `FINALIZATION_RULEBOOK.md` | Older release/finalization rules | Archive after extracting still-valid rules into canonical docs. |
| `MANIFEST.txt` | Hand-maintained file/architecture manifest | Regenerate from canonical package/migration metadata or retire. |
| `MULTIBOT2_CANONICAL_NOTES.md` | Older canonical project notes | Archive; version is stale. |
| `MULTIBOT2_UI_UX_REAUDIT.md` | Historical UI/UX re-audit | Archive with date/version. |
| `README.md` | Public project overview and setup | Keep; update strategy inventory, plugin instructions, database and deployment. |
| `SENIOR_PONYTAIL_AUDIT.md` | Historical engineering audit | Keep as history or archive; do not use as current file map. |
| `STRATEGY_DEVELOPER_GUIDE.md` | Strategy plugin guide | Move to docs/strategy; correct manifest/API instructions. |
| `UI_UX_AUDIT_REPORT.md` | Historical UI/UX report | Archive. |
| `WHATS_NEW.md` | Current release highlights | Keep; generated/synchronised from release_notes.py. |
| `_redirects` | External static-host routing and API proxy | Keep at publish root until host mapping is verified; correct target if needed. |
| `app-icon.svg` | PWA icon | Keep as frontend asset. |
| `app.js` | Main dashboard client and API polling | Keep as frontend source; preserve ETag request behaviour. |
| `appearance-overrides.css` | Final visual override layer | Keep initially; consolidate only with visual regression proof. |
| `appearance.js` | Appearance state bridge | Keep as frontend module. |
| `backtest.py` | Backtest simulation and metrics | Move to trading/backtest. |
| `bandwidth_metrics.py` | Process-local request/payload telemetry | Move to telemetry; distinguish estimates from wire bytes. |
| `bot_settings.py` | Operator account/asset/routing settings | Move to config service; fix hot-update registry contract. |
| `calendar_store.py` | Weekly economic-calendar persistence | Move to calendar/store; inject production DB. |
| `candles.py` | Candle index/closure validation | Move to market_data/candles. |
| `channels.py` | Notification channel configuration | Move to notifications/channels. |
| `config.py` | Global settings, asset universe, routing and environment | Move to config; remove unused settings after reference check. |
| `dashboard-live-wiring.js` | Read-only frontend history bridge | Keep as frontend module; preserve single dashboard request owner. |
| `dashboard.html` | Dashboard HTML shell | Keep as frontend entry page; move only with hosting config. |
| `dashboard.py` | Dashboard payload/serialization helpers | Move to dashboard/serializers. |
| `db.py` | SQLite/Turso adapter and shared persistence operations | Split shared repository operations from concrete adapters; retire Turso only after callers/tests are migrated. |
| `foundation.css` | Shared dashboard component styles | Keep; define ownership relative to styles.css and overrides. |
| `main.py` | Runtime orchestration, WSGI routes, workers and Telegram polling | Split into runtime/dashboard/worker modules; retain a thin root launcher. |
| `manifest.webmanifest` | PWA manifest | Keep as frontend asset. |
| `market_data.py` | OHLC validation/quarantine and older candle builders | Split active validation from unused/legacy builders; correct 19-asset comments. |
| `market_sessions.py` | Exchange/session calendar checks | Move to market_data/sessions. |
| `news.py` | Forex Factory calendar service | Move to calendar/service; inject store/database. |
| `news_gate.py` | Optional economic-event pause gate | Move to calendar/gate; correct currency mapping and add tests. |
| `notification_service.py` | Notification fan-out and delivery audit | Move to notifications/dispatcher. |
| `notifications.js` | Notification settings UI | Keep as frontend module. |
| `pyproject.toml` | Package metadata and canonical dependency declaration | Keep at root; remove stale Poetry block and define package layout. |
| `release_notes.py` | Canonical version and release highlights | Keep as release metadata source. |
| `reminders.py` | Reminder worker/service | Move to notifications/reminders or runtime workers after dependency review. |
| `render.yaml` | Render Blueprint | Keep; reconcile with live service and declare deployment security requirements. |
| `report_builder.py` | Manual dependency/cascade report generator | Move to tools and regenerate graph from actual imports; current graph is incomplete. |
| `requirements.txt` | Live Render dependency installation list | Keep only as generated/synchronised lock input or remove after Render uses canonical packaging. |
| `schema.sql` | Old schema snapshot | Archive/retire after rebuild-kit references are migrated; migrations are authoritative. |
| `signal_gate.py` | Freshness/actionability gate | Move to signals/gate. |
| `signal_lifecycle.py` | Canonical signal identity/lifecycle helpers | Move to signals/identity. |
| `startup.py` | Backward-compatible launcher | Keep as a thin compatibility wrapper. |
| `strategy_engine.py` | Strategy data fetch/evaluation engine | Move to strategies/engine. |
| `strategy_scheduler.py` | Strategy scan scheduling | Move to runtime/scheduler; implement event-aligned completion. |
| `strategy_service.py` | Live scan, dispatch and trade acceptance | Move to strategies/service; fix dynamic assets and atomic ledger calls. |
| `styles.css` | Dashboard base/legacy stylesheet | Keep initially; establish explicit layer ownership. |
| `supabase_db.py` | Production Supabase Postgres adapter | Move to persistence/supabase_postgres; remove misleading Turso aliases. |
| `sw.js` | Installability-only service worker | Keep; no-cache behaviour is intentional for live trading state. |
| `sweep_engine.py` | Sweep candle preparation and diagnostics | Move to market_data/sweep. |
| `telegram.py` | Telegram API client and message templates | Move to notifications/telegram. |
| `trade_monitor.py` | Open trade monitor and settlement | Move to trading/monitor; add transaction and concurrency guarantees. |
| `trading.py` | Account, risk, trade plan and paper-trade rules | Move to trading/accounting; preserve all current formulas. |
| `yahoo_provider.py` | Yahoo fetch/cache/backoff provider | Move to market_data/yahoo; fix rate-limit logging and stale-window contract. |
| `yahoo_request_coordinator.py` | Process-wide priority request admission | Move to market_data/coordinator; document process-local scope. |

### Strategy package files (11)

| File | Purpose | Planned treatment |
|---|---|---|
| `strategies/__init__.py` | Strategy package exports | Keep as plugin namespace or adapt to new registry package. |
| `strategies/_template/strategy.py` | New-strategy template | Keep; align its instructions with the actual Python StrategyManifest contract. |
| `strategies/adaptive_trend/__init__.py` | Adaptive Trend plugin entry | Keep. |
| `strategies/adaptive_trend/strategy.py` | Trend Pulse strategy logic | Preserve all rules; document trailing-stop discrepancy. |
| `strategies/base.py` | Strategy, manifest and signal contract | Keep; move to strategy core if plugin discovery is preserved. |
| `strategies/engulfing_66_sma/__init__.py` | Engulf plugin entry | Keep. |
| `strategies/engulfing_66_sma/strategy.py` | Engulf 66 SMA strategy logic | Preserve all indicators/conditions; fix dynamic asset support outside the strategy rules. |
| `strategies/engulfing_66_sma/tests/test_strategy.py` | Strategy-specific regression tests | Keep under strategy tests. |
| `strategies/registry.py` | Dynamic plugin discovery and registry | Keep; ensure hot settings changes do not leave stale manifest assets. |
| `strategies/sweep_v2/__init__.py` | Sweep plugin entry | Keep. |
| `strategies/sweep_v2/strategy.py` | Sweep 4H strategy logic | Preserve all classifications and levels. |

### Supabase files (3)

| File | Purpose | Planned treatment |
|---|---|---|
| `supabase/migrations/20261125000000_initial_multibot_schema.sql` | Initial production schema | Keep as immutable migration history. |
| `supabase/migrations/20261125175557_multibot_security_and_request_coordination.sql` | RLS/private-schema/request coordination migration | Keep as immutable migration history; add future migrations rather than editing applied files. |
| `supabase/schema.sql` | Older schema snapshot | Archive/retire after confirming no external consumer; do not treat as current migration source. |

### Test files (54)

Tests should be grouped by domain after imports are updated. Existing tests remain valuable; legacy tests should be replaced with equivalent production-adapter tests rather than simply deleted.

| File | Coverage / planned treatment |
|---|---|
| `tests/test_account_limits.py` | Trading account limits; move to trading unit tests. |
| `tests/test_account_routing.py` | Account routing/session rules; move to config/routing tests. |
| `tests/test_adaptive_trend.py` | Adaptive strategy contract; keep under strategy tests and add explicit trailing-policy contract test. |
| `tests/test_api_contract.py` | HTTP/API and documentation contract; keep under contracts and update for current routes/health semantics. |
| `tests/test_appearance_system.py` | Appearance controls and style contract; keep under frontend tests. |
| `tests/test_backtest.py` | Backtest account sizing/limits; keep and add API-reported planned-risk correctness. |
| `tests/test_backtest_metrics.py` | Backtest metrics; keep under trading tests. |
| `tests/test_bandwidth_metrics.py` | Telemetry accounting; keep under market-data/telemetry tests. |
| `tests/test_bot_settings.py` | Operator settings/assets/routing; keep and add hot-add after registry/service initialization. |
| `tests/test_candles.py` | Canonical candle close rules; keep under market-data tests. |
| `tests/test_completed_candle_contract.py` | Incomplete-candle exclusion; keep and pair with scheduler boundary tests. |
| `tests/test_config.py` | Configuration invariants; keep under config tests and distinguish built-in 25 from operator additions. |
| `tests/test_contrast_tokens.py` | WCAG/theme token contract; keep under frontend tests. |
| `tests/test_dashboard_ui.py` | Dashboard UI/ETag/static contract; keep under frontend tests. |
| `tests/test_dashboard_wiring_audit.py` | Dashboard wiring; replace Turso source assertions with Supabase/migration assertions. |
| `tests/test_db.py` | Local persistence operations; keep as SQLite adapter tests. |
| `tests/test_delivery_consistency.py` | Signal delivery status; keep under notification/signal tests and include persistence-failure visibility. |
| `tests/test_durable_app_config.py` | Currently tests Turso restart persistence; replace with Supabase adapter/restart contract tests. |
| `tests/test_final_consistency_contract.py` | Dashboard signal contract; keep under API/signal contracts. |
| `tests/test_fresh_signal_lifecycle.py` | Signal freshness/restart; keep under signal regression tests. |
| `tests/test_frontend_syntax.py` | JS/assets/load order; keep under frontend tests and pin Node version in CI. |
| `tests/test_keepalive_health.py` | Ping/health contract; update to distinguish liveness from readiness. |
| `tests/test_main.py` | WSGI/auth/scan orchestration; keep under runtime/API tests and add standby-fetch guard cases. |
| `tests/test_market_data.py` | OHLC and legacy candle builders; keep active validation tests, mark unused builders explicitly. |
| `tests/test_market_sessions.py` | Exchange sessions/closed-market gating; keep under market-data tests. |
| `tests/test_no_wall_clock_dependence.py` | Deterministic time contract; keep under regression/contracts. |
| `tests/test_notification_channels.py` | Channels, subscriptions and summaries; keep and add durable summary watermark tests. |
| `tests/test_notification_service.py` | Notification delivery resilience; keep under notifications. |
| `tests/test_ponytail_fixes.py` | Historical trading regressions; keep but merge duplicate coverage into domain suites when proven redundant. |
| `tests/test_rebuild_kit.py` | Rebuild-kit archive; update file inventory and target structure. |
| `tests/test_rebuild_spec_inventory.py` | Root-module inventory guard; replace with package/file-manifest guard after restructure. |
| `tests/test_release_docs.py` | Release metadata/docs sync; keep under docs/tooling. |
| `tests/test_runtime_lifecycle.py` | Lease/workers/startup; add real Supabase adapter lease tests and heartbeat failure policy coverage. |
| `tests/test_scan_history_persistence.py` | Scan history; remove Turso-specific assertion and test Supabase persistence contract. |
| `tests/test_schema_parity.py` | Currently validates db.py/Turso, not production migrations; replace with migration/table/index/RLS parity checks. |
| `tests/test_signal_event_identity.py` | Canonical signal identity; keep under signals. |
| `tests/test_signal_gate.py` | Freshness/dedup; keep under signals. |
| `tests/test_strategies.py` | Strategy contracts/backtest engine; keep under strategies. |
| `tests/test_strategy_contract.py` | Plugin independence; keep under strategies. |
| `tests/test_strategy_registry.py` | Dynamic plugin discovery; add runtime asset mutation coverage. |
| `tests/test_strategy_scheduler.py` | Scheduler behaviour; replace interval-only expectations where wall-clock candle events are required. |
| `tests/test_supabase_db_adapter.py` | SQL translation; keep and expand composite-key/transaction coverage. |
| `tests/test_supabase_pool.py` | Connection pool lifecycle; add explicit-commit/context-exit and rollback-failure tests. |
| `tests/test_supabase_security_migration.py` | RLS migration contract; keep and validate migration execution/schema state. |
| `tests/test_sweep_canonical.py` | Sweep classification; keep unchanged. |
| `tests/test_sweep_market_data_errors.py` | Sweep OHLC diagnostics/alerts; keep and preserve failure categorisation. |
| `tests/test_telegram_messages.py` | Telegram formatting; keep under notifications. |
| `tests/test_turso_database.py` | Legacy Turso adapter tests; retire or convert to explicit legacy compatibility tests if Turso is removed. |
| `tests/test_turso_retry_degradation.py` | Legacy Turso transport tests; replace with Supabase Postgres transient-error/lease tests. |
| `tests/test_version_consistency.py` | Version/strategy inventory; keep and include package metadata. |
| `tests/test_visual_consistency_audit.py` | Large CSS/DOM guard suite; keep under frontend regression tests. |
| `tests/test_yahoo_cache_json.py` | Cache compression/persistence; rename away from Turso and add stale-coverage tests. |
| `tests/test_yahoo_provider.py` | Provider errors/cache; add logged-rate-limit/empty-frame and stale-window cases. |
| `tests/test_yahoo_request_coordinator.py` | Priority/queue; keep and document process-local admission boundary. |

### Documentation files (21)

| File | Planned treatment |
|---|---|
| `docs/API.md` | Update from actual WSGI route implementation; correct Supabase and health semantics. |
| `docs/DESIGN_SYSTEM/components.md` | Keep under docs/design; verify current component contract. |
| `docs/DESIGN_SYSTEM/geometry.md` | Keep under docs/design; verify current geometry contract. |
| `docs/DESIGN_SYSTEM/icons.md` | Keep under docs/design; verify current icon contract. |
| `docs/DESIGN_SYSTEM/motion.md` | Keep under docs/design; verify reduced-motion contract. |
| `docs/DESIGN_SYSTEM/type.md` | Keep under docs/design; verify type-scale contract. |
| `docs/DESIGN_SYSTEM/validation.md` | Keep under docs/design; align manual browser checks with CI. |
| `docs/KIT_README.md` | Keep as rebuild-kit documentation; update after package/layout changes. |
| `docs/LESSONS_LEARNED.md` | Keep as historical engineering lessons; label dates and current status. |
| `docs/LOCKED_RULES.md` | Make canonical strategy/runtime invariants; correct Turso references. |
| `docs/MULTIBOT2_MASTER_AUDIT_FIX_PLAN.md` | Archive as superseded; it describes old issues/phases and is not the current plan. |
| `docs/NOTIFICATIONS.md` | Keep; update database persistence and Telegram polling details. |
| `docs/PRODUCTION_INCIDENT_NOTES.md` | Update with November Yahoo/strategy-cycle/dashboard observations and verified causes only. |
| `docs/REBUILD_BRIEF.md` | Archive or rewrite as a current architecture brief; old UI-only scope is no longer applicable. |
| `docs/RUNTIME_LIFECYCLE_AUDIT.md` | Update live Render config and Supabase leader contract. |
| `docs/START_HERE.md` | Archive; it explicitly forbids Python changes and reports an old test count. |
| `docs/SUPABASE_DATABASE.md` | Keep as database setup source; add CalendarStore and migration-test details. |
| `docs/THEME_SYSTEM.md` | Keep under docs/design; reconcile version and actual frontend CSS order. |
| `docs/TURSO_RELIABILITY_FIX_PLAN.md` | Archive as historical; production uses Supabase Postgres. |
| `docs/architecture/multibot2-architecture.html` | Keep route-compatible until regenerated from current graph; generated artifact, not source. |
| `docs/architecture/multibot2-architecture.json` | Keep only if confirmed as the HTML source model; otherwise archive with generated artifact metadata. |

### Tooling files (5)

| File | Planned treatment |
|---|---|
| `tools/build_rebuild_kit.py` | Keep; update its fixed file list and output layout after restructure. |
| `tools/check_release_docs.py` | Keep under release tooling; ensure CI invokes it or equivalent tests fully cover it. |
| `tools/mutate_design_guards.py` | Keep as manual mutation testing for frontend guards. |
| `tools/sweep_appearance.js` | Keep as manual browser appearance-matrix QA; document required Playwright CLI. |
| `tools/verify_matrix_reload.js` | Keep as manual browser reload/localStorage QA; document required Playwright CLI. |

### CI file (1)

| File | Planned treatment |
|---|---|
| `.github/workflows/ci.yml` | Keep; add dependency-lock consistency, linter/type checks if selected, migration validation and the new regression tests. Current CI installs from pyproject, while live Render installs requirements.txt. |

## 8. One integrated implementation and verification checklist

This is a dependency-ordered checklist for one PR, not separate rollout phases.

1. Freeze the current behaviour contract and capture baseline tests/strategy outputs. Record all existing strategy versions, parameters, account values, asset mappings, schedule rules and trade-plan outputs.
2. Introduce the domain package layout and update every import, dynamic strategy discovery path, pyproject package declaration, Render entrypoint, rebuild-kit list and test path together. Keep root main.py as the stable launcher.
3. Split persistence into shared repository operations and explicit SQLite/Supabase adapters. Keep the versioned Supabase migrations authoritative. Replace Turso-specific names and tests only where the compatibility implementation is actually removed.
4. Inject the Supabase database into CalendarStore and use portable explicit composite-key upserts. Verify calendar cache survives process recreation.
5. Add transaction-level trade open/close operations and shared account-state coordination. Add failure-injection and concurrency tests before changing service call sites.
6. Correct Yahoo rate-limit classification, provider cooldown persistence, stale cache coverage and request-admission boundaries. Test yfinance's logged rate-limit/empty-frame behaviour without classifying generic empty data as provider-wide failure.
7. Enforce the runtime leader boundary for every HTTP endpoint that can fetch upstream data. Confirm standby processes can still serve safe cached/read-only pages without creating Yahoo requests.
8. Implement the agreed event-aligned scheduler contract for completed candles. Preserve market-session and incomplete-candle rejection.
9. Resolve dynamic asset updates so an asset added after registry startup is either safely accepted by the existing strategy contract or the settings change is explicitly rejected until a safe registry refresh. All scan/diagnostic/backtest paths must agree.
10. Resolve the news currency map and add coverage for all asset groups. Keep the news gate disabled unless the user explicitly wants it enabled.
11. Correct scan error classification, persistence-failure visibility, API health semantics and deployment token requirements.
12. Update docs, manifests, architecture graph, generated report, rebuild kit and static-host/Render deployment descriptions.
13. Run the complete test suite, compile/import checks, migration validation, frontend syntax and appearance checks, plus integration tests against a disposable Postgres instance. Compare strategy fixtures and trade/account results against the frozen baseline.
14. Review the final diff file-by-file. No strategy-rule changes, unrelated cleanup or automatic deployment. Production deployment requires separate explicit approval.

## 9. Required tests before merge

At minimum, the integrated change must add or strengthen tests for:

- Atomic trade open and close when either DB write/commit fails.
- Concurrent scanner entry and monitor exit against the same account.
- Trade-close retry idempotency; no double P&L or risk release.
- Yahoo logged rate-limit diagnostic plus empty frame; generic empty response; queue timeout; provider cooldown across restart.
- Stale cache shorter/longer requested windows and indicator input preservation.
- Backtest/diagnostic/calendar API requests on a standby process.
- Hot-added asset after registry and StrategyService are already constructed.
- Actual wall-clock completion schedule for NSE/global/daily strategies, including late startup and restart.
- News currency filtering for NSE, BTC, GC=F and every Forex pair.
- Calendar cache persistence through Supabase and composite-key upserts.
- Persistence failure visible in scan totals and alerts.
- Admin token required in deployed configuration while local tests remain usable.
- Supabase migrations create all required tables/indexes/RLS and the adapter can execute real repository operations.
- ETag 200/304 behaviour from the actual deployed frontend bundle, including the absence of timestamp cache-busting.
- Render Blueprint matches the agreed live service build/start/health-check settings.

## 10. Decisions that cannot be inferred from the repository

These are the only external assumptions that need confirmation before the integrated change is finalised:

1. Is `DASHBOARD_API_TOKEN` already configured manually in the live Render service? The Blueprint does not declare it; secret values are not available from repository inspection.
2. Is the custom domain in `_redirects` definitely mapped to the Render service, and which host currently publishes the static frontend?
3. Should the old Turso adapter be removed completely, or retained as an explicitly supported compatibility backend? Current Render config points to Supabase.
4. Should Adaptive Trend's declared trailing-stop capability be implemented, or should the capability/metadata be corrected to match the current fixed SL/TP behaviour? This decision changes trade behaviour.
5. Should the optional news gate remain off by default? The audit assumes yes.

## 11. Audit boundary

This branch contains only this planning document. No Python, JavaScript, CSS, SQL migration, Render setting, Supabase row or strategy rule has been modified.

The next safe action is to review this plan and confirm the external hosting/authentication assumptions. After that, the repository changes can be prepared as one dependency-aware PR and reviewed before any merge or deployment.


## 12. Additional call-path findings from the final pass

The following items were confirmed after tracing the worker and API call paths. They are added here so the implementation checklist does not miss interactions between threads and endpoints.

### Scan-cycle overlap and Telegram command replay

- `run_all_cycles()` is called by the scheduled scanner and by the Telegram `/scan` command. The command handler starts a new thread for each update. There is no cycle-wide lock around the full scan cycle. The strategy service's dispatch lock protects only its dispatch/account section; it does not serialize all scans.
- Yahoo per-symbol locks and cache reduce duplicate network calls, but they do not make concurrent full cycles safe or prevent duplicate database work and conflicting scan-status updates.
- The Telegram update offset is local to `telegram_commands()` and starts at zero after process restart. If a process exits before the next polling request confirms an update, Telegram may return that unconfirmed command again.
- Required treatment: add one runtime scan-cycle admission lock for scheduled and manual scans, and persist or otherwise make command-update processing idempotent. Preserve the user's ability to issue manual commands.

### API data-fetch and health boundaries

- `/api/backtest` and `/api/diagnostics/sweep` fetch through `SERVICE.engine.fetch` directly and do not invoke the service runtime guard. `/api/calendar` can also trigger a cache-miss fetch through the process-local calendar service.
- A standby process is still an HTTP server. These endpoints can therefore initiate external requests outside the leader's worker ownership and outside another process's Yahoo coordinator.
- `/api/health` reports liveness/keepalive information; it does not prove that Supabase is reachable or that the runtime leader is active. The dashboard payload currently labels the database `TURSO` when the Supabase adapter's compatibility alias is true.
- Required treatment: distinguish liveness, readiness and leader status; gate upstream data-fetch work; correct the database label. Do not make a health probe perform a Yahoo request.

### Scan result accounting and backtest display

- The scan result error count includes `MARKET_DATA_ERROR` and `TELEGRAM_FAILED`, but not `SENT_PERSISTENCE_FAILED`. A Telegram-delivered signal whose trade/account persistence failed can therefore be shown as a clean scan.
- `_backtest_payload()` calculates the displayed `planned_risk` as number of trades multiplied by the global `RISK_PER_TRADE_INR`, even though the backtest simulator receives the routed account and uses account-specific risk settings. The displayed figure can disagree with the actual account-specific simulation.
- Required treatment: use a typed scan-result classification and source the displayed planned risk from the same account risk calculation used by the simulator.

### Strategy metadata and docs contract

- The README's built-in strategy table and architecture drawing show Trend Pulse and Sweep, omitting the shipped Engulfing 66 SMA strategy.
- The README's plugin layout asks for `manifest.yaml`, while the current loader discovers Python packages exposing `create_strategy()` and reads the Python `StrategyManifest` contract. No YAML manifest loader was found.
- Strategy manifests expose parameter metadata, including editable flags, but the live engine calls strategy validation with default configuration and the operator settings document does not provide a strategy-parameter persistence path. Do not imply those parameters are runtime-editable until that path exists.
- The README and architecture material also describe trailing policy as a supported strategy feature, while the live monitor/backtest discrepancy is recorded above.
- Required treatment: make README, strategy guide, manifest contract and runtime capability metadata agree with actual behaviour.

### Schema and database documentation mismatch

- Both schema snapshot files begin by saying runtime schema is initialized by db.py and uses Turso/libSQL. This is no longer the production architecture.
- The root and Supabase schema snapshots are not identical. The test named `test_schema_parity.py` does not compare those files; it asserts the legacy db.py table list and Turso/SQLite implementation.
- A comment in `supabase/schema.sql` says that this test enforces the two schema files being identical, which it does not.
- Required treatment: make versioned migrations the sole production schema source, replace the misleading parity test with migration validation, and archive both snapshots if no external consumer depends on them.

### Intentional behaviour that must not be “optimised” away

- `sw.js` intentionally caches nothing because cached trading state can misrepresent current signals, trades and P&L.
- `dashboard-live-wiring.js` intentionally consumes the single snapshot fetched by app.js; it must not add another dashboard polling loop.
- `NewsService.get(force=True)` currently does not bypass the weekly cache. The refresh command is cache-first rather than an instruction to fetch Forex Factory immediately. This is consistent with reducing external requests; change only if an explicit force-refresh feature is wanted.
- The three CSS files form a deliberate cascade. Repeated selectors are not proof of dead CSS because many are responsive/state overrides. Consolidate only after ownership and visual regression checks.
- CSS/JS delivery through the external static host must be distinguished from Render API egress. Do not count frontend asset bytes as Render bandwidth until the live hosting path is confirmed.

## 13. Test and CI coverage gaps

The current CI workflow performs Python 3.12 setup, installs from pyproject extras, compiles Python, imports main and supabase_db, then runs pytest. It does not currently execute a live Postgres migration/integration suite, a type checker, a linter, a Render Blueprint validation or a real browser appearance run.

Specific missing or misleading coverage:
- There is no dedicated TradeMonitor test module covering transaction failure, repeated settlement or concurrent account mutation.
- There is no dedicated NewsGate test module for the current asset-market currency mappings.
- CalendarStore tests exercise the old local/Turso-style adapter; there is no production Supabase CalendarStore test.
- The strategy scheduler tests cover elapsed intervals, not actual wall-clock candle-close alignment.
- The Yahoo tests cover raised rate-limit exceptions and generic empty responses separately, but not yfinance's logged rate-limit diagnostic with an empty result.
- The Supabase migration test checks migration text/expected statements; it does not execute the migrations against a disposable Postgres database.
- The Supabase pool test covers basic pool return/commit, but not the inherited explicit-commit followed by context-exit double-commit path or rollback failure.
- The asset test named as receiving signals verifies configuration/account resolution; it does not add an asset after the registry is loaded and exercise the complete live scan/dispatch path.
- The schema-parity and dashboard-wiring tests assert legacy Turso implementation details, so they are not reliable production-Supabase architecture tests.

## 14. Clarification to the file inventory

The two schema snapshots are historical public-schema SQL, not the current private `multibot` schema created by the migrations. Their comments are stale. The test named schema parity is also stale and does not validate migration parity. These files should not be used as a basis for any new production migration.

The frontend asset-size figures in this plan are repository sizes, not measured Render egress. The current external-host routing must be verified before using those figures in a Render bandwidth budget.
