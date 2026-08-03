# Kitting Station v2 — Technical Documentation

## Stack (fixed — do not change without asking the client/owner)

| Layer | Choice |
|---|---|
| Backend | Flask, Blueprints |
| Templates | Jinja2, server-rendered |
| Real-time | Flask-SocketIO — **not wired yet** |
| Database | MongoDB — **not connected yet** |
| CSS | Plain CSS + custom properties. No Tailwind/Bootstrap, no build step |
| JS | Vanilla JS only. No framework, no bundler, no inline `<script>` in templates |
| Config | `config.yaml` (non-secret) + `.env` (secrets), merged by a loader module. No hardcoded values in app code |
| File storage | Filesystem (`data/`) — no DB yet for uploaded files |

## Project structure

```
station_monitor/
├── app.py                          # entry point
├── config.yaml                     # non-secret runtime config
├── .env / .env.example             # secrets
├── requirements.txt
├── data/
│   └── pqpr/                       # PQPR file + parsed cache live here (gitignored except .gitkeep)
├── app/
│   ├── __init__.py                 # app factory, blueprint registration, context processor
│   ├── config/
│   │   └── loader.py               # merges config.yaml + .env, validates required keys
│   ├── blueprints/
│   │   ├── home/
│   │   ├── live_kitting_activities/
│   │   ├── history/
│   │   └── configuration/
│   │       ├── routes.py           # all configuration routes incl. PQPR upload/search
│   │       └── pqpr_parser.py      # Excel -> JSON parser for the PQPR sheet
│   ├── templates/
│   │   ├── base.html               # shell: header/nav/subnav block/main/footer
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
```

`app/config/loader.py`:
- `load_settings()` reads both, merges, and **fails fast** (raises `ValueError`) if any required key is missing — check `_validate_settings()` before adding new config sections, extend the `required_paths` list there.
- Exposes `BASE_DIR` (project root) as a module-level constant.

### Runtime access
`app/__init__.py`'s `create_app()`:
- Stores full settings dict at `app.config["SETTINGS"]`.
- Stores `app.config["BASE_DIR"]`, `app.config["SECRET_KEY"]`, `app.config["MAX_CONTENT_LENGTH"]`.
- A `context_processor` injects `current_theme`, `theme_cookie_name`, `theme_cookie_max_age_days`, `app_name`, `app_version`, `client_name`, `client_brand`, `client_logo_path`, `developer_name` into **every** template automatically — no per-route work needed to use these in a template.

## Theming
- Dark is default. `current_theme` is resolved server-side from the `theme_preference` cookie in the context processor, and written onto `<html data-theme="...">` in `base.html` — **this is what avoids flash-of-wrong-theme**, don't move theme resolution to client JS.
- All colors/spacing/fonts are CSS custom properties in `variables.css`, scoped under `[data-theme="dark"]` / `[data-theme="light"]`.
- `theme-toggle.js` only flips the attribute + sets the cookie client-side after the initial correct render.

## Fit-to-screen (HMI) layout
`layout.css`: `html, body { height: 100vh; overflow: hidden; }`, `body` is a column flex with fixed-height header/subnav/footer and `.app-main { flex:1; min-height:0; overflow-y:auto; }`. This means **no page ever needs its own scroll CSS** — any page's content that overflows will scroll inside `.app-main` automatically. `.app-main` also has a visible border (per client request, to delineate the working window).

## Blueprint routing pattern
Each blueprint: `blueprints/<name>/__init__.py` (creates the `Blueprint`, imports `routes` at the bottom to avoid circular imports) + `routes.py`. Templates live in a matching `templates/<name>/` folder. `active_page` is passed into every render so `base.html` can highlight the right top-nav item.

**Configuration blueprint has a second level**: `active_subtab` + `templates/configuration/_subnav.html` (included via `{% block subnav %}` in `base.html`, which is empty for non-configuration pages). Follow this same pattern if another top-nav page needs sub-tabs later.

## PQPR Analytics — data flow

1. **Upload** (`POST /configuration/pqpr-analytics/upload`, multipart `pqpr_file`):
   - Validates extension against `storage.pqpr_allowed_extensions`.
   - Deletes any existing `pqpr_current.*` in `data/pqpr/`, saves the new one under that fixed name (extension preserved) — **overwrite only, no version history**.
   - Writes `data/pqpr/pqpr_meta.json`: `{original_filename, stored_extension, uploaded_at}`.
   - Calls `pqpr_parser.parse_pqpr_workbook()` and caches the result to `data/pqpr/pqpr_parsed.json`.
2. **Download** (`GET /configuration/pqpr-analytics/download`): serves the stored file back with the original filename via `send_file(..., download_name=...)`.
3. **Parsing** (`app/blueprints/configuration/pqpr_parser.py`):
   - Everything about sheet layout is read from `pqpr_parsing` config — sheet name, header row, kit name/EDP columns, where component columns start. **If the client's sheet layout changes, update `config.yaml` only — no code change needed**, per the original requirement.
   - A cell is treated as quantity `1` if its value is literally `"x"` (case-insensitive), otherwise it's parsed as an int if possible, otherwise skipped.
   - `is_top10` is just `row_index <= pqpr_parsing.top10_row_count` — **not a computed metric**, purely positional in the sheet.
   - Output shape:
     ```json
     {
       "components": ["A50C", "A75C", ...],
       "kits": [
         {"edp": "0241276", "kit_name": "1675KIT48", "is_top10": true,
          "components": {"A75C": 1, "A50N": 1}}
       ]
     }
     ```
4. **On-demand fallback**: `_load_parsed_data()` in `routes.py` re-parses from the stored Excel file if `pqpr_parsed.json` is missing (covers files uploaded before the parsing feature existed, or if the cache file is deleted).

### Search endpoints

| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/configuration/pqpr-analytics/search-kits` | `q` | `{results: [{edp, kit_name, is_top10}]}` (max 20) |
| GET | `/configuration/pqpr-analytics/kit-details` | `edp` | `{success, edp, kit_name, is_top10, components: [{name, qty}]}` |
| GET | `/configuration/pqpr-analytics/search-components` | `q` | `{results: ["A75C", ...]}` (max 20) |
| GET | `/configuration/pqpr-analytics/component-details` | `component` | `{success, component, kits: [{edp, kit_name, is_top10, qty}]}`, top10 kits sorted first |

All four are wrapped in `try/except Exception` and always return valid JSON (500 with an `error` field on failure) — **this matters**: the frontend JS assumes `response.json()` always succeeds, so any new endpoint added for this UI should keep that contract, or the JS will silently break (this happened once — see fix commit where all 4 endpoints got wrapped).

## Frontend architecture

### CSS (`app/static/css/`, one file per concern, all linked in `base.html`)
`reset.css` → `variables.css` → `layout.css` → `nav.css` → `branding.css` → `subnav.css` → `upload-widget.css` → `split-panels.css`

### JS (`app/static/js/`, no bundler, plain `<script src>` tags)
- `theme-toggle.js` — global, loaded in `base.html`.
- `pqpr-upload.js` — upload/replace/download widget logic, AJAX via `fetch`. Reads endpoint URLs from `data-*` attributes on `#pqpr-upload-widget` (never hardcode URLs in JS — always pass via `url_for()` in the template into a `data-` attribute).
- `pqpr-search.js` — both search panels. Same `data-*` URL pattern via `#pqpr-search-panels`. Debounced type-ahead (250ms) + explicit Enter/Search-button path that also handles the zero-match / single-match cases directly.

**Convention going forward:** any new AJAX feature should follow the same pattern — endpoint URLs generated server-side with `url_for()`, exposed via `data-*` attributes on a container element, read by an isolated JS file with a single `DOMContentLoaded` listener.

## Known gaps / next-session TODO
- Flask-SocketIO not wired — needed for Live Kitting Activities real-time feed.
- MongoDB not connected — needed for History, and eventually should replace the filesystem-based PQPR storage if multi-user/audit-trail matters.
- No authentication/authorization layer yet.
- Current Kits Configuration tab is still a placeholder.
- PQPR storage is single-file-overwrite by design (client's explicit choice) — if version history is ever wanted, that's a deliberate scope change, confirm with client first.
