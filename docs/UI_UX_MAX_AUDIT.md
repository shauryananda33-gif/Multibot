# MULTIBOT2 — UX/UI Max Audit & Live Tools Verification Report

**Target:** `https://multibot-3hsb.onrender.com/`  
**Audited:** 2026-11-28  
**Method:** Live browser verification (1440×900 desktop & 390×844 mobile across Modern, Material 3, and Neo Brutalism) + source-code inspection (`dashboard.html`, `app.js`, `dashboard-live-wiring.js`, `notifications.js`, `styles.css`, `appearance-overrides.css`, `main.py`).

---

## 1. Executive Summary

The core runtime and API layer are healthy:
- **Zero HTTP 4xx/5xx errors** on read endpoints (`/` HTML, CSS, JS, `/api/dashboard`, `/api/settings`, `/api/notifications`, `/api/calendar`, `/api/backtest`).
- **Bandwidth optimizations verified live:** `/api/dashboard` returns `200 OK` on initial load and `304 Not Modified` on cached polls; all 5 accounts and 4 strategies (`Trend Pulse`, `Engulf 66 SMA`, `Engulf 66 SMA 5min`, `Sweep 4H`) render.
- **Zero JS console errors** across all 5 tabs and all 3 visual themes.

However, the live UI has **7 concrete functional/data bugs** and **6 high-impact UX/design gaps** that make the interface feel unfinished or misleading—especially around read-only public controls, mobile data density, Open Positions currency formatting, and `nifty_5m` / `Engulf 66 SMA 5min` parity.

---

## 2. UX/UI Max Critique (Beyond Generic "AI Slop")

### What Works Well
- **3-theme token architecture** (`Modern`, `Material 3`, `Neo Brutalism` × `Light`/`Dark` × 5 accents) is genuinely cohesive—no hard-coded hex leaks, crisp contrast in `Material 3 + Indigo + Dark` and `Neo Brutalism + Rose + Light`.
- **Desktop navigation rail** (`188px` left sidebar) and **mobile bottom bar** (`60px` fixed, `25px+` clearance) have zero horizontal overflow (`390px`) and zero bottom-clipping.

### What Feels Like "Template / AI-Slop" & Needs Elevation
1. **Fake-interactive controls on a read-only public dashboard:**
   Every `+ New asset`, `+ New account`, `+ New channel`, `Save`, and `Reset` button on Tools looks 100% enabled and editable, only to fail with `HTTP 403 ("Settings editing is disabled on this public dashboard.")` on click. Either lock/badge the Tools editors as **Read-Only** in public mode or gate them behind an explicit admin token unlock flow—never invite edits you immediately reject.
2. **Duplicate / inconsistent data renderers (`History` Open Positions):**
   Initial render uses `app.js` (flat cards with `View` button, no `₹` on entry). As soon as `/api/dashboard` completes, `dashboard-live-wiring.js` overwrites `#historyOpenTrades` with date-grouped accordions that **drop the `View` button**, **prefix `₹` onto Forex prices** (`Entry ₹1.31` on `GBP/USD`), and show `Live P/L —`. One canonical renderer should own Open Positions.
3. **Mobile (`390px`) hides the exact numbers a trader opens the app for:**
   In `History`, completed trade rows hide **Entry** and **P/L** on mobile, forcing a tap into `View` for every single trade. A compact 2-line card (Asset + Strategy on top; Entry -> Exit + **P/L** bolded on bottom) makes mobile immediately scannable without extra taps.
4. **Header & banner truncation on `390px`:**
   `MULTIBOT2 · PAPER` truncates to `MULTIBOT2 · ...`, `Daily P/L` subtitle truncates to `Latest completed ...`, and Calendar's `Saved 27 Nov 2026` truncates to `Saved 27 No...`. Shorten the mobile micro-copy (`PAPER`, `27 Nov`, `Fri P/L`) instead of relying on `text-overflow: ellipsis`.
5. **Overview `Risk Control (Locked limits)` contradicts the multi-account reality:**
   Overview shows `Account ₹1,00,000 | Risk / trade ₹2,000` (single-book default) right below `Account value ₹4,91,359.23` (5 books × ₹1,00,000). Either label it `Per-book default: ₹1,00,000` or show `5 Books · ₹5,00,000 total`.
6. **URL hash does not track active tab:**
   Switching between `Home`, `Signals`, `History`, `Calendar`, and `Tools` leaves URL at `/`, so browser Back/Refresh always drops the user back on `Home`.

---

## 3. Tools Page — Complete Settings Verification Matrix

Every section in **Tools** was tested live against `https://multibot-3hsb.onrender.com/`:

| Section | Live Test Result | Status | Root Cause / Finding |
|---|---|---|---|
| **Appearance** (Style, Accent, Theme, Compact, Reduce motion) | All 5 axes update `<html>` (`data-style`, `data-accent`, `data-theme`, `data-compact`, `data-reduce-motion`) and persist cleanly in `localStorage`. | ✅ **PASS** | Works end-to-end. |
| **Historical Backtest** | Tested `Engulf 66 SMA 5min` + `^NSEI` + `30d`: `GET /api/backtest` returned `200 OK`, `375 candles` (`2026-11-20` to `2026-11-27`), Start `₹1,00,000`, End `₹1,00,000`, `0` trades. | ⚠️ **PARTIAL BUG** | `Engulfing66SMA5m.data_request()` hardcodes `("5m", "5d")`, ignoring the `30d` period chosen in the Backtest UI. Should respect `period` when called from backtest (`5d`/`30d`/`60d`). |
| **Assets** (`25 shipped`) | Expands cleanly; `+ New asset` adds inline draft row; `Save` -> `POST /api/settings` `403`. `Reset` **does not remove** unsaved draft rows. | ⚠️ **BUG** | `Reset` only reloads saved values into existing rows or skips clearing client-side drafts; public `Save` is intentionally `403` (`main.py:882`). |
| **Accounts** (5 books) | All 5 books render. `nifty_5m` displays raw snake_case `nifty_5m` and shows a `Remove` button; helper copy still says *"the four built-in accounts cannot be deleted"*. `Reset` does not clear `+ New account` draft (`book_1`). `Save` -> `403`. | ❌ **BUG** | `app.js:417` `ACCOUNT_LABELS` is missing `nifty_5m: "Nifty 5m"`, built-in check/copy still assumes 4 accounts, and `Reset` doesn't purge unsaved drafts. |
| **Routing** (NY session hours + 5 rules) | Start/End `<select>` (`00:00`–`23:00`), `↑`/`↓` reorder, and rule toggles work in DOM. `Reset` fails to revert cleanly when drafts exist; `Save` -> `403`. | ⚠️ **PARTIAL** | Public `Save` intentionally `403`. |
| **Locked Rules** (`Execution contract`) | Renders read-only contract. | ❌ **STALE** | `dashboard.html` lists only 3 strategies (`Trend Pulse`, `Engulf 66 SMA`, `Sweep 4H`) and omits `Engulf 66 SMA 5min`. |
| **Notifications** (`Telegram`, `1/1 enabled`) | `+ New channel` adds Webhook card. **3 bugs:** (1) `Auth secret` prefills `[REDACTED]`, (2) event chips only toggle `aria-pressed` without `.active` class so pressed vs unpressed look identical, (3) `Reset` does not remove unsaved new channel. `Save` -> `POST /api/notifications` `403`. | ❌ **BUG** | `notifications.js:64,135` + `styles.css`/`appearance-overrides.css` expect `.active` class. |

---

## 4. Other Page Findings (`Signals` & `Calendar`)

- **Signals:** Empty state renders cleanly (`0 signals`), though two `Refresh` buttons appear in the same empty-state view.
- **Calendar:** `GET /api/calendar?date=2026-11-28&impact=All` returns `200 OK` (`CACHED`, `0` events). The empty state says *"No events match the selected date."*, but **no date picker or impact filter chips exist in the Calendar UI** to change `date` or `impact`.
- **What's New Modal:** `🛟` emoji in bullet 7 renders as a missing-glyph box (`□`) in the Linux/browser font stack.

---

## 5. Prioritized Fix Plan

### P0 — Functional & Data Accuracy Bugs
1. **`dashboard-live-wiring.js`**: Remove `₹` from `Entry` in Open Positions (only format `Risk` and `Live P/L` with `money()`), and keep a `View` button or let `app.js` own Open Positions.
2. **`app.js` & `dashboard.html`**: Add `nifty_5m: "Nifty 5m"` to `ACCOUNT_LABELS`, update built-in account list/copy from 4 to 5 (hide `Remove` on `nifty_5m`), and add `Engulf 66 SMA 5min` to Locked Rules.
3. **`notifications.js`**:
   - Do not prefill `[REDACTED]` in `Auth secret` on newly added channels (`secret: ""`, `has_secret: false`).
   - Add `.active` class alongside `aria-pressed="true"` on event chips and `Enabled` toggle so active states are visually unmistakable.
4. **`strategies/engulfing_66_sma_5m/strategy.py`**: Respect `period` in `data_request(symbol, period="5d")` (e.g. `return "5m", period if period in {"5d", "1mo", "30d", "60d"} else "5d"`) so Backtest `30d` actually fetches 30 days instead of 5 days.
5. **Read-only public mode clarity (`app.js` / `notifications.js`)**: When public editing is disabled, show a clear `"Read-only public dashboard"` notice and disable `Save` / `+ New` buttons (or add a working `Reset` that discards unsaved client drafts).

### P1 — UX & Mobile Polish
6. **Mobile (`390px`) History rows**: Show `Entry` and `P/L` on a compact 2-line row instead of hiding them behind `View`.
7. **Mobile micro-copy**: Shorten `MULTIBOT2 · PAPER` badge, `Daily P/L` subtitle (include date e.g. `Fri 27 Nov`), and Calendar `Saved` timestamp so none truncate with `...` at `390px`.
8. **Calendar UI**: Add date input + impact filter chips (`All`, `High`, `Medium`, `Low`) wired to `/api/calendar?date=...&impact=...`.
9. **URL hash routing**: Sync active tab to `#overview`, `#signals`, `#history`, `#calendar`, `#tools`.
10. **What's New emoji**: Replace `🛟` with `🛡️` in `release_notes.py`, `WHATS_NEW.md`, and `README.md`.
