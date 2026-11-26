# Yahoo candle-boundary audit

**Audit date:** 2026-11-26  
**Scope:** Yahoo Finance chart observations for the live Multibot symbols and the existing scheduler/provider contracts.  
**Decision:** Do not change generic scan scheduling or candle timestamp normalization in this PR without a complete, symbol-specific semantic test.

## What was inspected

The live universe and provider intervals were read from `config.py`, `strategies/sweep_v2/strategy.py`, `strategy_scheduler.py`, `yahoo_provider.py`, and `sweep_engine.py`.

- Sweep requests 1-hour data for NSE assets and 30-minute data for Gold, Forex and Crypto.
- Sweep builds its own configured 4-hour windows from provider timestamps; it requires every expected sub-bar and rejects incomplete windows.
- The generic `completed_candle` scheduler is elapsed-time based: it starts its timer at the first call and then waits the manifest timeframe. It is not aligned to an exchange session or a Yahoo timestamp.
- Trend Pulse uses daily Yahoo bars and drops the current session-date bar. Its daily schedule is a 24-hour interval, not a market-close event.

## Live Yahoo chart observations

The Yahoo chart endpoint was queried with `range=5d` on the audit date. These are point-in-time observations, not a permanent provider contract.

| Live symbol / group | Requested interval | Yahoo chart timezone metadata | Observed first timestamp(s) |
|---|---:|---|---|
| `RELIANCE.NS` (NSE) | 1h | `IST` / `Asia/Kolkata` | 2026-11-19 09:15, 10:15, 11:15 IST |
| `GC=F` (Gold) | 30m | `EST` / `America/New_York` | 30-minute epoch cadence; exchange trading periods use New York time |
| `EURUSD=X`, `GBPUSD=X`, `AUDUSD=X`, `USDJPY=X`, `NZDUSD=X`, `EURJPY=X` (Forex) | 30m | `Europe/London` | 30-minute epoch cadence |
| `BTC-USD` (Crypto) | 30m | `UTC` | 30-minute UTC epoch cadence |

Direct chart responses inspected:

- https://query1.finance.yahoo.com/v8/finance/chart/RELIANCE.NS?range=5d&interval=1h
- https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF?range=5d&interval=30m
- https://query1.finance.yahoo.com/v8/finance/chart/EURUSD%3DX?range=5d&interval=30m
- https://query1.finance.yahoo.com/v8/finance/chart/GBPUSD%3DX?range=5d&interval=30m
- https://query1.finance.yahoo.com/v8/finance/chart/AUDUSD%3DX?range=5d&interval=30m
- https://query1.finance.yahoo.com/v8/finance/chart/USDJPY%3DX?range=5d&interval=30m
- https://query1.finance.yahoo.com/v8/finance/chart/NZDUSD%3DX?range=5d&interval=30m
- https://query1.finance.yahoo.com/v8/finance/chart/EURJPY%3DX?range=5d&interval=30m
- https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?range=5d&interval=30m

The responses expose exchange/timezone metadata and epoch timestamps. The observations establish that the markets do not share one timezone or one session boundary. They do **not**, by themselves, conclusively establish whether every yfinance DataFrame index should be interpreted as a bar-open label or a bar-close label for every symbol and interval. That distinction must be proven before shifting timestamps or changing the scheduler.

## Why no scheduler patch was made

A generic wall-clock alignment would risk scanning a partial bar or skipping a completed one. In particular:

1. NSE has a defined 09:15-15:30 IST session and a shortened final interval.
2. Gold has a New York exchange timezone, a daily maintenance break and a weekend closure.
3. Forex uses a separate session calendar and Yahoo reports a London timezone for the inspected symbols.
4. Crypto is continuous and Yahoo reports UTC.
5. Yahoo's returned timestamp cadence is not enough to infer a completed candle without verifying each interval's timestamp-label semantics and the exact OHLC coverage of its first/last session bars.

The current code's market-session and completed-window gates remain in place. No entry/exit, sizing, SL/TP, signal, or Gold ticker behavior was changed.

## Required evidence before a future scheduling change

For each live symbol and requested interval, collect provider responses across multiple full sessions, including the open, close, maintenance break, weekend transition and DST transition where applicable. For every timestamp, compare the Yahoo epoch label with its actual OHLC interval and verify the last complete bar against the exchange session. Then add deterministic fixtures and tests for:

- timestamp label semantics (open vs close);
- shortened or missing session bars;
- completed-window eligibility immediately before, at and after each close;
- daylight-saving transitions for New York and London;
- restart/replay behavior when the service is down across one or more close events.

Until those tests pass, retain the current scheduler behavior rather than guessing.

## Release status and operational gates

- **Dependency lock:** Added `requirements.lock` with the complete runtime dependency version set resolved by the successful Python 3.12/Linux CI install on 2026-11-26. Added `requirements-test.lock` for the pinned test toolchain. Render and CI now install from these lockfiles; CI also runs `pip check` and tests that each direct dependency pin satisfies its declared version range. The lock pins package versions; it does not currently include artifact hashes.
- **Telegram migration:** Applied to production Supabase project `pmhmoekqdbozsczwbnlb` as migration version `20261126112433`. Verified both `multibot.telegram_updates` and `multibot.telegram_poll_state` exist and have RLS enabled. The repository migration filename was aligned to the exact applied version.
- The operator must confirm `DASHBOARD_API_TOKEN` is configured in the live Render service. The value must never be copied into chat or repository files.
- Deployment and merge remain operator-approved actions; this PR remains draft.
