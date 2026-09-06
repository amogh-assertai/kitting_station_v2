# TSD — Live Kitting Activities

Technical spec for the Live Kitting Activities blueprint and the
`cv_ingest` blueprint that feeds it live detection data. For functional
behavior, see `FRD_LIVE_KITTING_ACTIVITIES.md`.

**Status: fully built and live-tested.** Part counts, the completed/
pending split, per-camera sound, kit-level timing, camera/activity
completion, and cross-client real-time sync are all driven by real
events posted from the local DeepStream application — this is not a
stub.

## File map

```
app/blueprints/live_kitting_activities/
├── __init__.py
├── routes.py                    # landing, create flow, monitor page, complete-manually
└── activities_data.py           # MongoDB data access + validation; monitor view shaping

app/blueprints/cv_ingest/         # detection ingest blueprint, no url_prefix (routes are /api/...)
├── __init__.py
├── routes.py                    # /api/detection-update, /api/validate-kit, /api/toggle-sound,
│                                 # /api/detection-image/<dir>/<file>, Socket.IO room join
└── detection_data.py            # validation, image save, count/sound/timing resolution, Mongo writes

app/templates/live_kitting_activities/
├── index.html
├── create.html
├── camera_check.html
└── monitor.html                 # detection pop-ups, sound toggle, per-kit timer, completion overlay

app/static/css/
├── live-activities.css          # landing + create + camera-check (unchanged from before detection wiring)
└── monitor.css                  # monitor page + detection pop-up + sound toggle + completion overlay

app/static/js/
├── live-activity-create.js
├── live-activities-list.js
├── monitor.js                   # timers + Socket.IO live sync + sound playback + completion redirect
└── vendor/
    └── socket.io.min.js         # self-hosted Socket.IO v4.7.5 client (see "Why self-hosted" below)

app/extensions.py                 # shared `socketio = SocketIO(...)` singleton
```

## MongoDB collections

One collection only. An earlier pass in this build used a separate
`detection_events` collection — **removed** in favor of embedding
everything on the activity document itself, per client decision: one
`activity_id` must return the complete picture via a single `find_one`,
no join, no second collection to keep in sync. Do not re-add a
`detection_events`-style collection without re-confirming that decision.

```yaml
mongodb:
  collections:
    current_kits: "current_kit_configurations"   # existing - READ ONLY from this blueprint
    live_activities: "live_activity_details"      # read/write, all detection data lives here too
    activity_history: "activity_history"          # auto- AND manually-completed activities land here
```

## `live_activity_details` — full current document shape

```python
{
  "table_id": int,
  "table_name": str,
  "kit_id": ObjectId,
  "kit_name": str,
  "edp_number": str,
  "order_number": str,
  "quantity_required": int,           # target kit count, shared by both cameras
  "parts_configured": [ ... ],        # copied fresh from the kit doc at creation

  "camera_images": {"cam1": str, "cam2": str},

  "current_kit_index_cam1": int,      # 1-based. Advances independently per
  "current_kit_index_cam2": int,      # camera via /api/validate-kit. Can go
                                       # ONE past quantity_required - that's
                                       # the "this camera is done" sentinel
                                       # (see "Completion semantics" below).

  "status": "live" | "completed" | "completed-manually",
  "created_at": iso str,
  "updated_at": iso str,

  # --- Table Settings snapshot (one-time copy at activity creation) ---
  "table_settings": {
      "audio_settings": { "camera_1_green": {...}, "camera_1_red": {...},
                           "camera_2_green": {...}, "camera_2_red": {...} },
      "expected_client_ips": [str, ...],
      "push_notification_emails": [str, ...],
      "push_notifications": { "<notification_id>": {"enabled": bool, "threshold_percent": float|None}, ... }
  },
  # Copied from configuration/table_settings_data.py's table_configuration
  # collection, ONCE, at activity-creation time. Never re-read or updated
  # afterward - later edits to Table Settings do NOT retroactively change
  # an in-progress activity's snapshot. Only "audio_settings" is consumed
  # anywhere right now (sound playback, see below). expected_client_ips
  # and push_notifications are captured but UNUSED so far - reserved for
  # a future iteration per client's explicit note.

  # --- Sound toggle (per-camera, per-ACTIVITY, not per-table) ---
  "green_sound_enabled_cam1": bool,
  "green_sound_enabled_cam2": bool,
  # Seeded at creation from table_settings.audio_settings.camera_{N}_green
  # .default_enabled, then independently toggleable via /api/toggle-sound
  # for the lifetime of this activity. Flipping this NEVER writes back to
  # table_configuration (client's explicit instruction: "don't change in
  # default"). Red sound has NO equivalent field - it always reads
  # table_settings.audio_settings.camera_{N}_red.default_enabled directly
  # at playback time, every time, never toggleable per-activity.

  # --- Fast-path read fields (never derived by scanning detections) ---
  "part_counts_cam1": { "<kit_index>": { "<part_name>": <int count> } },
  "part_counts_cam2": { "<kit_index>": { "<part_name>": <int count> } },
  # What the monitor page/socket handlers actually read on every render.
  # Updated via $inc, one integer, one write. kit_index keys are cast to
  # str() on write/read (Mongo object keys are always strings on disk).

  "last_detected_cam1": {"part_name": str, "count": int, "detected_at": iso str} | None,
  "last_detected_cam2": {...} | None,
  # Drives the "Last detected" badge on a completed part-card. Updated
  # via $set on every MATCHED detection only - an unmatched (red-path)
  # detection never touches this, so the badge always reflects the most
  # recent SUCCESSFUL detection, not the most recent detection of any kind.

  # --- Per-kit record: timing + audit log, ONE path per kit ---
  "detections": {
      "cam1": {
          "<kit_index>": {
              "timing": {
                  "actual_kit_start_time": iso str,
                  "first_part_detected_time": iso str | None,
                  "validated_at": iso str | None,
              },
              "validation": { ... } | None,   # RESERVED, not yet populated -
                                               # see "Reserved: validation
                                               # detail" below
              "events": [
                  {
                      "detected_part": str,           # validation-driving label
                      "ai_detected_part_name": str,    # raw AI output, stored, unused for logic
                      "avg_threshold": float | None,
                      "tracking_id": str | None,
                      "image_path": str | None,        # relative path under detection_image_dir
                      "matched": bool,                 # true = green path, false = red path
                      "created_at": iso str,
                  },
                  ...
              ]
          }
      },
      "cam2": { ... }
  }
}
```

### Schema history — read this before touching `detections`

This shape went through two real revisions in this build, both driven by
explicit client feedback:

1. **Separate `detection_events` collection → embedded.** Confirmed
   requirement: one `activity_id`, one `find_one`, complete picture, no
   join.
2. **Flat `kit_timings_cam{1,2}` tree → nested inside
   `detections.cam{N}.<kit_index>.timing`.** Client's explicit
   restructure request: "we are creating new keys kit_timings_cam1
   separately... we can store that in detections→cam1→1(kit
   number)... also validation details also can be saved there in the
   future... so all the information will be in one direction to read."
   This meant `detections.cam1.<kit_index>` could no longer be a bare
   array (timing fields have no natural home in an array) — it became an
   object `{timing, validation, events}`, with the old array moving to
   the `.events` key. **Every `$push` now targets `<kit_base>.events`,
   not `<kit_base>` directly.**

If you're about to add a third kind of per-kit data (anything else that
belongs to "this kit, this camera"), it almost certainly belongs as a
new sibling key under `detections.<cam>.<kit_index>`, not a new
top-level tree. That's the whole point of this restructure.

### Reserved: validation detail

`detections.<cam>.<kit_index>.validation` is a **reserved, currently
unpopulated** key. `/api/validate-kit` already accepts an optional
`image` field, but as of this build that image is only saved to disk
(via `save_detection_image`) and then **discarded** — no `image_path` or
any other validation detail is written into Mongo yet. When a future
build needs to store "what did the kit look like at validation time,"
or "did this kit pass/fail and why," write it under this key —
alongside `timing` and `events` for that same kit, not a new tree.

### Kit-index keys are strings on disk, ints in Python

`kit_index` is always an `int` in application code (`current_kit_index_cam1`,
loop variables, etc.), but every nested Mongo path segment built from it
(`f"detections.{cam_id}.{kit_index}"`, `f"part_counts_{cam_id}.{kit_index}"`)
gets auto-cast to a string by MongoDB's dotted-path mechanism on write.
**Every read must explicitly `str(kit_index)`** when indexing into the
dict pulled back from Mongo — Python dicts don't do that coercion for
you. Every existing helper (`_kit_start_time`, `get_part_count`, etc.)
already does this; follow the same pattern for anything new.

### Completion semantics

`current_kit_index_cam{N}` can exceed `quantity_required` by **exactly
one step**. Example: `quantity_required=5` → kit index 5 is a completely
normal working kit, exactly like kits 1–4. Validating kit 5 advances the
index to **6**, and index 6 (which has no real kit data of its own — no
`parts_configured` slot, no card, nothing) is the sentinel meaning "this
camera has completed all its kits."

`_is_camera_completed(activity_doc, cam_id)` in `cv_ingest/detection_data.py`
is the single source of truth for this check:

```python
def _is_camera_completed(activity_doc, cam_id):
    kit_index = activity_doc.get(_kit_index_field(cam_id), 1)
    target = activity_doc.get("quantity_required", 0)
    return target > 0 and kit_index > target
```

Called everywhere it matters: `record_detection`, `validate_kit`, and
`activities_data.build_monitor_view` (independently — `build_monitor_view`
recomputes its own local `is_completed` per camera rather than importing
across blueprints, per the decoupled-blueprints convention). Once a
camera is completed:
- **Further detections** for that camera are rejected (`reason:
  "camera_completed"`, see "API error contract" below)
- **Further validate_kit calls** for that camera are also rejected, same
  reason
- The **other** camera is completely unaffected — independent per
  camera, confirmed requirement

### Whole-activity completion (both cameras done)

When `validate_kit` on one camera causes `activity_fully_completed=True`
(checked by also inspecting the *other* camera's already-known index —
no extra query, since the pre-update `activity_doc` still has it), the
whole activity auto-moves to `activity_history`:

- Status becomes `"completed"` (the same value already used alongside
  `"completed-manually"` — reached automatically here instead of via the
  landing page's Complete Manually button)
- `completed_at` is stamped with the **exact timestamp of the
  triggering `validate_kit` call**, not a fresh one computed later, so
  the monitor page's "Total time" freezes at precisely that instant
  (see `cv_ingest.detection_data.complete_activity_if_both_cameras_done`)
- `stop_reason` is `None` (this isn't a manual stop)
- The full document is copied (not reconstructed) into
  `activity_history`, mirroring
  `live_kitting_activities/activities_data.py`'s own
  `complete_activity_manually()` pattern exactly, duplicated rather than
  imported per this project's decoupled-blueprints convention
- The original document is deleted from `live_activity_details`

The function is idempotent-safe: if called twice (shouldn't happen, but
defensively), a missing document is a silent no-op, never a raised
error — by the time this runs, the camera-level `validate` has already
succeeded and returned 200 to the caller; failing to *also* complete to
history should never surface as an error on top of that.

## Routes

### `live_kitting_activities` blueprint

| Route | Method | Purpose |
|---|---|---|
| `/live-kitting-activities` | GET | Landing page |
| `/live-kitting-activities/create` | GET | Step 1 form |
| `/live-kitting-activities/lookup-edp` | POST (AJAX) | EDP lookup |
| `/live-kitting-activities/check-table-busy` | POST (AJAX) | Busy check |
| `/live-kitting-activities/create/camera-check` | GET | Step 2 |
| `/live-kitting-activities/create/finalize` | POST | Writes the activity doc, snapshots table_settings, seeds sound toggle defaults and kit 1's timing |
| `/live-kitting-activities/<activity_id>/complete-manually` | POST (AJAX) | Moves to history, status `completed-manually` |
| `/live-kitting-activities/<activity_id>/monitor` | GET | Monitor page — real counts, sound toggle state, per-kit timer start |

`create_live_activity()` signature (in `activities_data.py`):

```python
def create_live_activity(
    activities_collection,
    kits_collection,
    payload,
    camera_images,
    table_settings_collection=None,   # optional, backward compatible
):
```

When `table_settings_collection` is passed (routes.py always passes it,
via `_table_settings_collection()` pointing at the `table_configuration`
collection), the new activity doc gets: a `table_settings` snapshot,
`green_sound_enabled_cam1/2` seeded from that snapshot, and
`detections.cam{1,2}.1` pre-seeded with `{"timing": {"actual_kit_start_time":
<now>, "first_part_detected_time": None, "validated_at": None}, "events": []}`.

### `cv_ingest` blueprint

No `url_prefix` — every route is under `/api/...` directly at the
individual route level.

| Route | Method | Purpose |
|---|---|---|
| `/api/detection-update` | POST (multipart) | One part-detection event from the DeepStream app |
| `/api/validate-kit` | POST (multipart) | `validate_now` signal — advances one camera's kit index |
| `/api/toggle-sound` | POST (JSON) | Flips one camera's green-sound toggle on the table's current live activity |
| `/api/detection-image/<table_dir>/<filename>` | GET | Serves a saved detection frame for the pop-up's `<img>` |
| (Socket.IO) `join_activity` | — | Client joins the `activity:<id>` room on page load |

Same `_get_tables()` / `_get_table()` / `_require_built_table()` /
`_require_built_table_json()` contract as every other blueprint,
duplicated locally per this project's decoupled-blueprints convention.

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

1. Look up the table's current `status: "live"` activity — if none,
   raise `ValidationError(..., reason=REASON_NO_LIVE_ACTIVITY)`.
2. Check `_is_camera_completed` — if true, raise `ValidationError(...,
   reason=REASON_CAMERA_COMPLETED)`.
3. Match `detectedpart` against `parts_configured`, **scoped to the
   given camera only** (cam1 detections never match cam2-configured
   parts, and vice versa).
4. **Matched** → green path: `$inc` the part's counter, `$set`
   `last_detected`, `$push` the full event onto
   `detections.<cam>.<kit_index>.events`, `$set`
   `detections.<cam>.<kit_index>.timing.first_part_detected_time` if not
   already set. Emits `detection:green`.
5. **Unmatched** → red path: still `$push`s the audit event (`matched:
   false`), does **not** touch any counter or `last_detected`, but
   **does** still stamp `first_part_detected_time` if this is the first
   detection call for the kit (client's spec: "first part detected"
   means any detection call, matched or not — a wrong-part detection
   still means someone started working the kit). Emits `detection:red`.
   Full alert-type differentiation (Validation Error vs Wrong Part
   Error) is still deferred — this is a visual stub only.
6. All of steps 3–5 happen in **one atomic `find_one_and_update`**
   (returns the post-update doc so the new count can be read directly,
   no separate read-back call), plus one small follow-up `$set` to
   backfill the count into `last_detected` — 2 Mongo round trips total
   per detection.
7. Resolves whether a sound should play (see "Sound system" below)
   using the already-fetched post-update document — no extra query.

**Response:** `{"success": true, "matched": bool, "count": int,
"message": "Detection recorded."}` on success; `{"success": false,
"reason": <code>, "message": str}` (400/500) otherwise. Never a raw 500
traceback. See "API error contract" below for the full reason-code list.

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

`audio_url` is `null` when no sound should play for this event — the
browser does nothing if it's null, no separate enabled/disabled logic
needed client-side.

#### `POST /api/validate-kit`

**Request:** `tableid`, `camid`, `message` (must be exactly
`"validate_now"`), `image` (optional, saved to disk for audit only — see
"Reserved: validation detail" above, not yet attached to any stored
record).

**Server logic** (`detection_data.validate_kit`):

1. No live activity → `ValidationError(reason=REASON_NO_LIVE_ACTIVITY)`.
2. Camera already completed → `ValidationError(reason=REASON_CAMERA_COMPLETED)`
   (the call that takes the index from `quantity_required` to
   `quantity_required + 1` is itself a normal, ALLOWED call — it's what
   *marks* the camera done; only a call *after* that point is rejected).
3. Advances `current_kit_index_cam{N}` by 1. Stamps
   `detections.<cam>.<old_index>.timing.validated_at` AND
   `detections.<cam>.<new_index>.timing.actual_kit_start_time` — the
   **same timestamp**, in the same `update_one` call (finishing kit N
   and starting kit N+1 are the same instant by definition).
4. Checks whether this camera just became completed
   (`is_completed`), and if so, whether the **other** camera is
   *already* completed too (`activity_fully_completed`).

**Response:** `{"success": true, "new_kit_index": int, "is_completed":
bool, "activity_fully_completed": bool, "message": str}`.

**Socket.IO emits** (room `activity:<id>`):

```
"kit:advanced" → {cam_id, new_kit_index, is_completed, kit_start_time}
```

...and, **only if `activity_fully_completed` is true**, additionally:

```
"activity:completed" → {completed_at}
```

after the history-move has already happened server-side.

#### `POST /api/toggle-sound`

**Request (JSON):** `{"table_id": int, "camid": "1"|"2"|"cam1"|"cam2"}`.

**Server logic** (`detection_data.toggle_green_sound`): flips
`green_sound_enabled_cam{N}` on the table's current live activity.
Effective **immediately** for the current kit — no "wait for next kit"
delay. Writes only to `live_activity_details`; never touches
`table_configuration` (the table's saved Audio Settings default) —
confirmed requirement.

**Socket.IO emit:** `"sound:toggled" → {cam_id, green_sound_enabled}` —
broadcast to the whole room **including the tab that triggered it**, so
all viewers update from the same code path rather than an optimistic
client-side flip that could desync on a failed request.

#### `GET /api/detection-image/<table_dir>/<filename>`

Serves a saved detection frame. Path shape mirrors exactly what
`save_detection_image()` returns (e.g. `table_1/ab12cd34.jpg`) — a
two-segment route rather than a wildcard, to avoid directory-traversal
ambiguity.

## API error contract

Every `cv_ingest` endpoint returns the same shape on failure:

```json
{"success": false, "reason": "<code>", "message": "<human-readable>"}
```

| Reason code | Meaning |
|---|---|
| `no_live_activity` | The table has no `status: "live"` activity at all |
| `camera_completed` | This specific camera has already validated past `quantity_required` |
| `validation_error` | Any other bad input (missing field, bad camid, etc.) |
| `database_error` | `PyMongoError` — Mongo unreachable |

**Implementation note:** `detection_data.ValidationError` is a custom
exception carrying a `.reason` attribute, set at each raise site via
`REASON_NO_LIVE_ACTIVITY` / `REASON_CAMERA_COMPLETED` /
`REASON_VALIDATION_ERROR` constants (defined at the top of
`detection_data.py`). `routes.py` reads `exc.reason` directly —
**do not** reintroduce string-sniffing the message (e.g. `"already
completed" in str(exc)`) to guess the reason; an earlier pass in this
build did exactly that and it was fragile/wrong in one case (a
"no live activity" error was being reported as `reason:
"validation_error"` instead of its own code — reported by the client
directly from a real test run and fixed by adding the `.reason`
attribute).

## Sound system

Two independent rules, per camera:

| Color | Rule | Toggleable? |
|---|---|---|
| **Green** (matched) | Plays if `green_sound_enabled_cam{N}` (on the activity) is true | Yes — `/api/toggle-sound`, per-camera, per-activity, immediate |
| **Red** (unmatched) | Plays if `table_settings.audio_settings.camera_{N}_red.default_enabled` (the table's saved default) is true | No — always reads the snapshot directly, every time |

`detection_data.resolve_sound_for_detection(activity_doc, cam_id, matched)`
implements both rules and also checks that the relevant audio slot
actually has a file uploaded (`original_filename` present) —
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

**Known real-world gotcha (not a code bug):** on kiosk-mode Chrome, a
tab that never receives a genuine user gesture has ALL audio blocked by
browser policy — this looks like "sound isn't working" but is actually
expected browser behavior. Fixed at the browser-launch level, not in
this app's code — see `launchers/README.md`, specifically the
`--autoplay-policy=no-user-gesture-required` flag on both the Windows
`.bat` and Ubuntu `.desktop`/`.sh` kiosk launchers delivered alongside
this build.

## Monitor page — detection pop-up UI

### Full-height pop-up (confirmed requirement, iterated multiple times)

On a detection event, that camera's pop-up covers the **entire page
height on that camera's side** — the global Back button row, the shared
status/progress header, and the camera panel — not just the camera
panel box. Still strictly split left/right by camera; a cam1 event
never crosses into cam2's half, and vice versa.

**Implementation:** the two pop-up elements
(`.detection-popup[data-cam="cam1"]` / `[data-cam="cam2"]`) are **direct
children of `.monitor-page`**, siblings of `.monitor-header` and
`.monitor-cameras` — not nested inside `.camera-panel`. They're
`position: absolute` against `.app-main.app-main--full-bleed` (which is
`position: relative`, and has **zero padding** — padding lives on
`.app-main__top-row` and `.monitor-page` individually instead), with
`top: 0; bottom: 0` and a `left`/`right` split matching
`.monitor-cameras`' two-column grid.

**Lesson learned (documented for future edits to any full-page overlay
in this file):** an earlier version put padding on the positioning
parent itself and tried to cancel it with a matching negative inset on
the overlay. This broke in one real deployment where the two values
didn't line up exactly, leaving a visible gap. Fixed by moving padding
to a padded-only *child* element instead, so the positioning parent has
zero padding to fight in the first place. The same pattern is reused for
the activity-complete overlay (see below) — apply it again for any
future full-page overlay added to this file.

**Image fit:** `object-fit: cover`, not `contain` — `contain` preserves
aspect ratio and can letterbox (leave a visible gap) when the source
image's shape doesn't match the pop-up box; `cover` always fills
completely, cropping if needed.

**Colors:** the whole pop-up (not just a metadata strip) is theme-tinted
— dark green/red for the image area, brighter green/red for the
metadata strip. No `--color-success`/`--color-danger` tokens exist yet
in `variables.css` — hardcoded to match that same color family, same
known gap as the Complete Manually button elsewhere in the app.

**Metadata format:** one centered line, `Detected: <part name> | Qty:
<count> / <required>` for green (qty segment omitted for red, since
there's no required-qty to show against an unmatched part), plus a
right-aligned timestamp.

**Duration:** `green_popup_uptime_sec` / `red_popup_uptime_sec` from
`config.yaml`, exposed to JS via `data-green-popup-uptime-sec` /
`data-red-popup-uptime-sec` on `.monitor-page` — never hardcoded in JS.
Configured **separately** per color (client's explicit call).

### "Last detected" badge

Exactly one part-card carries the badge at a time, per camera — driven
by `last_detected_cam{N}` on the activity doc (server-side, for
page-load/refresh) and `clearLastDetectedBadges()` in `monitor.js`
(client-side, before tagging a new card on a live socket event).

### Sound toggle button

Sits next to "Kit #N" in each camera panel's header
(`.camera-panel__kit-index-group`). Click → `POST /api/toggle-sound` →
waits for the `sound:toggled` broadcast (including back to the same tab)
to actually flip its own icon/state, rather than an optimistic update —
keeps the server as the single source of truth.

### Per-camera "Kit timer"

Each camera panel shows a timer measuring time on its **current kit**
(`data-kit-timer`, anchored to `detections.<cam>.<current_kit>.timing
.actual_kit_start_time`), completely separate from the header's
activity-wide "Total time" (`data-activity-timer`, anchored to
`created_at`). Resets to `00:00:00` live, independently per camera,
whenever that camera's `kit:advanced` socket event arrives —
`resetKitTimer()` uses the server-provided `kit_start_time`, not client
`Date.now()`, so every viewer's timer is anchored to the same
authoritative instant.

**Hidden once that camera individually completes** (client's explicit
requirement: don't show a camera-wise kit timer once that camera's kits
are done — there's no "current kit" left for it to measure). Handled
both server-side (`hidden` attribute rendered in the template when
`cam.is_completed`) and client-side (`handleKitAdvanced`'s completed
branch sets `.hidden = true` and removes the element from the tick
registry, so it also stops being needlessly recomputed every second).

### "Total time" freeze on whole-activity completion

The header's activity-wide timer **freezes** the instant BOTH cameras
complete (client's explicit requirement), rather than continuing to
tick after the activity has effectively finished. Implementation:
`data-completed-at=""` starts empty on every server render (the monitor
route 404s before reaching this template if the activity isn't live, so
`completed_at` is guaranteed absent at render time); `freezeActivityTimer()`
writes the server's `completed_at` timestamp into that same dataset
attribute on the `"activity:completed"` socket event, and the existing
`tick()` loop in `initTimers()` picks it up on its very next tick — no
separate interval, no module-level "is this done" flag, just one shared
loop that checks the element's own state each time.

### Activity-complete overlay + auto-redirect

On `"activity:completed"` (both cameras done, activity already moved to
history server-side): `handleActivityCompleted()` shows a full-page
overlay (`position: fixed; inset: 0`, covers **both** camera halves —
unlike the detection pop-up, which is per-camera, this spans the whole
page since the *activity* as a whole is done) with a checkmark,
"Activity Completed" text, and a "Returning to Live Kitting
Activities…" subtext, then redirects to the landing page
(`data-landing-url`, built server-side via `url_for()`) after a 2.5
second delay. The redirect is necessary, not cosmetic — the activity
document this page was watching literally no longer exists in
`live_activity_details` after the move, so staying on this URL would
otherwise eventually dead-end.

### "Kits Completed" per-camera state

When one camera individually completes (before or independent of the
other camera), its Completed/Pending sections and part-cards are
entirely removed from the DOM (not just visually hidden) and replaced
with a checkmark + "Kits Completed" state
(`.camera-panel__done-state`), both server-rendered (initial page load)
and live via `handleKitAdvanced`'s completed branch (socket-driven, for
anyone already viewing the page when it happens). The top progress bar
for that camera also updates live to show the capped percentage (see
below) — this was a real gap found and fixed mid-session: the top bar
is server-rendered only by default and does **not** update on its own;
`updateTopProgressBar()` was added specifically to keep it in sync after
a live socket-driven completion.

**Progress percentage capping:** since `kit_index` can be one past
`quantity_required` once completed (e.g. index 6 with target 5), both
the server (`build_monitor_view`) and the client
(`updateTopProgressBar`) cap the displayed count/percent at the target —
`effective_index = min(kit_index, target)` — so the bar never shows
something like "6/5 · 120%".

## Socket.IO infrastructure

`app/extensions.py` holds the shared `socketio = SocketIO(...)`
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
`join_activity` Socket.IO event sent by `monitor.js` on `connect`
(fires on every reconnect too, not just the first connection — so a
transient network blip and auto-reconnect naturally re-joins the room
without any extra client-side logic). Every detection/kit-advance/
sound-toggle/completion event for that activity is emitted only to that
room — never broadcast app-wide.

**Known race (documented, not fixed):** if a detection arrives before a
browser tab's `join_activity` handshake completes (e.g. right as the
monitor page opens), that event is silently missed by that specific tab
— no error, just a missed pop-up/count update for that one tab (other
already-joined tabs are unaffected, and the underlying Mongo write still
happens regardless). Low probability in real operation; client
confirmed no queueing/buffering fix is needed for now.

## Known gaps / next-session TODO

- **Red-popup alert-type logic** is still a stub — full differentiation
  between Validation Error and Wrong Part Error (per the per-camera
  alert config already in Current Kits Configuration) is deferred.
- **No per-kit timer breakdown UI** beyond the live monitor page — the
  data (`detections.<cam>.<kit>.timing`, every individual event's own
  `created_at`) is fully captured for analytics, but there's no History
  viewer built yet to browse it.
- **"See current settings" and "History" buttons** are still unwired
  placeholders.
- **`table_settings` snapshot only partially consumed** — only
  `audio_settings` (for sound) is read anywhere right now.
  `expected_client_ips` and `push_notifications` are captured at
  creation time but not yet used by any code path.
- **`detections.<cam>.<kit>.validation` is reserved but unpopulated** —
  `/api/validate-kit` accepts an image but currently discards it after
  saving to disk; a future build should write validation detail here.
- **Audio playback not verified with real MP3 files in a real
  (non-headless) browser** — testing this build used placeholder
  non-decodable audio bytes and a headless browser; URL resolution and
  toggle logic are fully verified, actual audible output is not.
- Camera-check images are still fixed static placeholders.
- No rate-limiting on the ingest endpoints.
- No authentication/authorization layer anywhere in the app.
