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
| `docs/frd/FRD_LIVE_KITTING_ACTIVITIES.md` | Functional spec of Live Kitting Activities — landing page, create-activity flow, monitor page, live detection pop-ups, per-camera sound, kit timing, completion |
| `docs/tsd/TSD_LIVE_KITTING_ACTIVITIES.md` | Technical spec — routes (incl. `/api/activity-settings`), embedded MongoDB schema (including its three schema-history revisions), the `cv_ingest` blueprint, detection pipeline, alert-type/master-switch logic, Socket.IO events, sound resolution, kit-level timing, completion detection, API error contract |
| `docs/tsd/TSD_CONFIGURATION.md` | Technical spec of the Configuration section, including live-activity config propagation and audio-file caching |
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
- **Live detection ingest — fully built**, including the red-screen /
  error-lock feature, a kit-advance confirmation pop-up, live
  propagation of kit-config edits, and a "See current settings" modal
  (all detailed below and in `FRD_LIVE_KITTING_ACTIVITIES.md` /
  `TSD_LIVE_KITTING_ACTIVITIES.md`): a local DeepStream application
  posts detection events and kit-advance signals to
  `/api/detection-update` and `/api/validate-kit`. The monitor page
  updates in real time via Socket.IO — part counts, Completed/Pending
  card movement, a full-page-half pop-up with the part's photo and
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
  **Two alert types (Wrong Part Error, Validation Error)**, each gated
  by a per-kit, per-camera master switch: a genuinely unrecognized part
  not on the neglect list, or a missing/undercount/overcount issue
  found at kit-validate time, raises a **blocking** red-screen — stays
  on screen (audio looping) until the operator picks System Error or
  Process Error (with an optional comment) and submits; every viewer
  sees and can resolve the same red-screen, and a late-joining viewer
  sees the same locked state immediately. Resolving a Wrong Part Error
  just unlocks the camera; resolving a Validation Error also advances
  the kit and shows the validate call's own image on the red-screen.
  **Neglected-part detections, and an unrecognized part whose alert is
  switched OFF, are both treated as visually expected** — green
  pop-up/sound, counted/carded, never a red interruption — while the
  permanent record always still says exactly what was detected
  (matched / neglected / wrong_part), so nothing is lost even when
  nothing alerts.
  A clean kit advance (no red-screen raised) now shows a brief
  confirmation pop-up — green "Kit N completed, next Kit N+1" with the
  validate call's own image, or a distinct blue "All kits in Cam`<N>`
  completed" when that camera just finished its last kit.
  **Editing the exact kit a live activity is running now propagates to
  that activity immediately** (parts, neglect list, camera alert
  config) — previously a strict one-time snapshot at creation, this is
  the one case where that rule has been deliberately reversed.
  **The same propagation now also applies to Table Settings** — saving
  Audio Settings, Expected Client IPs, or Push Notification Settings
  updates any live activity on that table immediately (table-scoped,
  not kit-scoped, since Table Settings belongs to the table as a
  whole).
  **"See current settings" is now a working modal**, not a placeholder
  — fetches the activity's own live snapshot fresh from MongoDB on
  every open (never the kit's master config or the table's master
  settings, and never cached), showing kit info, per-camera runtime
  state/parts/neglect list/alert configuration, and — added a round
  after the modal's initial build — the activity's Table Settings
  snapshot too (audio slots, expected IPs, push notification emails and
  types).
  **Audio files are now cache-enabled** (`Cache-Control: max-age=3600`
  + conditional ETag/304 support) — previously re-fetched over the
  network on every single play, for every connected client.
  **Red (unexpected-part) audio can no longer be disabled** in Table
  Settings — both radios still render per camera, but Disabled is
  locked out, enforced server-side so a crafted request can't bypass
  the UI either.
  **Two smaller fixes this round:** the Validation Error red-screen's
  issue lines now use the client's exact requested format ("Missing
  Component: `<name>`| Required: `<n>` | Found: `<n>`." for missing,
  a simpler `<name>` | Required: `<n>` | Found: `<n>` for undercount/
  overcount); and a repeat wrong-part detection (alert disabled) now
  correctly creates its own new card each time instead of incorrectly
  re-tagging an earlier card as "Last detected."
  See `FRD_LIVE_KITTING_ACTIVITIES.md` / `TSD_LIVE_KITTING_ACTIVITIES.md`
  for full detail on all of the above; the audio-caching and
  red-audio-lock mechanisms are documented in `TSD_CONFIGURATION.md`
  (they live in the Configuration blueprint, not `cv_ingest`).
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
  timestamp, and every alert raised and how it was resolved — no
  viewer exists yet)
- `detections.<cam>.<kit>.validation` reserved schema key remains
  unpopulated — the validate-call's image is now actually USED (shown
  on the kit-advance confirmation pop-up, and on a Validation Error
  red-screen), but nothing writes a structured pass/fail record to this
  specific key yet; that's still a separate, deferred concern
- History section — placeholder, needs MongoDB
- No authentication/authorization layer
- **`config.yaml` needs a new `live_kitting.validate_popup_uptime_sec`
  key** (plus the matching `app/config/loader.py` fail-fast entry)
  before the kit-advance confirmation pop-up can actually run — flagged
  in `TSD_LIVE_KITTING_ACTIVITIES.md`'s Known Gaps, not yet confirmed
  done as of this doc update

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
│   ├── current_kits_data.py             # kit CRUD + validation; live-activity
│   │                                      # config propagation (update_kit_live_snapshot)
│   └── table_settings_data.py           # audio/IPs/push-notification CRUD + validation;
│                                          # live-activity propagation (update_table_settings_
│                                          # live_snapshot); red-audio-always-enabled enforcement
├── blueprints/live_kitting_activities/
│   └── activities_data.py              # table_settings + neglect/alert-config snapshot, sound toggle
│                                         # seeding, real detection counts + completion state + kit
│                                         # timer start, neglected/wrong_part card shaping,
│                                         # "See current settings" modal view shaping (incl.
│                                         # table_settings sub-section)
├── blueprints/cv_ingest/                # detection ingest from local DeepStream app
│   └── detection_data.py               # validation, image save, count/sound/timing resolution,
│                                         # per-camera + whole-activity completion detection,
│                                         # camera lock state, wrong_part/validation_error alert
│                                         # logic + resolution, Mongo writes
├── extensions.py                        # shared socketio singleton
├── config/
│   ├── loader.py                       # live_kitting.* + activity_history validation -
│   │                                     # STILL NEEDS validate_popup_uptime_sec added, see
│   │                                     # TSD_LIVE_KITTING_ACTIVITIES.md's Known Gaps
│   └── db.py
├── templates/base.html
├── templates/configuration/
│   └── table_settings.html             # Audio Settings rows (red slots locked to Enabled),
│                                         # Expected Client IPs, Push Notification Settings
├── templates/live_kitting_activities/
│   └── monitor.html                    # detection pop-ups, blocking red-screen (issues/buttons/
│                                         # comment), kit-advance confirmation pop-up (green/blue),
│                                         # "See current settings" modal (incl. Table Settings
│                                         # section), sound toggle, kit timer, completion overlay
└── static/{css,js}/
    ├── css/monitor.css                 # detection pop-up, blocking red-screen, neglected/wrong_part
    │                                     # card styling (incl. S/P badge), kit-advance confirmation
    │                                     # pop-up (incl. blue variant), settings modal, sound toggle,
    │                                     # kit timer, completion overlay
    ├── css/table-settings.css          # Audio Settings/IP list/push-notification styling, incl.
    │                                     # the locked-radio look for red audio
    └── js/
        ├── monitor.js                  # Socket.IO wiring, all live-update handlers (incl. error:red/
        │                                 # error:resolved/kit:validated/config:updated), live card
        │                                 # creation for neglected/wrong_part, settings-modal fetch +
        │                                 # render (incl. Table Settings section), sound playback
        │                                 # (one-shot + looping)
        ├── live-activities-list.js     # landing page card behavior; "Started" now shows full
        │                                 # date + time, not time-only
        ├── table-settings.js           # Audio/IP/push-notification staged-save behavior; red
        │                                 # audio slots hardcoded to "enabled" on save regardless
        │                                 # of (locked) DOM radio state
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
