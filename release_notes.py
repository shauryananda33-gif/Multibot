"""Canonical release metadata and What's New source for MULTIBOT2."""
from __future__ import annotations
from typing import Final

APP_VERSION: Final[str] = "3.6.0"

RELEASE_HIGHLIGHTS: Final[tuple[str, ...]] = (
    "🎨 Redesigned Mavis Dashboard v2: 3 distinct visual styles (Terminal, Neo Brutalism, Modern glassmorphism), Dark/Light modes, 5 accent-reactive palettes, and 4 background patterns (Plain, Grid, Dots, Glow).",
    "📱 Mobile-first workspace: compact Home product banner, split-pane overview, 5-equal mobile bottom nav, inline compact trade detail expansion, and color-coded Economic Calendar impact cards (High/Medium/Low).",
    "🧪 Backtest Signals & Trades ledger: displays all directional signals generated (Entry/SL/TP + reason) and all completed trades (Entry/Exit/bars + P/L), with collapsible Backtest and Clear controls.",
    "📈 New Engulf 66 SMA 5min strategy & dedicated nifty_5m account (20 daily limit, 10 max trades/asset/day), with period-aware Yahoo candle fetching in backtests.",
    "🔇 Per-sweep scan noise is gone: Scan complete Telegram alerts stay opt-in per channel, while reminders and trade-close notifications remain active.",
    "⚡ Render & Supabase bandwidth cuts: 180s snapshot cache with stable ETags (304), gzip compression (>=512B), 150-signal history cap, and redacted Telegram channel secrets.",
)

def markdown_whats_new() -> str:
    lines = [f"# What's New — MULTIBOT2 v{APP_VERSION}", "", "Generated from release_notes.py.", ""]
    lines.extend(f"- {item}" for item in RELEASE_HIGHLIGHTS)
    return "\n".join(lines) + "\n"

def telegram_whats_new() -> str:
    body = "\n".join(f"• {item}" for item in RELEASE_HIGHLIGHTS)
    return f"🆕 *WHAT'S NEW — MULTIBOT2 v{APP_VERSION}*\n━━━━━━━━━━━━━━━━\n{body}\n━━━━━━━━━━━━━━━━"

__all__ = ["APP_VERSION", "RELEASE_HIGHLIGHTS", "markdown_whats_new", "telegram_whats_new"]
