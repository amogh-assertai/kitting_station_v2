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
| `docs/frd/FRD_LIVE_KITTING_ACTIVITIES.md` | Functional spec of Live Kitting Activities — landing page, create-activity flow, monitor page, live detection pop-ups, per-camera sound, kit timing, completion |
| `docs/tsd/TSD_LIVE_KITTING_ACTIVITIES.md` | Technical spec — routes, embedded MongoDB schema (including its two schema-history revisions), the `cv_ingest` blueprint, detection pipeline, Socket.IO events, sound resolution, kit-level timing, completion detection, API error contract |
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
- **Live detection ingest — fully built, including the red-screen /
  error-lock feature added this session:** a local DeepStream
  application posts detection events and kit-advance signals to
  `/api/detection-update` and `/api/validate-kit`. The monitor page
  updates in real time via Socket.IO — part counts, Completed/Pending
  card movement, a full-page-half pop-up (green for a matched or
  neglected part, red for an unmatched one) with the part's photo and
  detection detail, per-camera detection sound (green toggleable per
  activity and synced across every viewer, red always follows the
  table's saved default), and a per-camera "Kit timer" that resets to
  zero on every validate and hides once that camera finishes.
  Kit-advance signals move a camera's current kit index forward
  independently per camera, with all prior kits' detection data
  (timing + full event log) retained as history nested under that
  kit's own record. Once a camera finishes all its kits it shows a
  "Kits Completed" state and rejects further detections/validations
  with a specific reason code; once **both** cameras finish, the whole
  activity auto-moves to history, "Total time" freezes, and viewers
  see a brief confirmation before being redirected to the landing
  page.
  **Two alert types (Wrong Part Error, Validation Error) are now
  fully built**, each gated by a per-kit, per-camera master switch: an
  unmatched part not on the neglect list, or a missing/undercount/
  overcount issue found at kit-validate time, raises a **blocking**
  red-screen — stays on screen (audio looping) until the operator
  picks System Error or Process Error (with an optional comment) and
  submits; every viewer sees and can resolve the same red-screen, and
  a late-joining viewer sees the same locked state immediately.
  Resolving a Wrong Part Error just unlocks the camera; resolving a
  Validation Error also advances the kit. Neglected-part detections
  are now treated as expected (green pop-up/sound/count), just shown
  with a distinct red-tinted card so the operator can see they were
  intentionally not alerted on. See `FRD_LIVE_KITTING_ACTIVITIES.md` /
  `TSD_LIVE_KITTING_ACTIVITIES.md` for full detail.
- **Kiosk deployment** — `launchers/` at the project root has a
  double-clickable Windows `.bat` and Ubuntu `.desktop`/`.sh` pair that
  open the monitor in Chrome kiosk mode with the flag required for
  detection sound to actually play (`--autoplay-policy=no-user-gesture-required`).
  See `launchers/README.md`.
- `test_kitting_v2_api.py` — a standalone CLI script for exercising the
  detection ingest API without a real DeepStream box; see the file
  itself for usage (`--tableid --camid --object_detected "<part>"` or
  `--tableid --camid --validate`).

**Not yet built:**

- Table 2 (Truck Cell 1) and Table 3 (Truck Cell 2) — still
  registry-only placeholders
- A UI to browse a completed kit's retained detection/timing/alert
  history (the data is fully recorded — per-kit start/first-detection/
  validated timestamps, every individual detection event's own
  timestamp, and now every alert raised and how it was resolved — no
  viewer exists yet)
- Validation-image detail storage (`/api/validate-kit` accepts an image
  but currently discards it after saving to disk — a reserved
  `validation` key exists in the schema for a future build to populate;
  distinct from the new `errors` array, which IS populated)
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
│   └── activities_data.py              # table_settings + neglect/alert-config snapshot, sound toggle
│                                         # seeding, real detection counts + completion state + kit
│                                         # timer start, neglected/wrong_part card shaping for the UI
├── blueprints/cv_ingest/                # detection ingest from local DeepStream app
│   └── detection_data.py               # validation, image save, count/sound/timing resolution,
│                                         # per-camera + whole-activity completion detection,
│                                         # camera lock state, wrong_part/validation_error alert
│                                         # logic + resolution, Mongo writes
├── extensions.py                        # shared socketio singleton
├── config/
│   ├── loader.py                       # live_kitting.* + activity_history validation
│   └── db.py
├── templates/base.html
├── templates/configuration/...
├── templates/live_kitting_activities/
│   └── monitor.html                    # detection pop-ups, blocking red-screen (issues/buttons/
│                                         # comment), sound toggle, kit timer, completion overlay
└── static/{css,js}/
    ├── css/monitor.css                 # detection pop-up, blocking red-screen, neglected/wrong_part
    │                                     # card styling (incl. S/P badge), sound toggle, kit timer,
    │                                     # completion overlay
    └── js/
        ├── monitor.js                  # Socket.IO wiring, all live-update handlers (incl. error:red/
        │                                 # error:resolved), live card creation for neglected/wrong_part,
        │                                 # sound playback (one-shot + looping)
        └── vendor/socket.io.min.js     # self-hosted client

launchers/                               # kiosk-mode deployment, separate from the Flask app
├── Kitting_Station_Kiosk.bat
├── Kitting_Station_Kiosk.desktop
├── kitting-station-kiosk.sh
└── README.md
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
