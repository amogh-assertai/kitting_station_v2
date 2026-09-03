# FRD — Base Layout (Shared Shell)

Functional requirements for the UI shell every page shares: header, navigation, theming, back button, table badge, and fit-to-screen behavior.

## Header

- Client logo (Watts) shown top-left in a white chip (visible on both themes).
- App name + version shown next to the logo.
- Primary navigation: **Home · Live Kitting Activities · History · Configuration**. Active page is visually highlighted; hover states on all nav links.
- Theme toggle button, top-right.

## Sub-navigation

Shown only on pages that need a second level of tabs — currently just the Configuration section, and only once a **built** table has been selected (see `FRD_CONFIGURATION.md`). It shows:
- A **"← Tables"** link back to the table-selection landing page.
- A **table name label** (e.g. "HVGKC-CELL") showing which table's configuration is being viewed — not clickable, just context.
- The tab links themselves: **Current Kits Configuration · PQPR Analytics · Table Settings**.

The tab links are styled as a row of buttons/pills — the same visual treatment as the top nav (rounded background + border on hover/active) — rather than an underlined-tab style, so the whole nav (top nav + sub-nav) reads as one consistent set of controls. The active sub-tab is highlighted the same way the active top-nav item is.

Any future top-nav page that needs sub-tabs should follow this same pattern (button-style tabs, active-state highlight) rather than inventing a new one.

## Back button + table badge

Every page has a **Back** button at the top of its main content area (above the page's own heading).

- Clicking it returns to whatever page the user actually came from — not a fixed "parent page" per screen.
- If there's no prior page to return to (e.g. the page was opened directly via a bookmark or typed URL), it falls back to Home.
- This applies uniformly across the whole app, including Home itself — it's a consistent, predictable control rather than something that appears only on "drill-down" pages.

On **table-scoped** pages (currently: Current Kits Configuration, PQPR Analytics, Table Settings, and the kit create/edit form), a **table badge** — "Table `<id>` — `<name>`", e.g. "Table 1 — HVGKC-CELL" — sits in the same row immediately to the right of the Back button. This is a page-supplied element (empty on pages that aren't table-scoped, like Home or the table-selection landing page), so it never appears where there's no table context.

## Theming

- Dark theme is default; user can toggle to light.
- Preference is remembered (cookie) so the correct theme shows on first load — no flash of wrong theme.

## Fit-to-screen (HMI) behavior

- The app is used on both laptops and larger fixed monitors, so there is **no page-level scrolling** — the whole shell fits the viewport.
- Only the main content area scrolls internally when a page's content overflows. Any new page should rely on this automatically rather than adding its own scroll handling.
- The main content area has a visible border, per client request, to delineate the working window.

## Footer

- "Dormont — a Watts Water brand"
- "Kitting Station v2.0 — powered by AssertAI"
