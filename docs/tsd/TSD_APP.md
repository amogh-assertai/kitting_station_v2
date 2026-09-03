# TSD — Kitting Station v2 (Whole App)

Technical architecture at the app level. For shell implementation detail, see `TSD_BASE_LAYOUT.md`. For Configuration blueprint detail (table registry, routes, MongoDB schemas, data flow), see `TSD_CONFIGURATION.md`. For Live Kitting Activities blueprint detail, see `TSD_LIVE_KITTING_ACTIVITIES.md`.

## Stack (fixed — do not change without asking the client/owner)

| Layer | Choice |
|---|---|
| Backend | Flask, Blueprints |
| Templates | Jinja2, server-rendered |
| Real-time | Flask-SocketIO — **not wired yet** |
| Database | MongoDB (`kitting_station_v2`) — **connected for Current Kits Configuration, Table Settings, and Live Kitting Activities**; History does not use it yet |
| CSS | Plain CSS + custom properties. No Tailwind/Bootstrap, no build step |
| JS | Vanilla JS only. No framework, no bundler, no inline `<script>` in templates |
| Config | `config.yaml` (non-secret) + `.env` (secrets), merged by a loader module. No hardcoded values in app code |
| File storage | Filesystem (`data/`), namespaced per `table_id` — used for PQPR upload and Table Settings' audio uploads |

## Project structure

```
station_monitor/
├── app.py                          # entry point
├── config.yaml                     # non-secret runtime config
├── .env / .env.example             # secrets
├── requirements.txt
├── data/
│   ├── pqpr/table_<id>/            # PQPR file + parsed cache per table (gitignored except .gitkeep)
│   └── audio/table_<id>/           # Table Settings audio files per table, one per slot (gitignored)
├── app/
│   ├── __init__.py                 # app factory: registers blueprints, context processors, calls init_mongo()
│   ├── config/
│   │   ├── loader.py               # merges config.yaml + .env, fail-fast validation
│   │   └── db.py                   # MongoDB client setup (lazy connection)
│   ├── blueprints/
│   │   ├── home/
│   │   ├── live_kitting_activities/
│   │   │   ├── routes.py               # landing, create flow (2 steps), monitor page, complete-manually - all routes for this blueprint
│   │   │   └── activities_data.py      # MongoDB data access + validation (live_activity_details, activity_history); reads current_kit_configurations read-only for EDP lookup
│   │   ├── history/
│   │   └── configuration/
│   │       ├── routes.py               # all configuration routes (landing, PQPR, Current Kits, Table Settings) - all table_id-scoped
│   │       ├── pqpr_parser.py          # Excel -> JSON parser for PQPR
│   │       ├── current_kits_data.py    # MongoDB data access + validation for Current Kits (current_kit_configurations)
│   │       └── table_settings_data.py  # MongoDB data access + validation for Table Settings (table_configuration)
│   ├── templates/
│   │   ├── base.html               # shell: header/nav/back-button+table-badge row/subnav block/main/footer
│   │   └── <blueprint_name>/*.html
│   └── static/
│       ├── css/                    # one file per concern (see below)
│       ├── js/                     # one file per concern (see below)
│       └── images/watts_logo.png
```

## Config system

### `config.yaml` (non-secret)
```yaml
app:        { name, version, host, port, debug }
client:     { name, brand, logo_path }
developer:  { name }
theme:      { default, cookie_name, cookie_max_age_days }
storage:
  pqpr_dir: "data/pqpr"
  pqpr_allowed_extensions: [".xlsx", ".xls"]
  max_upload_size_mb: 20
  audio_dir: "data/audio"
  audio_allowed_extensions: [".mp3"]
mongodb:
  db_name: "kitting_station_v2"
  collections:
    current_kits: "current_kit_configurations"
    table_configuration: "table_configuration"
    live_activities: "live_activity_details"
    activity_history: "activity_history"
pqpr_parsing:
  sheet_name: "PQPR - FG -- Copy"
  header_row: 1
  kit_name_column: "B"
  edp_column: "C"
  component_start_column: "H"
  top10_row_count: 10
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

`configuration.tables` is the **table registry** — the single source of truth for which tables exist, their display names, and whether they have real functionality (`built: true`) or show a placeholder (`built: false`). Adding table 4/5 later is purely a config change: append an entry here, nothing in code needs to change for it to show up on the landing page (though its routes will still 404/placeholder until a `built: true` table's worth of routes/templates/data-layer functions are actually written for it, following the Table 1 pattern in `TSD_CONFIGURATION.md`).

### `.env` (secrets)
```
SECRET_KEY=...
FLASK_ENV=development
MONGO_URI=mongodb://localhost:27017/
```

`app/config/loader.py`:
- `load_settings()` reads both, merges, and **fails fast** (raises `ValueError`) if any required key is missing, including `MONGO_URI` — check `_validate_settings()` before adding new config sections, extend `required_paths` there. *(Note: `configuration.tables` was added without editing this file in the session that introduced it — confirm whether fail-fast validation should cover it too.)*
- Exposes `BASE_DIR` (project root) as a module-level constant.

### `app/config/db.py`
- `init_mongo(app, settings)` creates a `MongoClient` and stashes `app.config["MONGO_CLIENT"]` / `app.config["MONGO_DB"]`.
- **Connection is lazy** — pymongo doesn't open a socket until the first operation, matching how the rest of the app doesn't eagerly touch external state at startup. Routes using the DB catch `pymongo.errors.PyMongoError` and return a clean JSON/HTML error instead of a 500 stack trace.

### Runtime access
`app/__init__.py`'s `create_app()`:
- Stores full settings dict at `app.config["SETTINGS"]`.
- Stores `app.config["BASE_DIR"]`, `app.config["SECRET_KEY"]`, `app.config["MAX_CONTENT_LENGTH"]`.
- Calls `init_mongo(app, settings)`.
- A `context_processor` injects theme + branding variables into **every** template automatically — see `TSD_BASE_LAYOUT.md` for the full list.

## Blueprint routing pattern

Each blueprint: `blueprints/<name>/__init__.py` (creates the `Blueprint`, imports `routes` at the bottom to avoid circular imports) + `routes.py`. Templates live in a matching `templates/<name>/` folder. `active_page` is passed into every render so `base.html` can highlight the right top-nav item.

Configuration blueprint is **table_id-scoped end to end**: every URL under `/configuration/table/<int:table_id>/...` (except the landing page itself), every Mongo document, and every filesystem path carries `table_id`. See `TSD_CONFIGURATION.md` for the full route table and the `_require_built_table()` guard pattern. Configuration also has a second nav level (`active_subtab` + `_subnav.html`) — see `TSD_BASE_LAYOUT.md` for the pattern.

Live Kitting Activities follows the same `table_id`-scoping and `_require_built_table()` guard convention (duplicated locally in its own `routes.py` rather than imported, keeping blueprints decoupled) — see `TSD_LIVE_KITTING_ACTIVITIES.md` for its full route table and MongoDB schemas.

**If a future blueprint (e.g. History) needs to vary per table, follow the same conventions**: `table_id` as a URL path parameter, a table-registry lookup + `built` guard before rendering, `table_id` stored on any Mongo documents it writes, and (if it needs file storage) a `data/<concern>/table_<id>/` directory.

## Frontend architecture

### CSS (`app/static/css/`, one file per concern)

**Globally linked** in `base.html`'s `<head>`:
`reset.css` → `variables.css` → `layout.css` → `nav.css` → `branding.css` → `subnav.css` → `upload-widget.css` → `split-panels.css` → `kits-table.css` → `kit-form.css` → `back-button.css`

**Page-specific**, loaded via `{% block extra_css %}` only on the pages that need them (same reasoning as `extra_js` below — a page-specific concern doesn't belong in the global chain):
| File | Loaded on |
|---|---|
| `config-landing.css` | Configuration landing page, table placeholder page |
| `table-settings.css` | Table Settings page |
| `live-activities.css` | Live Kitting Activities landing, create (step 1), camera-check (step 2) |
| `monitor.css` | Live Kitting Activities monitor page only — includes the `.app-main--full-bleed` override (see `TSD_LIVE_KITTING_ACTIVITIES.md`) |

### JS (`app/static/js/`, no bundler, plain `<script src>` tags, all page-specific via `{% block extra_js %}`)
| File | Loaded | Purpose |
|---|---|---|
| `theme-toggle.js` | global | Theme flip + cookie persistence |
| `back-button.js` | global | Browser-history-based back navigation |
| `pqpr-upload.js` | PQPR Analytics page | Upload/replace/download AJAX |
| `pqpr-search.js` | PQPR Analytics page | Two-panel component/kit search |
| `current-kits.js` | Current Kits list page | Live search, delete, row rendering |
| `kit-form.js` | Create/Edit kit page | Dynamic part/neglect-part rows, camera alert config, AJAX save |
| `table-settings.js` | Table Settings page | Deferred audio save + preview, staged IP list, staged email list + notification toggles |
| `live-activity-create.js` | Live Kitting Activities create page (step 1) | Enter-to-advance focus, EDP AJAX lookup, table-busy check on submit |
| `live-activities-list.js` | Live Kitting Activities landing page | Local-timezone start-time formatting, Complete Manually inline confirm + AJAX, View Monitor navigation |
| `monitor.js` | Live Kitting Activities monitor page | Live-ticking elapsed-time timers (header Total Time + both camera panels) |

**Convention:** any new AJAX feature follows the same pattern — endpoint URLs generated server-side with `url_for()` (always including `table_id` for Configuration routes), exposed via `data-*` attributes on a container element, read by an isolated JS file with a single `DOMContentLoaded` listener. Never hardcode a URL in JS.

## Known gaps / next-session TODO

- Flask-SocketIO not wired anywhere yet — Live Kitting Activities' monitor page has live-looking elements (timers, progress bars) but they update via client-side JS against server-rendered static data, not a real push channel. Wiring real detection counts will likely need this, or another push mechanism.
- Live Kitting Activities: every part's detected count is hardcoded to 0 — no CV/detection ingest path exists yet. See `TSD_LIVE_KITTING_ACTIVITIES.md` for the fuller list of gaps specific to that blueprint (per-kit timers, placeholder buttons, missing color tokens).
- MongoDB not connected for History yet.
- No authentication/authorization layer.
- No flash-message system exists yet — silent-redirect is used instead where a message would normally go (e.g. editing a kit that no longer exists).
- PQPR storage is single-file-overwrite-per-table by design (client's explicit choice) — version history would be a deliberate scope change, confirm with client first.
- Table Settings' audio storage is single-file-overwrite-per-slot-per-table, same convention as PQPR.
- Current Kits part-name search uses an unindexed Mongo regex — fine at current scale; add a text index if it grows large and search feels slow.
- `app/config/loader.py`'s `_validate_settings()` includes `configuration.tables` and both Live Kitting Activities collections (`live_activities`, `activity_history`) in its required-paths fail-fast check.
- Tables 2 and 3 are registry-only — no Current Kits Configuration, PQPR Analytics, Table Settings, or Live Kitting Activities functionality exists for them yet. Building it out is a matter of repeating the Table 1 pattern (routes, templates, data-layer functions already all take `table_id` as a parameter) and flipping `built: true` in `config.yaml`.
