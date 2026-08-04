# TSD — Base Layout (Shared Shell)

## File map

| File | Role |
|---|---|
| `app/templates/base.html` | Shell markup: header/nav/back-button/subnav block/main/footer |
| `app/templates/configuration/_subnav.html` | Configuration's sub-nav, included via `{% block subnav %}` |
| `app/static/css/reset.css` | Minimal reset |
| `app/static/css/variables.css` | Theme tokens (CSS custom properties), scoped under `[data-theme="dark"]`/`[data-theme="light"]` |
| `app/static/css/layout.css` | Fit-to-screen shell (header/main/footer flex layout) |
| `app/static/css/nav.css` | Top nav + theme toggle button styling |
| `app/static/css/branding.css` | Logo chip + app name/version styling |
| `app/static/css/subnav.css` | Sub-nav tab styling |
| `app/static/css/back-button.css` | Back button styling |
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

## Back button (implementation)

**Markup** — rendered once, globally, in `base.html`:
```html
<main class="app-main">
  <button type="button" id="back-button" class="back-button" aria-label="Go back"
          data-fallback-url="{{ url_for('home.index') }}">
    <span aria-hidden="true">&larr;</span> Back
  </button>
  {% block content %}{% endblock %}
</main>
```
Placed once at the shell level (same pattern already used for CSS/JS files being linked globally rather than per-page) — no per-template work needed for a new page to get a working back button.

**Behavior** (`back-button.js`):
```js
if (window.history.length > 1) {
  window.history.back();
} else {
  window.location.href = button.dataset.fallbackUrl;
}
```
Uses real browser history so "back" returns to wherever the user actually navigated from, not a hardcoded parent route per page. The fallback URL is generated server-side via `url_for('home.index')` and passed through a `data-*` attribute — same convention already used for AJAX endpoint URLs, never hardcode a URL in JS.

**Known trade-off:** the button also renders on Home. If there's browser history from outside the app, "Back" from Home could navigate away from the site entirely. Not suppressed by default — flagged as an open item if the client wants Home excluded.

## Sub-nav pattern (for future top-nav pages needing tabs)

Each blueprint that needs a second nav level:
1. Adds `active_subtab` to its render context alongside `active_page`.
2. Has its own `templates/<blueprint>/_subnav.html`.
3. Overrides `{% block subnav %}{% include "<blueprint>/_subnav.html" %}{% endblock %}` in its templates — the block is empty by default in `base.html`, so pages without sub-tabs render nothing there.

Configuration is currently the only blueprint using this.
