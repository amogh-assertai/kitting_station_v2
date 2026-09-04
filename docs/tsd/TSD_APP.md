# TSD — Kitting Station v2 (Whole App)

Technical architecture at the app level. For shell implementation detail,
see `TSD_BASE_LAYOUT.md`. For Configuration blueprint detail, see
`TSD_CONFIGURATION.md`. For Live Kitting Activities and the new
detection-ingest blueprint, see `TSD_LIVE_KITTING_ACTIVITIES.md`.

## Stack (fixed — do not change without asking the client/owner)

| Layer | Choice |
|---|---|
| Backend | Flask, Blueprints |
| Templates | Jinja2, server-rendered |
| Real-time | **Flask-SocketIO — now wired.** Powers live detection pop-ups, kit-advance sync, and sound-toggle sync on the Live Kitting Activities monitor page. See `TSD_LIVE_KITTING_ACTIVITIES.md`. |
| Database | MongoDB (`kitting_station_v2`) — connected for Current Kits Configuration, Table Settings, and Live Kitting Activities (including all detection data, embedded — no separate detection collection); History does not use it yet |
| CSS | Plain CSS + custom properties. No Tailwind/Bootstrap, no build step |
| JS | Vanilla JS only. No framework, no bundler, no inline `<script>` in templates. One exception: `app/static/js/vendor/socket.io.min.js` is a self-hosted third-party library (see below) |
| Config | `config.yaml` (non-secret) + `.env` (secrets), merged by a loader module. No hardcoded values in app code |
| File storage | Filesystem (`data/`), namespaced per `table_id` — used for PQPR upload, Table Settings' audio uploads, and (new) saved detection frames |

## Project structure

```
station_monitor/
├── app.py                          # entry point - now calls socketio.run(app, ...) instead of app.run(...)
├── config.yaml
├── .env / .env.example
├── requirements.txt
├── data/
│   ├── pqpr/table_<id>/
│   ├── audio/table_<id>/
│   └── detections/table_<id>/      # NEW - saved detection frames, <uuid4hex><ext>
├── app/
│   ├── __init__.py                 # app factory: now also calls socketio.init_app(app)
│   ├── extensions.py                # NEW - shared `socketio = SocketIO(...)` singleton
│   ├── config/
│   │   ├── loader.py                # merges config.yaml + .env; now also validates live_kitting.*
│   │   └── db.py
│   ├── blueprints/
│   │   ├── home/
│   │   ├── live_kitting_activities/
│   │   │   ├── routes.py               # + passes table_configuration collection into create_live_activity()
│   │   │   └── activities_data.py      # + table_settings snapshot, green sound toggle seeding, real detection counts in build_monitor_view()
│   │   ├── cv_ingest/                   # NEW blueprint - detection ingest from local DeepStream app
│   │   │   ├── __init__.py             # no url_prefix; routes are /api/...
│   │   │   ├── routes.py               # /api/detection-update, /api/validate-kit, /api/toggle-sound, /api/detection-image/<dir>/<file>
│   │   │   └── detection_data.py       # validation, image save, count/sound resolution, Mongo writes
│   │   ├── history/
│   │   └── configuration/
│   ├── templates/
│   │   ├── base.html
│   │   └── <blueprint_name>/*.html     # live_kitting_activities/monitor.html now includes detection pop-ups + sound toggle UI
│   └── static/
│       ├── css/
│       │   └── monitor.css             # + detection pop-up, sound toggle styling
│       ├── js/
│       │   ├── monitor.js              # + Socket.IO client wiring, sound playback
│       │   └── vendor/
│       │       └── socket.io.min.js    # NEW - self-hosted Socket.IO v4.7.5 client
│       └── images/watts_logo.png
```

## Config system

### `config.yaml` additions

```yaml
mongodb:
  collections:
    current_kits: "current_kit_configurations"
    table_configuration: "table_configuration"
    live_activities: "live_activity_details"
    activity_history: "activity_history"
    # NOTE: an earlier pass in this build added a "detection_events"
    # collection here. It was REMOVED — detection data is embedded on
    # live_activity_details instead (client's explicit decision: one
    # activity_id must return the complete picture via a single
    # find_one, no join). Do not re-add a detection_events entry
    # without re-confirming that decision with the client.

# NEW section - detection ingest tuning
live_kitting:
  green_popup_uptime_sec: 2      # how long the green detection pop-up stays on screen
  red_popup_uptime_sec: 3        # separately configurable from green (client's explicit call)
  detection_image_dir: "data/detections"
  allowed_image_extensions: [".jpg", ".jpeg", ".png"]
```

`app/config/loader.py`'s `_validate_settings()` fail-fast check now also
covers `mongodb.collections.activity_history`,
`live_kitting.green_popup_uptime_sec`, `live_kitting.red_popup_uptime_sec`,
`live_kitting.detection_image_dir`, and
`live_kitting.allowed_image_extensions`.

### `.env` — unchanged

### Runtime access — `app/__init__.py`'s `create_app()`

Same as before, plus:
- Calls `socketio.init_app(app)` (the `socketio` object lives in the new
  `app/extensions.py`, not created inline — this keeps `create_app()`'s
  signature unchanged, so nothing that already calls it needs to change).
- Registers the new `cv_ingest_bp` alongside the existing four
  blueprints.

`app.py` calls `socketio.run(app, host=..., port=..., debug=...,
allow_unsafe_werkzeug=True)` instead of `app.run(...)` — this is the
only other file that needed to change for Socket.IO to work end to end.

## Blueprint routing pattern

Unchanged general pattern (see `TSD_CONFIGURATION.md` /
`TSD_LIVE_KITTING_ACTIVITIES.md` for the `_require_built_table()`
convention). The new `cv_ingest` blueprint follows the same
duplicated-guard convention as every other blueprint, and registers with
**no `url_prefix`** since its own routes are already prefixed `/api/...`
at the individual route level.

## Frontend architecture

### CSS — no new global files; `monitor.css` (page-specific, unchanged
loading convention via `{% block extra_css %}`) gained substantial new
rules this revision — see `TSD_LIVE_KITTING_ACTIVITIES.md` for the
detection pop-up layout details and the padding-ownership lesson learned
while building it.

### JS

| File | Loaded | Purpose |
|---|---|---|
| `vendor/socket.io.min.js` | Live Kitting Activities monitor page only | Self-hosted Socket.IO v4.7.5 client — **not** loaded from a CDN. This is an on-prem manufacturing HMI; live detection sync should not depend on outbound internet access at runtime. Pulled from the official `socket.io-client` npm package. |
| `monitor.js` | Live Kitting Activities monitor page only | Timers (unchanged) + Socket.IO room join + live pop-up rendering + sound playback + sound-toggle click handling |

**Convention reminder for any future AJAX/socket feature:** endpoint
URLs generated server-side with `url_for()` and exposed via `data-*`
attributes, never hardcoded in JS. The detection pop-up's image URL and
audio URL both follow this — `cv_ingest/routes.py` builds them via
`url_for()` (reusing the existing
`configuration.table_settings_audio_file` route for audio, rather than
duplicating file-serving logic) and sends them over the socket payload;
`monitor.js` just uses whatever URL it's given.

## Known gaps / next-session TODO

Carried over from before this revision, still open:
- MongoDB not connected for History yet.
- No authentication/authorization layer.
- No flash-message system — silent-redirect used instead where a
  message would normally go.
- PQPR and Table Settings' audio storage remain single-file-overwrite by
  design.
- Current Kits part-name search still uses an unindexed Mongo regex.
- Tables 2 and 3 are registry-only.

New from this revision — see `TSD_LIVE_KITTING_ACTIVITIES.md`'s own
"Known gaps" section for the full list (red-alert-type logic, per-kit
timers, a join-before-emit race on the socket connection, audio
playback not yet verified with real MP3 files in a real browser, etc.).
