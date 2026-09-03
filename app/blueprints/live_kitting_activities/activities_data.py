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

No `neglect_parts` or `camerawise_alert_config` copy yet - not part of
this build's scope (nothing in the current UI surfaces them). If a later
requirement needs them for live monitoring, add the fields then, copied
the same way `parts_configured` is.
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


def create_live_activity(activities_collection, kits_collection, payload, camera_images):
    """Finalizes an activity: re-validates everything server-side (the
    2-step flow only carries data through hidden form fields / query
    params - nothing before this point is trusted), re-fetches the kit
    from current_kit_configurations by kit_id to get an authoritative
    parts_configured snapshot (never trust a parts array round-tripped
    through the browser), and inserts one live_activity_details doc with
    status "live".

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
        "camera_images": {
            "cam1": camera_images.get("cam1", ""),
            "cam2": camera_images.get("cam2", ""),
        },
        "current_kit_index_cam1": 1,
        "current_kit_index_cam2": 1,
        "status": STATUS_LIVE,
        "created_at": now,
        "updated_at": now,
    }
    result = activities_collection.insert_one(doc)
    return str(result.inserted_id)


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
    per-camera structure. Splits parts_configured by camera, and starts
    every part's detected count at 0 (confirmed scope: this is a UI-only
    build - progress counts are not yet driven by real detection events,
    that wiring is a later build). A part is "completed" once its count
    reaches quantity_required; all parts currently start pending since
    count is always 0 here.

    The progress bar/percent is NOT derived from part quantities - it
    tracks kits packed so far (current_kit_index_cam{1,2}) against the
    activity's overall target (quantity_required, e.g. 50 units to
    pack), confirmed scope. Per-part Qty X/Y on each card is a separate,
    unrelated number (how many of that specific part have been detected
    for the CURRENT kit, out of how many that kit needs)."""

    target = doc.get("quantity_required", 0)

    def _parts_for_camera(camera):
        parts = []
        for part in doc.get("parts_configured", []):
            if part.get("camera") != camera:
                continue
            required = part.get("quantity_required", 0)
            count = 0  # static for this UI-only build - not yet wired to detections
            parts.append({
                "part_name": part.get("part_name"),
                "count": count,
                "quantity_required": required,
                "completed": count >= required and required > 0,
            })
        return parts

    def _camera_summary(camera, kit_index):
        parts = _parts_for_camera(camera)
        completed = [p for p in parts if p["completed"]]
        pending = [p for p in parts if not p["completed"]]
        percent = round((kit_index / target) * 100, 2) if target else 0.0
        return {
            "camera_label": "CAM1" if camera == "cam1" else "CAM2",
            "current_kit_index": kit_index,
            "completed_parts": completed,
            "pending_parts": pending,
            "total_count": kit_index,
            "total_required": target,
            "percent": percent,
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
