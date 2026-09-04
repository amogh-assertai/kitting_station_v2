# Kitting Station v2 — Project Overview

Read this first. It orients a new agent session (or a new developer) on
what this app is, what's built, and where to find detail.

## What this is

A Flask-based, server-rendered web app styled and used like an HMI
(Human-Machine Interface) — built for a manufacturing kitting station.
Runs on laptop monitors and larger fixed screens; no page-level scroll.

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
| `docs/tsd/TSD_APP.md` | Whole-app technical architecture — stack, project structure, config system, frontend conventions, Socket.IO wiring |
| `docs/frd/FRD_BASE_LAYOUT.md` | Functional spec of the shared shell |
| `docs/tsd/TSD_BASE_LAYOUT.md` | Technical spec of the shell |
| `docs/frd/FRD_CONFIGURATION.md` | Functional spec of the Configuration section |
| `docs/tsd/TSD_CONFIGURATION.md` | Technical spec of the Configuration section |
| `docs/frd/FRD_LIVE_KITTING_ACTIVITIES.md` | Functional spec of Live Kitting Activities — landing page, create-activity flow, monitor page, **live detection pop-ups, per-camera sound (new)** |
| `docs/tsd/TSD_LIVE_KITTING_ACTIVITIES.md` | Technical spec — routes, embedded MongoDB schema, **the `cv_ingest` blueprint, detection pipeline, Socket.IO events, sound resolution (new)** |
| `docs/WORKING_STYLE_AND_CONSTRAINTS.md` | How the client works. **Read before making any change or delivering anything.** |

## Multi-table concept

Unchanged — see `configuration.tables` in `config.yaml`. Only Table 1
(HVGKC-CELL) is built. Live Kitting Activities' detection ingest, like
everything else, only functions for Table 1 (Tables 2/3 have no kit data
to detect against).

## Current state (high level)

**Built (Table 1 / HVGKC-CELL only):**

- App shell — theming, HMI fit-to-screen layout, top nav, global back
  button + table badge
- Configuration → table-selection landing page, Current Kits
  Configuration (full CRUD), PQPR Analytics, Table Settings (Audio
  Settings, Expected Client IPs, Push Notification Settings)
- Live Kitting Activities — landing page, 2-step create-activity flow,
  full-width/height monitor page
- **Live detection ingest (new this revision):** a local DeepStream
  application posts detection events and kit-advance signals to
  `/api/detection-update` and `/api/validate-kit`. The monitor page
  updates in real time via Socket.IO — part counts, Completed/Pending
  card movement, a full-page-half pop-up (green for an expected part,
  red for an unexpected one) with the part's photo and detection detail,
  and per-camera detection sound (green toggleable per activity, red
  always follows the table's saved default). Kit-advance signals move a
  camera's current kit index forward independently per camera, with all
  prior kits' detection data retained as history. See
  `FRD_LIVE_KITTING_ACTIVITIES.md` / `TSD_LIVE_KITTING_ACTIVITIES.md`
  for full detail.
- `test_kitting_v2_api.py` — a standalone CLI script for exercising the
  detection ingest API without a real DeepStream box; see the file
  itself for usage (`--tableid --camid --object_detected "<part>"` or
  `--tableid --camid --validate`).

**Not yet built:**

- Table 2 (Truck Cell 1) and Table 3 (Truck Cell 2) — still
  registry-only placeholders
- Full alert-type logic for unexpected/wrong-part detections (only the
  visual red pop-up exists so far — no differentiation between
  Validation Error and Wrong Part Error yet)
- Per-kit timing (both camera panels still show the whole activity's
  elapsed time, not a per-kit reset)
- A UI to browse a completed kit's retained detection history (the data
  is recorded, no viewer exists yet)
- History section — placeholder, needs MongoDB
- No authentication/authorization layer

## Tech stack (fixed — don't change without asking the client)

Flask + Blueprints · Jinja2 (server-rendered) · **Flask-SocketIO — now
wired** (see `TSD_LIVE_KITTING_ACTIVITIES.md`) · MongoDB
(`kitting_station_v2` db) · plain CSS + custom properties · vanilla JS,
no bundler (one exception: a self-hosted, not CDN-loaded, Socket.IO
client — see `TSD_APP.md`) · `config.yaml` (non-secret) + `.env`
(secrets)

Full detail: `docs/tsd/TSD_APP.md`.

## Running locally

1. `pip install -r requirements.txt` (Flask-SocketIO already listed; no
   new dependencies were added by the detection-ingest work — see
   `test_kitting_v2_api.py`'s own docstring for its two extra test-only
   dependencies, `requests` and `Pillow`, not needed to run the app
   itself)
2. Copy `.env.example` → `.env`, set `SECRET_KEY` and `MONGO_URI`
3. Make sure MongoDB is running and reachable at `MONGO_URI`
4. `python app.py` — this now starts the app via `socketio.run()`, not
   `app.run()` (required for Socket.IO's websocket/polling transport to
   work), but is otherwise a drop-in equivalent for local dev

## Where things live

```
app/
├── blueprints/<name>/routes.py
├── blueprints/configuration/
│   ├── pqpr_parser.py
│   ├── current_kits_data.py
│   └── table_settings_data.py
├── blueprints/live_kitting_activities/
│   └── activities_data.py              # + table_settings snapshot, sound toggle seeding, real detection counts
├── blueprints/cv_ingest/                # NEW - detection ingest from local DeepStream app
│   └── detection_data.py               # validation, image save, count/sound resolution, Mongo writes
├── extensions.py                        # NEW - shared socketio singleton
├── config/
│   ├── loader.py                       # + live_kitting.* validation
│   └── db.py
├── templates/base.html
├── templates/configuration/...
├── templates/live_kitting_activities/
│   └── monitor.html                    # + detection pop-ups, sound toggle UI
└── static/{css,js}/
    ├── css/monitor.css                 # + detection pop-up, sound toggle styling
    └── js/
        ├── monitor.js                  # + Socket.IO wiring, sound playback
        └── vendor/socket.io.min.js     # NEW - self-hosted client
```

Filesystem storage (gitignored, under `data/`, namespaced per table_id):
```
data/pqpr/table_<id>/
data/audio/table_<id>/
data/detections/table_<id>/         # NEW - saved detection frames, <uuid4hex><ext>
```

## Before you change anything

Read `docs/WORKING_STYLE_AND_CONSTRAINTS.md`. Short version: confirm
scope before building, ask short option-based questions when something's
ambiguous, state assumptions explicitly, test end-to-end with
`mongomock` (and, for anything touching layout/CSS, a real headless
browser — Playwright was used throughout the detection-ingest build to
catch layout bugs that mongomock-only testing would have missed) before
delivering, and deliver only changed/new files (zipped with real
relative paths if more than 3).
