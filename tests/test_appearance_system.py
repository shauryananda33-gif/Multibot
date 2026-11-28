from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "dashboard.html").read_text(encoding="utf-8")
APP = (ROOT / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "styles.css").read_text(encoding="utf-8")
FOUNDATION = (ROOT / "foundation.css").read_text(encoding="utf-8")
OVERRIDES = (ROOT / "appearance-overrides.css").read_text(encoding="utf-8")


def test_v36_exposes_the_supported_style_theme_and_accent_choices():
    for style in ("terminal", "neo", "modern"):
        assert f'data-style-set="{style}"' in HTML
        assert f'data-style="{style}"' in CSS
    for theme in ("dark", "light"):
        assert f'data-theme-set="{theme}"' in HTML
        assert f'data-theme="{theme}"' in CSS
    for accent in ("emerald", "indigo", "amber", "rose", "cyan"):
        assert f'data-accent-set="{accent}"' in HTML
        assert f'data-accent="{accent}"' in CSS


def test_appearance_preferences_are_applied_by_the_current_app():
    assert "function applyPrefs()" in APP
    for key in ("v2-style", "v2-theme", "v2-accent", "v2-bg", "v2-compact", "v2-motion"):
        assert key in APP


def test_appearance_controls_are_wired_and_accessible():
    assert "data-style-set" in APP and "data-theme-set" in APP
    assert "data-accent-set" in APP and "data-bg-set" in APP
    assert 'id="themeBtn"' in HTML and 'id="styleQuickBtn"' in HTML


def test_geometry_and_appearance_are_separate_layers():
    assert "--ui-collapse-size" in FOUNDATION
    assert ".appearance-style-grid" in OVERRIDES
    assert 'html[data-style="neo"]' in CSS
    assert 'html[data-style="modern"]' in CSS


def test_reduce_motion_is_supported():
    assert "reduceMotion" in APP
    assert "prefers-reduced-motion" in CSS or "prefers-reduced-motion" in FOUNDATION
