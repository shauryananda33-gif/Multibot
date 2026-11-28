# Mavis Dashboard v2 Theme System — v3.6.0

This document describes the styles actually shipped by dashboard.html, app.js and styles.css.

## Supported appearance axes

The dashboard has 3 styles × 2 themes × 5 accents = 30 combinations.

| Axis | Supported values | Default |
|---|---|---|
| Interface style | terminal, neo, modern | terminal |
| Theme | dark, light | dark |
| Accent | emerald, indigo, amber, rose, cyan | emerald |
| Background texture | plain, grid, dots, glow | grid |
| Density | false, true | false |
| Reduced motion | false, true | false |

## Ownership

- styles.css owns colour tokens, theme/style surfaces, typography and base components.
- foundation.css owns layout geometry, spacing, responsive reservations and shared collapse-control geometry.
- appearance-overrides.css owns appearance-specific option controls and interaction polish.
- app.js applyPrefs() applies local preferences from the v2-* localStorage keys. Appearance is client-side only; it does not call the server or change trading settings.
- dashboard.html loads the stylesheets in this exact order: styles.css → foundation.css → appearance-overrides.css.

## Runtime rules

1. The server-rendered default attributes are data-style="terminal", data-theme="dark" and data-accent="emerald".
2. The page shell and data remain the same for all 30 combinations; styling never changes signal, risk, trade, account or API behavior.
3. The current v3.6 interface uses themeBtn, styleQuickBtn, and the data-style-set, data-theme-set, data-accent-set, and data-bg-set controls.
4. Do not load the legacy appearance.js bridge into this shell. It uses a different style vocabulary and storage contract.
5. Respect prefers-reduced-motion and the user's persisted reduced-motion preference.

## Accessibility and contrast

Body text uses --text over the selected --base-bg / --base-surface surfaces. tests/test_contrast_tokens.py verifies core token coverage for every style/accent/theme combination and checks the base text/background pair against WCAG AA. Interactive controls retain semantic buttons and visible focus styles.

## Change checklist

- Update the matching data-* controls in dashboard.html.
- Update token definitions in styles.css, not the geometry layer.
- Keep foundation.css presentation-neutral.
- Keep appearance-overrides.css from redefining core contrast tokens.
- Add a test for all combinations and ensure the 30-combination matrix remains complete.
