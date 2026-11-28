"use strict";

const $ = (id) => document.getElementById(id);
const $$ = (sel) => [...document.querySelectorAll(sel)];
const ACCT_LABELS = { macro: "Macro", nifty: "Nifty", nifty_5m: "Nifty 5m", ny_session: "NY session", sweep_4h: "Sweep 4H" };
const acctName = (k) => ACCT_LABELS[String(k || "").toLowerCase()] || String(k || "—");
const esc = (v) => String(v ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
const inr = (v) => { const n = Number(v); return Number.isFinite(n) ? `${n < 0 ? "−" : ""}₹${Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: 2 })}` : "—"; };
const px = (v) => { const n = Number(v); if (!Number.isFinite(n)) return "—"; const d = Math.abs(n) >= 100 ? 2 : Math.abs(n) >= 10 ? 3 : 4; return n.toLocaleString("en-IN", { maximumFractionDigits: d }); };
const tsFmt = (v) => { if (!v) return "—"; const d = new Date(v); return Number.isNaN(d.getTime()) ? "—" : new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false }).format(d); };
const dayKey = (v) => { if (!v) return "unknown"; const d = new Date(v); return Number.isNaN(d.getTime()) ? "unknown" : new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(d); };
const dayLabel = (k) => k === "unknown" ? "Unknown" : new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", weekday: "short", day: "2-digit", month: "short" }).format(new Date(`${k}T00:00:00`));

const state = {
  page: "overview",
  histTab: "open",
  data: null,
  etag: null,
  calendar: null,
  calDate: new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date()),
  calImpact: "All",
  settings: null,
  dashboardLoading: false,
};

function applyPrefs() {
  const root = document.documentElement;
  root.dataset.style = localStorage.getItem("v2-style") || "terminal";
  root.dataset.theme = localStorage.getItem("v2-theme") || "dark";
  root.dataset.accent = localStorage.getItem("v2-accent") || "emerald";
  root.dataset.bg = localStorage.getItem("v2-bg") || "grid";
  root.dataset.compact = localStorage.getItem("v2-compact") || "false";
  root.dataset.reduceMotion = localStorage.getItem("v2-motion") || "false";
  $$("[data-style-set]").forEach((b) => b.classList.toggle("active", b.dataset.styleSet === root.dataset.style));
  $$("[data-theme-set]").forEach((b) => b.classList.toggle("active", b.dataset.themeSet === root.dataset.theme));
  $$("[data-accent-set]").forEach((b) => b.classList.toggle("active", b.dataset.accentSet === root.dataset.accent));
  $$("[data-bg-set]").forEach((b) => b.classList.toggle("active", b.dataset.bgSet === root.dataset.bg));
  $("compactBtn")?.classList.toggle("active", root.dataset.compact === "true");
  $("motionBtn")?.classList.toggle("active", root.dataset.reduceMotion === "true");
  const quickLabels = { terminal: "TERM", neo: "NEO", modern: "MOD" };
  $("styleQuickBtn").textContent = quickLabels[root.dataset.style] || "TERM";
  const cap = (s) => s ? s[0].toUpperCase() + s.slice(1) : "";
  const styleNames = { terminal: "Terminal", neo: "Neo Brutalism", modern: "Modern" };
  if ($("appearSummary")) {
    $("appearSummary").textContent = `${styleNames[root.dataset.style] || "Terminal"} · ${cap(root.dataset.theme)} · ${cap(root.dataset.accent)} · ${cap(root.dataset.bg)}`;
  }
}

function setPage(p) {
  const valid = ["overview", "signals", "history", "calendar", "tools"].includes(p) ? p : "overview";
  state.page = valid;
  $$(".page").forEach((el) => el.classList.toggle("active", el.id === `page-${valid}`));
  $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.page === valid));
  if (location.hash !== `#${valid}`) history.replaceState(null, "", `#${valid}`);
  if (valid === "calendar" && !state.calendar) loadCalendar();
  if (valid === "tools" && !state.settings) loadTools();
}

function equitySvg(points) {
  if (!points || points.length < 2) return `<div class="empty-box">Not enough points</div>`;
  const vals = points.map((p) => Number(p.equity) || 0);
  const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const w = 600, h = 110, pad = 6;
  const coords = vals.map((v, i) => [pad + (i / (vals.length - 1)) * (w - pad * 2), h - pad - ((v - min) / span) * (h - pad * 2)]);
  const line = coords.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} L${coords[coords.length - 1][0].toFixed(1)},${h} L${coords[0][0].toFixed(1)},${h} Z`;
  const color = vals[vals.length - 1] >= vals[0] ? "var(--pos)" : "var(--neg)";
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><path d="${area}" fill="${color}" fill-opacity="0.10"/><path d="${line}" fill="none" stroke="${color}" stroke-width="2"/></svg>`;
}

function tradeRowHtml(t, idx) {
  const plan = t.plan || t;
  const side = String(plan.side || t.type || "").toUpperCase();
  const isClosed = String(t.status || "OPEN").toUpperCase() === "CLOSED";
  const pnl = Number(t.pnl);
  const sym = t.label || t.symbol || "Trade";
  const rightVal = isClosed ? inr(pnl) : inr(t.planned_risk ?? plan.planned_risk);
  const rightCls = isClosed ? (pnl >= 0 ? "pos" : "neg") : "";
  return `<article class="ledger-row" data-trade-card="${idx}">
    <div class="row-top">
      <span class="row-title"><b>${esc(sym)}</b><small class="row-meta">${esc(plan.strategy || t.strategy || "")}</small></span>
      <span class="row-actions">
        <span class="badge ${side === "BUY" ? "buy" : "sell"}">${esc(side || "—")}</span>
        <button class="btn-mini" type="button" data-trade-idx="${idx}" aria-expanded="false">View</button>
      </span>
    </div>
    <div class="row-bot row-meta">
      <span>Entry ${px(plan.entry ?? t.entry)}${isClosed ? ` → ${px(t.exit_price)}` : ""}</span>
      <span class="mono ${rightCls}">${isClosed ? "P/L " : "Risk "}${rightVal}</span>
    </div>
    <div class="inline-detail" hidden></div>
  </article>`;
}

function signalRowHtml(s) {
  const dir = String(s.signal || s.direction || "NO_SIGNAL").toUpperCase();
  return `<article class="ledger-row">
    <div class="row-top">
      <span class="row-title">${esc(s.symbol)} <small class="row-meta">${esc(s.strategy || "")} · ${esc(s.timeframe || "")}</small></span>
      <span class="badge ${dir === "BUY" ? "buy" : "sell"}">${esc(dir)}</span>
    </div>
    <div class="row-bot row-meta">
      <span>E ${px(s.entry)} · SL ${px(s.stop_loss)} · TP ${px(s.take_profit)}</span>
      <span>${esc(s.pipeline_status || s.freshness || tsFmt(s.timestamp))}</span>
    </div>
  </article>`;
}

function renderOverview() {
  const d = state.data; if (!d) return;
  const accts = Array.isArray(d.accounts?.data) ? d.accounts.data : [];
  const trades = Array.isArray(d.trades) ? d.trades : [];
  const open = trades.map((t, i) => ({ t, i })).filter((x) => String(x.t.status).toUpperCase() === "OPEN");
  const closed = trades.filter((t) => String(t.status).toUpperCase() === "CLOSED");
  const sigs = (Array.isArray(d.signals) ? d.signals : []).filter((s) => ["BUY", "SELL"].includes(String(s.direction || s.signal).toUpperCase()));
  const active = sigs.filter((s) => s.actionable || String(s.freshness).toUpperCase() === "FRESH");

  const start = accts.reduce((a, x) => a + Number(x.starting_balance || 0), 0) || 100000;
  const eq = accts.reduce((a, x) => a + Number(x.balance || 0), 0) || start;
  const pnl = closed.reduce((a, x) => a + Number(x.pnl || 0), 0);

  $("ovEquity").textContent = inr(eq);
  if ($("bannerEquity")) $("bannerEquity").textContent = inr(eq);
  $("ovPnl").textContent = inr(pnl);
  $("ovPnl").className = pnl >= 0 ? "pos" : "neg";
  $("ovOpen").textContent = String(open.length);
  $("ovSignals").textContent = String(active.length);

  const scan = d.scan || {};
  $("ovScanBar").textContent = String(scan.status).toUpperCase() === "COMPLETE"
    ? `Scan ${tsFmt(scan.at)} · ${scan.checked || 0} chk · ${scan.directional || 0} dir · ${scan.sent || 0} sent`
    : "No scan yet";

  $("ovAccounts").innerHTML = accts.map((a) => {
    const mine = closed.filter((t) => String(t.account || "").toLowerCase() === a.name.toLowerCase());
    const apnl = mine.reduce((s, t) => s + Number(t.pnl || 0), 0);
    return `<button class="acct-line" type="button" data-page-link="history">
      <b>${esc(acctName(a.name))}</b>
      <span>${inr(a.balance)}</span>
      <span class="${apnl >= 0 ? "pos" : "neg"}">${inr(apnl)}</span>
      <span class="row-meta">${a.trades_today || 0}/${a.daily_trade_limit || 0} · ${mine.length}c</span>
    </button>`;
  }).join("");

  const pts = [{ equity: start }];
  closed.slice().sort((a, b) => String(a.closed_at || "").localeCompare(String(b.closed_at || ""))).forEach((t) => pts.push({ equity: pts[pts.length - 1].equity + Number(t.pnl || 0) }));
  if (pts.length === 1) pts.push({ equity: eq });
  $("ovEqVal").textContent = inr(eq);
  $("ovEqSub").textContent = `${closed.length} closed`;
  $("ovEqChart").innerHTML = equitySvg(pts);

  $("ovOpenList").innerHTML = open.length ? open.map((x) => tradeRowHtml(x.t, x.i)).join("") : `<div class="empty-box">No open positions</div>`;
  $("ovSigList").innerHTML = active.length ? active.slice(0, 5).map(signalRowHtml).join("") : `<div class="empty-box">No active signals</div>`;
  $("whatsNewList").innerHTML = (d.whats_new || []).map((w) => `<li>${esc(w)}</li>`).join("");
  $("whatsNewTitle").textContent = `What's New — v${d.version || "3.5.0"}`;
}

function renderSignals() {
  const sigs = (state.data?.signals || []).filter((s) => ["BUY", "SELL"].includes(String(s.direction || s.signal).toUpperCase()));
  $("sigCount").textContent = `${sigs.length} directional`;
  if (!sigs.length) { $("sigList").innerHTML = `<div class="empty-box">No directional signals recorded yet.</div>`; return; }
  const groups = new Map();
  sigs.forEach((s) => { const k = dayKey(s.timestamp); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(s); });
  $("sigList").innerHTML = [...groups.entries()].sort((a, b) => b[0].localeCompare(a[0])).map(([k, rows], i) => `
    <details class="date-acc" ${i === 0 ? "open" : ""}>
      <summary><span>${esc(dayLabel(k))}</span><small>${rows.length} signal${rows.length === 1 ? "" : "s"}</small></summary>
      <div class="date-acc-body">${rows.map(signalRowHtml).join("")}</div>
    </details>`).join("");
}

function renderHistory() {
  const trades = Array.isArray(state.data?.trades) ? state.data.trades : [];
  const open = trades.map((t, i) => ({ t, i })).filter((x) => String(x.t.status).toUpperCase() === "OPEN");
  const closed = trades.map((t, i) => ({ t, i })).filter((x) => String(x.t.status).toUpperCase() === "CLOSED");
  const scans = Array.isArray(state.data?.scan_history) ? state.data.scan_history : [];

  const wins = closed.filter((x) => Number(x.t.pnl) > 0).length;
  const dates = closed.map((x) => dayKey(x.t.closed_at || x.t.opened_at)).filter((k) => k !== "unknown").sort();
  const lastDay = dates[dates.length - 1];
  const dayPnl = lastDay ? closed.filter((x) => dayKey(x.t.closed_at || x.t.opened_at) === lastDay).reduce((s, x) => s + Number(x.t.pnl || 0), 0) : 0;

  $("histSummary").textContent = `${open.length} open · ${closed.length} closed · ${scans.length} scans`;
  $("histClosed").textContent = String(closed.length);
  $("histDailyLbl").textContent = lastDay ? `${dayLabel(lastDay)} P/L` : "DAY P/L";
  $("histDailyPnl").textContent = lastDay ? inr(dayPnl) : "—";
  $("histDailyPnl").className = lastDay ? (dayPnl >= 0 ? "pos" : "neg") : "";
  $("histWinRate").textContent = closed.length ? `${Math.round((wins / closed.length) * 100)}%` : "—";

  $("histOpenCount").textContent = String(open.length);
  $("histClosedTabCount").textContent = String(closed.length);
  $("histScanCount").textContent = String(scans.length);

  $("histPanelOpen").innerHTML = open.length ? `<div class="pane-section">${open.map((x) => tradeRowHtml(x.t, x.i)).join("")}</div>` : `<div class="empty-box">No open positions</div>`;

  const cGroups = new Map();
  closed.forEach((x) => { const k = dayKey(x.t.closed_at || x.t.opened_at); if (!cGroups.has(k)) cGroups.set(k, []); cGroups.get(k).push(x); });
  $("histPanelClosed").innerHTML = closed.length ? [...cGroups.entries()].sort((a, b) => b[0].localeCompare(a[0])).map(([k, rows], i) => `
    <details class="date-acc" ${i === 0 ? "open" : ""}>
      <summary><span>${esc(dayLabel(k))}</span><small>${rows.length} trade${rows.length === 1 ? "" : "s"}</small></summary>
      <div class="date-acc-body">${rows.map((x) => tradeRowHtml(x.t, x.i)).join("")}</div>
    </details>`).join("") : `<div class="empty-box">No completed trades</div>`;

  $("histPanelScans").innerHTML = scans.length ? `<div class="pane-section">${scans.slice(0, 30).map((s) => {
    const p = s.payload || {};
    return `<article class="ledger-row"><div class="row-top"><span class="row-title">${esc(s.strategy_id)}</span><span class="badge closed">${esc(s.status || "OK")}</span></div><div class="row-bot row-meta"><span>${tsFmt(s.finished_at || s.started_at)}</span><span>${p.checked || 0} chk · ${p.directional || 0} dir · ${p.sent || 0} sent</span></div></article>`;
  }).join("")}</div>` : `<div class="empty-box">No scan history</div>`;
}

async function loadCalendar() {
  $("calStatusText").textContent = "Loading…";
  try {
    const r = await fetch(`/api/calendar?date=${encodeURIComponent(state.calDate)}&impact=${encodeURIComponent(state.calImpact)}`, { cache: "no-store" });
    state.calendar = await r.json();
    const c = state.calendar || {}, cnt = c.counts || {}, items = c.items || [];
    $("calStatusText").textContent = `${c.status || "OK"}${c.fetched_at ? ` · ${tsFmt(c.fetched_at)}` : ""}`;
    $("calAll").textContent = String((cnt.high || 0) + (cnt.medium || 0) + (cnt.low || 0) + (cnt.holiday || 0) || items.length);
    $("calHigh").textContent = String(cnt.high || 0);
    $("calMed").textContent = String(cnt.medium || 0);
    $("calLow").textContent = String((cnt.low || 0) + (cnt.holiday || 0));
    $("calList").innerHTML = items.length ? items.map((ev) => {
      const imp = String(ev.impact || "low").toLowerCase();
      const impCls = imp.includes("high") ? "high" : imp.includes("med") ? "medium" : "low";
      return `<details class="date-acc cal-card impact-${impCls}">
        <summary><span><b class="mono">${esc(ev.time || "All day")}</b> · <b class="cal-cur">${esc(ev.currency || "")}</b> · ${esc(ev.title)}</span><span class="badge ${impCls}">${esc(ev.impact || "Low")}</span></summary>
        <div class="date-acc-body row-meta">Actual: ${esc(ev.actual || "—")} · Forecast: ${esc(ev.forecast || "—")} · Prev: ${esc(ev.previous || "—")}</div>
      </details>`;
    }).join("") : `<div class="empty-box">${esc(c.message || "No events for selected date/filter.")}</div>`;
  } catch (e) { $("calStatusText").textContent = e.message; }
}

async function loadTools() {
  const d = state.data || {};
  const strats = d.strategies || [];
  $("btStrategy").innerHTML = strats.map((s) => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join("");
  const fillBtSymbols = () => {
    const sid = $("btStrategy").value;
    const st = strats.find((x) => x.id === sid);
    const allowed = new Set(st?.assets || []);
    const all = d.backtest_assets || [];
    const list = allowed.size ? all.filter((a) => allowed.has(a.key) || allowed.has(a.ticker)) : all;
    $("btSymbol").innerHTML = list.map((a) => `<option value="${esc(a.key || a.ticker)}">${esc(a.label)}</option>`).join("");
  };
  fillBtSymbols();
  $("btStrategy").onchange = fillBtSymbols;

  const accts = d.accounts?.data || [];
  $("toolsAcctCount").textContent = `${accts.length} books`;
  $("toolsAccounts").innerHTML = accts.map((a) => `
    <div class="ledger-row"><div class="row-top"><span class="row-title">${esc(acctName(a.name))}</span><span class="mono">${inr(a.balance)}</span></div>
    <div class="row-bot row-meta"><span>Start ${inr(a.starting_balance)} · Risk ${inr(a.risk_per_trade || 2000)}</span><span>${a.trades_today || 0}/${a.daily_trade_limit || 0} trades</span></div></div>`).join("");

  $("toolsStratCount").textContent = `${strats.length} strategies · ${(d.universe?.count || 25)} assets`;
  $("toolsContract").innerHTML = strats.map((s) => `
    <div class="ledger-row"><div class="row-top"><span class="row-title">${esc(s.name)} <small class="row-meta">v${esc(s.version)}</small></span><span class="badge closed">${esc((s.timeframes || []).join(","))}</span></div>
    <div class="row-bot row-meta"><span>${(s.assets || []).length} assets</span><span>Books: ${esc([...new Set(Object.values(s.routes || {}).flat().map(acctName))].join(", ") || acctName(s.account))}</span></div></div>`).join("");

  try {
    const [sr, nr] = await Promise.all([fetch("/api/settings"), fetch("/api/notifications")]);
    const sj = await sr.json(), nj = await nr.json();
    const sess = sj.settings?.session || {};
    $("toolsSessionTag").textContent = `NY ${sess.start_hour ?? 8}:00–${sess.end_hour ?? 17}:00 (${sess.active_now ? "OPEN" : "CLOSED"})`;
    $("toolsRouting").innerHTML = (sj.settings?.rules || []).map((r) => `
      <div class="ledger-row"><div class="row-top"><span class="row-title">${esc(acctName(r.account))}</span><span class="row-meta">${r.in_ny_session === true ? "NY Session" : r.in_ny_session === false ? "Outside NY" : "Anytime"}</span></div>
      <div class="row-bot row-meta"><span>${r.strategies ? r.strategies.join(", ") : "All strategies"}</span><span>${r.asset_groups ? r.asset_groups.join(", ") : "All groups"}</span></div></div>`).join("");

    const chs = nj.channels || [];
    $("toolsNotifyTag").textContent = `${chs.filter((c) => c.enabled).length}/${chs.length} enabled`;
    $("toolsNotify").innerHTML = chs.map((c) => `
      <div class="ledger-row"><div class="row-top"><span class="row-title">${esc(c.label || c.id)} (${esc(c.type)})</span><span class="badge ${c.enabled ? "buy" : "closed"}">${c.enabled ? "Enabled" : "Off"}</span></div>
      <div class="row-bot row-meta"><span>Events: ${(c.events || []).join(", ")}</span><span>${c.has_target ? "Configured" : "Not set"}</span></div></div>`).join("");
  } catch (e) { console.warn("Tools extra load failed", e); }
}

async function runBacktest() {
  const btn = $("btRunBtn"); btn.disabled = true;
  $("btStatus").textContent = "Running backtest on Yahoo candles…";
  $("btResults").hidden = true;
  try {
    const qs = new URLSearchParams({ strategy: $("btStrategy").value, symbol: $("btSymbol").value, period: $("btPeriod").value });
    const r = await fetch(`/api/backtest?${qs}`, { cache: "no-store" });
    const res = await r.json();
    if (!res.ok) throw new Error(res.error || "Backtest failed");
    $("btStatus").textContent = `${res.strategy} · ${res.symbol} · ${res.period} · ${res.candle_count} candles`;
    const m = res.metrics || {};
    const sigs = Array.isArray(res.signals) ? res.signals : [];
    const trades = Array.isArray(res.trades) ? res.trades : [];
    const totalDir = (res.buy_signals ?? 0) + (res.sell_signals ?? 0) || sigs.length;
    const sigRows = sigs.length ? sigs.slice().reverse().map((s) => {
      const dir = String(s.direction || s.signal || "").toUpperCase();
      return `<article class="ledger-row bt-item">
        <div class="row-top">
          <span class="row-title"><span class="badge ${dir === "BUY" ? "buy" : "sell"}">${esc(dir)}</span><span class="mono">${tsFmt(s.timestamp)}</span></span>
          <span class="badge closed">${esc(s.timeframe || "")}</span>
        </div>
        <div class="bt-levels">
          <span><small>ENTRY</small><b>${px(s.entry)}</b></span>
          <span><small>SL</small><b class="neg">${px(s.stop_loss)}</b></span>
          <span><small>TP</small><b class="pos">${px(s.take_profit)}</b></span>
        </div>
        ${s.reason ? `<div class="row-reason">${esc(s.reason)}</div>` : ""}
      </article>`;
    }).join("") : `<div class="empty-box">No signals generated in this period</div>`;
    const tradeRows = trades.length ? trades.slice().reverse().map((tr) => {
      const dir = String(tr.direction || "").toUpperCase();
      const pnl = Number(tr.pnl || 0);
      return `<article class="ledger-row bt-item">
        <div class="row-top">
          <span class="row-title"><span class="badge ${dir === "BUY" ? "buy" : "sell"}">${esc(dir)}</span><span class="mono">${tsFmt(tr.timestamp)}</span></span>
          <span class="mono ${pnl >= 0 ? "pos" : "neg"}"><b>${inr(pnl)}</b></span>
        </div>
        <div class="bt-levels">
          <span><small>ENTRY</small><b>${px(tr.entry)}</b></span>
          <span><small>EXIT</small><b>${px(tr.exit)}</b></span>
          <span><small>HELD</small><b>${tr.bars_held || 0} bars</b></span>
        </div>
      </article>`;
    }).join("") : `<div class="empty-box">No trades taken in this period</div>`;
    $("btResults").innerHTML = `
      <div class="kpi-bar" style="margin:8px 0 6px">
        <div class="kpi-item"><small>RETURN</small><strong class="${m.return_pct >= 0 ? "pos" : "neg"}">${Number(m.return_pct || 0).toFixed(2)}%</strong></div>
        <div class="kpi-item"><small>TRADES</small><strong>${res.trades_taken || trades.length}</strong></div>
        <div class="kpi-item"><small>WIN RATE</small><strong>${Number(m.win_rate_pct || 0).toFixed(1)}%</strong></div>
        <div class="kpi-item"><small>RATING</small><strong>${esc(m.rating_label || "—")}</strong></div>
      </div>
      <div class="muted-note" style="margin-bottom:6px">Signals: ${totalDir} (${res.buy_signals || 0} buy · ${res.sell_signals || 0} sell) · Max DD ${Number(m.max_drawdown_pct || 0).toFixed(2)}% · Sharpe ${Number(m.sharpe || 0).toFixed(2)}</div>
      <div class="chart-box">${equitySvg(res.equity_curve || [])}</div>
      <div class="bt-split">
        <div class="bt-box">
          <div class="sec-head"><b>Signals Generated</b><small>${sigs.length} shown / ${totalDir} total</small></div>
          <div class="bt-scroll">${sigRows}</div>
        </div>
        <div class="bt-box">
          <div class="sec-head"><b>Trades Taken</b><small>${trades.length} completed</small></div>
          <div class="bt-scroll">${tradeRows}</div>
        </div>
      </div>`;
    $("btResults").hidden = false;
    if ($("btClearBtn")) $("btClearBtn").hidden = false;
  } catch (e) { $("btStatus").textContent = `Error: ${e.message}`; }
  finally { btn.disabled = false; }
}

function clearBacktest() {
  $("btResults").hidden = true;
  $("btResults").innerHTML = "";
  $("btStatus").textContent = "Select strategy, asset and period to test.";
  if ($("btClearBtn")) $("btClearBtn").hidden = true;
}

function openTradeDrawer(idx, btn) {
  const t = (state.data?.trades || [])[idx]; if (!t) return;
  const card = btn?.closest(".ledger-row");
  const box = card?.querySelector(".inline-detail");
  if (!box) return;
  const isOpen = !box.hidden;
  if (isOpen) {
    box.hidden = true;
    btn.textContent = "View";
    btn.setAttribute("aria-expanded", "false");
    return;
  }
  const plan = t.plan || t;
  const isClosed = String(t.status || "").toUpperCase() === "CLOSED";
  box.innerHTML = `<div class="kv-grid compact">
    <div class="kv-box"><small>Account</small><b>${esc(acctName(t.account))}</b></div>
    <div class="kv-box"><small>Qty</small><b>${Number(t.qty || 0).toFixed(4)}</b></div>
    <div class="kv-box"><small>Stop Loss</small><b class="neg">${px(plan.stop_loss ?? t.sl)}</b></div>
    <div class="kv-box"><small>Take Profit</small><b class="pos">${px(plan.take_profit ?? t.tp)}</b></div>
    <div class="kv-box"><small>${isClosed ? "Exit" : "Risk"}</small><b>${isClosed ? px(t.exit_price) : inr(t.planned_risk)}</b></div>
    <div class="kv-box"><small>${isClosed ? "Closed" : "Opened"}</small><b>${tsFmt(isClosed ? t.closed_at : t.opened_at)}</b></div>
  </div>`;
  box.hidden = false;
  btn.textContent = "Hide";
  btn.setAttribute("aria-expanded", "true");
}

async function loadDashboard() {
  // The minute poll, manual refresh and retry button share one in-flight request.
  if (state.dashboardLoading) return;
  state.dashboardLoading = true;
  try {
    const hdr = state.etag ? { "If-None-Match": state.etag } : {};
    const r = await fetch("/api/dashboard", { cache: "no-store", headers: hdr });
    if (r.status === 304) {
      $("statusText").textContent = "ONLINE";
      $("statusPill").classList.remove("offline");
      $("connBanner").hidden = true;
      return;
    }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const etag = r.headers.get("ETag");
    if (etag) state.etag = etag;
    const payload = await r.json();
    if (!payload || payload.ok === false) throw new Error(payload?.error || "Dashboard data unavailable");
    state.data = payload;
    $("statusText").textContent = "ONLINE";
    $("statusPill").classList.remove("offline");
    $("connBanner").hidden = true;
    renderOverview();
    renderSignals();
    renderHistory();
    if (state.page === "tools") loadTools();
  } catch (e) {
    $("statusText").textContent = "OFFLINE";
    $("statusPill").classList.add("offline");
    const banner = $("connBanner");
    banner.replaceChildren(document.createTextNode(`Connection issue: ${e.message} `));
    const retry = document.createElement("button");
    retry.type = "button";
    retry.id = "dashboardRetryBtn";
    retry.className = "btn-mini";
    retry.textContent = "Retry";
    banner.append(retry);
    banner.hidden = false;
  } finally {
    state.dashboardLoading = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  applyPrefs();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  $("calDate").value = state.calDate;
  const tick = () => { $("clockChip").textContent = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date()); };
  tick(); setInterval(tick, 1000);

  document.addEventListener("click", (e) => {
    const retry = e.target.closest("#dashboardRetryBtn");
    if (retry) { loadDashboard(); return; }
    const nav = e.target.closest("[data-page],[data-page-link]");
    if (nav) { e.preventDefault(); setPage(nav.dataset.page || nav.dataset.pageLink); return; }
    const ht = e.target.closest("[data-hist-tab]");
    if (ht) {
      state.histTab = ht.dataset.histTab;
      $$("#histTabs .seg-btn").forEach((b) => b.classList.toggle("active", b === ht));
      $("histPanelOpen").hidden = state.histTab !== "open";
      $("histPanelClosed").hidden = state.histTab !== "closed";
      $("histPanelScans").hidden = state.histTab !== "scans";
      return;
    }
    const tr = e.target.closest("[data-trade-idx]");
    if (tr) { openTradeDrawer(Number(tr.dataset.tradeIdx), tr); return; }
    const ci = e.target.closest("[data-impact]");
    if (ci) {
      state.calImpact = ci.dataset.impact;
      $$("#calImpactChips .chip").forEach((b) => b.classList.toggle("active", b === ci));
      loadCalendar(); return;
    }
    const st = e.target.closest("[data-style-set]");
    if (st) { localStorage.setItem("v2-style", st.dataset.styleSet); applyPrefs(); return; }
    const th = e.target.closest("[data-theme-set]");
    if (th) { localStorage.setItem("v2-theme", th.dataset.themeSet); applyPrefs(); return; }
    const ac = e.target.closest("[data-accent-set]");
    if (ac) { localStorage.setItem("v2-accent", ac.dataset.accentSet); applyPrefs(); return; }
    const bg = e.target.closest("[data-bg-set]");
    if (bg) { localStorage.setItem("v2-bg", bg.dataset.bgSet); applyPrefs(); return; }
  });

  $("styleQuickBtn").onclick = () => {
    const order = ["terminal", "neo", "modern"];
    const next = order[(order.indexOf(document.documentElement.dataset.style) + 1) % order.length];
    localStorage.setItem("v2-style", next);
    applyPrefs();
  };
  $("themeBtn").onclick = () => { localStorage.setItem("v2-theme", document.documentElement.dataset.theme === "dark" ? "light" : "dark"); applyPrefs(); };
  $("compactBtn").onclick = () => { localStorage.setItem("v2-compact", document.documentElement.dataset.compact === "true" ? "false" : "true"); applyPrefs(); };
  $("motionBtn").onclick = () => { localStorage.setItem("v2-motion", document.documentElement.dataset.reduceMotion === "true" ? "false" : "true"); applyPrefs(); };
  $("refreshBtn").onclick = loadDashboard;
  $("sigRefreshBtn").onclick = loadDashboard;
  $("histRefreshBtn").onclick = loadDashboard;
  $("calRefreshBtn").onclick = loadCalendar;
  $("calDate").onchange = () => { state.calDate = $("calDate").value || state.calDate; loadCalendar(); };
  $("btRunBtn").onclick = runBacktest;
  if ($("btClearBtn")) $("btClearBtn").onclick = clearBacktest;
  $("drawerClose").onclick = () => { $("drawerBackdrop").hidden = true; };
  $("drawerBackdrop").onclick = (e) => { if (e.target.id === "drawerBackdrop") $("drawerBackdrop").hidden = true; };
  $("whatsNewBtn").onclick = () => { $("whatsNewBackdrop").hidden = false; };
  $("whatsNewClose").onclick = () => { $("whatsNewBackdrop").hidden = true; };
  $("whatsNewBackdrop").onclick = (e) => { if (e.target.id === "whatsNewBackdrop") $("whatsNewBackdrop").hidden = true; };

  const initial = location.hash.replace("#", "");
  if (["overview", "signals", "history", "calendar", "tools"].includes(initial)) setPage(initial);
  window.addEventListener("hashchange", () => setPage(location.hash.replace("#", "")));

  loadDashboard();
  setInterval(loadDashboard, 60000);
});
