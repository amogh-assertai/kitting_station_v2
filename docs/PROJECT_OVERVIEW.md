# Kitting Station v2 — Project Overview

Read this first. It orients a new agent session (or a new developer) on what this app is, what's built, and where to find detail.

## What this is

A Flask-based, server-rendered web app styled and used like an HMI (Human-Machine Interface) — built for a manufacturing kitting station. Runs on laptop monitors and larger fixed screens; no page-level scroll.

| | |
|---|---|
| Product | Kitting Station v2 |
| Developer | AssertAI |
| Client | Watts Water |
| Client brand | Dormont |
| Domain | Manufacturing / kitting station monitoring |

## Doc index

| Doc | Covers |
|---|---|
| `docs/frd/FRD_APP.md` | Whole-app functional requirements — product identity, navigation, page-by-page status |
| `docs/tsd/TSD_APP.md` | Whole-app technical architecture — stack, project structure, config system, frontend conventions |
| `docs/frd/FRD_BASE_LAYOUT.md` | Functional spec of the shared shell — header, nav, theming, back button, table badge, sub-nav, fit-to-screen behavior |
| `docs/tsd/TSD_BASE_LAYOUT.md` | Technical spec of the shell — how theming/back-button/table-badge/sub-nav are implemented |
| `docs/frd/FRD_CONFIGURATION.md` | Functional spec of the Configuration section — multi-table selection, Current Kits Configuration, PQPR Analytics, Table Settings |
| `docs/tsd/TSD_CONFIGURATION.md` | Technical spec of the Configuration section — table registry, MongoDB schemas, routes, data flow |
| `docs/WORKING_STYLE_AND_CONSTRAINTS.md` | How the client works — communication style, file delivery convention, build philosophy. **Read before making any change or delivering anything.** |

There is no longer a single monolithic `FUNCTIONAL_DOC.md`/`TECHNICAL_DOC.md` — docs are split by section (FRD = what it does, TSD = how it's built) so each area can be updated independently as it's built out.

## Multi-table concept (important — read before touching Configuration or building new sections)

The app now models multiple physical kitting **tables** (stations/cells), not just one. Each table has a stable integer `table_id` (1, 2, 3, ... — extensible) and a display `name`. The registry lives in `config.yaml` under `configuration.tables`, each entry with a `built` flag:

```yaml
configuration:
  tables:
    - id: 1
      name: "HVGKC-CELL"
      built: true
    - id: 2
      name: "Truck Cell 1"
      built: false
    - id: 3
      name: "Truck Cell 2"
      built: false
```

- `table_id` is the reference used everywhere (URLs, MongoDB documents, filesystem paths) — never the table name.
- `built: true` is the only table with real functionality right now (Table 1 / HVGKC-CELL). Tables 2 and 3 exist in the registry and show a placeholder page, but have no functionality yet.
- If a future page/section (e.g. Live Kitting Activities, History) needs to be table-scoped too, follow the same pattern: `table_id` in the URL, a `_require_built_table()`-style guard, and Mongo documents carrying a `table_id` field.

## Current state (high level)

**Built (Table 1 / HVGKC-CELL only):**
- App shell — theming, HMI fit-to-screen layout, top nav, global back button + table badge
- Configuration → table-selection landing page (3 cards: HVGKC-CELL, Truck Cell 1, Truck Cell 2)
- Configuration → Current Kits Configuration — full CRUD, live search, parts + parts-to-neglect sub-tables, per-camera alert configuration, Total Parts / Total Parts to Neglect counts
- Configuration → PQPR Analytics — Excel upload/replace/download, two-panel component/kit search
- Configuration → Table Settings — Audio Settings (4 camera/color slots, MP3 upload + preview + default enabled/disabled), Expected Client IP Addresses, Push Notification Settings (emails + 4 notification toggles, one with a threshold percent)

**Not yet built:**
- Table 2 (Truck Cell 1) and Table 3 (Truck Cell 2) — registry entries exist, everything else is a placeholder
- Live Kitting Activities — placeholder, needs Flask-SocketIO (not wired)
- History — placeholder, needs MongoDB (Current Kits Configuration and Table Settings already use Mongo; History does not yet)
- No authentication/authorization layer

## Tech stack (fixed — don't change without asking the client)

Flask + Blueprints · Jinja2 (server-rendered) · Flask-SocketIO (not wired) · MongoDB (`kitting_station_v2` db) · plain CSS + custom properties · vanilla JS, no bundler · `config.yaml` (non-secret) + `.env` (secrets)

Full detail: `docs/tsd/TSD_APP.md`.

## Running locally

1. `pip install -r requirements.txt` (add `pymongo` if not already listed)
2. Copy `.env.example` → `.env`, set `SECRET_KEY` and `MONGO_URI`
3. Make sure MongoDB is running and reachable at `MONGO_URI`
4. `python app.py`

## Where things live

```
app/
├── blueprints/<name>/routes.py             # HTTP layer per blueprint
├── blueprints/configuration/
│   ├── pqpr_parser.py                      # Excel -> JSON, config-driven layout
│   ├── current_kits_data.py                # MongoDB data access + validation (current_kit_configurations)
│   └── table_settings_data.py              # MongoDB data access + validation (table_configuration)
├── config/
│   ├── loader.py                           # config.yaml + .env merge, fail-fast validation
│   └── db.py                               # MongoDB client setup
├── templates/base.html                     # shell: header/nav/back-button+table-badge row/subnav/main/footer
├── templates/configuration/
│   ├── landing.html                        # table-selection cards
│   ├── table_placeholder.html              # "not yet built" page for tables 2/3
│   ├── _subnav.html                        # Current Kits / PQPR Analytics / Table Settings tabs
│   ├── current_kits.html, kit_form.html, _kit_row.html, _part_row.html, _neglect_row.html
│   ├── pqpr_analytics.html
│   └── table_settings.html
└── static/{css,js}/                        # one file per concern; globally-linked files listed in base.html, page-specific ones loaded via {% block extra_css %}/{% block extra_js %}
```

Filesystem storage (gitignored, under `data/`, namespaced per table_id):
```
data/pqpr/table_<id>/         # PQPR Excel + parsed cache, one active file per table
data/audio/table_<id>/        # MP3s for Table Settings' Audio Settings, one file per slot per table
```

## Before you change anything

Read `docs/WORKING_STYLE_AND_CONSTRAINTS.md`. Short version: confirm scope before building, ask short option-based questions when something's ambiguous, state assumptions explicitly, test end-to-end with `mongomock` before delivering, and deliver only changed/new files (zipped with real relative paths if more than 3).
