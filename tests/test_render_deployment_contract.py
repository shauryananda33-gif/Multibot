"""Deployment contract: Render is the only application host."""
from pathlib import Path
import io

import main


ROOT = Path(__file__).resolve().parents[1]


def test_render_blueprint_matches_the_live_single_web_service():
    config = (ROOT / "render.yaml").read_text()
    assert "name: Multibot" in config
    assert "runtime: python" in config
    assert "region: singapore" in config
    assert "branch: main" in config
    assert "buildCommand: pip install -r requirements.txt" in config
    assert "startCommand: python3 main.py" in config
    assert "healthCheckPath: /ping" in config
    assert "https://multibot-3hsb.onrender.com/dashboard" in config
    assert "https://multibot-3hsb.onrender.com/architecture" in config
    assert "SUPABASE_DB_URL" in config
    assert "DASHBOARD_API_TOKEN" in config


def test_netlify_proxy_configuration_is_not_shipped():
    assert not (ROOT / "_redirects").exists()
    config = (ROOT / "render.yaml").read_text().lower()
    readme = (ROOT / "README.md").read_text().lower()
    assert "netlify" not in config
    assert "appliedintelligencecorporation.com" not in config
    assert "appliedintelligencecorporation.com" not in readme


def test_dashboard_assets_are_served_by_the_python_app():
    app = main.build_app()
    for path, expected in (
        ("/", b"<html"),
        ("/dashboard", b"<html"),
        ("/app.js", b""),
        ("/styles.css", b""),
    ):
        captured = {}

        def start_response(status, headers):
            captured["status"] = status

        body = b"".join(app({
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "REQUEST_METHOD": "GET",
            "wsgi.input": io.BytesIO(b""),
        }, start_response))
        assert captured["status"] == "200 OK", path
        assert body
        if expected:
            assert expected in body


def test_admin_api_fails_closed_on_deployment_without_token(monkeypatch):
    monkeypatch.delenv("DASHBOARD_API_TOKEN", raising=False)
    monkeypatch.setenv("PORT", "10000")
    assert main._admin_token_allowed({}) is False


def test_admin_api_keeps_local_development_compatible_without_token(monkeypatch):
    monkeypatch.delenv("DASHBOARD_API_TOKEN", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    assert main._admin_token_allowed({}) is True
