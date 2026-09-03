# FRD — Kitting Station v2 (Whole App)

Functional requirements at the app level. For the shared shell (nav, theming, back button, table badge), see `FRD_BASE_LAYOUT.md`. For Configuration tab detail, see `FRD_CONFIGURATION.md`.

## Product identity

| | |
|---|---|
| Product name | Kitting Station (v2) |
| Developer | AssertAI |
| Client | Watts Water |
| Client brand | Dormont |
| App type | Server-rendered web app, styled/used like an HMI |
| Devices | Laptop monitors and larger fixed screens (fit-to-screen, no page scroll) |
| Domain | Manufacturing / kitting station monitoring |

## Multi-table concept

The app configures and (eventually) monitors multiple physical kitting **tables** (stations/cells) — not just one. Each table has a stable numeric reference (`table_id`: 1, 2, 3, ...) and a display name. Currently registered:

| table_id | Name | Status |
|---|---|---|
| 1 | HVGKC-CELL | Built — full Configuration functionality |
| 2 | Truck Cell 1 | Registered, not yet built (placeholder) |
| 3 | Truck Cell 2 | Registered, not yet built (placeholder) |

More tables can be added later (4, 5, ...) — this is a config change, not a code change. Live Kitting Activities already follows the same `table_id`-scoped pattern established in Configuration (see `FRD_LIVE_KITTING_ACTIVITIES.md` / `TSD_LIVE_KITTING_ACTIVITIES.md`); any future section (e.g. History) that needs to vary per table should do the same.

## Navigation structure

**Top nav (all pages):** Home · Live Kitting Activities · History · Configuration

**Configuration section:**
1. Entering "Configuration" from the top nav always lands on a **table-selection landing page** — a card per registered table (id + name shown), plus a "not yet configured" note on unbuilt tables. Clicking a card enters that table's configuration.
2. Once inside a **built** table (currently only Table 1), a sub-nav appears with three tabs: **Current Kits Configuration · PQPR Analytics · Table Settings**, plus a "← Tables" link back to the landing page and a label showing which table you're in. The sub-nav is styled as a row of buttons (matching the top nav's look), with the active tab visually highlighted.
3. Entering an **unbuilt** table (2 or 3) shows a simple "Configuration for `<table name>` not yet built." placeholder — no sub-nav, since there's nothing to navigate to yet.

Active page/tab is visually highlighted throughout. Every page also has a global **Back** button (top of the main content area) that returns to wherever the user came from — see `FRD_BASE_LAYOUT.md`. On table-scoped pages, a **table badge** ("Table `<id>` — `<name>`") sits next to the Back button so it's always clear which table's configuration is being viewed.

## Page-by-page status

| Page | Status | User goal |
|---|---|---|
| Home | Shell only | Landing page |
| Live Kitting Activities | **Built** — UI, routes, and MongoDB schema complete; detected part counts are static until real detection events are wired | Start and monitor a live kit-packing run: create an activity, watch per-camera progress, complete it (normally or manually) |
| History | Placeholder — needs MongoDB | Look up past kitting activity/records |
| Configuration (landing) | **Built** | Choose which table to configure |
| Configuration → Table 1 (HVGKC-CELL) → Current Kits Configuration | **Built** | Create, edit, search, and delete kit definitions (parts, cameras, alert rules, per-camera alert toggles) |
| Configuration → Table 1 (HVGKC-CELL) → PQPR Analytics | **Built** | Upload the PQPR Excel workbook; look up which components are in a kit, or which kits use a component |
| Configuration → Table 1 (HVGKC-CELL) → Table Settings | **Built** | Configure per-table Audio Settings, Expected Client IP Addresses, and Push Notification Settings |
| Configuration → Table 2 (Truck Cell 1) | Placeholder | — |
| Configuration → Table 3 (Truck Cell 2) | Placeholder | — |

## Out of scope (not yet built)

- Table 2 / Table 3 functionality (any of Current Kits Configuration, PQPR Analytics, Table Settings, or Live Kitting Activities for those tables)
- Live Kitting Activities' real-time detection wiring — part counts are currently static (see `FRD_LIVE_KITTING_ACTIVITIES.md`); needs a CV-side ingest path and likely Flask-SocketIO
- History browsing/audit trail (needs MongoDB integration for that blueprint)
- Any authentication/authorization

## Where to look for more

- Shell (header, nav, theming, back button, table badge, sub-nav, fit-to-screen behavior): `FRD_BASE_LAYOUT.md`
- Configuration section (table selection, both Table 1 sub-tabs, Table Settings, full functional detail): `FRD_CONFIGURATION.md`
- Live Kitting Activities (landing page, create-activity flow, monitor page): `FRD_LIVE_KITTING_ACTIVITIES.md`
