"""
CV Ingest - MongoDB data access + validation for the DeepStream detection
pipeline.

REVISED SCHEMA (per client decision): no separate detection_events
collection. Everything lives on the live_activity_details document
itself, so a single find_one({"_id": activity_id}) returns the full
picture for both cameras and every kit iteration - no join, no second
collection to keep in sync.

Fields added to live_activity_details (all kept in step by every write
in this module):

  "current_kit_index_cam1": int          # already existed
  "current_kit_index_cam2": int          # already existed

  "part_counts_cam1": {                  # FAST PATH - what the monitor
      "<kit_index>": {                   # page / socket handlers read
          "<part_name>": <int count>     # on every request. Updated via
      }                                  # $inc, one integer, one write -
  },                                      # never derived by scanning an
  "part_counts_cam2": { ... },            # array or a second collection.

  "last_detected_cam1": {                # FAST PATH for the "Last
      "part_name": str,                  # detected" badge on a
      "count": int,                      # completed part-card - $set,
      "detected_at": iso str             # not derived by re-reading
  } | null,                              # history.
  "last_detected_cam2": { ... } | null,

  "detections": {                        # PER-KIT RECORD - one object
      "cam1": {                          # per kit index, holding
          "<kit_index>": {               # everything about that kit's
              "timing": {                # working life in one place
                  "actual_kit_start_time": iso str,
                  "first_part_detected_time": iso str | None,
                  "validated_at": iso str | None,
              },
              "validation": {            # RESERVED for a later build -
                  "image_path": str,     # validate_kit currently sends
                  "validated_at": iso str,   # an optional image but
                  ...                        # nothing is stored under
              } | None,                      # this key yet (see
                                              # validate_kit's docstring)
              "events": [                # AUDIT TRAIL - full event log,
                  {                      # write-heavy ($push to
                      "detected_part": str,      # events specifically),
                      "ai_detected_part_name": str,  # rarely read (a
                      "avg_threshold": float | None,  # later History
                      "tracking_id": str | None,       # drill-down, not
                      "image_path": str | None,         # the live
                      "matched": bool,                   # monitor page).
                      "created_at": iso str,
                  }
              ]
          }
      },
      "cam2": { ... }
  }

  RESTRUCTURED this session (client's explicit call): kit-level timing
  used to live in a separate top-level tree, "kit_timings_cam{1,2}". It
  is now nested INSIDE detections.cam{N}.<kit_index>.timing instead, so
  everything about one kit (timing, a reserved slot for future
  validation detail, and the raw detection log) sits under ONE path -
  "one direction to read" per the client. A future "validate_kit sends
  an image and validation detail" build should populate the sibling
  "validation" key at that same path, not invent a new top-level tree.

  Kit index is an int in application code throughout; Mongo stores the
  nested object key as a string on disk regardless ("1", "2", ...) -
  this module always re-casts with str(kit_index) on read and relies on
  Mongo's automatic string-casting of dotted-path segments on write.

  actual_kit_start_time and validated_at are set together, ONE
  timestamp shared across two kit indices, at the moment validate_kit
  advances the camera: the OLD kit's validated_at and the NEW kit's
  actual_kit_start_time are the exact same instant (finishing kit N and
  starting kit N+1 are the same moment by definition). Kit 1's own
  actual_kit_start_time is stamped separately at activity creation (see
  activities_data.create_live_activity) - there's no "kit 0" to validate
  out of to produce it the normal way.

Completion semantics: current_kit_index_cam{N} can exceed
quantity_required by exactly one step - e.g. quantity_required=5,
kit index 5 is a completely normal working kit; validating it advances
the index to 6, and index 6 (which has no real kit data of its own) is
the sentinel meaning "this camera has completed all its kits." Checked
via _is_camera_completed() everywhere it matters (record_detection,
validate_kit, and the monitor page's build_monitor_view). Once
completed, BOTH further detections AND further validate_kit calls for
that camera are rejected with a clear message (ValidationError) - never
silently accepted, never a generic/opaque error. Independent per
camera - cam1 completing has no effect on cam2's own state.

Sizing note (confirmed acceptable at stated scale: 7 components/camera,
up to ~400 kits/activity): worst case is roughly 1-4MB for the whole
`detections` tree across a full activity lifetime - comfortably under
MongoDB's 16MB document cap. If a future table runs far larger volumes,
each kit's "events" array (the audit log only - NOT "timing", which
stays tiny regardless of volume) is the piece to consider splitting out
first.

validate_kit() does NOT touch part_counts/last_detected/detections.events
for the OLD kit index - that data stays exactly as it was, forming that
kit's permanent history. The "reset" the UI sees for the new kit is
simply because the new kit_index has no key yet in these maps (reads
default to 0 / None), not because anything was deleted.
"""

from datetime import datetime, timezone

CAM_IDS = ("cam1", "cam2")


class ValidationError(Exception):
    """Raised on bad input - caught in routes.py, turned into a 400 JSON
    response, never a 500. Carries an optional machine-readable `reason`
    code (see REASON_* constants below) so routes.py can return a
    structured {success, reason, message} response instead of lumping
    every failure under one generic "validation_error" bucket."""

    def __init__(self, message, reason="validation_error"):
        super().__init__(message)
        self.reason = reason


# Machine-readable reason codes - used by routes.py to build the
# {success, reason, message} response shape. Kept as constants (not
# inline strings scattered through this file) so routes.py's mapping
# from exception -> reason stays a single source of truth.
REASON_NO_LIVE_ACTIVITY = "no_live_activity"
REASON_CAMERA_COMPLETED = "camera_completed"
REASON_VALIDATION_ERROR = "validation_error"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize_cam_id(raw_cam_id):
    """Accepts 1/"1"/"cam1" style input (client sends camid as 1 or 2 per
    spec) and normalizes to the internal "cam1"/"cam2" convention already
    used throughout parts_configured / live_activity_details."""
    text = str(raw_cam_id).strip().lower()
    if text in ("1", "cam1"):
        return "cam1"
    if text in ("2", "cam2"):
        return "cam2"
    raise ValidationError('camid must be 1 or 2 (or "cam1"/"cam2").')


def _kit_index_field(cam_id):
    return f"current_kit_index_{cam_id}"


def _kit_path(cam_id, kit_index):
    """Base dotted path for one kit's whole record -
    detections.cam1.<kit_index> - the root that "timing", "validation",
    and "events" all nest under."""
    return f"detections.{cam_id}.{kit_index}"


# ---------------------------------------------------------------------------
# Image storage - filesystem, namespaced per table_id (unchanged from the
# previous version - only the Mongo side changed)
# ---------------------------------------------------------------------------

def save_detection_image(base_dir, detection_image_dir, table_id, file_storage, allowed_extensions):
    """Saves an uploaded image file to
    <base_dir>/<detection_image_dir>/table_<id>/<uuid><ext> and returns
    the path relative to detection_image_dir. Returns None if no image
    was sent - image presence/frequency was explicitly left open by the
    client, so this must not hard-fail on a request with no image."""
    import os
    import uuid

    if not file_storage or not getattr(file_storage, "filename", ""):
        return None

    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in allowed_extensions:
        raise ValidationError(
            f'Image extension "{ext}" not allowed. Allowed: {", ".join(allowed_extensions)}'
        )

    table_dir = os.path.join(base_dir, detection_image_dir, f"table_{table_id}")
    os.makedirs(table_dir, exist_ok=True)

    filename = f"{uuid.uuid4().hex}{ext}"
    file_storage.save(os.path.join(table_dir, filename))

    return os.path.join(f"table_{table_id}", filename)


# ---------------------------------------------------------------------------
# Validation of incoming payloads
# ---------------------------------------------------------------------------

def _validate_detection_payload(form):
    try:
        table_id = int(form.get("tableid"))
    except (TypeError, ValueError):
        raise ValidationError("tableid is required and must be an integer.")

    cam_id = normalize_cam_id(form.get("camid"))

    detected_part = (form.get("detectedpart") or "").strip()
    if not detected_part:
        raise ValidationError("detectedpart is required.")

    ai_detected_part_name = (form.get("Aidetectedpartname") or "").strip()

    avg_threshold_raw = form.get("avg_threshold")
    avg_threshold = None
    if avg_threshold_raw not in (None, ""):
        try:
            avg_threshold = float(avg_threshold_raw)
        except (TypeError, ValueError):
            raise ValidationError("avg_threshold must be a number if provided.")

    tracking_id = (form.get("tracking_id") or "").strip() or None
    kit_name = (form.get("kitname") or "").strip()

    return {
        "table_id": table_id,
        "cam_id": cam_id,
        "detected_part": detected_part,
        "ai_detected_part_name": ai_detected_part_name,
        "avg_threshold": avg_threshold,
        "tracking_id": tracking_id,
        "kit_name": kit_name,
    }


def _validate_validate_kit_payload(form):
    try:
        table_id = int(form.get("tableid"))
    except (TypeError, ValueError):
        raise ValidationError("tableid is required and must be an integer.")

    cam_id = normalize_cam_id(form.get("camid"))

    message = (form.get("message") or "").strip()
    if message != "validate_now":
        raise ValidationError('message must be "validate_now".')

    return {"table_id": table_id, "cam_id": cam_id}


# ---------------------------------------------------------------------------
# Matching a detected part against the live activity's configured parts
# ---------------------------------------------------------------------------

def _find_matching_part(activity_doc, cam_id, detected_part):
    """Cam-scoped exact match (confirmed: cam1 detections only ever
    consider cam1-configured parts, and vice versa). Returns the part
    dict, or None if not configured for this camera (the red-popup /
    unexpected-part path)."""
    for part in activity_doc.get("parts_configured", []):
        if part.get("camera") == cam_id and part.get("part_name") == detected_part:
            return part
    return None


# ---------------------------------------------------------------------------
# record_detection - the /api/detection-update handler's core logic
# ---------------------------------------------------------------------------

def _is_camera_completed(activity_doc, cam_id):
    """True once this camera has validated past its last real kit - i.e.
    current_kit_index_cam{N} > quantity_required (confirmed semantics:
    if quantity_required=5, kit index 5 is a normal working kit like any
    other; validating it advances the index to 6, and THAT is the
    sentinel meaning "done" - index 6 has no real kit data of its own).
    Checked independently per camera - cam1 completing never affects
    cam2's own state."""
    kit_index = activity_doc.get(_kit_index_field(cam_id), 1)
    target = activity_doc.get("quantity_required", 0)
    return target > 0 and kit_index > target


def record_detection(activities_collection, form, image_path):
    """Validates + persists one detection event directly onto the
    live_activity_details document, and returns everything routes.py
    needs to build the Socket.IO payload.

    OPTIMIZED to a single atomic round trip (find_one_and_update) instead
    of the earlier version's 3 calls (update_one for push+inc, find_one
    to read the new count back, update_one again for last_detected).
    find_one_and_update(..., return_document=AFTER) does the write AND
    hands back the updated document in the same round trip, so the new
    counter value is read directly off the response - no separate read.

    Rejects (ValidationError, reason=REASON_NO_LIVE_ACTIVITY) if the
    table has no live activity at all, and separately (ValidationError,
    reason=REASON_CAMERA_COMPLETED) if this camera has already completed
    all its kits (current_kit_index_cam{N} > quantity_required) - these
    are DISTINCT failure reasons, not both lumped under a generic
    "validation_error" (client's explicit ask: the API should say WHY,
    not just fail).

    One update, all in one operation:
      1. detections.<cam>.<kit_index>.events       - $push, full event (audit)
      2. part_counts_<cam>.<kit_index>.<part>      - $inc by 1 (ONLY if matched)
      3. last_detected_<cam>                        - $set (ONLY if matched)
      4. detections.<cam>.<kit_index>.timing.first_part_detected_time -
         $set, ONLY if this is the first detection recorded for this
         kit index on this camera (never overwritten after the first
         write - see the module docstring's "timing" section).

    The initial find_one() to fetch parts_configured/kit_index for
    matching is unavoidable - matching against configured parts has to
    happen in Python before we know which count field to $inc - but that
    is now the ONLY extra read, and only on the write path (not doubled
    for the count re-read anymore).

    Returns:
    {
      "matched": bool, "table_id": int, "cam_id": str,
      "activity_id": str, "kit_index": int, "part_name": str,
      "count": int, "quantity_required": int|None, "image_path": str|None,
    }
    """
    from pymongo import ReturnDocument

    data = _validate_detection_payload(form)

    activity_doc = activities_collection.find_one(
        {"table_id": data["table_id"], "status": "live"}
    )
    if not activity_doc:
        raise ValidationError(
            f'No live activity found on table {data["table_id"]} - '
            f"cannot record a detection for a table with no active kitting run.",
            reason=REASON_NO_LIVE_ACTIVITY,
        )

    cam_id = data["cam_id"]

    if _is_camera_completed(activity_doc, cam_id):
        raise ValidationError(
            f'Camera {cam_id} on table {data["table_id"]} has already completed '
            f'all {activity_doc.get("quantity_required")} kits for this activity - '
            f"no further detections are accepted for this camera.",
            reason=REASON_CAMERA_COMPLETED,
        )

    activity_id = activity_doc["_id"]
    kit_index = activity_doc.get(_kit_index_field(cam_id), 1)
    part_name = data["detected_part"]

    matched_part = _find_matching_part(activity_doc, cam_id, part_name)
    matched = matched_part is not None
    quantity_required = matched_part.get("quantity_required") if matched_part else None

    now = _now_iso()
    event = {
        "detected_part": part_name,
        "ai_detected_part_name": data["ai_detected_part_name"],
        "avg_threshold": data["avg_threshold"],
        "tracking_id": data["tracking_id"],
        "image_path": image_path,
        "matched": matched,
        "created_at": now,
    }

    # Dotted paths - MongoDB creates intermediate objects/arrays as
    # needed, so no separate "does this kit_index key exist yet" check
    # is required before the first write for a given kit. Everything
    # about this kit now nests under ONE base path (kit_base) - events,
    # timing, and (reserved) validation all sit together, per the
    # client's explicit restructure request.
    kit_base = _kit_path(cam_id, kit_index)
    events_path = f"{kit_base}.events"
    count_path = f"part_counts_{cam_id}.{kit_index}.{part_name}"
    last_detected_path = f"last_detected_{cam_id}"
    first_part_path = f"{kit_base}.timing.first_part_detected_time"

    update = {
        "$push": {events_path: event},
        "$set": {"updated_at": now},
    }
    if matched:
        update["$inc"] = {count_path: 1}
        # $set and $inc can target different paths in the same update
        # document safely (Mongo only forbids the SAME path in two
        # operators, not two different paths under the same top-level
        # key) - last_detected_cam1 and part_counts_cam1.* are distinct
        # top-level fields, so this is a single valid atomic update.
        update["$set"][last_detected_path] = {
            "part_name": part_name,
            "detected_at": now,
            # count is filled in below once we have the post-update
            # document - can't reference the $inc result inside the
            # same $set expression with plain update operators (would
            # need the aggregation-pipeline update form for that, not
            # worth the added complexity for one field).
        }

    # first_part_detected_time is set on EVERY detection call (matched or
    # not - client's spec is "first part detected", not "first MATCHED
    # part", since even a wrong-part detection means someone started
    # working this kit), but only takes effect the first time, via
    # $setOnInsert-style semantics achieved here with a conditional
    # pre-check rather than a Mongo-side "set if not exists" (Mongo's
    # $set always overwrites; there's no native "set only if missing" for
    # a nested path short of $setOnInsert, which only fires on document
    # INSERT, not on updates to an existing doc) - so this is checked in
    # Python against the pre-update document instead.
    existing_first_part = (
        activity_doc.get("detections", {})
        .get(cam_id, {})
        .get(str(kit_index), {})
        .get("timing", {})
        .get("first_part_detected_time")
    )
    if not existing_first_part:
        update["$set"][first_part_path] = now

    updated_doc = activities_collection.find_one_and_update(
        {"_id": activity_id},
        update,
        return_document=ReturnDocument.AFTER,
    )

    count = 0
    if matched:
        count = (
            updated_doc.get(f"part_counts_{cam_id}", {})
            .get(str(kit_index), {})
            .get(part_name, 0)
        )
        # Backfill the count into last_detected now that we have it from
        # the same round trip's response - a second tiny $set, but only
        # for one small field, and still one fewer call than before
        # (previously: update, read-back, update = 3; now: update+read
        # in one call, then this = 2 total).
        activities_collection.update_one(
            {"_id": activity_id},
            {"$set": {f"{last_detected_path}.count": count}},
        )

    sound = resolve_sound_for_detection(updated_doc, cam_id, matched)

    return {
        "matched": matched,
        "table_id": data["table_id"],
        "cam_id": cam_id,
        "activity_id": str(activity_id),
        "kit_index": kit_index,
        "part_name": part_name,
        "count": count,
        "quantity_required": quantity_required,
        "image_path": image_path,
        "detected_at": now,
        "should_play_sound": sound["should_play"],
        "audio_slot_id": sound["slot_id"],
    }


# ---------------------------------------------------------------------------
# validate_kit - the /api/validate-kit handler's core logic
# ---------------------------------------------------------------------------

def validate_kit(activities_collection, form):
    """Advances ONE camera's current_kit_index forward by 1 (cam1/cam2
    advance independently, confirmed). Does NOT touch part_counts,
    last_detected, or the OLD kit's events at all - that data stays
    exactly as-is, forming permanent history. The "reset" the UI sees
    for the new kit happens naturally because the new kit_index has no
    key yet in part_counts (reads default to 0).

    Rejects (ValidationError, reason=REASON_NO_LIVE_ACTIVITY /
    REASON_CAMERA_COMPLETED - distinct reason codes, not one generic
    bucket) if the table has no live activity, or if this camera has
    already completed all its kits (current_kit_index_cam{N} >
    quantity_required already) - confirmed semantics: the call that
    takes the index from quantity_required to quantity_required+1 is
    itself a normal, ALLOWED validate (it's what marks the camera
    "done"); only a call AFTER that point is rejected.

    Kit timing: stamps "validated_at" on the OLD kit index (the one
    just finished) and "actual_kit_start_time" on the NEW kit index -
    both the SAME timestamp, since finishing kit N and starting kit N+1
    are the same instant by definition. Kit 1's own
    actual_kit_start_time is stamped separately, at activity creation
    (see activities_data.create_live_activity) - there is no "kit 0" to
    validate out of. Both now write under
    detections.<cam>.<kit_index>.timing (restructured this session -
    see module docstring) rather than a separate kit_timings_cam{N} tree.

    A "validation" image (optional, per the API contract) is currently
    only saved to disk and otherwise discarded - see routes.py. This
    function reserves detections.<cam>.<kit_index>.validation as WHERE
    that detail should be written once a later build actually stores it
    (image path, pass/fail detail, etc.) - not populated yet, so this
    key does not appear in the document until that build happens.

    Full validation-before-advance rules ("did this kit actually pass?")
    are explicitly deferred per client - this just advances the counter.
    """
    data = _validate_validate_kit_payload(form)

    activity_doc = activities_collection.find_one(
        {"table_id": data["table_id"], "status": "live"}
    )
    if not activity_doc:
        raise ValidationError(
            f'No live activity found on table {data["table_id"]}.',
            reason=REASON_NO_LIVE_ACTIVITY,
        )

    cam_id = data["cam_id"]

    if _is_camera_completed(activity_doc, cam_id):
        raise ValidationError(
            f'Camera {cam_id} on table {data["table_id"]} has already completed '
            f'all {activity_doc.get("quantity_required")} kits for this activity - '
            f"no further validation is accepted for this camera.",
            reason=REASON_CAMERA_COMPLETED,
        )

    field = _kit_index_field(cam_id)
    old_index = activity_doc.get(field, 1)
    new_index = old_index + 1
    now = _now_iso()

    activities_collection.update_one(
        {"_id": activity_doc["_id"]},
        {
            "$set": {
                field: new_index,
                "updated_at": now,
                f"{_kit_path(cam_id, old_index)}.timing.validated_at": now,
                f"{_kit_path(cam_id, new_index)}.timing.actual_kit_start_time": now,
            }
        },
    )

    target = activity_doc.get("quantity_required", 0)
    is_now_completed = target > 0 and new_index > target

    activity_fully_completed = False
    if is_now_completed:
        # Check the OTHER camera's already-stored index (not re-fetched -
        # this camera's own update just happened above, and the other
        # camera's field is untouched by this call, so the pre-update
        # activity_doc's value for it is still current). If both cameras
        # are now past target, the activity as a whole is done - client's
        # explicit requirement: auto-move to history, freeze Total time
        # at this exact instant (the later of the two completions).
        other_cam_id = "cam2" if cam_id == "cam1" else "cam1"
        other_index = activity_doc.get(_kit_index_field(other_cam_id), 1)
        other_target = target  # quantity_required is shared across both cameras
        other_completed = other_target > 0 and other_index > other_target

        if other_completed:
            activity_fully_completed = True

    return {
        "table_id": data["table_id"],
        "cam_id": cam_id,
        "activity_id": str(activity_doc["_id"]),
        "new_kit_index": new_index,
        "is_completed": is_now_completed,
        "kit_start_time": now,
        "activity_fully_completed": activity_fully_completed,
        "completed_at": now if activity_fully_completed else None,
    }


def complete_activity_if_both_cameras_done(activities_collection, history_collection, activity_id, completed_at):
    """Moves a live activity to activity_history with status "completed"
    (client's confirmed choice - the same status value already used
    conceptually alongside "completed-manually", just reached
    automatically instead of via the landing page's Complete Manually
    button). Called from cv_ingest/routes.py right after validate_kit()
    reports activity_fully_completed=True.

    Mirrors live_kitting_activities/activities_data.py's
    complete_activity_manually() pattern exactly (copy the FULL document
    rather than reconstructing a subset, so any field added later is
    automatically carried into history without this function needing to
    know about it) - duplicated here rather than imported, per this
    project's decoupled-blueprints convention (cv_ingest never imports
    from live_kitting_activities, and vice versa).

    completed_at is passed in (the timestamp from the validate_kit call
    that triggered this) rather than computed fresh here with _now_iso(),
    so "Total time" freezes at the EXACT instant the second camera
    completed, not a few milliseconds later when this follow-up call
    happens to run.

    Idempotent-safe: if the activity doc is already gone (e.g. a
    duplicate/retried call), find_one returns None and this is a no-op -
    never raises, since by the time this is called the camera-level
    validate has already succeeded and been persisted; failing to also
    complete-to-history should not surface as an error response to the
    caller that already got a valid 200.
    """
    from bson import ObjectId

    try:
        object_id = ObjectId(activity_id)
    except Exception:
        return

    doc = activities_collection.find_one({"_id": object_id})
    if not doc:
        return

    history_doc = dict(doc)
    history_doc["status"] = "completed"
    history_doc["stopped_at"] = completed_at
    history_doc["completed_at"] = completed_at
    history_doc["stop_reason"] = None
    history_doc["updated_at"] = completed_at
    history_doc.pop("_id", None)

    history_collection.insert_one(history_doc)
    activities_collection.delete_one({"_id": object_id})


# ---------------------------------------------------------------------------
# Sound - green toggle (per-camera, per-activity) + red (always follows
# the table_settings snapshot's default, never toggleable)
# ---------------------------------------------------------------------------

def toggle_green_sound(activities_collection, table_id, cam_id):
    """Flips ONE camera's green-sound-enabled flag on the CURRENT live
    activity for this table. Effective immediately for the current kit
    (client's explicit call - no "next kit" delay). Writes only to
    live_activity_details, never to table_configuration (client's
    explicit instruction: "don't change in default")."""
    activity_doc = activities_collection.find_one(
        {"table_id": table_id, "status": "live"}
    )
    if not activity_doc:
        raise ValidationError(
            f"No live activity found on table {table_id}.",
            reason=REASON_NO_LIVE_ACTIVITY,
        )

    field = f"green_sound_enabled_{cam_id}"
    new_value = not activity_doc.get(field, True)

    activities_collection.update_one(
        {"_id": activity_doc["_id"]},
        {"$set": {field: new_value, "updated_at": _now_iso()}},
    )

    return {
        "table_id": table_id,
        "cam_id": cam_id,
        "activity_id": str(activity_doc["_id"]),
        "green_sound_enabled": new_value,
    }


def resolve_sound_for_detection(activity_doc, cam_id, matched):
    """Decides whether a sound should play for this detection event, and
    which audio file to serve, given the activity's table_settings
    snapshot and (for green only) its per-activity toggle.

    - matched=True  (green path): plays only if this camera's toggle
      (green_sound_enabled_cam{N}, mutable per-activity) is currently on.
    - matched=False (red path): plays only if the table's SAVED default
      for camera_{N}_red is enabled - never toggleable per-activity,
      always reads the snapshot directly (client's explicit instruction).

    Returns {"should_play": bool, "slot_id": str|None} - slot_id is the
    audio_settings key (e.g. "camera_1_green") used to build the file
    URL in routes.py via the existing
    configuration.table_settings_audio_file route. Returns
    should_play=False (no sound) if the activity has no table_settings
    snapshot at all (e.g. an older activity created before this feature,
    or the table never saved Audio Settings) - silently, not an error,
    since a missing snapshot just means "nothing configured to play."
    """
    cam_number = "1" if cam_id == "cam1" else "2"
    color = "green" if matched else "red"
    slot_id = f"camera_{cam_number}_{color}"

    table_settings = activity_doc.get("table_settings")
    if not table_settings:
        return {"should_play": False, "slot_id": None}

    audio_settings = table_settings.get("audio_settings", {})
    slot = audio_settings.get(slot_id, {})

    # A slot with no file ever uploaded has no original_filename - even
    # if default_enabled happens to be true, there's nothing to serve.
    if not slot.get("original_filename"):
        return {"should_play": False, "slot_id": None}

    if matched:
        should_play = activity_doc.get(f"green_sound_enabled_{cam_id}", True)
    else:
        should_play = slot.get("default_enabled", True)

    return {"should_play": bool(should_play), "slot_id": slot_id if should_play else None}


# ---------------------------------------------------------------------------
# Read helpers for the monitor page (activities_data.build_monitor_view
# calls into these instead of touching a second collection)
# ---------------------------------------------------------------------------

def get_part_count(activity_doc, cam_id, kit_index, part_name):
    """Reads the fast-path counter for one part at one kit index.
    Defaults to 0 if that kit index has no detections yet (new kit,
    just advanced past validate_kit) - this is the mechanism behind the
    UI's "reset" for a new kit, not a delete."""
    return (
        activity_doc.get(f"part_counts_{cam_id}", {})
        .get(str(kit_index), {})
        .get(part_name, 0)
    )


def get_last_detected(activity_doc, cam_id):
    """Reads the fast-path last-detected badge info for one camera.
    Returns None if nothing has been detected yet on that camera this
    activity."""
    return activity_doc.get(f"last_detected_{cam_id}")
