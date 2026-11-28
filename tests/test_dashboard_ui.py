from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "dashboard.html").read_text(encoding="utf-8")
APP = (ROOT / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "styles.css").read_text(encoding="utf-8")
FOUNDATION = (ROOT / "foundation.css").read_text(encoding="utf-8")
OVERRIDES = (ROOT / "appearance-overrides.css").read_text(encoding="utf-8")


def test_v36_shell_contains_the_five_live_pages():
    for page in ("overview", "signals", "history", "calendar", "tools"):
        assert f'id="page-{page}"' in HTML
    assert 'data-theme="dark"' in HTML
    assert 'data-style="terminal"' in HTML
    assert 'data-accent="emerald"' in HTML


def test_every_static_app_dom_lookup_exists_in_the_html():
    ids = set(re.findall(r'\$\("([A-Za-z][A-Za-z0-9_-]*)"\)', APP))
    present = set(re.findall(r'id="([^"]+)"', HTML))
    missing = sorted(ids - present)
    assert not missing, f"app.js references missing dashboard elements: {missing}"


def test_dashboard_data_is_same_origin_public_read_only_and_etag_aware():
    assert 'fetch("/api/dashboard"' in APP
    assert "If-None-Match" in APP and "r.status === 304" in APP
    assert "Authorization" not in APP and "Bearer " not in APP
    assert 'id="connBanner"' in HTML


def test_dashboard_renders_the_actual_snapshot_sections():
    for ident in ("ovEquity", "ovPnl", "ovOpen", "ovSigList", "sigList",
                  "histPanelOpen", "histPanelClosed", "histPanelScans"):
        assert f'id="{ident}"' in HTML
    for renderer in ("renderOverview", "renderSignals", "renderHistory"):
        assert f"{renderer}()" in APP


def test_current_theme_and_layout_layers_are_loaded_in_order():
    order = re.findall(r'href="/?([a-z-]+\.css)\?v=[^"]+"', HTML)
    assert order == ["styles.css", "foundation.css", "appearance-overrides.css"]
    assert "--base-bg" in CSS and "--text" in CSS
    assert "--ui-collapse-size" in FOUNDATION
    assert ".appearance-style-grid" in OVERRIDES


def test_mobile_navigation_and_reduced_motion_have_responsive_rules():
    assert "data-page=" in HTML
    assert "@media" in CSS and "@media" in FOUNDATION
    assert "prefers-reduced-motion" in CSS or "prefers-reduced-motion" in FOUNDATION


def test_backtest_keeps_generated_signals_separate_from_completed_trades():
    assert "/api/backtest?" in APP
    assert "signals" in APP and "trades" in APP
    assert "Historical Backtest" in HTML and 'id="btResults"' in HTML
