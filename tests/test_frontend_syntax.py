"""Frontend syntax and asset wiring guards for the shipped v3.6 shell."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_current_dashboard_javascript_parses():
    result = subprocess.run(
        [NODE, "--check", str(ROOT / "app.js")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        "app.js does not parse; the dashboard would remain on its loading state.\n"
        + result.stderr
    )


def test_dashboard_references_only_existing_current_shell_assets():
    html = (ROOT / "dashboard.html").read_text(encoding="utf-8")
    assets = re.findall(r'(?:src|href)="/?([^"?]+)(?:\?[^"]*)?"', html)
    for asset in assets:
        if asset.endswith((".js", ".css")):
            assert (ROOT / asset).is_file(), f"{asset} referenced but missing"
    assert "app.js" in assets
    assert "styles.css" in assets
    assert "foundation.css" in assets
    assert "appearance-overrides.css" in assets


def test_stylesheets_load_in_the_v36_cascade_order():
    html = (ROOT / "dashboard.html").read_text(encoding="utf-8")
    order = re.findall(r'href="/?([a-z-]+\.css)\?v=[^"]+"', html)
    assert order == ["styles.css", "foundation.css", "appearance-overrides.css"]


def test_app_dom_selectors_are_present_in_the_html_shell():
    html = (ROOT / "dashboard.html").read_text(encoding="utf-8")
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    used = set(re.findall(r'\$\("([A-Za-z][A-Za-z0-9_-]*)"\)', app))
    present = set(re.findall(r'id="([^"]+)"', html))
    assert not sorted(used - present), f"missing app DOM IDs: {sorted(used - present)}"


def test_dashboard_loader_is_async_etag_aware_and_has_a_retry_path():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    assert "async function loadDashboard()" in app
    assert "If-None-Match" in app
    assert "r.status === 304" in app
    assert 'id = "dashboardRetryBtn"' in app
    assert 'textContent = "Retry"' in app
    assert "dashboardLoading" in app
