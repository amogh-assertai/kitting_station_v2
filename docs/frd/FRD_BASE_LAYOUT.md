# FRD — Base Layout (Shared Shell)

Functional requirements for the UI shell every page shares: header, navigation, theming, back button, and fit-to-screen behavior.

## Header

- Client logo (Watts) shown top-left in a white chip (visible on both themes).
- App name + version shown next to the logo.
- Primary navigation: **Home · Live Kitting Activities · History · Configuration**. Active page is visually highlighted; hover states on all nav links.
- Theme toggle button, top-right.

## Sub-navigation

Shown only on pages that need a second level of tabs — currently just **Configuration** (Current Kits Configuration · PQPR Analytics). Active sub-tab is highlighted. Any future top-nav page that needs sub-tabs should follow this same pattern rather than inventing a new one.

## Back button

Every page has a **Back** button at the top of its main content area (above the page's own heading).

- Clicking it returns to whatever page the user actually came from — not a fixed "parent page" per screen.
- If there's no prior page to return to (e.g. the page was opened directly via a bookmark or typed URL), it falls back to Home.
- This applies uniformly across the whole app, including Home itself — it's a consistent, predictable control rather than something that appears only on "drill-down" pages.

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
