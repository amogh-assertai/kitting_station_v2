# TSD — Live Kitting Activities

Technical spec for the Live Kitting Activities blueprint and the
`cv_ingest` blueprint that feeds it live detection data. For functional
behavior, see `FRD_LIVE_KITTING_ACTIVITIES.md`.

**Status: fully built and live-tested.** Part counts, the completed/
pending split, per-camera sound, kit-level timing, camera/activity
completion, cross-client real-time sync, and (as of this session) the
full red-screen / error-lock feature — Wrong Part Error and Validation
Error alert types, per-kit-per-camera master switches, neglected-part
handling, operator resolution (System Error/Process Error + comment),
and persistent camera-lock state — are all driven by real events posted
from the local DeepStream application. This is not a stub.

## File map

```
app/blueprints/live_kitting_activities/
├── __init__.py
├── routes.py                    # landing, create flow, monitor page, complete-manually
└── activities_data.py           # MongoDB data access + validation; monitor view shaping

app/blueprints/cv_ingest/         # detection ingest blueprint, no url_prefix (routes are /api/...)
├── __init__.py
├── routes.py                    # /api/detection-update, /api/validate-kit, /api/resolve-error,
│                                 # /api/toggle-sound, /api/detection-image/<dir>/<file>,
│                                 # Socket.IO room join
└── detection_data.py            # validation, image save, count/sound/timing resolution,
                                  # camera lock state, wrong_part/validation_error alert logic,
                                  # error resolution, Mongo writes

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

  # --- Copied at creation, added this session for the red-screen /
  # error-lock feature (previously NOT copied - see "Schema history"
  # below) ---
  "neglect_parts": [{"part_name": str, "camera": "cam1"|"cam2"}, ...],
  "camerawise_alert_config": [
      {"camera": "cam1", "alert_validation_error": bool, "alert_wrong_part_error": bool},
      {"camera": "cam2", "alert_validation_error": bool, "alert_wrong_part_error": bool},
  ],
  # Same one-time-snapshot rule as parts_configured/table_settings -
  # editing a kit's neglect list or alert config in Current Kits
  # Configuration after an activity has started does NOT retroactively
  # change that activity's already-running snapshot.

  "camera_images": {"cam1": str, "cam2": str},

  "current_kit_index_cam1": int,      # 1-based. Advances independently per
  "current_kit_index_cam2": int,      # camera via /api/validate-kit. Can go
                                       # ONE past quantity_required - that's
                                       # the "this camera is done" sentinel
                                       # (see "Completion semantics" below).

  "status": "live" | "completed" | "completed-manually",
  "created_at": iso str,
  "updated_at": iso str,

  # --- Camera lock state (NEW this session) ---
  "camera_state_cam1": "open" | "locked",
  "camera_state_cam2": "open" | "locked",
  # "locked" while a red-screen (either alert type) is showing and
  # unresolved on that camera; "open" otherwise. Distinct from - and
  # independent of - _is_camera_completed()'s "all kits done" state,
  # which is permanent and has nothing to do with this per-kit lock.

  "current_kit_errors_cam1": {...} | None,
  "current_kit_errors_cam2": {...} | None,
  # The ACTIVE, unresolved error on that camera, or None if open.
  # Exists purely for PERSISTENCE - a viewer opening (or refreshing) the
  # monitor page WHILE a red-screen is already active on some other
  # client renders the same locked state immediately, sourced from this
  # field, rather than only ever learning about it via a socket event
  # that a fresh page load would have missed entirely. Shape:
  #   {
  #     "error_type": "validation_error" | "wrong_part",
  #     "kit_index": int,
  #     "issues": [{"part_name": str, "issue": "missing"|"undercount"|"overcount"|"unrecognized",
  #                 "required": int|None, "found": int|None}],
  #     "image_path": str | None,
  #     "detected_at": iso str,
  #     "wrong_part_detected_at": iso str,   # wrong_part only - links this
  #                                            # active error back to its own
  #                                            # entry in wrong_part_cards
  #                                            # (see below) so resolve_error()
  #                                            # can attach the operator's
  #                                            # resolution to the SAME card
  #   }
  # Set to None and camera_state flips back to "open" the moment
  # /api/resolve-error succeeds.

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
  # at playback time, every time, never toggleable per-activity. This is
  # unchanged by the red-screen feature - the red-screen's LOOPING
  # playback (vs. the brief pop-up's one-shot) is a client-side
  # difference only (see "Sound system," below), not a new server field.

  # --- Fast-path read fields (never derived by scanning detections) ---
  "part_counts_cam1": { "<kit_index>": { "<part_name>": <int count> } },
  "part_counts_cam2": { "<kit_index>": { "<part_name>": <int count> } },
  # What the monitor page/socket handlers actually read on every render.
  # Updated via $inc, one integer, one write. kit_index keys are cast to
  # str() on write/read (Mongo object keys are always strings on disk).
  # NEW this session: a NEGLECTED part now also increments here, using
  # the exact same structure a real configured part uses (client:
  # "count increments like a normal part") - this is what makes the
  # neglected-card's grouping-by-name + running count come for free out
  # of activities_data.build_monitor_view, no separate counter needed.

  "last_detected_cam1": {"part_name": str, "count": int, "detected_at": iso str} | None,
  "last_detected_cam2": {...} | None,
  # Drives the "Last detected" badge on a completed part-card. Updated
  # via $set on every MATCHED-OR-NEGLECTED detection (widened this
  # session to include neglected, since a neglected detection now plays
  # the green path too) - a genuine wrong_part detection never touches
  # this, so the badge always reflects the most recent SUCCESSFUL (or
  # neglected) detection, not the most recent detection of any kind.

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
                      "matched": bool,                 # true = green path (matched OR neglected), false = red path
                      "outcome": "matched" | "neglected" | "wrong_part",  # NEW this session -
                                                        # explicit, self-describing tag on every
                                                        # audit-log event (client: "wrong_part or
                                                        # neglected part info should be inside the
                                                        # code somewhere clearly") - do not re-derive
                                                        # this from parts_configured/neglect_parts at
                                                        # read time, since those snapshots could in
                                                        # principle be edited by a future build; this
                                                        # field is the permanent record of what was
                                                        # true AT DETECTION TIME.
                      "created_at": iso str,
                  },
                  ...
              ],
              "wrong_part_cards": [           # NEW this session - see below
                  {
                      "part_name": str,
                      "detected_at": iso str,
                      "image_path": str | None,
                      "resolution": {"chosen_option": "system_error"|"process_error",
                                      "comment": str|None, "resolved_at": iso str} | None,
                  },
                  ...
              ],
              "errors": [                     # NEW this session - see below
                  {
                      "error_type": "validation_error" | "wrong_part",
                      "kit_index": int,
                      "issues": [...],         # same shape as current_kit_errors_cam{N}.issues
                      "image_path": str | None,
                      "detected_at": iso str,
                      "resolution": {"chosen_option": str, "comment": str|None, "resolved_at": iso str},
                  },
                  ...
              ],
          }
      },
      "cam2": { ... }
  }
}
```

### `wrong_part_cards` vs `errors` - two different arrays, two different jobs

Added this session, both nested under the same `detections.<cam>.<kit_index>`
base path (per the existing "everything about this kit is a sibling key
here" convention - see "Schema history," below):

- **`wrong_part_cards`** - one entry per wrong-part **occurrence**,
  INDIVIDUAL, never grouped or counted (client: "every wrong_part gets
  its own separate card since its option and comment can vary depending
  on what operator choose"). This is what `activities_data
  ._wrong_part_cards_for_camera()` reads to render the Completed
  section's red "Wrong-part" cards. `resolution` starts `None` and is
  filled in by `resolve_error()` **only** for the specific occurrence
  that actually triggered the red-screen being resolved (matched via
  `wrong_part_detected_at`, see below) - if the camera's
  `alert_wrong_part_error` switch was off, a card still gets created
  here (client: "still logged in backend"), but `resolution` simply
  stays `None` forever, since no red-screen ever blocked it.

- **`errors`** - one entry per red-screen that was actually **raised and
  resolved** (i.e. only entries where the master switch was ON). Both
  alert types write here on resolve, but only wrong_part ALSO writes to
  `wrong_part_cards` - validation_error has no "card" concept, its
  issues only ever live in `current_kit_errors_cam{N}` (transient) and
  here (permanent). This is the array a future History viewer should
  read to answer "what alerts happened on this kit and how were they
  resolved."

### Linking an active error back to its card - `wrong_part_detected_at`

`current_kit_errors_cam{N}` and the specific `wrong_part_cards` entry it
corresponds to are two separate documents (one transient/single, one
inside a growing array) that need to stay linked so `resolve_error()`
knows which card to badge. Linked by **timestamp match**
(`wrong_part_detected_at` on the active error === `detected_at` on the
card), since both are stamped with the exact same `_now_iso()` call at
detection time and a kit realistically never has two wrong-part
detections at the identical microsecond. `resolve_error()` uses
MongoDB's `array_filters` (`update_one(..., array_filters=[{"card
.detected_at": ...}])`) to update that one array element in place -
**mongomock does not implement `array_filters`** (confirmed gap in this
project's test tooling, not a MongoDB limitation - standard, supported
since MongoDB 3.6), so this specific write path could not be verified
with the project's usual mongomock test suite and should be checked
against a real MongoDB instance if this area is touched again.

### Schema history — read this before touching `detections`

This shape went through three real revisions in this build, all driven by
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
3. **Red-screen / error-lock feature added two more sibling keys**
   (this session): `wrong_part_cards` and `errors`, both under the same
   `detections.<cam>.<kit_index>` base path as `timing`/`validation`/
   `events`. Same rule as revision 2 — this is a new *kind* of per-kit
   data, so it becomes a new sibling key, not a new top-level tree.
   `neglect_parts` and `camerawise_alert_config` were also added as new
   **top-level** activity-doc fields (not per-kit — they're copied once
   at creation and apply to the whole activity, same tier as
   `parts_configured`).

If you're about to add a new kind of per-kit data (anything else that
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

**Checked BEFORE the lock check below** in both `record_detection` and
`validate_kit` — a permanently-completed camera takes priority over a
"currently locked" state, since a camera that finished all its kits
should never re-enter a lock cycle.

## Camera lock state and alert logic (NEW this session)

`_is_camera_locked(activity_doc, cam_id)` in `cv_ingest/detection_data.py`
is the single source of truth for whether a camera currently has an
unresolved red-screen:

```python
def _is_camera_locked(activity_doc, cam_id):
    return activity_doc.get(_camera_state_field(cam_id), CAMERA_STATE_OPEN) == CAMERA_STATE_LOCKED
```

Checked in both `record_detection` and `validate_kit`, **after** the
completion check (see above). While locked, further calls for that
specific camera are rejected with `reason="camera_locked"` (a new,
distinct reason code from `camera_completed` — see "API error contract"
below) — **not written to Mongo at all**, only logged server-side
(`current_app.logger.info(...)` in `cv_ingest/routes.py`), since a
DeepStream client that keeps sending while locked has no audit value
beyond "yes, it kept sending" (client: "camera stays locked... ignored/
logged, no new red-screen").

### Master switches — `camerawise_alert_config`

Both alert types are gated by a **per-kit, per-camera master switch**,
read via `_camera_alert_switches(activity_doc, cam_id)`:

```python
def _camera_alert_switches(activity_doc, cam_id):
    for entry in activity_doc.get("camerawise_alert_config", []):
        if entry.get("camera") == cam_id:
            return {
                "alert_validation_error": bool(entry.get("alert_validation_error", True)),
                "alert_wrong_part_error": bool(entry.get("alert_wrong_part_error", True)),
            }
    return {"alert_validation_error": True, "alert_wrong_part_error": True}
```

**Client's explicit confirmation on what "master switch" means:** if
off, the underlying issue is still detected/computed (and, for
wrong_part, still logged to the normal audit trail and given its own
`wrong_part_cards` entry) but does **NOT** raise a red-screen or lock
the camera. If on, it does both. This is checked independently of, and
in addition to, each part's own `alert_missing`/`alert_undercount`/
`alert_overcount` flags (unchanged fields on `parts_configured`) — the
master switch decides *whether to raise at all*; the per-part flags
decide *which specific issues qualify* once raising is permitted.

### Wrong Part Error — checked in `record_detection`

A detected part that doesn't match any configured part for that camera
is a **wrong_part candidate** — UNLESS it's also present in the
activity's `neglect_parts` list for that camera, in which case it's
**neglected**, not wrong_part (see "Detection outcomes" in the FRD, and
below). Neglect-list membership is checked via
`_neglected_part_names(activity_doc, cam_id)`, camera-scoped (a part
neglected on cam1 does not suppress wrong_part on cam2 for the same part
name).

If it's a genuine wrong_part candidate:
1. A `wrong_part_cards` entry is **always** created (client: "still
   logged in backend"), `resolution: None`.
2. If `alert_wrong_part_error` is on for this camera → the camera locks,
   `current_kit_errors_cam{N}` is set, and `error:red` is emitted
   (blocking).
3. If the switch is off → nothing else happens; the same brief,
   non-blocking `detection:red` pop-up plays as before this session.

### Neglected parts — now treated as a green-path outcome

**Client's explicit reversal** of the original design (where a
neglected part was invisible — never counted, never shown, never
sounded): a neglected part now:
- Increments `part_counts_<cam>.<kit_index>.<part_name>` via the exact
  same `$inc` a real matched part uses (client: "count increments like
  a normal part") — this is what makes the neglected-card's grouping +
  running count come for free out of `build_monitor_view`, no separate
  counter structure.
- Plays the **green** pop-up and sound, not red — implemented as a
  `plays_as_green` flag passed to `resolve_sound_for_detection()`,
  distinct from the `matched` field in the returned payload (which
  still correctly reflects `parts_configured` membership, used
  elsewhere e.g. `quantity_required`).
- Always reports `quantity_required` as `0` in the response and on the
  card (client: "2 detected, then it shows 2/0") — trivially always
  "completed," never appears in Pending.
- Is tagged `"outcome": "neglected"` on its audit-log event (see schema,
  above).

### Validation Error — checked in `validate_kit`, before advancing

`_find_validation_issues(activity_doc, cam_id, kit_index)` checks every
part configured on that camera against its detected count for the
**current** kit index, using each part's own alert flags:

```python
if part.get("alert_missing") and found == 0:
    issue = "missing"
elif part.get("alert_undercount") and 0 < found < required:
    issue = "undercount"
elif part.get("alert_overcount") and found > required:
    issue = "overcount"
```

This computation happens **regardless of the master switch** (client:
"we dont raise alert but still logged in backend") — the switch is only
consulted afterward, to decide whether to actually raise. **All
qualifying issues across every part on that camera are collected into
ONE list** (client: "one validation error, can have multiple parts
issue, but combined its one validation error" — never split into
several separate red-screens for one validate call).

If the switch is on and `issues` is non-empty: `validate_kit` does
**NOT** advance the kit index. It locks the camera, sets
`current_kit_errors_cam{N}` to the combined error object, and returns
`validation_error=True` so `routes.py` emits a blocking `error:red`
instead of the normal `kit:advanced`. The kit only actually advances
once the operator resolves via `/api/resolve-error`.

If the switch is off, or no issues were found: `validate_kit` proceeds
exactly as before this session — unconditional advance.

### Resolving a red-screen — `resolve_error()`

The **only** way a locked camera becomes open again. Takes
`chosen_option` (`"system_error"` or `"process_error"`, validated
against `ALLOWED_CHOSEN_OPTIONS`) and an optional free-text `comment`.

Behavior differs by `error_type` — this is the one place in the whole
feature where the two alert types genuinely diverge in what resolving
*does*, not just what triggered it:

| | Kit index | Card written | Permanent record |
|---|---|---|---|
| **`wrong_part`** | **Unchanged** — camera just unlocks; the detection system must send its own separate `validate_now` afterward | Yes — the SAME `wrong_part_cards` entry gets `resolution` filled in via `array_filters` (see "Linking an active error back to its card," above) | Appended to `detections.<cam>.<kit_index>.errors` |
| **`validation_error`** | **Advances** — identical timing-stamp logic to a normal `validate_kit` advance (`timing.validated_at` on the old index, `timing.actual_kit_start_time` on the new one), in the SAME `update_one` call as the resolve | No card exists for this type — issues only ever lived in `current_kit_errors_cam{N}` | Appended to `detections.<cam>.<old_kit_index>.errors` |

In **both** cases: `camera_state_cam{N}` → `"open"`,
`current_kit_errors_cam{N}` → `None`, and the resolved error (original
issues + a new `resolution: {chosen_option, comment, resolved_at}` key)
is permanently appended to `detections.<cam>.<kit_index>.errors` (client:
"every wrong_part error... gets its own permanent entry under that kit,
same as validation_error" — even though only validation_error also
advances).

Returns `resolution_code` (`"S"` for `system_error`, `"P"` for
`process_error`) so `routes.py`'s `error:resolved` broadcast can tell
every viewer which badge to render — see "Socket.IO events," below.

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
| `/api/validate-kit` | POST (multipart) | `validate_now` signal — advances one camera's kit index, or raises a Validation Error red-screen instead (NEW this session) |
| `/api/resolve-error` | POST (JSON) | **NEW this session.** Operator submits `system_error`/`process_error` (+ optional comment) to resolve the active red-screen on one camera — the only way a locked camera reopens |
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
3. Check `_is_camera_locked` (NEW this session) — if true, raise
   `ValidationError(..., reason=REASON_CAMERA_LOCKED)`, not written to
   Mongo, server-log only.
4. Match `detectedpart` against `parts_configured`, **scoped to the
   given camera only** (cam1 detections never match cam2-configured
   parts, and vice versa).
5. **Matched** → green path: `$inc` the part's counter, `$set`
   `last_detected`, `$push` the full event onto
   `detections.<cam>.<kit_index>.events`, `$set`
   `detections.<cam>.<kit_index>.timing.first_part_detected_time` if not
   already set. Emits `detection:green`.
6. **Neglected** (NEW this session) → ALSO green path, same as matched
   in every respect above (counter, `last_detected`, event push,
   `detection:green` emit) — see "Neglected parts," above, for why.
   `quantity_required` reported as `0`.
7. **Wrong part candidate** (unmatched AND not neglected) → red path:
   still `$push`es the audit event (`matched: false`, `outcome:
   "wrong_part"`), does **not** touch any counter or `last_detected`,
   but **does** still stamp `first_part_detected_time` if this is the
   first detection call for the kit (client's spec: "first part
   detected" means any detection call, matched or not). ALSO pushes a
   `wrong_part_cards` entry (NEW this session, always, regardless of
   the master switch). If `alert_wrong_part_error` is on for this
   camera → locks the camera, sets `current_kit_errors_cam{N}`, emits
   blocking `error:red` INSTEAD of `detection:red`. If off → emits the
   old non-blocking `detection:red`, same as before this session.
8. All of steps 4–7 happen in **one atomic `find_one_and_update`**
   (returns the post-update doc so the new count can be read directly,
   no separate read-back call), plus one small follow-up `$set` to
   backfill the count into `last_detected` — 2 Mongo round trips total
   per detection.
9. Resolves whether a sound should play (see "Sound system" below)
   using the already-fetched post-update document — no extra query.

**Response:** `{"success": true, "matched": bool, "count": int,
"message": "Detection recorded."}` on success; `{"success": false,
"reason": <code>, "message": str}` (400/500) otherwise. Never a raw 500
traceback. See "API error contract" below for the full reason-code list.

**Socket.IO emit** (room `activity:<id>`):

```
"detection:green" → {
  cam_id, part_name, count, quantity_required, kit_index,
  image_url, detected_at, popup_uptime_sec, audio_url,
  neglected: bool          # NEW this session - True when this
                            # detection is a neglected-list match, not
                            # a real configured part. monitor.js uses
                            # this to decide whether to build a NEW
                            # card live (a neglected part has no
                            # Pending-section placeholder to find and
                            # flip, unlike a real configured part).
}
"detection:red" → {
  cam_id, detected_part, kit_index,
  image_url, detected_at, popup_uptime_sec, audio_url
}
# Non-blocking, brief - fires ONLY for a genuine wrong_part occurrence
# where alert_wrong_part_error is OFF for this camera/kit. A neglected
# detection NEVER reaches this event anymore (moved to detection:green
# this session).

"error:red" → {          # NEW this session - BLOCKING, no auto-hide
  cam_id,
  error: {error_type, kit_index, issues, image_path, detected_at, ...},
  image_url, audio_url
}
# Fires from EITHER record_detection (wrong_part, switch on) or
# validate_kit (validation_error, switch on + issues found). Stays on
# screen until /api/resolve-error succeeds. Red audio LOOPS for this
# event, unlike detection:red's one-shot playback.
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
3. Camera currently locked (NEW this session) →
   `ValidationError(reason=REASON_CAMERA_LOCKED)`.
4. **Validation Error check (NEW this session), BEFORE any advance** —
   see "Validation Error — checked in `validate_kit`," above. If the
   camera's `alert_validation_error` switch is on and issues were
   found: locks the camera, sets `current_kit_errors_cam{N}`, returns
   `validation_error=True` with the combined issue list — **does not
   advance**. Skip to step 6 below in this case.
5. Advances `current_kit_index_cam{N}` by 1. Stamps
   `detections.<cam>.<old_index>.timing.validated_at` AND
   `detections.<cam>.<new_index>.timing.actual_kit_start_time` — the
   **same timestamp**, in the same `update_one` call (finishing kit N
   and starting kit N+1 are the same instant by definition).
6. Checks whether this camera just became completed
   (`is_completed`), and if so, whether the **other** camera is
   *already* completed too (`activity_fully_completed`). Not reached if
   step 4 raised a Validation Error this call.

**Response:** `{"success": true, "validation_error": bool, "new_kit_index":
int, "is_completed": bool, "activity_fully_completed": bool, "message":
str}`. `validation_error` is `True` when this call raised a red-screen
instead of advancing — `new_kit_index` in that case equals the
**unchanged** index (nothing moved).

**Socket.IO emits** (room `activity:<id>`):

```
"kit:advanced" → {cam_id, new_kit_index, is_completed, kit_start_time}
```

...only when `validation_error` is `False`. When `validation_error` is
`True`, `error:red` is emitted instead (same event shape as the
wrong_part case — see above), with the audio URL resolved separately
(a fresh `_activities_collection().find_one()` by `_id`, since
`validate_kit`'s own return only carries the activity id as a string,
not the full document `resolve_sound_for_detection` needs).

...and, **only if `activity_fully_completed` is true** (only reachable
via the normal-advance path, step 5–6 above), additionally:

```
"activity:completed" → {completed_at}
```

after the history-move has already happened server-side.

#### `POST /api/resolve-error` (NEW this session)

**Request (JSON):** `{"table_id": int, "camid": "1"|"2"|"cam1"|"cam2",
"chosen_option": "system_error"|"process_error", "comment": str|None}`.

**Server logic** (`detection_data.resolve_error`) — see "Resolving a
red-screen," above, for the full behavior split between the two alert
types. Summary:
1. No live activity → `REASON_NO_LIVE_ACTIVITY`.
2. `chosen_option` not one of the two allowed values → plain
   `ValidationError` (default reason — an operator-input problem, not a
   camera-state problem, so it doesn't need its own reason code).
3. No active error on this camera (`current_kit_errors_cam{N}` already
   `None`) → plain `ValidationError` — nothing to resolve.
4. Unlocks the camera, appends the resolved error to
   `detections.<cam>.<kit_index>.errors`. For `wrong_part`, ALSO writes
   the resolution onto the matching `wrong_part_cards` entry via
   `array_filters`. For `validation_error`, ALSO advances the kit index
   with the same timing-stamp logic `validate_kit` itself uses.

**Response:** `{"success": true, "new_kit_index": int, "message": str}`.

**Socket.IO emit** (room `activity:<id>`, including back to the
resolving tab — same "server is the single source of truth" convention
already used by `sound:toggled`):

```
"error:resolved" → {
  cam_id, error_type, new_kit_index, is_completed, kit_start_time,
  resolution_code: "S" | "P"
}
```

`monitor.js`'s `handleErrorResolved` branches on `error_type`:
`validation_error` reuses the exact same UI path `kit:advanced` would
trigger (Completed/Pending reset, Kit timer reset, "Kit #N" update, top
progress bar update) by calling `handleKitAdvanced()` directly, so the
two code paths can never drift apart; `wrong_part` just reveals the
panel body again and appends the `resolution_code` badge to the card
`error:red` created when the red-screen first appeared.

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
| `camera_locked` | **NEW this session.** This camera currently has an unresolved red-screen — distinct from `camera_completed`: "waiting on the operator" vs. "permanently done with the whole activity." Rejections for this reason are never written to Mongo, only server-logged. |
| `validation_error` | Any other bad input (missing field, bad camid, etc.) |
| `database_error` | `PyMongoError` — Mongo unreachable |

**Naming note:** `validation_error` here is the generic "bad input"
reason code (unchanged, pre-existing) and is unrelated to the new
**Validation Error** *alert type* (missing/undercount/overcount) added
this session, despite the name collision — the alert type has its own
`error_type: "validation_error"` field inside the `error:red`/
`error:resolved` socket payloads, a different namespace entirely from
this reason-code table.

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
| **Green** (matched, or neglected — see below) | Plays if `green_sound_enabled_cam{N}` (on the activity) is true | Yes — `/api/toggle-sound`, per-camera, per-activity, immediate |
| **Red** (unmatched, non-blocking or blocking) | Plays if `table_settings.audio_settings.camera_{N}_red.default_enabled` (the table's saved default) is true | No — always reads the snapshot directly, every time |

**Neglected parts play GREEN, not red** (client's explicit reversal
this session) — implemented via a `plays_as_green` flag passed to
`resolve_sound_for_detection(activity_doc, cam_id, plays_as_green)`,
computed as `matched or is_neglected` in `record_detection`, kept
separate from the `matched` field in the function's returned payload
(which still means exactly "found in `parts_configured`," used
elsewhere for `quantity_required`).

`detection_data.resolve_sound_for_detection(activity_doc, cam_id, matched)`
implements both rules and also checks that the relevant audio slot
actually has a file uploaded (`original_filename` present) —
`default_enabled: true` with no file ever uploaded still resolves to no
sound, since there's nothing to serve.

The actual audio file is served by **reusing the existing route**
`configuration.table_settings_audio_file` (no new file-serving code in
`cv_ingest`) — `cv_ingest/routes.py`'s `_audio_url_for()` builds the URL
via `url_for()`.

**Browser playback** (`monitor.js`):
- `playDetectionSound(audioUrl)` — the ORIGINAL one-shot player, used
  for `detection:green` and non-blocking `detection:red`. Constructs a
  fresh `Audio(url)` per call (so two rapid detections don't cut each
  other off) and calls `.play()`, catching and logging (not throwing
  on) autoplay-block rejections — a blocked sound must never break the
  rest of the monitor page's live updates.
- `playErrorAudioLoop(camId, audioUrl)` — **NEW this session**, used
  exclusively for the blocking red-screen (`error:red`). Sets
  `audio.loop = true` and tracks the playing `Audio` element per camera
  in `_errorAudioRegistry` (a `Map`), so `stopErrorAudio(camId)` (called
  on `error:resolved`, and defensively before starting any new loop) can
  stop and reset exactly that element — a fresh `Audio()` per replay
  would leak/overlap, unlike the brief pop-up's one-shot sound which
  never needs to be stopped early.

**Known real-world gotcha (not a code bug):** on kiosk-mode Chrome, a
tab that never receives a genuine user gesture has ALL audio blocked by
browser policy — this looks like "sound isn't working" but is actually
expected browser behavior. Fixed at the browser-launch level, not in
this app's code — see `launchers/README.md`, specifically the
`--autoplay-policy=no-user-gesture-required` flag on both the Windows
`.bat` and Ubuntu `.desktop`/`.sh` kiosk launchers delivered alongside
this build.

**Debugging note from this session:** a reported "red-screen audio
silent" issue traced, on investigation, to a **stale audio-file
snapshot on an old activity** (the activity's `table_settings` snapshot
had been captured before the client re-uploaded a working MP3) — not a
code defect. Creating a fresh activity after re-uploading the audio
file resolved it immediately. If this is reported again, check the
specific activity's own `table_settings.audio_settings` snapshot before
assuming a code regression — the snapshot-at-creation design (see
above) means an old activity will never pick up a newer file.

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
Configured **separately** per color (client's explicit call). **Does
NOT apply to the blocking red-screen variant** (see below) — that one
has no auto-hide timer by design.

### The blocking red-screen variant (NEW this session)

Reuses the exact same `.detection-popup` element/positioning as the
brief pop-up above (client's original framing: the red-screen should
look like the pop-up, just extended) — a `.detection-popup--blocking`
modifier class is added by `showErrorScreen()` in `monitor.js`, never by
the plain `showPopup()` used for green/brief-red.

**Extra markup, present in both fixed popup elements from page load,
but hidden by default:** an issues list (`[data-error-issues]`), two
buttons (`[data-error-option="system_error"]` /
`[data-error-option="process_error"]`), a comment `<textarea>`
(`[data-error-comment]`), and a Submit button
(`[data-error-submit]`, disabled until an option is picked).

**Bug found and fixed this session:** these four elements initially had
no `display: none` default — they rendered on EVERY popup, including
green, because a **duplicate, unqualified CSS rule** further down the
same file (`display: flex` with no `--blocking` qualifier) won the
cascade at equal specificity by source order. Fixed by declaring
`display: none` as each element's OWN base rule (not a separate
hide-by-default block elsewhere in the file) and adding a
`.detection-popup--blocking` override per element. **Lesson for any
future addition to this popup's shared markup:** a new element meant
for only ONE popup variant needs its own `display: none` default
declared inline at its own rule, not in a separate rule the cascade
could reorder around.

**Defensive cleanup:** `showPopup()` (the plain green/brief-red path)
strips `detection-popup--blocking` before showing, in case of an
event-ordering race that could otherwise leave a stale blocking-state
class on the shared element from a prior red-screen.

**Audio:** loops for the duration (see "Sound system," above) — the one
real behavioral difference in playback logic between this variant and
the brief pop-up.

**Locking indicator:** `[data-camera-locked]` attribute on the
`.camera-panel` itself draws a thin red outline around the whole panel
— a visual cue distinguishing "locked, waiting on operator" at a glance
even in the instant before the pop-up itself finishes rendering.

### Neglected / Wrong-part cards in the Completed section (NEW this session)

Both card types are wrapped in a `.part-card-wrapper` (`position:
relative`), which every existing Completed/Pending card is also now
wrapped in — the grid (`display: grid` on `.camera-panel__cards`) lays
out wrappers as its direct children instead of bare `.part-card`
elements, so an existing card with nothing extra to show renders
pixel-identical to before this session.

**`card_type` field** (`"normal"` | `"neglected"` | `"wrong_part"`) is
computed server-side in `activities_data.build_monitor_view` and
rendered as a `data-card-type` attribute + a distinct CSS class
(`part-card--neglected` / `part-card--wrong_part`, red-tinted, vs. the
existing green `part-card--completed`).

**Grouped vs. individual** (client's explicit distinction — see FRD):
- `_neglected_cards_for_camera()` groups by `part_name`, reading the
  SAME `part_counts_<cam>.<kit_index>.<part_name>` structure a real
  part uses — one card, count keeps incrementing.
- `_wrong_part_cards_for_camera()` reads the NEW `wrong_part_cards`
  array directly (see schema, above) — one card per array entry, never
  merged, since each has its own independent `resolution`.

**Live (socket-driven) card creation** — the harder half of this
feature, client-side: unlike a real configured part, neither a
neglected part nor a wrong-part occurrence has a pre-existing DOM node
for `findPartCard()` to find and update on the FIRST occurrence in a
kit. `monitor.js` handles this with dedicated builder functions:
- `createNeglectedCard(panel, payload)` — called from
  `handleGreenDetection()` when `payload.neglected` is true and no
  existing card matches (a SECOND detection of the same neglected part
  correctly falls through to the normal "found existing card" branch
  instead, achieving the grouping behavior live, not just on refresh).
- `createWrongPartCard(panel, {partName, resolutionCode})` — called
  from BOTH `handleRedDetection()` (non-blocking, switch off) and
  `handleErrorRed()` (blocking, switch on) — always creates a NEW card,
  never looks for an existing one, matching the individual/never-grouped
  rule.

**S/P resolution badge — positioning (iterated once this session):**
first shipped as a flex-row sibling beside the card (inside
`.part-card-wrapper`, `display: flex`); client feedback moved it to
**hang off the card's own top-right corner** instead. Current
implementation: `.part-card-wrapper` is `position: relative`, the badge
itself is `position: absolute; top: -0.4rem; right: -0.4rem`, a small
negative offset so it visually overlaps the corner rather than sitting
flush inside or fully outside it. `appendResolutionBadge(wrapper, code)`
in `monitor.js` attaches it; `resolve_error()`'s `resolution_code`
return value (`"S"`/`"P"`) is what the socket payload carries to every
viewer — see "Socket.IO events," above.

**Card cleanup on kit advance — bug found and fixed this session:**
`handleKitAdvanced()`'s reset loop originally ran
`querySelectorAll('.part-card')` unqualified, which caught neglected/
wrong_part cards too and incorrectly recycled them into the Pending
section with a bogus `Qty: 0 / <required>` (client report: "these red
cards after validation coming to pending section... and going off once
i refresh page" — the refresh "fix" was really just a fresh, CORRECT
server render papering over the live-side bug). Fixed by explicitly
`.remove()`-ing every `.part-card--neglected`/`.part-card--wrong_part`
card (and its wrapper) on kit advance instead of resetting it, and
excluding those classes from the normal-part reset loop via `:not()`
selectors. **Lesson for any future card type added to this same grid:**
`handleKitAdvanced()`'s reset loop assumes every `.part-card` it touches
is a real configured part with a `quantity_required` to reset to — a
new card type needs an explicit exclusion here, the same as this fix,
or it will silently misbehave on the next kit advance.

### "Last detected" badge

Exactly one part-card carries the badge at a time, per camera — driven
by `last_detected_cam{N}` on the activity doc (server-side, for
page-load/refresh) and `clearLastDetectedBadges()` in `monitor.js`
(client-side, before tagging a new card on a live socket event). Now
also set for a **neglected** detection (see "Sound system," above, for
the corresponding `last_detected` widening) — a genuine wrong_part
detection still never touches this field.

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

- **`array_filters` (used by `resolve_error()` to badge the correct
  `wrong_part_cards` entry) is untestable with this project's mongomock
  suite** — mongomock does not implement it (confirmed this session,
  not a MongoDB limitation). Logic was reviewed manually and the query
  shape validated as well-formed, but this specific write path has not
  been exercised against a real MongoDB instance. Verify here first if
  a reported bug involves the S/P badge not appearing on the right
  card.
- **No per-kit timer breakdown UI** beyond the live monitor page — the
  data (`detections.<cam>.<kit>.timing`, every individual event's own
  `created_at`, and now every alert raised + how it was resolved) is
  fully captured for analytics, but there's no History viewer built yet
  to browse it.
- **"See current settings" and "History" buttons** are still unwired
  placeholders.
- **`table_settings` snapshot only partially consumed** — only
  `audio_settings` (for sound) is read anywhere right now.
  `expected_client_ips` and `push_notifications` are captured at
  creation time but not yet used by any code path.
- **`detections.<cam>.<kit>.validation` is reserved but unpopulated** —
  `/api/validate-kit` accepts an image but currently discards it after
  saving to disk; a future build should write validation detail here.
  (Not to be confused with the new `validation_error` *alert type* or
  the `errors` array — this reserved key is still specifically about
  storing what the kit looked like/whether it passed at validation
  time, a separate concern.)
- **Audio playback not verified with real MP3 files in a real
  (non-headless) browser** by this project's own automated testing —
  testing used placeholder non-decodable audio bytes and a headless
  browser; URL resolution and toggle/loop logic are fully verified,
  actual audible output was confirmed manually by the client during
  this session (see "Sound system" debugging note, above) but not by
  an automated test.
- Camera-check images are still fixed static placeholders.
- No rate-limiting on the ingest endpoints.
- No authentication/authorization layer anywhere in the app.
- **No real-MongoDB integration test exists in this project at all** —
  every automated test in this build (including this session's 76
  assertions across two suites) runs against mongomock. This has been
  sufficient so far but `array_filters` (above) is the first concrete
  case where that choice left a real gap; worth considering a
  real-MongoDB (or `mongomock`-alternative) test tier if more
  MongoDB-version-specific features get used going forward.
