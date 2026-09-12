"""
History - MongoDB data access + filtering/pagination logic.

Reads ONLY from activity_history (mongodb.collections.activity_history).
Read/delete only from this module - History has no independent create
path; documents arrive here exclusively via
live_kitting_activities.activities_data.complete_activity_manually()
(and, once built, the equivalent auto-completion path - see
WORKING_STYLE_AND_CONSTRAINTS.md/this session's own scope note: history
listing is a separate, independent blueprint - no cross-blueprint
imports, per explicit instruction).

Document shape read here (copied verbatim from live_activity_details at
completion time - see activities_data.complete_activity_manually):
{
  "_id": ObjectId,
  "table_id": int, "table_name": str,
  "kit_id": ObjectId, "kit_name": str, "edp_number": str,
  "order_number": str, "quantity_required": int,
  "current_kit_index_cam1": int, "current_kit_index_cam2": int,
  "detections": {
      "cam1": {"<kit_index>": {"errors": [...], ...}, ...},
      "cam2": {"<kit_index>": {"errors": [...], ...}, ...},
  },
  "status": "completed" | "completed-manually",
  "created_at": iso str, "stopped_at": iso str (manual only),
  "stop_reason": str | None,
  ...
}

Each entry in detections.<cam>.<kit_index>.errors (populated by
cv_ingest/detection_data.resolve_error) has the shape:
{
  "error_type": "validation_error" | "wrong_part",
  "resolution": {"chosen_option": "system_error" | "process_error",
                 "comment": str | None, "resolved_at": iso str} | None,
  ...
}
An entry with resolution=None (should not normally exist once an
activity has moved to history - see resolve_error's own docstring:
resolution is only ever appended AS PART OF resolving) is defensively
skipped when tallying chosen_option, rather than raising.
"""

import os
import re
import shutil
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from bson.errors import InvalidId

STATUS_COMPLETED = "completed"
STATUS_COMPLETED_MANUALLY = "completed-manually"
HISTORY_STATUSES = (STATUS_COMPLETED, STATUS_COMPLETED_MANUALLY)

DEFAULT_DATE_RANGE_DAYS = 7
DEFAULT_PER_PAGE = 10
ALLOWED_PER_PAGE = (10, 25)


class ValidationError(Exception):
    """Raised on bad input - caught in routes.py and turned into a
    clean fallback (e.g. defaulting an unparseable date/page value)
    rather than a 500, same convention as every other blueprint."""


def _to_object_id(value, field_label="id"):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise ValidationError(f"Invalid {field_label}.")


# ---------------------------------------------------------------------------
# Filter defaults / parsing
# ---------------------------------------------------------------------------

def default_date_range():
    """Last 7 days INCLUSIVE of today, as (date_from, date_to) date
    objects - matches the filter's stated default. today() is the
    server's current UTC date, same convention used everywhere else in
    this codebase (created_at is always stored as UTC ISO - see
    activities_data._now_iso)."""
    today = datetime.now(timezone.utc).date()
    return today - timedelta(days=DEFAULT_DATE_RANGE_DAYS - 1), today


def parse_date_param(raw_value):
    """Parses a "YYYY-MM-DD" query-param string into a date object.
    Returns None on missing/malformed input - callers fall back to the
    default range rather than raising, since a bad/missing filter
    param should never break the whole page (same "never crash over an
    optional field" convention already used throughout this app)."""
    if not raw_value:
        return None
    try:
        return datetime.strptime(raw_value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def parse_table_id_param(raw_value):
    """Returns an int table_id, or None for "All Tables" (empty/missing
    value) or an unparseable value - None means "no table filter"."""
    if not raw_value:
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def parse_per_page_param(raw_value):
    """Clamps to one of ALLOWED_PER_PAGE - any other value (including
    missing/malformed) falls back to DEFAULT_PER_PAGE rather than
    trusting an arbitrary client-supplied page size."""
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_PER_PAGE
    return value if value in ALLOWED_PER_PAGE else DEFAULT_PER_PAGE


def parse_page_param(raw_value):
    """1-indexed page number, minimum 1 - never trusts a negative/zero/
    non-numeric value from the query string."""
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return 1
    return value if value >= 1 else 1


# ---------------------------------------------------------------------------
# Error summary - tallies BOTH dimensions (error_type, chosen_option)
# from the SAME source array, per client's explicit confirmation: only
# detections.<cam>.<kit_index>.errors counts - wrong_part_cards is a
# separate display/audit structure and is NOT counted here (would
# double-count wrong_part occurrences relative to the resolved-error
# log).
# ---------------------------------------------------------------------------

def _tally_errors(doc):
    """Walks detections.<cam>.<kit_index>.errors for both cameras and
    every kit index, returning:
    {"validation_error": int, "wrong_part": int,
     "system_error": int, "process_error": int}

    validation_error/wrong_part are counted by error_type (every
    resolved error is exactly one or the other). system_error/
    process_error are counted by resolution.chosen_option - an entry
    with no resolution (defensive only - see module docstring) is
    counted toward its error_type but skipped for the chosen_option
    tally, since there's nothing to tally there.
    """
    counts = {
        "validation_error": 0,
        "wrong_part": 0,
        "system_error": 0,
        "process_error": 0,
    }

    detections = doc.get("detections", {}) or {}
    for cam_id in ("cam1", "cam2"):
        cam_data = detections.get(cam_id, {}) or {}
        for kit_data in cam_data.values():
            errors = kit_data.get("errors", []) or []
            for err in errors:
                error_type = err.get("error_type")
                if error_type in ("validation_error", "wrong_part"):
                    counts[error_type] += 1

                resolution = err.get("resolution")
                if not resolution:
                    continue
                chosen = resolution.get("chosen_option")
                if chosen in ("system_error", "process_error"):
                    counts[chosen] += 1

    return counts


# ---------------------------------------------------------------------------
# Row shaping
# ---------------------------------------------------------------------------

def _camera_progress(doc, cam_id):
    """Returns {"completed": int, "quantity_required": int} for one
    camera - completed = current_kit_index_cam{N} - 1, since
    current_kit_index is 1-based and overshoots by exactly 1 once a
    camera finishes all its kits (confirmed display convention: a
    finished 70-unit run shows "70/70", not the raw stored "71/70")."""
    raw_index = doc.get(f"current_kit_index_{cam_id}", 1)
    quantity_required = doc.get("quantity_required", 0)
    completed = max(raw_index - 1, 0)
    return {"completed": completed, "quantity_required": quantity_required}


def _row_summary(doc):
    return {
        "id": str(doc["_id"]),
        "created_at": doc.get("created_at"),
        "table_id": doc.get("table_id"),
        "table_name": doc.get("table_name"),
        "kit_name": doc.get("kit_name"),
        "edp_number": doc.get("edp_number"),
        "order_number": doc.get("order_number"),
        "status": doc.get("status"),
        "cam1": _camera_progress(doc, "cam1"),
        "cam2": _camera_progress(doc, "cam2"),
        "errors": _tally_errors(doc),
    }


# ---------------------------------------------------------------------------
# Listing - filter + paginate
# ---------------------------------------------------------------------------

def list_history_activities(collection, table_id, date_from, date_to, page, per_page):
    """Returns (rows, total_count).

    table_id: int to filter to one table, or None for "All Tables".
    date_from/date_to: date objects (inclusive range), matched against
    created_at (the activity's START date - confirmed scope; NOT
    stopped_at/completed_at).
    page: 1-indexed. per_page: rows per page (already clamped by the
    caller via parse_per_page_param).

    Sorted by created_at descending (latest activity first, confirmed
    scope) - a currently-"live" activity is never in this collection at
    all (see module docstring), so no separate exclusion is needed here.
    """
    query = {"status": {"$in": list(HISTORY_STATUSES)}}

    if table_id is not None:
        query["table_id"] = table_id

    # created_at is stored as a UTC ISO string (see activities_data.
    # _now_iso), which sorts/compares correctly as a plain string
    # comparison for same-format ISO timestamps - but for a date-RANGE
    # match we build explicit inclusive UTC bounds and compare as
    # strings in the same ISO format, rather than parsing every
    # document's created_at in Python (keeps the filtering inside the
    # Mongo query itself, which also means it can be indexed later).
    range_start = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
    range_end = datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc)
    query["created_at"] = {
        "$gte": range_start.isoformat(),
        "$lte": range_end.isoformat(),
    }

    total_count = collection.count_documents(query)

    skip = (page - 1) * per_page
    docs = (
        collection.find(query)
        .sort("created_at", -1)
        .skip(skip)
        .limit(per_page)
    )

    rows = [_row_summary(d) for d in docs]
    return rows, total_count


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def delete_activity(collection, activity_id, images_base_dir=None, detection_image_dir=None):
    """Permanently deletes one activity_history document AND its entire
    saved-images folder on disk (both cameras, every kit index) - the
    two are deleted together since a history record with no way to
    view its images, or orphaned images with no record, are both
    useless (client's explicit ask: deleting the record should also
    clean up its images).

    images_base_dir/detection_image_dir are optional (default None) so
    this function still works standalone against just the DB (e.g. in
    a test that only cares about the Mongo side) - routes.py always
    passes real values in production. When given, the document is
    fetched FIRST (before deleting from Mongo) so its table_id/
    created_at/kit_name/order_number are available to rebuild the
    exact same folder path used at save time - see
    _activity_image_folder() below. The image folder is removed AFTER
    the Mongo delete succeeds, not before - if the Mongo delete fails
    for any reason, we don't want to have already destroyed images for
    a record that's still sitting in the database.

    Image-folder removal is BEST-EFFORT: an OSError while removing the
    folder (permissions, folder already gone, etc.) is caught and
    logged, not raised - the record's Mongo deletion has already
    succeeded by that point and should not be reported as a failure to
    the operator over a filesystem cleanup issue. This mirrors the
    project's existing philosophy of not hard-failing over save-side
    filesystem issues (see save_detection_image's own None-on-no-image
    behavior).

    Raises ValidationError if the id is malformed or doesn't match any
    document - routes.py turns this into a 400/404 JSON response,
    never a 500.
    """
    object_id = _to_object_id(activity_id, "activity id")

    doc = None
    if images_base_dir is not None and detection_image_dir is not None:
        doc = collection.find_one({"_id": object_id})

    result = collection.delete_one({"_id": object_id})
    if result.deleted_count == 0:
        raise ValidationError("Activity not found - it may have already been deleted.")

    if doc is not None:
        _delete_activity_images(doc, images_base_dir, detection_image_dir)


# ---------------------------------------------------------------------------
# Image-folder deletion helpers
#
# Duplicated here from cv_ingest/detection_data.py's sanitizer rather
# than imported (client's explicit instruction: keep History fully
# independent, no cross-blueprint import). Any change to the SAVE-side
# sanitization in detection_data.py must be mirrored here too, or a
# delete could target the wrong folder - flagged in both places.
# ---------------------------------------------------------------------------

_UNSAFE_PATH_CHARS = re.compile(r'[^A-Za-z0-9._-]+')


def _sanitize_path_segment(value, fallback="unknown"):
    """MUST stay in sync with cv_ingest/detection_data.py's own
    _sanitize_path_segment - same logic, duplicated per explicit
    instruction rather than imported."""
    value = str(value or "").strip()
    value = value.replace("..", "_")
    value = _UNSAFE_PATH_CHARS.sub("_", value)
    value = value.strip("_")
    return value or fallback


def _activity_image_folder(doc, images_base_dir, detection_image_dir):
    """Rebuilds the SAME folder path save_detection_image() would have
    written this activity's images under - everything up to (but not
    including) the cam1/cam2 split, i.e.
    <base_dir>/<detection_image_dir>/table_<id>/<date>/<kit_name>_<order_number>/
    Removing this one folder removes both cameras' images and every
    kit index in one shot, matching how the folder was structured for
    exactly this purpose.

    Returns None if table_id/created_at are missing/malformed on the
    document - defensive only (these are always set at activity
    creation), so deletion just skips the image-folder step rather
    than raising over a document that's already otherwise deletable.
    """
    table_id = doc.get("table_id")
    if table_id is None:
        return None

    created_at_raw = doc.get("created_at")
    try:
        activity_date = datetime.fromisoformat(created_at_raw).date().isoformat()
    except (TypeError, ValueError):
        return None

    kit_name_segment = _sanitize_path_segment(doc.get("kit_name"), "unknown-kit")
    order_number_segment = _sanitize_path_segment(doc.get("order_number"), "unknown-order")
    kit_folder = f"{kit_name_segment}_{order_number_segment}"

    return os.path.join(
        images_base_dir,
        detection_image_dir,
        f"table_{table_id}",
        activity_date,
        kit_folder,
    )


def _delete_activity_images(doc, images_base_dir, detection_image_dir):
    """Best-effort removal of the activity's whole image folder (see
    docstring on delete_activity for why this never raises)."""
    import logging

    folder_path = _activity_image_folder(doc, images_base_dir, detection_image_dir)
    if folder_path is None:
        return

    # Containment check before rmtree, same principle as the
    # detection-image serve route's traversal guard - never remove
    # anything outside the configured images root, even if a malformed
    # document somehow produced a path that resolved oddly.
    images_root = os.path.abspath(os.path.join(images_base_dir, detection_image_dir))
    resolved_path = os.path.abspath(folder_path)
    try:
        if os.path.commonpath([images_root, resolved_path]) != images_root:
            logging.getLogger(__name__).warning(
                "history: refusing to delete image folder outside images root: %s", resolved_path
            )
            return
    except ValueError:
        return

    if not os.path.isdir(resolved_path):
        # Nothing to clean up - activity may have had no images saved
        # at all, or the folder was already removed some other way.
        return

    try:
        shutil.rmtree(resolved_path)
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "history: failed to delete image folder %s: %s", resolved_path, exc
        )
