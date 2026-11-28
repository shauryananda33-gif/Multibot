"""Visual regression guards for the shipped v3.6 Mavis dashboard."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "dashboard.html").read_text(encoding="utf-8")
APP = (ROOT / "app.js").read_text(encoding="utf-8")
SHEETS = [ROOT / name for name in ("styles.css", "foundation.css", "appearance-overrides.css")]


def test_every_dashboard_page_has_a_real_container_and_navigation_target():
    for page in ("overview", "signals", "history", "calendar", "tools"):
        assert f'id="page-{page}"' in HTML
        assert f'data-page="{page}"' in HTML or f'data-page-link="{page}"' in HTML


def test_shared_css_layers_are_present_and_brace_balanced():
    for path in SHEETS:
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        assert css.count("{") == css.count("}"), f"unbalanced CSS braces in {path.name}"


def test_layout_foundation_and_theme_overrides_own_distinct_concerns():
    foundation = SHEETS[1].read_text(encoding="utf-8")
    overrides = SHEETS[2].read_text(encoding="utf-8")
    assert "--f-section-gap" in foundation and "--ui-collapse-size" in foundation
    assert ".appearance-style-grid" in overrides
    assert "data-style" in SHEETS[0].read_text(encoding="utf-8")


def test_dashboard_has_a_recoverable_connection_error_state():
    assert 'id="connBanner"' in HTML
    assert 'id = "dashboardRetryBtn"' in APP
    assert 'textContent = "Retry"' in APP
    assert "dashboardLoading" in APP


def test_public_dashboard_does_not_render_or_request_an_admin_token():
    assert 'fetch("/api/dashboard"' in APP
    assert "Authorization" not in APP and "Bearer " not in APP
    assert "token" not in HTML.lower()


def test_compact_and_motion_preferences_are_persisted_locally():
    assert "v2-compact" in APP and "v2-motion" in APP
    assert 'localStorage.setItem("v2-compact"' in APP
    assert 'localStorage.setItem("v2-motion"' in APP
