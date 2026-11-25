# Multibot — Whole-System Remediation Plan (File-by-File)

**Status:** Audit-derived implementation specification; no runtime code or database changes have been made by this plan commit.  
**Baseline branch:** `main`  
**Baseline commit inspected:** `c5e6c514886c8caaafb92ba01e58e1df5a2c7636`  
**Application version in project metadata:** `3.5.0`  
**Deployment model in repository:** Render Python web service, `python main.py`, Supabase Postgres session-pooler connection, SQLite for local tests/development.  
**Engineering method:** Senior Ponytail / contract-first / dependency-first. Fix a shared contract at its owning boundary; do not patch consumers independently.

---

## 1. Objective and non-negotiable invariants

Deliver one coherent, reviewed change set that improves runtime reliability, Yahoo request discipline, cache efficiency, database connection efficiency, trade-monitor overhead, instrumentation and database security.

The implementation must preserve:

- Paper-only operation.
- Existing strategy IDs, strategy manifests, strategy parameters, indicators, entry/exit conditions and signal generation.
- Completed-candle ownership and freshness rules.
- Existing asset universe and account-routing behaviour.
- Risk sizing, leverage ceiling, stop-loss, take-profit, settlement and paper-trade lifecycle semantics.
- Existing signal identity, delivery limits, Telegram message contracts and dashboard API contracts.
- All currently open paper trades and their stored state.
- Yahoo Finance as the configured market-data provider.
- Existing cache data until a replacement has been proven equivalent.

No trading rule may be changed as an incidental consequence of infrastructure work. If a proposed fix would change an entry, exit, price source, freshness threshold, trade-monitor cadence or instrument identity, it is out of scope unless a separate explicit decision is recorded.

## 2. Verified repository and production facts

### Repository

- Repository: `shauryananda33-gif/Multibot`
- Default branch: `main`
- Inspected HEAD: `c5e6c514886c8caaafb92ba01e58e1df5a2c7636`
- No open pull requests were returned by GitHub at audit time.
- The root tree contains the runtime, strategies, dashboard, migrations and test suite. The current code is materially newer than the historical v3.2.6 Ponytail audit document.

### Important current-code facts

1. `main.py` already creates a single `YahooProvider` for the active `StrategyService`, injects the shared database into it, and creates one `TradeMonitor`.
2. Runtime leadership already exists: database-backed `runtime_leases`, 60-second TTL, 15-second renewal, a 5-second verification cache, fail-closed leadership checks, standby mode and orderly shutdown.
3. `yahoo_provider.py` already has per-symbol locks, memory/persistent cache, compatible in-memory lookback reuse, symbol backoff, provider-wide backoff for recognized rate-limit exceptions, and stale fallback.
4. A single empty Yahoo DataFrame currently activates only a symbol cooldown. This is deliberate because an empty response can also mean unsupported history or an unavailable instrument/timeframe. The current test explicitly protects unrelated symbols from a one-off empty Gold response.
5. `strategy_service.py` requests a 1-minute quote for directional signals and the trade monitor. The 1-minute memory TTL is 45 seconds. The monitor loop is configured at 20 seconds; this does not mean every 20-second pass necessarily reaches Yahoo.
6. `supabase_db.py` is the production database adapter. It subclasses the SQLite-compatible API in `db.py`, connects with psycopg to Supabase Postgres, and currently opens a new psycopg connection for each `_connect()`.
7. `main.py` imports `DatabaseManager` from `supabase_db.py`. The base data-access methods and SQLite test schema are in `db.py`.
8. `schema.sql` and `supabase/schema.sql` explicitly identify themselves as legacy snapshots. The production migration is `supabase/migrations/20261125000000_initial_multibot_schema.sql`.
9. The production migration creates a private `multibot` schema and revokes schema/table access from `PUBLIC`, `anon` and `authenticated`. A live read-only privilege check confirmed no schema USAGE and no SELECT privilege for `anon` or `authenticated` on `multibot.trades`. The application connection role was `postgres` with `BYPASSRLS=true`.
10. Supabase currently reports RLS disabled on all 13 tables in `multibot`. This is a defense-in-depth gap and triggers a critical advisor finding, even though the live privilege check did not find grants exposing those tables to `anon` or `authenticated`.
11. Supabase security advisors also report `public.rls_auto_enable()` as a SECURITY DEFINER function executable by `PUBLIC`, `anon` and `authenticated`. It is attached to the enabled `ensure_rls` DDL event trigger. This function's execute grants must be narrowed without disabling the event trigger.
12. Current Render configuration in `render.yaml` specifies the Free plan and `python main.py`. It documents an external 10-minute `/ping` job. An HTTP keepalive is not a substitute for an always-on worker entitlement and must not be treated as a guarantee that background work will run continuously.

These facts supersede stale documentation that describes Turso as the production database. The implementation must not reintroduce a Turso dependency.

## 3. System dependency map

The high-level dependency chain is:

```text
main.py
 ├─ supabase_db.DatabaseManager
 │   └─ db.py (shared SQL/data-access methods and local SQLite implementation)
 │       └─ Supabase migration / SQLite schema / schema parity tests
 ├─ StrategyService
 │   ├─ StrategyEngine
 │   │   └─ YahooProvider
 │   │       ├─ memory cache + persistent cache
 │   │       ├─ bandwidth_metrics
 │   │       └─ DatabaseManager
 │   ├─ strategy registry / strategies/*
 │   ├─ SignalGate / signal lifecycle
 │   └─ NotificationService
 ├─ TradeMonitor
 │   ├─ StrategyService.current_price
 │   │   └─ same YahooProvider instance/cache
 │   ├─ DatabaseManager
 │   └─ NotificationService
 ├─ StrategyScheduler
 └─ dashboard/API + Telegram workers

market_data.py
 ├─ YahooProvider (including a helper path that can construct its own instance)
 ├─ candles.py
 └─ config.py

bandwidth_metrics.py
 └─ instrumentation used by Yahoo and Telegram HTTP boundaries
```

The implementation must keep a single process-wide request-coordination contract even if a helper constructs another provider instance. Strategy evaluation, Sweep, signal quote lookup and trade monitoring must all pass through that contract. No strategy should implement its own Yahoo retry/backoff logic.

## 4. File-by-file change specification

The list below distinguishes files expected to change from files that must be inspected and protected. The final diff must be limited to files justified by this dependency map.

### A. Yahoo request coordination and error classification

| File | Planned edit | Dependencies / impact that must be checked |
|---|---|---|
| `yahoo_provider.py` | Make the shared coordinator the single gate for every upstream Yahoo request. Add global minimum request spacing, FIFO/priority-aware admission, same-request deduplication across provider instances, and one shared provider cooldown. Keep existing per-symbol locks, TTLs, exponential backoff and stale fallback unless tests prove a defect. Persist only provider-wide cooldown transitions so a process restart does not immediately resume hammering Yahoo. | `strategy_engine.py`, `strategy_service.py`, `market_data.py`, `main.py`, `bandwidth_metrics.py`, all Yahoo tests. Do not hold a DB connection while waiting for the request gate or while Yahoo is in flight. |
| **New** `yahoo_request_coordinator.py` | Own process-wide pacing, request admission, request identity/deduplication, priority ordering and cooldown state. Keep it provider-agnostic enough to unit-test without yfinance. The coordinator must not create a background thread that can outlive the runtime. | Imported by `yahoo_provider.py`; tests must cover concurrent callers, priority ordering, cancellation/timeouts, no deadlocks and independent symbols. |
| `strategy_engine.py` | Pass an explicit request purpose/priority through the existing provider boundary. Do not alter strategy data-request period, interval or candle preparation. | `strategies/base.py`, every strategy implementation, `yahoo_provider.py`, strategy contract tests. |
| `strategy_service.py` | Distinguish a monitor quote from a signal/scan quote when calling `current_price`; monitor quotes receive the highest market-data priority. Keep the existing signal-entry fallback and all dispatch/trade logic unchanged. | `main.py`, `trade_monitor.py`, `strategy_engine.py`, strategy service tests, paper-trade persistence tests. |
| `market_data.py` | Ensure helper fetch paths use the same process-wide provider/coordinator instead of silently constructing an isolated rate-limit state. Preserve OHLC validation, quarantine and NSE/global candle construction exactly. | `yahoo_provider.py`, `candles.py`, `sweep_engine.py`, all market-data and completed-candle tests. |
| `config.py` | Add validated, environment-overridable coordinator settings (initial spacing, queue wait ceiling and cooldown escalation window). Defaults are conservative starting controls, not claims about Yahoo's published rate limit. No strategy constants change. | `yahoo_provider.py`, startup validation, config tests and Render env configuration. |
| `tests/test_yahoo_provider.py` | Extend coverage for one global gate across symbols and provider instances, explicit 429, recognized rate-limit exceptions, single ambiguous empty response, repeated ambiguous failures, invalid ticker, timeout, malformed response, stale fallback, cache hit and recovery after cooldown. | Keep the existing assertion that one empty `GC=F` response does not block `SBIN.NS`. A provider-wide escalation must require corroborating evidence, not one empty response. |
| **New** `tests/test_yahoo_request_coordinator.py` | Deterministic concurrency and timing tests using injected clocks/sleepers; no real delays or network calls. | Coordinator public contract and provider integration. |

**Classification policy:** Explicit HTTP 429 / recognized Yahoo rate-limit exception = provider-wide cooldown. One empty response = symbol-only cooldown. Repeated ambiguous empty responses may raise provider-wide suspicion only when they affect multiple otherwise-valid symbols in a bounded time window; the reason must remain labelled *suspected*, not *confirmed 429*. Invalid ticker/no-history cases remain symbol-specific. Timeout/network errors use bounded transient backoff. Malformed OHLC remains rejected.

**Priority policy:** open-trade monitor quote > due strategy scan quote > scheduled refresh > manual diagnostic/history request. Priority changes request order only; it must never bypass a global cooldown or cache freshness validation.

### B. Cache reuse and incremental persistence

| File | Planned edit | Dependencies / impact that must be checked |
|---|---|---|
| `yahoo_provider.py` | Add a canonical series lookup keyed by provider + exact Yahoo symbol + interval + validation/session contract. Persistent reads should reuse a compatible longer lookback when it fully covers the requested range. Keep the existing period-keyed JSON cache as a compatibility fallback during migration. | `db.py`, `supabase_db.py`, migration, market-data tests. Never mix symbols, intervals, providers or validation modes. |
| `db.py` | Add the new candle-series/candle-row data-access methods and local SQLite schema. Use bounded range reads and idempotent upserts. Keep existing `market_data_cache` methods intact for rollback and legacy cache restore. | Inherited by `supabase_db.DatabaseManager`; SQLite tests; migration parity. Avoid broad rewrites of the existing data-access API. |
| `supabase_db.py` | Ensure the new data methods run through the same PostgreSQL adapter and transaction wrapper. Update schema validation to require the new tables. Add bounded connection-pool lifecycle here (see database section). | `db.py`, psycopg/psycopg-pool dependency, `main.py`, Supabase migration, adapter tests. |
| **New migration** under `supabase/migrations/` | Create canonical market-series metadata and candle storage with a unique key on exact series identity + canonical candle timestamp. Add indexes only for actual range-read patterns. Migration must be additive; do not drop or rewrite the current JSON cache. Generate the migration filename with the Supabase CLI workflow rather than inventing a timestamp. | Production `multibot` schema; migration list; `supabase_db.py` expected-table check; `tests/test_schema_parity.py`. |
| `tests/test_db.py` | Test incremental upsert, duplicate idempotency, latest-candle revision, range coverage, empty history and no rewrite of unchanged candles. | SQLite implementation. |
| `tests/test_supabase_db_adapter.py` | Test Postgres SQL translation, row handling and new candle upsert/read SQL. | Adapter and migration column types. |
| `tests/test_schema_parity.py` | Extend expected table set and assert local schema, migration and adapter expectations agree. | `db.py`, `supabase_db.py`, migration. |
| **New** `tests/test_incremental_market_cache.py` | Verify old JSON cache fallback, canonical cache hit across lookback sizes, exact symbol/interval/source separation, incomplete-candle handling and cache recovery. | Provider, database, `market_data.py`, `candles.py`. |

Do not switch all reads to the new cache until parity tests prove that it returns the same validated candle frame as the existing cache for the same symbol, interval, period and timestamp boundary. Keep the old JSON cache available for rollback. Do not delete existing cache rows as part of this remediation.

### C. Supabase connection efficiency and persistence safety

| File | Planned edit | Dependencies / impact that must be checked |
|---|---|---|
| `supabase_db.py` | Replace per-operation fresh `psycopg.connect()` with a small bounded process-local `psycopg_pool.ConnectionPool`. Preserve the sqlite-compatible `_PostgresConnection` contract; connection context exit must return connections to the pool, commit on success and rollback on failure. Add health/closed-state handling and an explicit `close()`. Do not share one raw connection concurrently across threads. | `db.py` API, psycopg version, thread concurrency in WSGI/workers, main shutdown, retry semantics, tests. |
| `requirements.txt` | Add the compatible psycopg pool extra/package and pin a tested version range consistent with current psycopg 3.2.9. | `pyproject.toml`, Render build, CI. |
| `pyproject.toml` | Keep runtime dependencies in sync with `requirements.txt`; do not add an unrelated dependency. | CI install and Render editable install. |
| `main.py` | Close the database pool only after dashboard and operational workers have drained. Do not close it while a worker can still use it. Preserve lease-release ordering: workers stop first, then release lease, then close pool. | `supabase_db.py`, runtime lifecycle tests, Render SIGTERM path. |
| `db.py` | Retain the current shared data-access methods and SQLite fallback. Clarify stale Turso naming/comments only where needed to describe the inherited compatibility layer accurately; do not remove compatibility methods that the Supabase adapter and tests still use. | All imports of `db.py`, `supabase_db.py`, `calendar_store.py`, tests with legacy names. |
| `tests/test_supabase_db_adapter.py` | Add pool checkout/return, bounded maximum, concurrent use, rollback, broken-connection replacement, pool close and retry tests. | Pool wrapper lifecycle. |
| `tests/test_runtime_lifecycle.py` | Verify pool closes after all workers stop and no worker accesses a closed pool. | `main.py`, `supabase_db.py`. |

Do not add a pool without an explicit upper bound. Initial pool sizing should be small (for example, max 4 per active process) and then checked against Supabase connection limits and Render memory. The Supabase session pooler remains the network endpoint; the client pool is an additional reuse layer, not a replacement.

### D. Trade-monitor and scheduler efficiency

| File | Planned edit | Dependencies / impact that must be checked |
|---|---|---|
| `trade_monitor.py` | Reuse the already-loaded OPEN-trade snapshot to calculate the returned active count instead of issuing a second full `load_trades("OPEN")` query at the end of every monitor pass. Keep SL/TP comparisons, settlement price, trade close ordering, account update and notification semantics byte-for-byte equivalent where possible. | `main.py`, `strategy_service.py`, `trading.py`, DB tests and trade-monitor tests. |
| `main.py` | Inject monitor-priority quote lookup into `TradeMonitor`. Keep current 20-second monitor cadence unless measurement proves it can change without altering protection. Add clear metrics for monitor duration, open-trade count, quote freshness and skipped/deferred quote reasons. | `trade_monitor.py`, `strategy_service.py`, `yahoo_provider.py`, runtime lifecycle. |
| `config.py` | Do not change `monitor_interval_seconds=20` or 1-minute quote TTL as part of the first integrated remediation. If any value is later changed, it needs a separate measured safety justification. | `main.py`, `yahoo_provider.py`, trade-monitor tests. |
| **New/extended** `tests/test_trade_monitor.py` | Assert one initial OPEN-trade read, no second count query, identical SL/TP trigger and settlement behavior, unavailable quote handling, multiple trades on one symbol and no duplicate close/notification. | `trade_monitor.py`, `trading.py`, database and notification fakes. |

The 20-second monitor loop is a protection cadence, not an instruction to fetch Yahoo every 20 seconds. The existing 45-second 1-minute memory TTL should continue to coalesce upstream requests. Do not increase the TTL or slow the monitor merely to improve a bandwidth chart.

### E. Runtime leadership and Render operations

| File | Planned edit | Dependencies / impact that must be checked |
|---|---|---|
| `main.py` | Keep the current database lease as the single runtime-owner mechanism. Add diagnostics around claim/renew/verify failures that distinguish transient database errors, true lease loss, expired lease and initialization failure. Ensure no exception path leaves a worker running after leadership is lost. Do not add a second leader mechanism. | `supabase_db.py`, `db.py`, `strategy_service.py`, `tests/test_runtime_lifecycle.py`, Render lifecycle. |
| `supabase_db.py` | Verify lease claim/renew SQL is atomic under PostgreSQL and the owner check uses the shared DB clock or a documented bounded clock-skew model. Keep owner-qualified release. | `main.py`, runtime lease tests, migration. |
| `tests/test_runtime_lifecycle.py` | Add Postgres-adapter-shaped tests for concurrent claims, lease expiry, takeover, transient connection failure, lost lease during scan, shutdown drain and exactly-one-worker ownership. | Main lifecycle and DB adapter. |
| `render.yaml` | Keep `python main.py` as the sole start command and keep `/ping` lightweight. Do not add more aggressive pings, duplicate workers or a second service as part of this change. Update only stale comments if needed. | Render deployment config and operational docs. |
| `docs/RUNTIME_LIFECYCLE_AUDIT.md` | Replace stale Turso wording with Supabase Postgres/session-pooler wording and document the actual lease/standby contract. | `main.py`, `supabase_db.py`, Render. |

**Platform boundary:** Render Free can suspend an idle web service. No Python code can turn a Free instance into a guaranteed always-on worker. The existing 10-minute external `/ping` job must not be described as guaranteed background-worker uptime. If uninterrupted scanning and trade monitoring are mandatory, the deployment needs an always-on Render runtime entitlement. This plan does not silently change billing or upgrade the service.

### F. Bandwidth and usage instrumentation

| File | Planned edit | Dependencies / impact that must be checked |
|---|---|---|
| `bandwidth_metrics.py` | Separate observed HTTP bytes, estimated decoded Yahoo payload bytes and estimated Postgres request/response payload bytes. Add component tags and bounded counters for DB reads/writes, cache hits/misses, provider requests, monitor quote requests and queue waits. Never label estimates as actual wire bytes. | `yahoo_provider.py`, `supabase_db.py`, `main.py`, tests. |
| `supabase_db.py` | Instrument query/parameter and returned-row payload estimates at the adapter boundary without logging SQL secrets, parameter contents or trade payloads. Keep instrumentation failure non-fatal. | `bandwidth_metrics.py`, connection pool wrapper, privacy review. |
| `yahoo_provider.py` | Record request count, cache source, backoff reason, stale age, estimated parsed bytes and time spent waiting for global admission. | Coordinator and metrics. |
| `main.py` | Emit bounded periodic operational summaries for scan duration, monitor duration, active lease state, queue wait and cache hit/miss. Do not persist high-frequency telemetry as rows in the primary trading tables. | Metrics, logging, runtime lifecycle. |
| `tests/test_bandwidth_metrics.py` | Verify categories remain distinct, counters are thread-safe, flush is bounded and no estimate is presented as actual wire traffic. | Metrics module. |

Render dashboard outbound bandwidth and Supabase project usage remain the authoritative allowance measurements. Application metrics explain which component caused activity; they are not a substitute for provider billing/usage meters.

### G. Supabase security and schema

| File | Planned edit | Dependencies / impact that must be checked |
|---|---|---|
| **New Supabase migration** | Enable RLS on all 13 private `multibot` tables as defense in depth. Do not add `anon` or `authenticated` policies and do not grant either role schema/table access. Confirm the production connection role remains `BYPASSRLS` (currently verified as `postgres`) so the server-side runtime continues to operate. Revoke EXECUTE on `public.rls_auto_enable()` from `PUBLIC`, `anon` and `authenticated`, while retaining the event-trigger registration and owner execution. | Current migration, live grants, Supabase advisors, adapter startup, SQL verification. |
| `supabase/migrations/20261125000000_initial_multibot_schema.sql` | Do not rewrite an already-applied migration. Keep it as historical baseline. Add a new forward-only migration for security and new cache schema. | Migration history and deployed DB. |
| `supabase_db.py` | Keep runtime connection in private `multibot` schema; no Supabase REST client or service-role key in browser code. | Environment config and SQL grants. |
| `tests/test_schema_parity.py` | Assert runtime tables remain private-schema objects and local schema contract is aligned. | Migration and DB methods. |
| **New** `tests/test_supabase_security_contract.py` | Test migration text for RLS on every private table, no anon/auth policies or grants, function EXECUTE revocation and preserved event trigger. Add live read-only SQL verification to the deployment checklist. | Supabase migration/advisors. |
| `docs/SUPABASE_DATABASE.md` | Document private schema, server-only Postgres connection, RLS defense-in-depth, role privileges and migration procedure. Explicitly distinguish live security facts from advisor heuristics. | Migration and current role checks. |

**Important security interpretation:** The current advisor labels the 13 RLS-disabled tables as exposed. A separate live SQL check returned no grants to `PUBLIC`, `anon` or `authenticated`, and those roles have no `USAGE` on `multibot`; the application role is `postgres` with `BYPASSRLS`. Do not tell the operator the data is currently publicly readable based only on the RLS warning. Still enable RLS as defense in depth. The exposed SECURITY DEFINER function is a separate confirmed advisor finding and must be fixed.

### H. Documentation and tests

| File | Planned edit | Dependencies / impact that must be checked |
|---|---|---|
| `AI_CONTEXT.md` | Update actual production architecture and operational invariants after implementation. | Final code and migration. |
| `README.md` | Correct stale database/runtime descriptions only; keep start/deploy commands consistent. | `main.py`, `render.yaml`, `supabase_db.py`. |
| `docs/RUNTIME_LIFECYCLE_AUDIT.md` | Correct Turso wording and document the current single-leader behavior and Render Free limitation. | Runtime implementation. |
| `docs/SUPABASE_DATABASE.md` | Document pool sizing, schema security and migration. | Supabase implementation. |
| `docs/PRODUCTION_INCIDENT_NOTES.md` | Record Yahoo empty-response vs confirmed rate-limit classification and the Gold `GC=F` incident without relabelling futures as spot. | Provider diagnostics. |
| `tests/test_yahoo_provider.py`, `tests/test_market_data.py`, `tests/test_sweep_market_data_errors.py`, `tests/test_runtime_lifecycle.py`, `tests/test_db.py`, `tests/test_supabase_db_adapter.py`, `tests/test_schema_parity.py`, `tests/test_main.py` | Extend existing contracts; do not delete or weaken existing assertions to make new behavior pass. | All code and migration changes. |
| `.github/workflows/ci.yml` | Ensure the complete Python suite and syntax checks run on the final branch; do not make CI skip existing tests. | Dependencies and tests. |

## 5. Files explicitly protected from trading-logic changes

These files must be read during implementation review, but are not expected to change:

- `strategies/adaptive_trend/strategy.py`
- `strategies/engulfing_66_sma/strategy.py`
- `strategies/sweep_v2/strategy.py`
- `strategies/base.py`
- `strategies/registry.py`
- `strategy_scheduler.py` (unless a verified scheduler defect is found)
- `trading.py`
- `signal_gate.py`
- `signal_lifecycle.py`
- `candles.py`
- `market_sessions.py`
- `release_notes.py`

No strategy implementation, manifest, indicator, risk formula, signal threshold, completed-candle rule or trade settlement function is part of the optimization.

## 6. Explicitly out of scope / do not touch without a separate finding

- `app.js`, `dashboard.html`, `styles.css`, `foundation.css`, `appearance-overrides.css`, `appearance.js`, `notifications.js`: no UI redesign is required for this infrastructure remediation.
- `schema.sql` and `supabase/schema.sql`: both are marked legacy; do not use them as the production migration source.
- `calendar_store.py`: inspect whether it is imported by a live path before changing it; it currently constructs `db.DatabaseManager` directly and must not be casually redirected or rewritten.
- `startup.py`: compatibility wrapper; do not create a second runtime entrypoint.
- `render.yaml`: do not change plan/billing, add extra worker services or rely on repeated pings as a substitute for always-on service.
- Gold ticker `GC=F`: do not replace with an OTC spot ticker. A UI label may be clarified as COMEX gold futures only if the display change is explicitly accepted; do not change the traded instrument.
- No new strategy, data provider, Redis, queue service or additional infrastructure service unless the dependency audit proves it is necessary and the operator approves the cost.

## 7. Integrated implementation and release contract (one coordinated change set)

There are no implementation phases in this plan. The work is one dependency-ordered engineering operation:

1. Reconfirm `main` HEAD and working tree; record the exact base SHA and existing open trades/lease state. Create one implementation branch from that exact SHA.
2. Complete the import/call-site scan for every file in Section 4. Record each caller and each public method signature that will change. If a file is not on a live dependency path, do not edit it.
3. Implement the coordinator, cache compatibility, pool lifecycle, monitor query reduction, metrics and security migration as one integrated change set. Keep schema changes additive and backward-compatible.
4. Apply the additive Supabase migration to the production schema immediately before deploying the code that requires the new tables. The code must retain the old cache path until the new schema is confirmed. Do not run destructive SQL or rewrite historical rows.
5. Run the full automated test suite and static checks on the complete branch. Do not merge or deploy if any required test is skipped, xfailed unexpectedly, or fails.
6. Review the complete diff against the protected trading files and compare strategy outputs using fixed fixtures. Any unexplained strategy-output difference blocks the release.
7. Create one reviewable pull request containing the plan-linked implementation and migration. Merge only after the complete change set passes.
8. Verify the exact deployed commit on Render, startup lease acquisition, one active leader, Telegram polling ownership, all strategy schedules, dashboard/API health, cache behavior, monitor behavior, Supabase migration state and resource metrics.
9. Preserve the prior commit and legacy cache for rollback. Rollback must not delete or mutate open trades. If schema has already been migrated, the additive tables can remain unused during code rollback.

No intermediate production deploys. No unrelated cleanup. No repeated speculative fixes. If a required dependency or external platform action cannot be verified, stop and report the precise blocker rather than entering a retry loop.

## 8. Required verification matrix

| Area | Required proof |
|---|---|
| Trading parity | Same strategy outputs for fixed historical fixtures before/after; no changes to strategy files or locked configuration. |
| Paper trades | Snapshot open trade IDs and payloads before release; prove unchanged after migration/deploy; prove no duplicate close/settlement. |
| Yahoo coordination | One shared spacing gate across symbols/instances; confirmed 429 global backoff; one empty Gold response remains symbol-only; repeated corroborated failures become labelled suspected provider outage; stale data is never labelled fresh. |
| Cache | Old JSON cache can still be read; new cache returns the same validated candles; no interval/symbol/provider mixing; no incomplete candle leaks into strategy evaluation. |
| Database pool | Bounded concurrent connections; connections returned after success/failure; no transaction leakage; retry is limited to idempotent operations. |
| Runtime leadership | Exactly one lease owner; standby cannot scan/monitor/poll Telegram; lease loss stops operational work; shutdown drains workers before releasing lease and closing pool. |
| Trade monitor | Same 20-second cadence and same SL/TP settlement semantics; fewer DB reads; monitor quote has priority but never bypasses provider cooldown. |
| Supabase security | RLS enabled on all 13 private tables; anon/auth have no schema USAGE or table grants; no public execute on SECURITY DEFINER event-trigger function; event trigger still functions; runtime postgres role can read/write. |
| Bandwidth | Render dashboard egress compared over equivalent market windows; Supabase egress/DB size/connection count recorded; app estimates are labelled estimates. |
| Regression | Full `pytest`; Python compile; JavaScript syntax check; release-doc check; CI green. |
| Deployment | Render deployed commit equals reviewed merge SHA; health endpoint works; logs show one leader; no restart/leader flapping; Telegram and dashboard work. |

## 9. Rollback triggers

Immediately stop rollout and roll back the application commit if any of these occur:

- Any open trade disappears, duplicates, changes state unexpectedly or settles differently.
- Any strategy produces a changed signal for the same fixture without an explicitly approved explanation.
- More than one process performs operational work.
- The active leader cannot renew or a standby process starts workers.
- Monitor quote freshness becomes worse than the existing contract.
- Cache returns a candle from a different symbol/interval/source or serves an incomplete candle as completed.
- Postgres pool exhaustion, transaction leakage or rising connection errors appear.
- Telegram command polling conflicts or duplicate notifications begin.
- Dashboard/API contract tests fail.
- Render or Supabase usage materially worsens without an explained trade-off.

## 10. Completion definition

This work is complete only when the single integrated branch passes the verification matrix, one reviewed commit is deployed, production is confirmed healthy, open paper trades are preserved, and before/after Render/Supabase measurements are recorded.

**The plan is not authorization to change strategy behavior, upgrade Render billing, or perform destructive database operations.**
