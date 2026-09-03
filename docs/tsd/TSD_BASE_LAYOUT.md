# TSD — Base Layout (Shared Shell)

## File map

| File | Role |
|---|---|
| `app/templates/base.html` | Shell markup: header/nav/back-button+table-badge row/subnav block/main/footer |
| `app/templates/configuration/_subnav.html` | Configuration's sub-nav (Tables link, table-name label, tab links), included via `{% block subnav %}` |
| `app/static/css/reset.css` | Minimal reset |
| `app/static/css/variables.css` | Theme tokens (CSS custom properties), scoped under `[data-theme="dark"]`/`[data-theme="light"]` |
| `app/static/css/layout.css` | Fit-to-screen shell (header/main/footer flex layout) + `.app-main__top-row` (back button + table badge row) |
| `app/static/css/nav.css` | Top nav + theme toggle button styling |
| `app/static/css/branding.css` | Logo chip + app name/version styling |
| `app/static/css/subnav.css` | Sub-nav styling — button/pill tabs matching the top nav, plus the "← Tables" link and table-name label |
| `app/static/css/back-button.css` | Back button styling + `.table-badge` component styling |
| `app/static/js/theme-toggle.js` | Theme flip + cookie persistence |
| `app/static/js/back-button.js` | Back-button click handling |

## Context processor (`app/__init__.py`)

`_register_context_processors()` injects into **every** template, no per-route work needed:

`current_theme`, `theme_cookie_name`, `theme_cookie_max_age_days`, `app_name`, `app_version`, `client_name`, `client_brand`, `client_logo_path`, `developer_name`

## Theming — server-resolved, no flash of wrong theme

- `current_theme` is resolved server-side from the `theme_preference` cookie in the context processor and written onto `<html data-theme="...">` in `base.html`. **This is what avoids flash-of-wrong-theme** — don't move theme resolution to client JS.
- All colors/spacing/fonts are CSS custom properties in `variables.css`.
- `theme-toggle.js` only flips the `data-theme` attribute + sets the cookie client-side, after the initial correct render — it never resolves the theme itself.

## Fit-to-screen (HMI) layout mechanics

`layout.css`:
```css
html, body { height: 100vh; overflow: hidden; }
body { display: flex; flex-direction: column; }
.app-main { flex: 1; min-height: 0; overflow-y: auto; border: 1px solid var(--color-border); }
```
`min-height: 0` is required for the flex child to actually scroll instead of overflowing. This means **no page ever needs its own scroll CSS** — any page's content that overflows scrolls inside `.app-main` automatically.

## Back button + table badge (implementation)

**Markup** — rendered once, globally, in `base.html`, with the Back button and an empty `{% block table_badge %}` wrapped in a flex row:
```html
<main class="app-main">
  <div class="app-main__top-row">
    <button type="button" id="back-button" class="back-button" aria-label="Go back"
            data-fallback-url="{{ url_for('home.index') }}">
      <span aria-hidden="true">&larr;</span> Back
    </button>
    {% block table_badge %}{% endblock %}
  </div>
  {% block content %}{% endblock %}
</main>
```
`layout.css` lays the row out with `display: flex; align-items: center; gap: var(--spacing-md);` and zeroes the back button's own `margin-bottom` inside the row (the row owns that spacing instead, to avoid double-spacing).

The `table_badge` block is empty by default, so pages that aren't table-scoped (Home, Live Kitting Activities, History, the Configuration landing page, the table placeholder page) render nothing there — no per-template work needed to opt out. A table-scoped page opts in with one line:
```html
{% block table_badge %}<span class="table-badge">Table {{ table_id }} — {{ table_name }}</span>{% endblock %}
```
Currently used by `current_kits.html`, `kit_form.html`, `pqpr_analytics.html`, and `table_settings.html` — all four receive `table_id` and `table_name` from their route (see `TSD_CONFIGURATION.md`).

**Back button behavior** (`back-button.js`, unchanged):
```js
if (window.history.length > 1) {
  window.history.back();
} else {
  window.location.href = button.dataset.fallbackUrl;
}
```
Uses real browser history so "back" returns to wherever the user actually navigated from, not a hardcoded parent route per page. The fallback URL is generated server-side via `url_for('home.index')` and passed through a `data-*` attribute — same convention already used for AJAX endpoint URLs, never hardcode a URL in JS.

**Known trade-off:** the button also renders on Home. If there's browser history from outside the app, "Back" from Home could navigate away from the site entirely. Not suppressed by default — flagged as an open item if the client wants Home excluded.

## Sub-nav (implementation)

`app/templates/configuration/_subnav.html` (shared by all three of Table 1's built pages):
```html
<nav class="app-subnav" aria-label="{{ table_name }} configuration sections">
  <div class="app-subnav__inner">
    <a href="{{ url_for('configuration.index') }}" class="app-subnav__link app-subnav__link--tables">← Tables</a>
    <span class="app-subnav__table-label">{{ table_name }}</span>
    <a href="{{ url_for('configuration.current_kits', table_id=table_id) }}"
       class="app-subnav__link {% if active_subtab == 'current_kits' %}app-subnav__link--active{% endif %}">Current Kits Configuration</a>
    <a href="{{ url_for('configuration.pqpr_analytics', table_id=table_id) }}"
       class="app-subnav__link {% if active_subtab == 'pqpr_analytics' %}app-subnav__link--active{% endif %}">PQPR Analytics</a>
    <a href="{{ url_for('configuration.table_settings', table_id=table_id) }}"
       class="app-subnav__link {% if active_subtab == 'table_settings' %}app-subnav__link--active{% endif %}">Table Settings</a>
  </div>
</nav>
```
Each page overrides `{% block subnav %}{% include "configuration/_subnav.html" %}{% endblock %}` and passes `table_id`, `table_name`, and `active_subtab` from its route — the same pattern documented in the original sub-nav design below.

`subnav.css` styles `.app-subnav__link` as a button/pill (padding, border-radius, background + border on hover/active) to match `.app-nav__link` in `nav.css`, rather than the earlier underline-tab style. `.app-subnav__link--tables` (the "← Tables" link) and `.app-subnav__table-label` (the static table-name label) are visually quieter — no active state, since they're not tabs.

### General pattern (for future top-nav pages needing tabs)

Each blueprint that needs a second nav level:
1. Adds `active_subtab` to its render context alongside `active_page`.
2. Has its own `templates/<blueprint>/_subnav.html`.
3. Overrides `{% block subnav %}{% include "<blueprint>/_subnav.html" %}{% endblock %}` in its templates — the block is empty by default in `base.html`, so pages without sub-tabs render nothing there.

Configuration is currently the only blueprint using this.
