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

---------------------------------------------------------------------
RED-SCREEN / ERROR-LOCK FEATURE (added this session)
---------------------------------------------------------------------

Two error types, both gated by a per-kit, per-camera MASTER SWITCH on
the activity doc's "camerawise_alert_config" (copied at creation time
from the kit doc's own camerawise_alert_config - see
activities_data.create_live_activity):

  camerawise_alert_config: [
      {"camera": "cam1", "alert_validation_error": bool, "alert_wrong_part_error": bool},
      {"camera": "cam2", "alert_validation_error": bool, "alert_wrong_part_error": bool},
  ]

Client's explicit confirmation: these are MASTER switches. If off, the
underlying issue is still detected/computed (and, for wrong_part,
logged to the normal audit trail as an unmatched event) but does NOT
raise a red-screen or lock the camera. If on, it does both.

1) wrong_part - checked in record_detection(), same moment as today's
   unmatched-part check. A detected part that doesn't match any
   configured part for that camera is "wrong_part" UNLESS it's also
   present in the activity's "neglect_parts" list for that camera (also
   newly copied from the kit doc at creation) - a neglected part is
   simply not tracked at all, no popup of either color.

2) validation_error - checked in validate_kit(), BEFORE advancing the
   camera's kit index. For every part configured on that camera, using
   each part's own alert_missing/alert_undercount/alert_overcount flags
   (already present on parts_configured - unchanged from before this
   session):
     - alert_missing    + found == 0            -> "missing"
     - alert_undercount + 0 < found < required   -> "undercount"
     - alert_overcount  + found > required        -> "overcount"
   All qualifying issues across every part on that camera are collected
   into ONE validation_error (client's explicit call: "one validation
   error, can have multiple parts issue, but combined its one
   validation error" - never split into several separate red-screens
   for one validate call).

BLOCKING BEHAVIOR - both error types now LOCK the camera
(camera_state_cam{N}: "open" | "locked") until an operator resolves via
the new /api/resolve-error endpoint:
  - wrong_part：kit index does NOT advance on resolve - camera just
    unlocks, DeepStream must send its own validate_now afterward.
  - validation_error: resolving IS the advance - kit index moves
    forward as part of the same resolve call (client: "for
    validation_error its advance, for wrong_part, it should stay in
    same kit").

While a camera is locked, further detection-update/validate-kit calls
for THAT camera are rejected with reason "camera_locked" (a NEW reason
code, distinct from "camera_completed") - logged server-side only, not
written to Mongo (client: "camera stays locked... ignored/logged, no
new red-screen").

PERSISTENCE for late-joining viewers - "current_kit_errors_cam{N}" on
the activity doc holds the ACTIVE, unresolved error (or null if the
camera is open):
  {
    "error_type": "validation_error" | "wrong_part",
    "kit_index": int,
    "issues": [{"part_name": str, "issue": "missing"|"undercount"|"overcount"|"unrecognized",
                "required": int|None, "found": int|None}],
    "image_path": str | None,
    "detected_at": iso str,
  } | None
A monitor page opened while this is non-null renders the locked/red
state immediately, instead of the normal camera panel - see
activities_data.build_monitor_view.

PERMANENT RECORD - on resolve, the SAME error object (plus a
"resolution" key: {"chosen_option": "system_error"|"process_error",
"comment": str|None, "resolved_at": iso str}) is appended to
detections.<cam>.<kit_index>.errors (a NEW array, sibling to "events"
and "timing" under the same per-kit record) - so a kit's error history
is queryable from the same single find_one that already returns
everything else about that kit. This happens for BOTH error types
(client: "every wrong_part error... gets its own permanent entry under
that kit, same as validation_error"), even though only validation_error
also advances the kit index.
"""

from datetime import datetime, timezone

CAM_IDS = ("cam1", "cam2")

# Camera lock states - "locked" while a red-screen (either error type)
# is active and unresolved; "open" otherwise. Distinct from
# _is_camera_completed()'s "all kits done" state, which is permanent
# and unrelated to this per-kit lock.
CAMERA_STATE_OPEN = "open"
CAMERA_STATE_LOCKED = "locked"

ERROR_TYPE_VALIDATION = "validation_error"
ERROR_TYPE_WRONG_PART = "wrong_part"


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
REASON_CAMERA_LOCKED = "camera_locked"  # NEW - distinct from
# REASON_CAMERA_COMPLETED: "locked" means a red-screen is active and
# waiting on the operator; "completed" means this camera is permanently
# done with the whole activity. Both reject detection-update/
# validate-kit calls, but a caller (DeepStream) needs to tell them apart.


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


def _camera_state_field(cam_id):
    return f"camera_state_{cam_id}"


def _current_kit_errors_field(cam_id):
    return f"current_kit_errors_{cam_id}"


def _is_camera_locked(activity_doc, cam_id):
    """True while a red-screen (either error type) is active on this
    camera and awaiting operator resolution. Independent of
    _is_camera_completed() - a camera can only be locked WHILE it still
    has kits left to work; once completed, further calls are rejected
    for that reason instead (checked first in both record_detection and
    validate_kit)."""
    return activity_doc.get(_camera_state_field(cam_id), CAMERA_STATE_OPEN) == CAMERA_STATE_LOCKED


def _neglected_part_names(activity_doc, cam_id):
    """Part names in this camera's neglect list (camera-scoped, per
    client confirmation: a part neglected on cam1 does not suppress
    wrong_part on cam2 for the same part name)."""
    return {
        p.get("part_name")
        for p in activity_doc.get("neglect_parts", [])
        if p.get("camera") == cam_id
    }


def _camera_alert_switches(activity_doc, cam_id):
    """Reads this camera's master switches from camerawise_alert_config
    (copied onto the activity doc at creation - see
    activities_data.create_live_activity). Defaults both to True if the
    camera has no entry (defensive only - _validate_camera_alert_config
    in current_kits_data.py always produces exactly one entry per
    camera at the kit-config level, so this should not normally be
    hit)."""
    for entry in activity_doc.get("camerawise_alert_config", []):
        if entry.get("camera") == cam_id:
            return {
                "alert_validation_error": bool(entry.get("alert_validation_error", True)),
                "alert_wrong_part_error": bool(entry.get("alert_wrong_part_error", True)),
            }
    return {"alert_validation_error": True, "alert_wrong_part_error": True}


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

    # NEW - locked camera (an unresolved red-screen is showing) rejects
    # further detections outright. Per client's explicit call: stays
    # locked, DeepStream is free to keep sending, this is simply
    # ignored/logged (server-side log only - see routes.py - never
    # written to Mongo, since it carries no useful audit value beyond
    # "yes, it kept sending while locked").
    if _is_camera_locked(activity_doc, cam_id):
        raise ValidationError(
            f'Camera {cam_id} on table {data["table_id"]} is locked pending operator '
            f"resolution of an active error - detection ignored.",
            reason=REASON_CAMERA_LOCKED,
        )

    activity_id = activity_doc["_id"]
    kit_index = activity_doc.get(_kit_index_field(cam_id), 1)
    part_name = data["detected_part"]

    matched_part = _find_matching_part(activity_doc, cam_id, part_name)
    matched = matched_part is not None
    quantity_required = matched_part.get("quantity_required") if matched_part else None

    now = _now_iso()

    # NEW (this session, revised) - a neglected part is now a THIRD
    # detection outcome, distinct from both "matched" and "wrong_part":
    # client's explicit reversal of the original "neglected = never
    # tracked, completely invisible" rule. A neglected part now:
    #   - counts (part_counts_<cam>.<kit>.<part_name> increments, same
    #     $inc mechanism as a real matched part - client: "count
    #     increments like a normal part")
    #   - gets a GREEN pop-up + green sound (client: "dont give error
    #     sound instead give green sound and green pop-up") - NOT a
    #     red-screen, NOT even the brief non-blocking red popup
    #   - quantity_required is always 0 for a neglect-list entry
    #     (client: "quantity required for neglect part should be
    #     zero... 2 detected, then it shows 2/0") - it is never
    #     "pending", trivially always at-or-past its own target
    #   - shows a permanent card in Completed, red-tinted with a
    #     "Neglected" badge, GROUPED by part_name (same X/0 card keeps
    #     incrementing on repeat detections, not a new card each time -
    #     see activities_data.build_monitor_view for the card list)
    #
    # A genuine wrong_part (unmatched AND not neglected) is unchanged in
    # its OWN behavior (red-screen if the master switch is on), but now
    # ALSO always gets a Completed-section card - INDIVIDUAL, one new
    # card per detection event, never merged/counted (client: "every
    # wrong_part gets its own separate card since its option and
    # comment can vary depending on what operator choose").
    is_neglected = not matched and part_name in _neglected_part_names(activity_doc, cam_id)
    is_wrong_part_candidate = not matched and not is_neglected

    should_raise_wrong_part = False
    wrong_part_issue = None
    if is_wrong_part_candidate:
        wrong_part_issue = {
            "part_name": part_name,
            "issue": "unrecognized",
            "required": None,
            "found": None,
        }
        switches = _camera_alert_switches(activity_doc, cam_id)
        should_raise_wrong_part = switches["alert_wrong_part_error"]

    event = {
        "detected_part": part_name,
        "ai_detected_part_name": data["ai_detected_part_name"],
        "avg_threshold": data["avg_threshold"],
        "tracking_id": data["tracking_id"],
        "image_path": image_path,
        "matched": matched,
        # NEW - explicit outcome tag on every audit-log event, so the
        # kit's permanent record (detections.<cam>.<kit>.events) is
        # self-describing without having to re-derive "was this
        # neglected?" from a snapshot that may itself change later
        # (client: "wrong_part or neglected part info should be inside
        # the code somewhere clearly"). One of "matched", "neglected",
        # "wrong_part".
        "outcome": "matched" if matched else ("neglected" if is_neglected else "wrong_part"),
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
    wrong_part_cards_path = f"{kit_base}.wrong_part_cards"

    update = {
        "$push": {events_path: event},
        "$set": {"updated_at": now},
    }

    # NEW - neglected parts now increment the SAME part_counts_<cam>
    # structure a real matched part uses (client: "count increments
    # like a normal part"). This is what makes the Completed-card
    # grouping-by-name + running-count come for free out of
    # activities_data.build_monitor_view's existing per-part-count
    # logic - no separate counter structure needed for neglected parts.
    if matched or is_neglected:
        update["$inc"] = {count_path: 1}
        update["$set"][last_detected_path] = {
            "part_name": part_name,
            "detected_at": now,
            # count is filled in below once we have the post-update
            # document - can't reference the $inc result inside the
            # same $set expression with plain update operators (would
            # need the aggregation-pipeline update form for that, not
            # worth the added complexity for one field).
        }

    # NEW - wrong_part detections get their OWN append-only array per
    # kit (client: "every wrong_part gets its own separate card" -
    # individual, never grouped/counted like neglected parts are).
    # image_path here lets the card show the same detection photo the
    # red-screen (if raised) would have shown. "resolution" starts as
    # None and is filled in by resolve_error() ONLY for the specific
    # wrong_part occurrence that actually triggered the active
    # red-screen being resolved - other wrong_part cards for this same
    # kit (if the switch was off, or if several occurred before this
    # one got resolved) are untouched, since each has its own
    # independent resolution per client's explicit rule.
    if is_wrong_part_candidate:
        wrong_part_card = {
            "part_name": part_name,
            "detected_at": now,
            "image_path": image_path,
            "resolution": None,
        }
        update.setdefault("$push", {})
        # Mongo forbids two $push operators on DIFFERENT top-level
        # array paths inside literally the same "$push" dict only if
        # they'd collide - events_path and wrong_part_cards_path are
        # distinct paths, so both can be pushed in one update via
        # $push's own multi-field form.
        update["$push"][wrong_part_cards_path] = wrong_part_card

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

    # NEW - if this unmatched detection raises a wrong_part red-screen
    # (master switch on), lock the camera and persist the active error
    # in the SAME atomic update as the audit-log push - one write, no
    # separate round trip, so a viewer can never observe a half-applied
    # state (event logged but camera not yet locked, or vice versa).
    error_payload = None
    if should_raise_wrong_part:
        error_payload = {
            "error_type": ERROR_TYPE_WRONG_PART,
            "kit_index": kit_index,
            "issues": [wrong_part_issue],
            "image_path": image_path,
            "detected_at": now,
            # NEW - links this active error back to its own entry in
            # wrong_part_cards (matched by detected_at, unique enough
            # within one kit's card list) so resolve_error() can attach
            # the operator's resolution to the SAME card shown in the
            # Completed section, not just the transient error object.
            "wrong_part_detected_at": now,
        }
        update["$set"][_camera_state_field(cam_id)] = CAMERA_STATE_LOCKED
        update["$set"][_current_kit_errors_field(cam_id)] = error_payload

    updated_doc = activities_collection.find_one_and_update(
        {"_id": activity_id},
        update,
        return_document=ReturnDocument.AFTER,
    )

    count = 0
    if matched or is_neglected:
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

    # NEW - neglected parts play the GREEN sound/pop-up, exactly like a
    # real matched part (client's explicit reversal: "dont give error
    # sound instead give green sound and green pop-up"). Pass
    # matched=True here for sound resolution purposes only - "matched"
    # in the RETURNED payload below still correctly reflects
    # parts_configured membership (used elsewhere, e.g. quantity_required),
    # this local plays_as_green flag is just for picking the green vs
    # red audio slot.
    plays_as_green = matched or is_neglected
    sound = resolve_sound_for_detection(updated_doc, cam_id, plays_as_green)

    return {
        "matched": matched,
        "neglected": is_neglected,
        "table_id": data["table_id"],
        "cam_id": cam_id,
        "activity_id": str(activity_id),
        "kit_index": kit_index,
        "part_name": part_name,
        "count": count,
        "quantity_required": quantity_required if matched else (0 if is_neglected else None),
        "image_path": image_path,
        "detected_at": now,
        "should_play_sound": sound["should_play"],
        "audio_slot_id": sound["slot_id"],
        # NEW - non-None only when this detection just raised a
        # wrong_part red-screen. routes.py uses this to decide whether
        # to emit "error:red" (blocking) INSTEAD OF the normal
        # "detection:red" (brief, non-blocking) event.
        "error": error_payload,
    }


# ---------------------------------------------------------------------------
# validation_error check - run at validate_kit time, BEFORE advancing
# ---------------------------------------------------------------------------

def _find_validation_issues(activity_doc, cam_id, kit_index):
    """Checks every part configured on this camera against its detected
    count for the CURRENT kit index, using each part's own
    alert_missing/alert_undercount/alert_overcount flags (unchanged
    fields on parts_configured). Returns a list of issue dicts (possibly
    empty) - ALL qualifying issues across every part are collected into
    one list, never split into multiple separate validation_errors for
    one validate call (client's explicit call).

    This computes issues regardless of the camera's
    alert_validation_error master switch - the switch only decides
    whether the CALLER raises a red-screen for them, not whether they're
    detected/logged (client: "we dont raise alert but still logged in
    backend")."""
    issues = []
    for part in activity_doc.get("parts_configured", []):
        if part.get("camera") != cam_id:
            continue

        part_name = part.get("part_name")
        required = part.get("quantity_required", 0)
        found = get_part_count(activity_doc, cam_id, kit_index, part_name)

        if part.get("alert_missing") and found == 0:
            issues.append({"part_name": part_name, "issue": "missing", "required": required, "found": found})
        elif part.get("alert_undercount") and 0 < found < required:
            issues.append({"part_name": part_name, "issue": "undercount", "required": required, "found": found})
        elif part.get("alert_overcount") and found > required:
            issues.append({"part_name": part_name, "issue": "overcount", "required": required, "found": found})

    return issues


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

    NEW this session - validation_error check runs BEFORE advancing:
    _find_validation_issues() collects every qualifying missing/
    undercount/overcount issue across all parts configured on this
    camera. If the camera's alert_validation_error master switch is ON
    and any issues were found, this call does NOT advance the kit index
    - instead it locks the camera (camera_state_cam{N} = "locked"),
    stores the combined issue list under current_kit_errors_cam{N}, and
    returns validation_error=True so routes.py emits a blocking
    "error:red" event instead of "kit:advanced". The kit only actually
    advances once the operator resolves via /api/resolve-error (client:
    "for validation_error its advance" - resolving the red-screen IS the
    advance for this error type, unlike wrong_part).

    If the switch is off, or no issues were found, this proceeds exactly
    as before - unconditional advance, same as the original build.
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

    # NEW - locked camera rejects further validate_kit calls too (same
    # reason code as record_detection's own lock check).
    if _is_camera_locked(activity_doc, cam_id):
        raise ValidationError(
            f'Camera {cam_id} on table {data["table_id"]} is locked pending operator '
            f"resolution of an active error - validation ignored.",
            reason=REASON_CAMERA_LOCKED,
        )

    field = _kit_index_field(cam_id)
    old_index = activity_doc.get(field, 1)
    now = _now_iso()

    # NEW - validation_error check, BEFORE any advance. Issues are
    # always computed (even if the master switch is off - client: "we
    # dont raise alert but still logged in backend"), but only lock +
    # block when the switch is on AND at least one issue exists.
    issues = _find_validation_issues(activity_doc, cam_id, old_index)
    switches = _camera_alert_switches(activity_doc, cam_id)
    should_raise_validation_error = switches["alert_validation_error"] and bool(issues)

    if should_raise_validation_error:
        error_payload = {
            "error_type": ERROR_TYPE_VALIDATION,
            "kit_index": old_index,
            "issues": issues,
            "image_path": None,  # validate_kit's own image, if sent, is
            # saved to disk by routes.py but not otherwise attached here
            # (same "discarded beyond disk" convention already in place
            # for validate_kit's image before this session).
            "detected_at": now,
        }
        activities_collection.update_one(
            {"_id": activity_doc["_id"]},
            {
                "$set": {
                    "updated_at": now,
                    _camera_state_field(cam_id): CAMERA_STATE_LOCKED,
                    _current_kit_errors_field(cam_id): error_payload,
                }
            },
        )
        return {
            "table_id": data["table_id"],
            "cam_id": cam_id,
            "activity_id": str(activity_doc["_id"]),
            "validation_error": True,
            "error": error_payload,
            # Kept for routes.py's response-shape consistency even
            # though no advance happened - new_kit_index equals the
            # OLD index here, since nothing moved.
            "new_kit_index": old_index,
            "is_completed": False,
            "kit_start_time": None,
            "activity_fully_completed": False,
            "completed_at": None,
        }

    new_index = old_index + 1

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
        "validation_error": False,
        "error": None,
        "new_kit_index": new_index,
        "is_completed": is_now_completed,
        "kit_start_time": now,
        "activity_fully_completed": activity_fully_completed,
        "completed_at": now if activity_fully_completed else None,
    }


# ---------------------------------------------------------------------------
# resolve_error - the /api/resolve-error handler's core logic (NEW)
# ---------------------------------------------------------------------------

CHOSEN_OPTION_SYSTEM_ERROR = "system_error"
CHOSEN_OPTION_PROCESS_ERROR = "process_error"
ALLOWED_CHOSEN_OPTIONS = (CHOSEN_OPTION_SYSTEM_ERROR, CHOSEN_OPTION_PROCESS_ERROR)


def resolve_error(activities_collection, table_id, cam_id, chosen_option, comment):
    """Operator resolves the active red-screen on one camera - the only
    way a locked camera becomes open again.

    chosen_option must be "system_error" or "process_error" (the two
    buttons on the red-screen); comment is optional free text.

    Behavior differs by error_type (client's explicit distinction):
      - "validation_error": resolving IS the advance - kit index moves
        forward in this SAME call, exactly like a normal validate_kit
        would (timing stamps included), since a validation_error only
        exists on the kit that was just about to be validated.
      - "wrong_part": kit index does NOT change - the camera simply
        unlocks. DeepStream must send its own separate validate_now
        afterward, same as any other kit.

    In BOTH cases, the resolved error (original error object + a new
    "resolution" key: {chosen_option, comment, resolved_at}) is
    permanently appended to detections.<cam>.<kit_index>.errors (a new
    array, sibling to "events"/"timing") - client: "every wrong_part
    error... gets its own permanent entry under that kit, same as
    validation_error", even though only validation_error also advances.

    Raises ValidationError (reason=REASON_NO_LIVE_ACTIVITY) if the table
    has no live activity, or a plain validation_error (default reason)
    if the camera isn't actually locked / chosen_option is invalid -
    these are operator-facing input problems, not camera-lock states,
    so they don't need their own reason codes.
    """
    activity_doc = activities_collection.find_one(
        {"table_id": table_id, "status": "live"}
    )
    if not activity_doc:
        raise ValidationError(
            f"No live activity found on table {table_id}.",
            reason=REASON_NO_LIVE_ACTIVITY,
        )

    if chosen_option not in ALLOWED_CHOSEN_OPTIONS:
        raise ValidationError(
            f'chosen_option must be one of {", ".join(ALLOWED_CHOSEN_OPTIONS)}.'
        )

    active_error = activity_doc.get(_current_kit_errors_field(cam_id))
    if not active_error:
        raise ValidationError(
            f"Camera {cam_id} has no active error to resolve."
        )

    now = _now_iso()
    comment = (comment or "").strip() or None

    resolved_error = dict(active_error)
    resolved_error["resolution"] = {
        "chosen_option": chosen_option,
        "comment": comment,
        "resolved_at": now,
    }

    kit_index = active_error["kit_index"]
    errors_path = f"{_kit_path(cam_id, kit_index)}.errors"

    update = {
        "$push": {errors_path: resolved_error},
        "$set": {
            "updated_at": now,
            _camera_state_field(cam_id): CAMERA_STATE_OPEN,
            _current_kit_errors_field(cam_id): None,
        },
    }

    is_validation_error = active_error.get("error_type") == ERROR_TYPE_VALIDATION

    # NEW - for a wrong_part resolution, ALSO write the resolution back
    # onto that SAME occurrence's card in wrong_part_cards (client:
    # "operator choise... should be indicated by P or S outside the
    # card but associated very near to card" - the card needs its own
    # resolution to render that badge). Matched by detected_at (unique
    # enough within one kit's card list) via Mongo's arrayFilters, since
    # wrong_part_cards is an array of embedded documents, not a single
    # value $set can target directly. validation_error has no matching
    # card to update (its issues live only in current_kit_errors_cam{N}
    # / detections.errors, never in wrong_part_cards).
    array_filters = None
    if not is_validation_error and active_error.get("wrong_part_detected_at"):
        wrong_part_cards_path = f"{_kit_path(cam_id, kit_index)}.wrong_part_cards"
        update["$set"][f"{wrong_part_cards_path}.$[card].resolution"] = {
            "chosen_option": chosen_option,
            "comment": comment,
            "resolved_at": now,
        }
        array_filters = [{"card.detected_at": active_error.get("wrong_part_detected_at")}]

    new_kit_index = kit_index
    kit_start_time = None
    is_now_completed = False
    activity_fully_completed = False

    if is_validation_error:
        # Resolving IS the advance - identical timing-stamp logic to
        # validate_kit's own normal-advance path (client: "for
        # validation_error its advance").
        new_kit_index = kit_index + 1
        update["$set"][_kit_index_field(cam_id)] = new_kit_index
        update["$set"][f"{_kit_path(cam_id, kit_index)}.timing.validated_at"] = now
        update["$set"][f"{_kit_path(cam_id, new_kit_index)}.timing.actual_kit_start_time"] = now
        kit_start_time = now

        target = activity_doc.get("quantity_required", 0)
        is_now_completed = target > 0 and new_kit_index > target
        if is_now_completed:
            other_cam_id = "cam2" if cam_id == "cam1" else "cam1"
            other_index = activity_doc.get(_kit_index_field(other_cam_id), 1)
            other_completed = target > 0 and other_index > target
            if other_completed:
                activity_fully_completed = True
    # else (wrong_part): kit index untouched entirely - camera just
    # unlocks, per client's explicit call.

    if array_filters:
        activities_collection.update_one(
            {"_id": activity_doc["_id"]}, update, array_filters=array_filters
        )
    else:
        activities_collection.update_one({"_id": activity_doc["_id"]}, update)

    return {
        "table_id": table_id,
        "cam_id": cam_id,
        "activity_id": str(activity_doc["_id"]),
        "error_type": active_error.get("error_type"),
        "new_kit_index": new_kit_index,
        "is_completed": is_now_completed,
        "kit_start_time": kit_start_time,
        "activity_fully_completed": activity_fully_completed,
        "completed_at": now if activity_fully_completed else None,
        # NEW - "S"/"P" for routes.py's "error:resolved" broadcast, so
        # monitor.js can render the resolution badge OUTSIDE the
        # wrong_part card it created when the red-screen first appeared
        # (client: "operator choise... indicated by P or S"). Not
        # meaningful for validation_error (no matching card exists), but
        # harmless to include either way.
        "resolution_code": "S" if chosen_option == CHOSEN_OPTION_SYSTEM_ERROR else "P",
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
