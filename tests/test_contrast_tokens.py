from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "styles.css").read_text(encoding="utf-8")
STYLES = ("terminal", "neo", "modern")
ACCENTS = ("emerald", "indigo", "amber", "rose", "cyan")
THEMES = ("light", "dark")


def _rgb(value):
    value = value.strip()
    if not value.startswith("#"):
        return None
    value = value[1:]
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return None
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _luminance(rgb):
    def channel(v):
        v = v / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return .2126 * channel(r) + .7152 * channel(g) + .0722 * channel(b)


def _ratio(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + .05) / (lo + .05)


def _tokens(style, accent, theme):
    source = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    resolved = {}
    active = {"style": style, "accent": accent, "theme": theme}
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", source):
        for item in selector.split(","):
            conditions = dict(re.findall(r'data-(style|accent|theme)="([a-z]+)"', item))
            if ("html" in item or ":root" in item) and all(active.get(k) == v for k, v in conditions.items()):
                for key, value in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", body):
                    resolved[key] = value.strip()
    return resolved


def test_every_current_style_accent_and_theme_declares_core_tokens():
    required = ("--base-bg", "--base-surface", "--text", "--muted", "--accent", "--accent-fg")
    for style in STYLES:
        for accent in ACCENTS:
            for theme in THEMES:
                found = _tokens(style, accent, theme)
                missing = [key for key in required if key not in found]
                assert not missing, f"{style}/{accent}/{theme} missing {missing}"


def test_body_text_meets_wcag_aa_against_each_server_defined_base_background():
    for style in STYLES:
        for accent in ACCENTS:
            for theme in THEMES:
                found = _tokens(style, accent, theme)
                fg, bg = _rgb(found["--text"]), _rgb(found["--base-bg"])
                assert fg and bg, f"unresolved text/background tokens for {style}/{accent}/{theme}"
                assert _ratio(fg, bg) >= 4.5, f"contrast below WCAG AA: {style}/{accent}/{theme}"
