"""
CV Ingest - MongoDB data access + validation for the DeepStream detection
pipeline.

REVISED SCHEMA (per client decision): no separate detection_events
collection. Everything lives on the live_activity_details document
itself, so a single find_one({"_id": activity_id}) returns the full
picture for both cameras and every kit iteration - no join, no second
collection to keep in sync.

Fields added to live_activity_details (all four kept in step by every
write in this module):

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

  "detections": {                        # AUDIT TRAIL - full event log,
      "cam1": {                          # write-heavy ($push), rarely
          "<kit_index>": [               # read (a later History
              {                          # drill-down, not the live
                  "detected_part": str,       # monitor page). Kit index
                  "ai_detected_part_name": str,  # is an int key here
                  "avg_threshold": float|None,   # (Mongo stores object
                  "tracking_id": str|None,       # keys as strings on
                  "image_path": str|None,        # disk regardless, but
                  "matched": bool,                # this module always
                  "created_at": iso str,          # treats/casts it as
              }                                    # an int in Python).
          ]
      },
      "cam2": { ... }
  }

Sizing note (confirmed acceptable at stated scale: 7 components/camera,
up to ~400 kits/activity): worst case is roughly 1-4MB for the whole
`detections` audit array across a full activity lifetime - comfortably
under MongoDB's 16MB document cap. If a future table runs far larger
volumes, `detections` (the audit log only - NOT part_counts/
last_detected, which are tiny) is the field to consider splitting out
first.

validate_kit() does NOT touch part_counts/last_detected/detections for
the OLD kit index - that data stays exactly as it was, forming that
kit's permanent history. The "reset" the UI sees for the new kit is
simply because the new kit_index has no key yet in these maps (reads
default to 0 / None), not because anything was deleted.
"""

from datetime import datetime, timezone

CAM_IDS = ("cam1", "cam2")


class ValidationError(Exception):
    """Raised on bad input - caught in routes.py, turned into a 400 JSON
    response, never a 500."""


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

    One update, all in one operation:
      1. detections.<cam>.<kit_index>          - $push, full event (audit)
      2. part_counts_<cam>.<kit_index>.<part>  - $inc by 1 (ONLY if matched)
      3. last_detected_<cam>                    - $set (ONLY if matched)

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
            f"cannot record a detection for a table with no active kitting run."
        )

    activity_id = activity_doc["_id"]
    cam_id = data["cam_id"]
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
    # is required before the first write for a given kit.
    detections_path = f"detections.{cam_id}.{kit_index}"
    count_path = f"part_counts_{cam_id}.{kit_index}.{part_name}"
    last_detected_path = f"last_detected_{cam_id}"

    update = {
        "$push": {detections_path: event},
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
    last_detected, or detections for the camera at all - the old kit
    index's data stays exactly as-is, forming permanent history. The
    "reset" the UI sees for the new kit happens naturally because the
    new kit_index has no key yet in part_counts (reads default to 0).

    Full validation-before-advance rules ("did this kit actually pass?")
    are explicitly deferred per client - this just advances the counter.
    """
    data = _validate_validate_kit_payload(form)

    activity_doc = activities_collection.find_one(
        {"table_id": data["table_id"], "status": "live"}
    )
    if not activity_doc:
        raise ValidationError(f'No live activity found on table {data["table_id"]}.')

    field = _kit_index_field(data["cam_id"])
    new_index = activity_doc.get(field, 1) + 1

    activities_collection.update_one(
        {"_id": activity_doc["_id"]},
        {"$set": {field: new_index, "updated_at": _now_iso()}},
    )

    return {
        "table_id": data["table_id"],
        "cam_id": data["cam_id"],
        "activity_id": str(activity_doc["_id"]),
        "new_kit_index": new_index,
    }


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
        raise ValidationError(f"No live activity found on table {table_id}.")

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
