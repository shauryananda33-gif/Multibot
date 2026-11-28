# What's New — MULTIBOT2 v3.5.0

Generated from release_notes.py.

- 🔇 Per-sweep scan noise is gone: the 🔎 Scan complete Telegram bubble is now strictly opt-in per channel, and stale, duplicate, reminder, account-limit and MARKET_DATA_ERROR evaluations stay silent while the dashboard and deliveries audit still record every evaluated signal.
- 🔔 Reminders & trade-close alerts fixed: NotificationService now applies the silence gate only to initial SIGNAL deliveries, preventing REMINDER and TRADE_CLOSED alerts from being suppressed.
- 📈 GitHub CSV candle cache: 1D/1H/30M candles load from local/GitHub CSV baselines and only tail-fetch recent bars from Yahoo Finance, bypassing Supabase candle storage.
- ⚡ Render & Supabase bandwidth cuts: dashboard snapshots cache for 180s with stable ETags (304 Not Modified), gzip compression (>=512B), 150-signal history cap, and slower idle polling.
- 🛠️ Scan error & trade monitor fixes: fixed MARKET_DATA_ERROR alert formatting (UnboundLocalError), null opened_at handling in trade settlement, and split re-download fallback.
- 🔐 Telegram chat ids are now secrets in the notifications card: the dashboard API redacts every channel target and secret, so a screenshot or API read can no longer expose your chat id.
- 🛟 The environment-default Telegram channel shows a Default chip instead of Remove, so the last working notification path cannot be deleted by accident, and editing it only changes the chat id.
- 📱 The notifications card was rebuilt into a compact three-line channel row with a scannable event grid, saving vertical space in Tools.
