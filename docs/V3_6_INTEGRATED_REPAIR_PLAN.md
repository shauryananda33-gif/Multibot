# v3.6.0 Integrated Repository Repair Plan

**Target:** preserve MULTIBOT2 / Mavis Dashboard v2 at **v3.6.0**. This is an in-place repair, not a redesign or strategy release.

## Dependency map and change order

| Order | Files | Dependency / contract | Planned change |
|---|---|---|---|
| 1. Release identity | `release_notes.py`, `pyproject.toml`, `MANIFEST.txt`, `WHATS_NEW.md`, `README.md`, `AI_REBUILD_SPEC.md` | `release_notes.APP_VERSION` is canonical; package, manifest and reconstruction spec must agree | Keep canonical version at 3.6.0; correct packaging metadata, shipped strategy inventory and five-account inventory |
| 2. Browser shell | `dashboard.html`, `main.py`, `styles.css`, `foundation.css`, `appearance-overrides.css` | HTML references static paths served by `main.build_app()`; CSS cascade order is base theme → geometry → appearance overrides | Load all three existing CSS layers in the approved order; cache JS/CSS with revalidation rather than a one-hour stale window; keep HTML and live API responses non-cacheable |
| 3. Dashboard runtime | `dashboard.html`, `app.js`, `main.py`, `dashboard.py` | `app.js` calls same-origin read-only `/api/dashboard`; server builds snapshot; frontend renders overview/signals/history | Verify every required DOM ID exists, response/error paths are explicit, initial fetch and manual retry work, and periodic refresh does not overlap or leave the page stuck in CONNECTING |
| 4. Account and strategy inventory | `config.py`, `bot_settings.py`, `strategies/registry.py`, `docs/LOCKED_RULES.md`, `MANIFEST.txt`, account/registry tests | Config is source of truth for built-in books and strategy registry is source of truth for shipped strategy IDs | Document/test all five built-in books and four shipped strategies, including `nifty_5m` and `engulfing_66_sma_5m`; preserve account limits and routing |
| 5. Historical backtest | `backtest.py`, `strategies/base.py`, strategy-specific `strategy.py`, `yahoo_provider.py`, PR #12 and parity tests | Batch signals must equal prefix-by-prefix reference signals; simulation owns trade ordering, sizing, limits and stop/target tie-breaking | Rebase/evaluate PR #12 on current v3.6.0; retain only parity-proven batch paths; keep Sweep on reference path until equivalent semantics are proven |
| 6. Yahoo historical cache | `yahoo_provider.py`, `tests/test_yahoo_cache_json.py`, cache fixtures | CSV cache is consulted before upstream Yahoo; incremental tail merges must preserve period coverage and OHLC integrity | Fix the fresh-CSV lookback boundary regression; add coverage for cache hit, stale tail refresh, merge, and insufficient lookback; do not weaken data validation |
| 7. Regression suite | `tests/test_api_contract.py`, `tests/test_frontend_syntax.py`, `tests/test_dashboard_ui.py`, `tests/test_appearance_system.py`, `tests/test_contrast_tokens.py`, `tests/test_visual_consistency_audit.py`, `tests/test_main.py`, `tests/test_bot_settings.py`, `tests/test_notification_channels.py` | Tests must describe the actual v3.6 terminal/neo/modern DOM and current API, not superseded Material 3/legacy markup | Replace obsolete selectors and assumptions with assertions against the current shipped HTML, CSS cascade, JavaScript assets, public read-only API, current accounts and registry; keep behavioral/security checks |
| 8. Release verification | `.github/workflows/ci.yml`, GitHub PR checks, Render service | Merge is gated by full CI; Render must run the merged main SHA | Require full green CI, deploy v3.6.0, verify public pages and same-origin dashboard API, then inspect live rendered data and logs |

## Explicit non-goals / invariants

- Do not change `APP_VERSION = 3.6.0`.
- Do not change the paper-only execution model, market universe, signal freshness, duplicate-send cap, position sizing, risk limits, completed-candle rules, strategy parameters or strategy routing.
- Do not add a token prompt or credential to public viewing pages. Read-only views remain public; no admin credential UI is introduced.
- Do not reset, migrate destructively, truncate or otherwise alter the production Supabase database.
- Do not load orphaned legacy UI scripts just to satisfy stale tests. In particular, `appearance.js` uses a different style/storage contract, and `dashboard-live-wiring.js` targets a DOM node not present in the v3.6 shell; only integrate a script if its dependencies and DOM contract are valid.
- Do not merge PR #12 until its base is current and the complete test suite plus batch/reference parity tests pass.

## Acceptance criteria

1. Package, manifest, docs and runtime all identify v3.6.0.
2. The HTML loads the intended CSS layers in order and static assets revalidate after a deploy.
3. All public viewing pages open without a token; same-origin read-only dashboard data returns successfully; cross-origin reads remain rejected.
4. Every dashboard selector used by `app.js` exists in the served HTML; JavaScript parses; failed initial loads show a usable retry path.
5. All five built-in accounts and four built-in strategies are represented consistently.
6. CSV baseline cache hits without a Yahoo request when coverage is sufficient; incremental tail merge tests pass.
7. Batch backtest signals match the reference implementation exactly; trade simulation and safety constraints remain unchanged.
8. CI is green before merge; Render's live deployment is the merged commit and v3.6.0 dashboard renders populated account/trade/scan data.
