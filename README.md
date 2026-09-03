# Kitting Station v2

Flask-based, server-rendered HMI web app for a manufacturing kitting station. Built for Watts Water (brand: Dormont) by AssertAI.

For full functional and technical detail, see `docs/` — start with `docs/PROJECT_OVERVIEW.md`.

## Setup

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set `SECRET_KEY` and `MONGO_URI` (a placeholder `.env` is included for local dev, but any real environment should use its own values).

MongoDB must be running and reachable at `MONGO_URI` — Current Kits Configuration, Table Settings, and Live Kitting Activities all depend on it.

## Run

```bash
python app.py
```

Visit http://localhost:7000 (see `app.port` in `config.yaml`).

## What's included so far

- **App shell** — dark/light theme (cookie-based, no flash of wrong theme), top nav with active-page highlighting, global Back button, HMI fit-to-screen layout (no page-level scroll)
- **Multi-table concept** — the app models multiple physical kitting tables/cells via a `table_id` registry in `config.yaml`; Table 1 (HVGKC-CELL) is fully built, Tables 2/3 are registered but show placeholders
- **Configuration** (Table 1 only) — table-selection landing page, Current Kits Configuration (full CRUD + search), PQPR Analytics (Excel upload + two-panel search), Table Settings (Audio Settings, Expected Client IPs, Push Notification Settings)
- **Live Kitting Activities** — landing page (live-activity cards, Complete Manually), 2-step create-activity flow (station/order/EDP lookup → camera check), full-width monitor page with per-camera completed/pending part tracking. Detected part counts are static for now — real detection wiring is a later build.
- `config.yaml` (non-secret runtime config) + `.env` (secrets) merged via `app/config/loader.py`, fail-fast on missing required keys
- CSS split by concern under `app/static/css/`; vanilla JS split by concern under `app/static/js/` — no bundler, no framework

## Not included yet

- Flask-SocketIO wiring (listed as a dependency, not yet connected anywhere)
- Real camera/detection integration for Live Kitting Activities (UI and schema are ready; part counts don't yet reflect live detections)
- History section (placeholder — needs MongoDB)
- Tables 2 and 3 functionality (registry-only)
- Authentication/authorization

## Project structure

```
app/
├── blueprints/            # home, live_kitting_activities, history, configuration
├── templates/              # base.html + one folder per blueprint
├── static/css/             # one file per concern, global + page-specific
├── static/js/               # one file per concern, global + page-specific
├── config/
│   ├── loader.py            # merges config.yaml + .env, fail-fast validation
│   └── db.py                 # MongoDB client setup (lazy connection)
data/                        # gitignored, filesystem storage (PQPR files, audio), namespaced per table_id
docs/
├── PROJECT_OVERVIEW.md      # start here
├── WORKING_STYLE_AND_CONSTRAINTS.md
├── frd/                      # functional specs, one per section
└── tsd/                      # technical specs, one per section
config.yaml                  # non-secret runtime config
.env / .env.example           # secrets
app.py                        # entry point
```

See `docs/PROJECT_OVERVIEW.md` for the full doc index, current build status, and where things live in more detail.
