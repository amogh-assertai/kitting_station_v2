# TSD — Kitting Station v2 (Whole App)

Technical architecture at the app level. For shell implementation detail, see `TSD_BASE_LAYOUT.md`. For Configuration blueprint detail (routes, MongoDB schema, data flow), see `TSD_CONFIGURATION.md`.

## Stack (fixed — do not change without asking the client/owner)

| Layer | Choice |
|---|---|
| Backend | Flask, Blueprints |
| Templates | Jinja2, server-rendered |
| Real-time | Flask-SocketIO — **not wired yet** |
| Database | MongoDB (`kitting_station_v2`) — **connected for Current Kits Configuration only**; History does not use it yet |
| CSS | Plain CSS + custom properties. No Tailwind/Bootstrap, no build step |
| JS | Vanilla JS only. No framework, no bundler, no inline `<script>` in templates |
| Config | `config.yaml` (non-secret) + `.env` (secrets), merged by a loader module. No hardcoded values in app code |
| File storage | Filesystem (`data/`) — used for PQPR upload only |

## Project structure

```
station_monitor/
├── app.py                          # entry point
├── config.yaml                     # non-secret runtime config
├── .env / .env.example             # secrets
├── requirements.txt
├── data/
│   └── pqpr/                       # PQPR file + parsed cache (gitignored except .gitkeep)
├── app/
│   ├── __init__.py                 # app factory: registers blueprints, context processors, calls init_mongo()
│   ├── config/
│   │   ├── loader.py               # merges config.yaml + .env, fail-fast validation
│   │   └── db.py                   # MongoDB client setup (lazy connection)
│   ├── blueprints/
│   │   ├── home/
│   │   ├── live_kitting_activities/
│   │   ├── history/
│   │   └── configuration/
│   │       ├── routes.py             # all configuration routes (PQPR + Current Kits)
│   │       ├── pqpr_parser.py        # Excel -> JSON parser for PQPR
│   │       └── current_kits_data.py  # MongoDB data access + validation for Current Kits
│   ├── templates/
│   │   ├── base.html               # shell: header/nav/back-button/subnav block/main/footer
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
storage:    { pqpr_dir, pqpr_allowed_extensions, max_upload_size_mb }
mongodb:
  db_name: "kitting_station_v2"
  collections:
    current_kits: "current_kit_configurations"
pqpr_parsing:
  sheet_name: "PQPR - FG -- Copy"
  header_row: 1
  kit_name_column: "B"
  edp_column: "C"
  component_start_column: "H"
  top10_row_count: 10
```

### `.env` (secrets)
```
SECRET_KEY=...
FLASK_ENV=development
MONGO_URI=mongodb://localhost:27017/
```

`app/config/loader.py`:
- `load_settings()` reads both, merges, and **fails fast** (raises `ValueError`) if any required key is missing, including `MONGO_URI` — check `_validate_settings()` before adding new config sections, extend `required_paths` there.
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

Configuration blueprint has a second level (`active_subtab` + `_subnav.html`) — see `TSD_BASE_LAYOUT.md` for the pattern, `TSD_CONFIGURATION.md` for its routes.

## Frontend architecture

### CSS (`app/static/css/`, one file per concern, all linked globally in `base.html`)
`reset.css` → `variables.css` → `layout.css` → `nav.css` → `branding.css` → `subnav.css` → `upload-widget.css` → `split-panels.css` → `kits-table.css` → `kit-form.css` → `back-button.css`

### JS (`app/static/js/`, no bundler, plain `<script src>` tags)
| File | Loaded | Purpose |
|---|---|---|
| `theme-toggle.js` | global | Theme flip + cookie persistence |
| `back-button.js` | global | Browser-history-based back navigation |
| `pqpr-upload.js` | PQPR Analytics page | Upload/replace/download AJAX |
| `pqpr-search.js` | PQPR Analytics page | Two-panel component/kit search |
| `current-kits.js` | Current Kits list page | Live search, delete, row rendering |
| `kit-form.js` | Create/Edit kit page | Dynamic part rows, AJAX save |

**Convention:** any new AJAX feature follows the same pattern — endpoint URLs generated server-side with `url_for()`, exposed via `data-*` attributes on a container element, read by an isolated JS file with a single `DOMContentLoaded` listener. Never hardcode a URL in JS.

## Known gaps / next-session TODO

- Flask-SocketIO not wired — needed for Live Kitting Activities real-time feed.
- MongoDB not connected for History yet.
- No authentication/authorization layer.
- No flash-message system exists yet — silent-redirect is used instead where a message would normally go (e.g. editing a kit that no longer exists).
- PQPR storage is single-file-overwrite by design (client's explicit choice) — version history would be a deliberate scope change, confirm with client first.
- Current Kits part-name search uses an unindexed Mongo regex — fine at current scale; add a text index if it grows large and search feels slow.
