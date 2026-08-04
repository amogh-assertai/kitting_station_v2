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
| `docs/frd/FRD_BASE_LAYOUT.md` | Functional spec of the shared shell — header, nav, theming, back button, fit-to-screen behavior |
| `docs/tsd/TSD_BASE_LAYOUT.md` | Technical spec of the shell — how theming/back-button/subnav are implemented |
| `docs/frd/FRD_CONFIGURATION.md` | Functional spec of the Configuration section — Current Kits Configuration + PQPR Analytics |
| `docs/tsd/TSD_CONFIGURATION.md` | Technical spec of the Configuration section — MongoDB schema, routes, data flow |
| `docs/WORKING_STYLE_AND_CONSTRAINTS.md` | How the client works — communication style, file delivery convention, build philosophy. **Read before making any change or delivering anything.** |

There is no longer a single monolithic `FUNCTIONAL_DOC.md`/`TECHNICAL_DOC.md` — docs are split by section (FRD = what it does, TSD = how it's built) so each area can be updated independently as it's built out.

## Current state (high level)

**Built:**
- App shell — theming, HMI fit-to-screen layout, nav, global back button
- Configuration → PQPR Analytics — Excel upload/replace/download, two-panel component/kit search
- Configuration → Current Kits Configuration — full CRUD, live search (kit name/EDP/part name), parts + parts-to-neglect sub-tables

**Not yet built:**
- Live Kitting Activities — placeholder, needs Flask-SocketIO (not wired)
- History — placeholder, needs MongoDB (Current Kits Configuration already uses Mongo; History does not yet)
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
├── blueprints/<name>/routes.py       # HTTP layer per blueprint
├── blueprints/configuration/
│   ├── pqpr_parser.py                # Excel -> JSON, config-driven layout
│   └── current_kits_data.py          # MongoDB data access + validation
├── config/
│   ├── loader.py                     # config.yaml + .env merge, fail-fast validation
│   └── db.py                         # MongoDB client setup
├── templates/base.html               # shell: header/nav/back-button/subnav/main/footer
├── templates/<blueprint>/*.html
└── static/{css,js}/                  # one file per concern, all linked globally in base.html
```

## Before you change anything

Read `docs/WORKING_STYLE_AND_CONSTRAINTS.md`. Short version: confirm scope before building, ask short option-based questions when something's ambiguous, state assumptions explicitly, test end-to-end with `mongomock` before delivering, and deliver only changed/new files (zipped with real relative paths if more than 3).
