# TSD — Live Kitting Activities

Technical spec for the Live Kitting Activities blueprint and the new
`cv_ingest` blueprint that feeds it live detection data. For functional
behavior, see `FRD_LIVE_KITTING_ACTIVITIES.md`.

**Status: detection wiring is now built.** Part counts, the completed/
pending split, and per-camera sound are all driven by real events posted
from the local DeepStream application — this is no longer a UI-only stub.

## File map

```
app/blueprints/live_kitting_activities/
├── __init__.py
├── routes.py                    # landing, create flow, monitor page, complete-manually
└── activities_data.py           # MongoDB data access + validation; monitor view shaping

app/blueprints/cv_ingest/         # NEW blueprint - detection ingest, no url_prefix (routes are /api/...)
├── __init__.py
├── routes.py                    # /api/detection-update, /api/validate-kit, /api/toggle-sound,
│                                 # /api/detection-image/<dir>/<file>, Socket.IO room join
└── detection_data.py            # validation, image save, count/sound resolution, Mongo writes

app/templates/live_kitting_activities/
├── index.html
├── create.html
├── camera_check.html
└── monitor.html                 # now includes per-camera detection pop-ups + sound toggle

app/static/css/
├── live-activities.css          # landing + create + camera-check (unchanged)
└── monitor.css                  # monitor page + detection pop-up + sound toggle styling

app/static/js/
├── live-activity-create.js
├── live-activities-list.js
├── monitor.js                   # timers + Socket.IO live sync + sound playback
└── vendor/
    └── socket.io.min.js         # NEW - self-hosted Socket.IO v4.7.5 client (see "Why self-hosted" below)

app/extensions.py                 # NEW - shared `socketio = SocketIO(...)` singleton
```

## MongoDB collections

Only **one** collection now — `detection_events` (introduced mid-build)
was removed in favor of embedding everything on the activity document
itself. See "Why embedded, not a separate collection" below.

```yaml
mongodb:
  collections:
    current_kits: "current_kit_configurations"   # existing - READ ONLY from this blueprint
    live_activities: "live_activity_details"      # read/write, all detection data lives here too
    activity_history: "activity_history"
```

### `live_activity_details` — full current shape

```
{
  "table_id": int,
  "table_name": str,
  "kit_id": ObjectId,
  "kit_name": str,
  "edp_number": str,
  "order_number": str,
  "quantity_required": int,
  "parts_configured": [ ... ],        # copied fresh from the kit doc at creation

  "camera_images": {"cam1": str, "cam2": str},

  "current_kit_index_cam1": int,       # 1-based, advances independently per camera
  "current_kit_index_cam2": int,       # via /api/validate-kit

  "status": "live" | "completed" | "completed-manually",
  "created_at": iso str,
  "updated_at": iso str,

  # --- Table Settings snapshot (added this session) ---
  "table_settings": {
      "audio_settings": { "camera_1_green": {...}, "camera_1_red": {...},
                           "camera_2_green": {...}, "camera_2_red": {...} },
      "expected_client_ips": [str, ...],
      "push_notification_emails": [str, ...],
      "push_notifications": { "<notification_id>": {"enabled": bool, "threshold_percent": float|None}, ... }
  },
  # One-time COPY of the table's Table Settings document (configuration/
  # table_settings_data.py's table_configuration collection), taken at
  # activity-creation time. Never re-read or updated afterward - later
  # edits to Table Settings do NOT retroactively change an in-progress
  # activity's snapshot. Not yet consumed anywhere except audio playback
  # (see below) - client's explicit note: "we will use that in next
  # iteration" for the rest (IPs, notifications).

  # --- Detection data (embedded, added this session) ---
  "part_counts_cam1": { "<kit_index>": { "<part_name>": <int count> } },
  "part_counts_cam2": { "<kit_index>": { "<part_name>": <int count> } },
  # FAST PATH - what the monitor page reads on every render. Updated via
  # $inc, one integer field, one write. NEVER derived by scanning the
  # detections array or querying a second collection. kit_index is an
  # int in application code; Mongo stores the nested key as a string
  # ("1", "2", ...) since object keys are always strings on disk.

  "last_detected_cam1": {"part_name": str, "count": int, "detected_at": iso str} | null,
  "last_detected_cam2": {...} | null,
  # FAST PATH for the "Last detected" badge on a completed part-card.
  # Updated via $set on every MATCHED detection only - an unmatched
  # (red-path) detection never touches this field, so the badge always
  # reflects the most recent successful detection, not the most recent
  # detection of any kind.

  "detections": {
      "cam1": { "<kit_index>": [ {detection event}, ... ] },
      "cam2": { "<kit_index>": [ {detection event}, ... ] }
  },
  # AUDIT TRAIL - full event log, write-heavy ($push), rarely read (a
  # future History drill-down, not the live monitor page). Each event:
  #   {
  #     "detected_part": str,             # validation-driving label
  #     "ai_detected_part_name": str,     # raw AI output, stored, unused for logic
  #     "avg_threshold": float | None,
  #     "tracking_id": str | None,
  #     "image_path": str | None,         # relative path under detection_image_dir
  #     "matched": bool,                  # true = green path, false = red path
  #     "created_at": iso str,
  #   }
  # validate_kit() does NOT touch part_counts/last_detected/detections
  # for the OLD kit index when advancing - that data stays as permanent
  # history. The "reset" the UI shows for a new kit is simply because
  # the new kit_index has no key yet in these maps (reads default to
  # 0 / None), not a delete.

  # --- Sound toggle (added this session) ---
  "green_sound_enabled_cam1": bool,
  "green_sound_enabled_cam2": bool
  # Per-camera, per-ACTIVITY (not per-table). Seeded at creation from
  # table_settings.audio_settings.camera_{N}_green.default_enabled, then
  # independently toggleable via /api/toggle-sound for the lifetime of
  # this activity. Flipping this NEVER writes back to the table's saved
  # Table Settings (table_configuration collection) - client's explicit
  # instruction. Red sound has NO equivalent field - it always reads
  # table_settings.audio_settings.camera_{N}_red.default_enabled
  # directly at playback time, every time, never toggleable per-activity.
}
```

### Why embedded, not a separate `detection_events` collection

An earlier pass in this build used a standalone `detection_events`
collection (activity_id as a foreign key). Client explicitly changed
this: **one activity_id must return the complete picture** with a single
`find_one`, no join, no second collection to keep in sync. All detection
data now lives on the activity document itself, nested camera-wise then
kit-index-wise, exactly as described above.

**Sizing note** (confirmed acceptable at stated scale — 7 components/
camera, up to ~400 kits per activity): worst case is roughly 1–4MB for
the whole `detections` audit array across a full activity's lifetime —
comfortably under MongoDB's 16MB document cap. If a future table runs
far larger volumes, `detections` (the audit log only — **not**
`part_counts`/`last_detected`, which stay tiny regardless of volume) is
the field to consider splitting out first.

## Routes

### `live_kitting_activities` blueprint (unchanged prefix/table)

Same route table as before this session, with one addition to the
`finalize` flow: it now also snapshots Table Settings (see
`create_live_activity()` below) and the `monitor` route reads
`green_sound_enabled` off the activity doc for the sound toggle's
initial render state.

| Route | Method | Purpose |
|---|---|---|
| `/live-kitting-activities` | GET | Landing page |
| `/live-kitting-activities/create` | GET | Step 1 form |
| `/live-kitting-activities/lookup-edp` | POST (AJAX) | EDP lookup |
| `/live-kitting-activities/check-table-busy` | POST (AJAX) | Busy check |
| `/live-kitting-activities/create/camera-check` | GET | Step 2 |
| `/live-kitting-activities/create/finalize` | POST | Writes the activity doc, **now also snapshots table_settings** |
| `/live-kitting-activities/<activity_id>/complete-manually` | POST (AJAX) | Moves to history |
| `/live-kitting-activities/<activity_id>/monitor` | GET | Monitor page, **now with real counts + sound toggle state** |

`create_live_activity()` (`activities_data.py`) signature changed:

```python
def create_live_activity(
    activities_collection,
    kits_collection,
    payload,
    camera_images,
    table_settings_collection=None,   # NEW - optional, backward compatible
):
```

When `table_settings_collection` is passed (routes.py always passes it
now, via a new `_table_settings_collection()` accessor pointing at the
`table_configuration` collection), the resulting activity doc gets a
`table_settings` key (see schema above) and `green_sound_enabled_cam1/2`
seeded from that snapshot. If omitted, behavior is identical to before
this session (no `table_settings` key, callers that don't know about it
still work).

### `cv_ingest` blueprint (new)

No url_prefix — every route is under `/api/...` directly.

| Route | Method | Purpose |
|---|---|---|
| `/api/detection-update` | POST (multipart) | One part-detection event from the DeepStream app |
| `/api/validate-kit` | POST (multipart) | `validate_now` signal — advances one camera's kit index |
| `/api/toggle-sound` | POST (JSON) | Flips one camera's green-sound toggle on the table's current live activity |
| `/api/detection-image/<table_dir>/<filename>` | GET | Serves a saved detection frame for the pop-up's `<img>` |
| (Socket.IO) `join_activity` | — | Client joins the `activity:<id>` room on page load |

Same `_get_tables()` / `_get_table()` / `_require_built_table()` /
`_require_built_table_json()` contract as every other blueprint,
duplicated locally per the project's decoupled-blueprints convention.

#### `POST /api/detection-update`

**Request** (multipart/form-data):

| Field | Type | Notes |
|---|---|---|
| `tableid` | int | Required |
| `camid` | `1` \| `2` \| `"cam1"` \| `"cam2"` | Normalized internally to `cam1`/`cam2` |
| `detectedpart` | str | Required — the validation-driving label |
| `Aidetectedpartname` | str | Raw AI output, stored, never used for matching logic |
| `avg_threshold` | float | Optional |
| `tracking_id` | str | Optional |
| `kitname` | str | Optional (falls back to the activity's own `kit_name`) |
| `image` | file | Optional — frequency/rules still open per client ("will clarify"); safest default is to send one every call |

**Server logic** (`detection_data.record_detection`):

1. Look up the table's current `status: "live"` activity — 400 if none.
2. Match `detectedpart` against `parts_configured`, **scoped to the
   given camera only** (cam1 detections never match cam2-configured
   parts, and vice versa).
3. **Matched** → green path: `$inc` the part's counter for the
   activity's current kit index on that camera, `$set` `last_detected`,
   `$push` the full event onto the audit log. Emits `detection:green`.
4. **Unmatched** → red path: still `$push`s the audit event (`matched:
   false`), does **not** touch any counter or `last_detected`. Emits
   `detection:red`. This is a visual stub only — alert-type
   differentiation (Validation Error vs Wrong Part Error) is still
   deferred, per client's explicit note.
5. All of the above happens in **one atomic `find_one_and_update`**
   (returns the post-update doc so the new count can be read directly,
   no separate read-back call), plus one small follow-up `$set` to
   backfill the count into `last_detected` — 2 Mongo round trips total
   per detection (was 3 in an earlier pass; optimized on client
   request).
6. Resolves whether a sound should play (see "Sound" below) using the
   already-fetched post-update document — no extra query.

**Response:** `{"success": true, "matched": bool, "count": int}` on
success; `{"success": false, "error": str}` (400/500) otherwise. Never a
raw 500 traceback.

**Socket.IO emit** (room `activity:<id>`):

```
"detection:green" → {
  cam_id, part_name, count, quantity_required, kit_index,
  image_url, detected_at, popup_uptime_sec, audio_url
}
"detection:red" → {
  cam_id, detected_part, kit_index,
  image_url, detected_at, popup_uptime_sec, audio_url
}
```

`audio_url` is `null` when no sound should play for this event (see
sound resolution below) — the browser does nothing if it's null, no
separate enabled/disabled logic needed client-side.

#### `POST /api/validate-kit`

**Request:** `tableid`, `camid`, `message` (must be exactly
`"validate_now"`), `image` (optional, saved for audit only, not attached
to any detection event).

**Server logic** (`detection_data.validate_kit`): advances **only** the
given camera's `current_kit_index_cam{N}` by 1. Confirmed: cam1/cam2
advance independently — a `validate_now` for cam1 never touches cam2.
Does not delete or reset any `part_counts`/`last_detected`/`detections`
data for the old kit index; that data becomes that kit's permanent
history simply by no longer being the "current" one read on the monitor
page.

**Socket.IO emit:** `"kit:advanced" → {cam_id, new_kit_index}`.

#### `POST /api/toggle-sound`

**Request (JSON):** `{"table_id": int, "camid": "1"|"2"|"cam1"|"cam2"}`.

**Server logic** (`detection_data.toggle_green_sound`): flips
`green_sound_enabled_cam{N}` on the table's current live activity.
Effective **immediately** for the current kit (client's explicit call —
no "wait for next kit" delay). Writes only to `live_activity_details`;
never touches `table_configuration` (the table's saved Audio Settings
default) — confirmed requirement, "don't change in default."

**Socket.IO emit:** `"sound:toggled" → {cam_id, green_sound_enabled}` —
broadcast to the whole room including the tab that triggered it, so all
viewers (including the one that clicked) update from the same code path
rather than an optimistic client-side flip that could desync on a failed
request.

#### `GET /api/detection-image/<table_dir>/<filename>`

Serves a saved detection frame. Path shape mirrors exactly what
`save_detection_image()` returns (e.g. `table_1/ab12cd34.jpg`) — a
two-segment route rather than a wildcard, to avoid directory-traversal
ambiguity.

## Detection image storage

Filesystem, namespaced per table, same convention as PQPR/audio:

```
data/detections/table_<id>/<uuid4hex><ext>
```

`save_detection_image()` (`cv_ingest/detection_data.py`) returns `None`
if no image was sent (image frequency/rules still open — must not
hard-fail on a request with no image), otherwise returns the path
relative to `detection_image_dir` (what gets stored in the Mongo audit
event and used to build `image_url`).

## Sound system

Two independent rules, per camera:

| Color | Rule | Toggleable? |
|---|---|---|
| **Green** (matched) | Plays if `green_sound_enabled_cam{N}` (on the activity) is true | Yes — `/api/toggle-sound`, per-camera, per-activity, immediate |
| **Red** (unmatched) | Plays if `table_settings.audio_settings.camera_{N}_red.default_enabled` (the table's saved default) is true | No — always reads the snapshot directly, every time |

`detection_data.resolve_sound_for_detection(activity_doc, cam_id,
matched)` implements both rules and also checks that the relevant audio
slot actually has a file uploaded (`original_filename` present) —
`default_enabled: true` with no file ever uploaded still resolves to no
sound, since there's nothing to serve.

The actual audio file is served by **reusing the existing route**
`configuration.table_settings_audio_file` (no new file-serving code in
`cv_ingest`) — `cv_ingest/routes.py`'s `_audio_url_for()` builds the URL
via `url_for()`.

**Browser playback** (`monitor.js`): `playDetectionSound(audioUrl)`
constructs a fresh `Audio(url)` per call (so two rapid detections don't
cut each other off) and calls `.play()`, catching and logging (not
throwing on) autoplay-block rejections — a blocked sound must never
break the rest of the monitor page's live updates.

## Monitor page — detection pop-up UI

### Layout (confirmed requirement, iterated twice this session)

On a detection event, that camera's pop-up covers the **entire page
height on that camera's side** — the global Back button row, the shared
status/progress header, and the camera panel — not just the camera
panel box. Still strictly split left/right by camera; a cam1 event never
crosses into cam2's half, and vice versa.

**Implementation:** the two pop-up elements
(`.detection-popup[data-cam="cam1"]` / `[data-cam="cam2"]`) are **direct
children of `.monitor-page`**, siblings of `.monitor-header` and
`.monitor-cameras` — not nested inside `.camera-panel`. They're
`position: absolute` against `.app-main.app-main--full-bleed` (which is
`position: relative`, and has **zero padding** — padding lives on
`.app-main__top-row` and `.monitor-page` individually instead), with
`top: 0; bottom: 0` and a `left`/`right` split matching
`.monitor-cameras`' two-column grid:

```css
.detection-popup[data-cam="cam1"] { left: 0; right: calc(50% + var(--spacing-md) / 2); }
.detection-popup[data-cam="cam2"] { left: calc(50% + var(--spacing-md) / 2); right: 0; }
```

**Lesson learned (documented for future edits to this CSS):** an earlier
version put padding on `.camera-panel` itself and tried to cancel it
with a matching negative inset on the pop-up
(`inset: calc(-1 * var(--spacing-md))`). This broke in one real
deployment where the two values didn't line up exactly, leaving a
visible gap. Fixed by moving padding to a padded-only child
(`.camera-panel__body`) so the positioning parent has no padding to
fight in the first place. Apply the same pattern (zero-padding
positioning parent, padding on a child) if this pop-up ever needs
further restructuring.

**Image fit:** `object-fit: cover`, not `contain` — `contain` preserves
aspect ratio and can letterbox (leave a visible gap) when the source
image's shape doesn't match the pop-up box; `cover` always fills
completely, cropping if needed. Verified against both a square test
image and a deliberately mismatched 1920×1080 image.

**Colors:** the whole pop-up (not just a metadata strip) is theme-tinted
— dark green/red for the image area, brighter green/red for the
metadata strip. No `--color-success`/`--color-danger` tokens exist yet
in `variables.css` (same known gap as the Complete Manually button) —
hardcoded to match that same color family.

**Metadata format:** one centered line, `Detected: <part name> | Qty: x
/ y` for green (qty segment omitted for red, since there's no
required-qty to show against an unmatched part), plus a right-aligned
timestamp.

**Duration:** `green_popup_uptime_sec` / `red_popup_uptime_sec` from
`config.yaml`, exposed to JS via `data-green-popup-uptime-sec` /
`data-red-popup-uptime-sec` on `.monitor-page` — never hardcoded in JS.
Configured **separately** per color (client's explicit call).

### "Last detected" badge

Exactly one part-card carries the badge at a time, per camera — driven
by `last_detected_cam{N}` on the activity doc (server-side, for
page-load/refresh) and `clearLastDetectedBadges()` in `monitor.js`
(client-side, before tagging a new card on a live socket event). An
earlier version rendered the badge unconditionally on every completed
card, which stuck to multiple cards — fixed on both the server template
(`{% if part.last_detected %}`) and the client JS.

### Sound toggle button

Sits next to "Kit #N" in each camera panel's header
(`.camera-panel__kit-index-group`). Click → `POST /api/toggle-sound` →
waits for the `sound:toggled` broadcast (including back to the same tab)
to actually flip its own icon/state, rather than an optimistic update —
keeps the server as the single source of truth and avoids a failed
request leaving the UI in a state the server doesn't have.

## Socket.IO infrastructure

`app/extensions.py` (new) holds the shared `socketio = SocketIO(...)`
singleton, `async_mode="threading"` (no eventlet/gevent in
`requirements.txt` — this mode needs neither). `app/__init__.py` calls
`socketio.init_app(app)`; `app.py` calls `socketio.run(app, ...)`
instead of `app.run(...)`.

**Why self-hosted, not CDN:** the client script
(`app/static/js/vendor/socket.io.min.js`) is bundled locally rather than
loaded from `cdn.socket.io`. This is an on-prem manufacturing HMI — the
monitor page's live detection sync should not depend on the station
having outbound internet access at runtime. Pulled from the official
`socket.io-client` npm package (same file the CDN would serve), version
4.7.5 to match Flask-SocketIO 5.3.x's default protocol.

**Room strategy:** one room per activity (`activity:<id>`), joined via a
`join_activity` Socket.IO event sent by `monitor.js` on `connect`. Every
detection/kit-advance/sound-toggle event for that activity is emitted
only to that room — never broadcast app-wide.

## Known gaps / next-session TODO

- **Red-popup alert-type logic** is still a stub — full differentiation
  between Validation Error and Wrong Part Error (per the per-camera
  alert config already in Current Kits Configuration) is deferred.
- **No per-kit timer** — unchanged from before this session; both camera
  panels' timers still show the whole activity's elapsed time.
- **"See current settings" and "History" buttons** are still unwired
  placeholders.
- **`table_settings` snapshot is stored but only partially consumed** —
  only `audio_settings` (for sound) is read anywhere right now.
  `expected_client_ips` and `push_notifications` are captured at
  creation time but not yet used by any code path (client's explicit
  note: "we will use that in next iteration").
- **Detection ingest race on page load**: if a detection arrives before
  a browser tab's Socket.IO `join_activity` handshake completes (e.g.
  right as the monitor page opens), that event is silently missed by
  that tab — no error, just a missed pop-up/count update for that one
  tab (other tabs already joined are unaffected, and the underlying
  Mongo write still happens regardless). Flagged, not yet fixed — low
  probability in real operation, and client confirmed no queueing is
  needed for now.
- **No rate-limiting** on the ingest endpoints.
- **Audio playback not verified with real MP3 files** — testing this
  session used placeholder non-decodable audio bytes in a headless
  browser (autoplay/`Audio.play()` was exercised via interception, not
  actual sound output). Confirm with real files in a real browser before
  relying on this in production.
- Camera-check images are still fixed static placeholders — unchanged
  from before this session.
