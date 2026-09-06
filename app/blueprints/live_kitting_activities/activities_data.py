"""
Live Kitting Activities - MongoDB data access + validation.

Two collections are involved here, by design:

1. `current_kits` (current_kit_configurations) - READ ONLY from this module.
   Used to resolve an EDP number -> kit (name + parts) during the create
   flow. Never written to from here.

2. `live_activities` (live_activity_details) - READ/WRITE. One document
   per kitting activity (a single run of packing a kit on a table).

Document shape (collection: mongodb.collections.live_activities):
{
  "table_id": int,
  "table_name": str,               # denormalized at creation time
  "kit_id": ObjectId,               # ref into current_kit_configurations
  "kit_name": str,                  # denormalized at creation time
  "edp_number": str,
  "order_number": str,              # free text, no format validation
  "quantity_required": int,         # "units to pack"
  "parts_configured": [ ... ],      # full parts array copied fresh from
                                     # the kit doc at creation time - never
                                     # trust a parts array passed through
                                     # the browser across the 2-step flow
  "camera_images": {
      "cam1": str,                  # static path for now (placeholder)
      "cam2": str
  },
  "current_kit_index_cam1": int,    # progress counter, default 1 at
  "current_kit_index_cam2": int,    # creation - "1/70" style card display.
                                     # Not yet driven by real detection
                                     # events - that wiring is a later
                                     # build (Socket.IO ingest).
  "status": "live" | "completed" | "completed-manually",
  "created_at": iso str,            # activity start time, shown on cards
  "updated_at": iso str,
}

Only ONE "live" status document is allowed per table_id at a time - see
get_live_activity_for_table() / is_table_busy(), enforced in routes.py
before both the create-page submit and the finalize step (race-safe
re-check at finalize, since two browser tabs could both pass the first
check before either finalizes).

Completing an activity (manually, from the landing page) does not
delete-then-reinsert - it copies the full document into
mongodb.collections.activity_history with two extra fields
(`stopped_at`, `stop_reason`) and status changed to
"completed-manually", then deletes the original from live_activities.
See complete_activity_manually().

`neglect_parts` and `camerawise_alert_config` ARE now copied (added this
session, for the red-screen / error-lock feature - see
cv_ingest/detection_data.py's module docstring for how they're used).
Same one-time-snapshot convention as `parts_configured` and
`table_settings` - editing a kit's neglect list or alert config in
Current Kits Configuration after an activity has started does NOT
retroactively change that activity's already-running snapshot.

Also new this session: `camera_state_cam{1,2}` ("open"|"locked") and
`current_kit_errors_cam{1,2}` (active-error persistence, null when
open) - see cv_ingest/detection_data.py.
"""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

STATUS_LIVE = "live"
STATUS_COMPLETED = "completed"
STATUS_COMPLETED_MANUALLY = "completed-manually"
ALLOWED_STATUSES = (STATUS_LIVE, STATUS_COMPLETED, STATUS_COMPLETED_MANUALLY)


class ValidationError(Exception):
    """Raised on bad input - caught in routes.py and turned into a 400
    JSON response or an inline form error, never a 500."""


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _to_object_id(value, field_label="id"):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise ValidationError(f"Invalid {field_label}.")


# ---------------------------------------------------------------------------
# Kit lookup (reads current_kit_configurations - passed in from routes.py,
# same "collection passed as a parameter" convention as current_kits_data.py)
# ---------------------------------------------------------------------------

def find_kit_by_edp(kits_collection, table_id, edp_number):
    """Exact EDP match, scoped to one table. Returns the raw kit doc, or
    None if not found - routes.py turns None into the "EDP not found on
    this table" error. No fuzzy/substring matching by design (confirmed:
    exact match only, no suggestions)."""
    edp_number = (edp_number or "").strip()
    if not edp_number:
        raise ValidationError("EDP number is required.")

    return kits_collection.find_one({"table_id": table_id, "edp_number": edp_number})


# ---------------------------------------------------------------------------
# Live activities - list (landing page cards)
# ---------------------------------------------------------------------------

def list_live_activities(collection):
    """All activities with status 'live', across all tables - the landing
    page groups these into one card per active activity. Sorted by
    creation time, most recent first."""
    docs = collection.find({"status": STATUS_LIVE}).sort("created_at", -1)
    return [_activity_summary(d) for d in docs]


def _activity_summary(doc):
    return {
        "id": str(doc["_id"]),
        "table_id": doc.get("table_id"),
        "table_name": doc.get("table_name"),
        "order_number": doc.get("order_number"),
        "kit_name": doc.get("kit_name"),
        "edp_number": doc.get("edp_number"),
        "quantity_required": doc.get("quantity_required"),
        "current_kit_index_cam1": doc.get("current_kit_index_cam1", 1),
        "current_kit_index_cam2": doc.get("current_kit_index_cam2", 1),
        "status": doc.get("status"),
        "created_at": doc.get("created_at"),
    }


# ---------------------------------------------------------------------------
# Table-busy check - only one "live" activity allowed per table at a time
# ---------------------------------------------------------------------------

def get_live_activity_for_table(collection, table_id):
    """Returns the current 'live' activity doc for this table, or None if
    the table is free. Used both when the create form is submitted (Next)
    and again at finalize (race-safe re-check - two tabs could both pass
    the first check before either one finalizes)."""
    return collection.find_one({"table_id": table_id, "status": STATUS_LIVE})


def is_table_busy(collection, table_id):
    return get_live_activity_for_table(collection, table_id) is not None


# ---------------------------------------------------------------------------
# Live activities - create (finalize step, from the camera-check page)
# ---------------------------------------------------------------------------

def _validate_create_payload(payload):
    table_id = payload.get("table_id")
    if not isinstance(table_id, int):
        try:
            table_id = int(table_id)
        except (TypeError, ValueError):
            raise ValidationError("A valid station/table must be selected.")

    table_name = (payload.get("table_name") or "").strip()
    if not table_name:
        raise ValidationError("Table name is missing - re-select the station.")

    order_number = (payload.get("order_number") or "").strip()
    if not order_number:
        raise ValidationError("Order number is required.")

    edp_number = (payload.get("edp_number") or "").strip()
    if not edp_number:
        raise ValidationError("EDP number is required.")

    kit_id_raw = payload.get("kit_id")
    if not kit_id_raw:
        raise ValidationError("Kit could not be resolved - re-enter the EDP number.")
    kit_id = _to_object_id(kit_id_raw, "kit id")

    kit_name = (payload.get("kit_name") or "").strip()
    if not kit_name:
        raise ValidationError("Kit name is missing - re-enter the EDP number.")

    try:
        quantity_required = int(payload.get("quantity_required"))
    except (TypeError, ValueError):
        raise ValidationError("Units to pack must be a whole number.")
    if quantity_required <= 0:
        raise ValidationError("Units to pack must be greater than 0.")

    return {
        "table_id": table_id,
        "table_name": table_name,
        "order_number": order_number,
        "edp_number": edp_number,
        "kit_id": kit_id,
        "kit_name": kit_name,
        "quantity_required": quantity_required,
    }


def create_live_activity(
    activities_collection,
    kits_collection,
    payload,
    camera_images,
    table_settings_collection=None,
):
    """Finalizes an activity: re-validates everything server-side (the
    2-step flow only carries data through hidden form fields / query
    params - nothing before this point is trusted), re-fetches the kit
    from current_kit_configurations by kit_id to get an authoritative
    parts_configured snapshot (never trust a parts array round-tripped
    through the browser), and inserts one live_activity_details doc with
    status "live".

    table_settings_collection (optional - the `table_configuration`
    collection from configuration/table_settings_data.py): when passed,
    that table's ENTIRE Table Settings document (audio_settings,
    expected_client_ips, push_notification_emails, push_notifications)
    is snapshotted as-is under this activity's "table_settings" key.
    This is a one-time copy, same convention as parts_configured -
    later edits to Table Settings do NOT retroactively change an
    already-created activity's snapshot. Optional (defaults to None) so
    any existing caller that doesn't pass it keeps working exactly as
    before, just without the new field - not yet used elsewhere in this
    build (client's explicit note: "we will use that in next
    iteration"), so no other code depends on it existing.

    camera_images: {"cam1": str, "cam2": str} - static paths for now.
    """
    data = _validate_create_payload(payload)

    # Race-safe re-check: the create page already checked this table wasn't
    # busy before letting the user reach camera-check, but that was a
    # separate request - re-check here, at the point of actually writing,
    # so two tabs/users racing on the same table can't both create a live
    # activity for it.
    if is_table_busy(activities_collection, data["table_id"]):
        busy_doc = get_live_activity_for_table(activities_collection, data["table_id"])
        raise ValidationError(
            f'Table {data["table_id"]} — {data["table_name"]} is already busy with '
            f'order "{busy_doc.get("order_number")}". Complete or stop that activity first.'
        )

    kit_doc = kits_collection.find_one({"_id": data["kit_id"], "table_id": data["table_id"]})
    if not kit_doc:
        raise ValidationError(
            "The selected kit no longer exists on this table - re-enter the EDP number."
        )

    table_settings_snapshot = None
    if table_settings_collection is not None:
        table_settings_snapshot = _snapshot_table_settings(
            table_settings_collection, data["table_id"]
        )

    # Green sound toggle - per-camera, per-activity, mutable after
    # creation (see cv_ingest/detection_data.toggle_green_sound()).
    # Seeded from the table's saved default_enabled at creation time
    # only - flipping this later never writes back to table_configuration
    # (client's explicit instruction: "don't change in default"). Red
    # sound has no equivalent field here - it always reads
    # table_settings.audio_settings.camera_{N}_red.default_enabled
    # directly at playback time, never toggleable per-activity.
    green_sound_defaults = _default_green_sound_enabled(table_settings_snapshot)

    now = _now_iso()
    doc = {
        "table_id": data["table_id"],
        "table_name": data["table_name"],
        "kit_id": data["kit_id"],
        "kit_name": kit_doc.get("kit_name", data["kit_name"]),
        "edp_number": data["edp_number"],
        "order_number": data["order_number"],
        "quantity_required": data["quantity_required"],
        "parts_configured": kit_doc.get("parts", []),
        # NEW (this session, red-screen feature) - both previously
        # NOT copied (see this module's original docstring note, now
        # superseded): required so validate-time validation_error
        # checks and detection-time wrong_part/neglect checks have the
        # data they need on the ACTIVITY doc itself, not just the kit
        # config doc (which could change after this activity started -
        # same "snapshot at creation, never retroactive" rule already
        # applied to parts_configured and table_settings).
        "neglect_parts": kit_doc.get("neglect_parts", []),
        "camerawise_alert_config": kit_doc.get("camerawise_alert_config", []),
        "camera_images": {
            "cam1": camera_images.get("cam1", ""),
            "cam2": camera_images.get("cam2", ""),
        },
        "current_kit_index_cam1": 1,
        "current_kit_index_cam2": 1,
        "green_sound_enabled_cam1": green_sound_defaults["cam1"],
        "green_sound_enabled_cam2": green_sound_defaults["cam2"],
        # NEW (red-screen feature) - both cameras start "open" (no
        # active error). "locked" is set by cv_ingest/detection_data.py
        # the moment a wrong_part or validation_error red-screen is
        # raised, and cleared back to "open" only when the operator
        # resolves via /api/resolve-error.
        "camera_state_cam1": "open",
        "camera_state_cam2": "open",
        # NEW - persistence for a viewer who opens the monitor page
        # WHILE a red-screen is already active on some other client
        # (client's explicit requirement) - null means no active error.
        "current_kit_errors_cam1": None,
        "current_kit_errors_cam2": None,
        # Kit-level timing lives NESTED inside detections.cam{N}.<kit>
        # .timing (restructured this session, per client's request - see
        # cv_ingest/detection_data.py's module docstring for the full
        # shape). Kit 1's start time is the activity's own creation
        # moment, since kit 1 is "current" from the instant the activity
        # begins - there's no "kit 0" to validate out of to produce this
        # the normal way (see cv_ingest/detection_data.validate_kit for
        # kit 2+'s start times, which come from the PREVIOUS kit's
        # validated_at). "validation" is left absent (not even an empty
        # dict) until a later build actually populates it - reserved,
        # not yet used.
        "detections": {
            "cam1": {"1": {"timing": {"actual_kit_start_time": now, "first_part_detected_time": None, "validated_at": None}, "events": []}},
            "cam2": {"1": {"timing": {"actual_kit_start_time": now, "first_part_detected_time": None, "validated_at": None}, "events": []}},
        },
        "status": STATUS_LIVE,
        "created_at": now,
        "updated_at": now,
    }
    if table_settings_snapshot is not None:
        doc["table_settings"] = table_settings_snapshot

    result = activities_collection.insert_one(doc)
    return str(result.inserted_id)


def _default_green_sound_enabled(table_settings_snapshot):
    """Reads camera_1_green / camera_2_green's default_enabled from the
    table_settings snapshot (or the module-wide DEFAULT_ENABLED=True
    fallback used throughout table_settings_data.py, if no snapshot was
    taken or the table never saved Audio Settings) - this becomes the
    STARTING value for this activity's green sound toggles, which the
    operator can then flip independently per camera without ever
    touching the table's saved default."""
    DEFAULT_ENABLED = True  # mirrors table_settings_data.DEFAULT_ENABLED
    if not table_settings_snapshot:
        return {"cam1": DEFAULT_ENABLED, "cam2": DEFAULT_ENABLED}

    audio_settings = table_settings_snapshot.get("audio_settings", {})
    return {
        "cam1": audio_settings.get("camera_1_green", {}).get("default_enabled", DEFAULT_ENABLED),
        "cam2": audio_settings.get("camera_2_green", {}).get("default_enabled", DEFAULT_ENABLED),
    }


def _snapshot_table_settings(table_settings_collection, table_id):
    """Reads the table's Table Settings document (from
    configuration/table_settings_data.py's `table_configuration`
    collection) and returns a plain dict copy for embedding into the
    new activity - organized under a single "table_settings" key so
    everything (audio, IPs, emails, notifications) is grouped together
    rather than spread across top-level fields on the activity doc.

    Uses find_one directly rather than importing
    table_settings_data.get_table_config() - that function lives in the
    configuration blueprint, and blueprints stay decoupled from each
    other in this codebase (same convention already followed for the
    duplicated _require_built_table() guard). The empty-skeleton
    fallback below mirrors get_table_config()'s shape exactly, so a
    table with no Table Settings saved yet still gets a
    consistently-shaped (if empty) snapshot rather than a missing key.
    """
    doc = table_settings_collection.find_one({"table_id": table_id})
    if not doc:
        return {
            "audio_settings": {},
            "expected_client_ips": [],
            "push_notification_emails": [],
            "push_notifications": {},
        }

    return {
        "audio_settings": doc.get("audio_settings", {}),
        "expected_client_ips": doc.get("expected_client_ips", []),
        "push_notification_emails": doc.get("push_notification_emails", []),
        "push_notifications": doc.get("push_notifications", {}),
    }


# ---------------------------------------------------------------------------
# Monitor page - single activity detail, with parts split by camera
# ---------------------------------------------------------------------------

def get_activity_by_id(collection, activity_id):
    """Fetch one activity doc by id, or None if it doesn't exist. Raises
    ValidationError on a malformed id (caught in routes.py -> 404)."""
    object_id = _to_object_id(activity_id, "activity id")
    return collection.find_one({"_id": object_id})


def build_monitor_view(doc):
    """Shapes a raw live_activity_details doc into the monitor page's
    per-camera structure. Splits parts_configured by camera.

    Per-part counts and the "last detected" badge are read directly off
    this SAME document (part_counts_cam{1,2}, last_detected_cam{1,2} -
    see cv_ingest/detection_data.py) - no second collection, no extra
    query. That's the whole point of the embedded schema: one
    find_one({"_id": activity_id}) (already done by the caller in
    routes.py) is all that's needed here.

    A part with no entry yet in part_counts_cam{N} for the CURRENT kit
    index defaults to 0 - this is what makes the UI show a fresh/reset
    state for a new kit after validate_kit advances the index, without
    anything having been deleted (the old kit index's counts are still
    sitting in part_counts_cam{N}, just not read here since only the
    current kit's numbers are ever shown live).

    A part is "completed" once its count reaches quantity_required.

    COMPLETION (added this session): current_kit_index_cam{N} can exceed
    quantity_required by exactly one step once validate_kit is called on
    the last real kit - e.g. quantity_required=5, kit index 5 is a
    normal working kit, and validating it advances to 6. Index 6 has no
    real kit data of its own; it's purely the sentinel meaning "this
    camera is done." When that's the case, completed_parts/pending_parts
    are both returned empty and is_completed=True is set instead - the
    template renders a "Kits Completed" state rather than any cards.
    Independent per camera - cam1 completing has no bearing on cam2.

    The progress bar/percent is NOT derived from part quantities - it
    tracks kits packed so far (current_kit_index_cam{1,2}) against the
    activity's overall target (quantity_required, e.g. 50 units to
    pack), confirmed scope, CAPPED at 100% once a camera completes
    (kit_index can be one past target - e.g. 6 with target 5 - and
    without capping this would show a nonsensical 120%). Per-part Qty
    X/Y on each card is a separate, unrelated number (how many of that
    specific part have been detected for the CURRENT kit, out of how
    many that kit needs)."""

    target = doc.get("quantity_required", 0)

    def _detected_count(camera, kit_index, part_name):
        return (
            doc.get(f"part_counts_{camera}", {})
            .get(str(kit_index), {})
            .get(part_name, 0)
        )

    def _parts_for_camera(camera, kit_index):
        parts = []
        for part in doc.get("parts_configured", []):
            if part.get("camera") != camera:
                continue
            required = part.get("quantity_required", 0)
            part_name = part.get("part_name")
            count = _detected_count(camera, kit_index, part_name)
            is_last_detected = (
                doc.get(f"last_detected_{camera}", {}) or {}
            ).get("part_name") == part_name
            parts.append({
                "part_name": part_name,
                "count": count,
                "quantity_required": required,
                "completed": count >= required and required > 0,
                "last_detected": is_last_detected,
                "card_type": "normal",
            })
        return parts

    def _neglected_cards_for_camera(camera, kit_index):
        """NEW (this session) - neglected-part cards, GROUPED by
        part_name with a running count (client: "count increments like
        a normal part"), same part_counts_<cam> structure a real
        matched part uses. quantity_required is always 0 for a neglect
        entry (client: "2 detected, then it shows 2/0") - so these are
        trivially always "completed" (count >= 0 is always true) and
        belong permanently in the Completed section, never Pending.
        Only includes a card once the part has actually been detected
        at least once this kit (count > 0) - an un-detected neglect-list
        entry shows nothing, same as an un-detected real part would show
        in Pending rather than a phantom 0-count Completed card."""
        cards = []
        for neglect_part in doc.get("neglect_parts", []):
            if neglect_part.get("camera") != camera:
                continue
            part_name = neglect_part.get("part_name")
            count = _detected_count(camera, kit_index, part_name)
            if count <= 0:
                continue
            is_last_detected = (
                doc.get(f"last_detected_{camera}", {}) or {}
            ).get("part_name") == part_name
            cards.append({
                "part_name": part_name,
                "count": count,
                "quantity_required": 0,
                "completed": True,
                "last_detected": is_last_detected,
                "card_type": "neglected",
            })
        return cards

    def _wrong_part_cards_for_camera(camera, kit_index):
        """NEW (this session) - wrong_part cards, INDIVIDUAL (one per
        detection event, never grouped/counted - client: "every
        wrong_part gets its own separate card since its option and
        comment can vary depending on what operator choose"). Sourced
        from detections.<cam>.<kit_index>.wrong_part_cards (see
        cv_ingest/detection_data.record_detection). "resolution" is None
        until an operator resolves the red-screen that (may have)
        accompanied this specific occurrence - see
        cv_ingest/detection_data.resolve_error's arrayFilters update."""
        raw_cards = (
            doc.get("detections", {})
            .get(camera, {})
            .get(str(kit_index), {})
            .get("wrong_part_cards", [])
        )
        cards = []
        for card in raw_cards:
            resolution = card.get("resolution")
            cards.append({
                "part_name": card.get("part_name"),
                "count": None,
                "quantity_required": None,
                "completed": True,
                "last_detected": False,
                "card_type": "wrong_part",
                "detected_at": card.get("detected_at"),
                # NEW - S/P badge source (client: "operator choise...
                # indicated by P or S"). None while unresolved (switch
                # was off, so no red-screen ever blocked this one) or
                # while a red-screen for it is still pending resolution.
                "resolution_code": (
                    "S" if resolution and resolution.get("chosen_option") == "system_error"
                    else "P" if resolution and resolution.get("chosen_option") == "process_error"
                    else None
                ),
            })
        return cards

    def _kit_start_time(camera, kit_index):
        """The CURRENT kit's start time, for the monitor page's per-kit
        timer (resets to 0 on every validate_kit for that camera - see
        FRD). Reads from detections.<camera>.<kit_index>.timing
        (restructured this session - was a separate kit_timings_cam{N}
        tree, now nested inside the per-kit detections record, per
        client's request). Falls back to the activity's own created_at
        if this kit index somehow has no timing entry yet (defensive
        only - kit 1 always gets one at creation, and every later kit
        gets one from validate_kit - this should not normally happen)."""
        return (
            doc.get("detections", {})
            .get(camera, {})
            .get(str(kit_index), {})
            .get("timing", {})
            .get("actual_kit_start_time")
            or doc.get("created_at")
        )

    def _camera_summary(camera, kit_index):
        is_completed = target > 0 and kit_index > target

        if is_completed:
            # No real kit data exists at an index past target - return
            # empty lists rather than attempting to look up parts for a
            # kit index that was never actually worked.
            completed, pending = [], []
        else:
            parts = _parts_for_camera(camera, kit_index)
            completed = [p for p in parts if p["completed"]]
            pending = [p for p in parts if not p["completed"]]
            # NEW - neglected + wrong_part cards are ALWAYS "completed"
            # by definition (client: they show up in the Completed
            # section, red-tinted, never in Pending) - appended after
            # the real parts so normal cards render first, extras last.
            # Does NOT affect total_count/percent below - those are
            # still computed purely from kit_index/target, unaffected
            # by neglected/wrong_part activity (client's explicit call).
            completed = completed + _neglected_cards_for_camera(camera, kit_index) + _wrong_part_cards_for_camera(camera, kit_index)

        # NEW (red-screen feature) - a viewer opening (or refreshing)
        # the monitor page while an error is already active on this
        # camera sees the locked/red state immediately, sourced from
        # current_kit_errors_cam{N} (persists across page loads - the
        # whole point of storing it on the doc rather than only ever
        # emitting it over a socket event, which a fresh page load would
        # miss entirely).
        active_error = doc.get(f"current_kit_errors_{camera}")
        is_locked = doc.get(f"camera_state_{camera}", "open") == "locked"

        # Capped at 100% - kit_index can be ONE past target once
        # completed (e.g. 6 with target 5), which would otherwise show
        # a nonsensical >100% on the progress bar.
        effective_index = min(kit_index, target) if target else kit_index
        percent = round((effective_index / target) * 100, 2) if target else 0.0

        return {
            "camera_label": "CAM1" if camera == "cam1" else "CAM2",
            "current_kit_index": kit_index,
            "is_completed": is_completed,
            "completed_parts": completed,
            "pending_parts": pending,
            "total_count": effective_index,
            "total_required": target,
            "percent": percent,
            # Green sound toggle state - per-camera, per-activity (see
            # cv_ingest/detection_data.toggle_green_sound()). Red sound
            # has no toggle; it always reads the table_settings snapshot's
            # default_enabled directly at playback time.
            "green_sound_enabled": doc.get(f"green_sound_enabled_{camera}", True),
            # Kit-level timing (added this session) - the CURRENT kit's
            # start time, for the monitor page's per-kit timer (resets
            # to 0 whenever validate_kit advances this camera).
            "kit_start_time": _kit_start_time(camera, kit_index),
            # NEW (red-screen feature)
            "is_locked": is_locked,
            "active_error": active_error,
        }

    return {
        "id": str(doc["_id"]),
        "table_id": doc.get("table_id"),
        "table_name": doc.get("table_name"),
        "kit_name": doc.get("kit_name"),
        "edp_number": doc.get("edp_number"),
        "order_number": doc.get("order_number"),
        "status": doc.get("status"),
        "created_at": doc.get("created_at"),
        "cam1": _camera_summary("cam1", doc.get("current_kit_index_cam1", 1)),
        "cam2": _camera_summary("cam2", doc.get("current_kit_index_cam2", 1)),
    }

def complete_activity_manually(activities_collection, history_collection, activity_id, reason):
    """Moves a live activity to the history collection with status
    "completed-manually". Copies the full document rather than deleting
    then reinserting a reconstructed one, so any field added to
    live_activity_details later is automatically carried into history
    without this function needing to know about it.

    reason: optional free-text string explaining why it was stopped early
    (None/blank is allowed - the confirmation's reason field is optional).
    """
    object_id = _to_object_id(activity_id, "activity id")
    doc = activities_collection.find_one({"_id": object_id})
    if not doc:
        raise ValidationError("Activity not found - it may have already been completed.")
    if doc.get("status") != STATUS_LIVE:
        raise ValidationError("Only a live activity can be completed manually.")

    reason = (reason or "").strip()
    now = _now_iso()

    history_doc = dict(doc)
    history_doc["status"] = STATUS_COMPLETED_MANUALLY
    history_doc["stopped_at"] = now
    history_doc["stop_reason"] = reason or None
    history_doc["updated_at"] = now
    # New _id in history - keep the live-activity _id out of it so a
    # duplicate-key collision can never happen if this ever runs twice
    # (e.g. retried request) on a doc already removed from live_activities.
    history_doc.pop("_id", None)

    history_collection.insert_one(history_doc)
    activities_collection.delete_one({"_id": object_id})
