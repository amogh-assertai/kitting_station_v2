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


# ---------------------------------------------------------------------------
# Activity Report - kit-level detail/analytics page (NEW this round)
#
# Reads a SINGLE already-fetched activity_history document (frozen -
# nothing here mutates or writes anything back) and derives a full
# report: header fields, activity/camera-level summary stats, and one
# "card" per (camera, kit_index) pair that ever had data.
#
# CORE INSIGHT the whole design rests on (confirmed by reading
# cv_ingest/detection_data.py directly, not assumed):
#
#   detections.<cam>.<kit_index>.errors only EVER gets an entry via
#   resolve_error(), and resolve_error() only ever runs on an error that
#   was raised in the first place because the relevant alert switch
#   (alert_validation_error / alert_wrong_part_error) was ON at the
#   moment the issue occurred. There is exactly one write path into
#   that array, always switch-gated. This means presence/absence of a
#   logged error entry is a COMPLETE, sufficient signal for "was the
#   alert on or off" - this module never reads camerawise_alert_config
#   itself, and does not need to.
#
#   Meanwhile, detections.<cam>.<kit_index>.events always tags every
#   detection with "outcome": "matched"|"neglected"|"wrong_part"
#   REGARDLESS of whether the wrong_part alert was on (see
#   cv_ingest/detection_data.py's own comment: "a switch-off wrong_part
#   is still tagged wrong_part here... even though it visually plays
#   green"). And part_counts_cam{N} / parts_configured are always
#   present and complete, letting missing/undercount/overcount be
#   recomputed from raw data independent of whether alert_validation_error
#   was on when it happened.
#
#   So: recompute what SHOULD have been flagged from raw data, compare
#   against what WAS actually logged (which only exists if the switch
#   was on) - anything in the "should have" set not covered by the
#   "was logged" set is exactly the silent/alert-off case. No need to
#   read the switches directly at all.
#
# Everything below is DUPLICATED from cv_ingest/detection_data.py, not
# imported - per this project's explicit "History stays fully
# independent, duplicate rather than import" convention (see this
# file's own sanitizer note above for the same pattern). Any change to
# the corresponding logic in detection_data.py (especially
# _find_validation_issues, get_part_count, or the "outcome" tagging on
# events) should be checked against this file too - flagged here on
# purpose, same as the image-path sanitizer caveat.
# ---------------------------------------------------------------------------

CAM_IDS = ("cam1", "cam2")

ISSUE_MISSING = "missing"
ISSUE_UNDERCOUNT = "undercount"
ISSUE_OVERCOUNT = "overcount"
ISSUE_UNRECOGNIZED = "unrecognized"  # wrong-part's own issue tag, matches detection_data.py exactly

CARD_COLOR_RED = "red"
CARD_COLOR_PURPLE = "purple"
CARD_COLOR_YELLOW = "yellow"
CARD_COLOR_GREEN = "green"


def get_activity_by_id(collection, activity_id):
    """Fetches one activity_history document by id, or None. Raises
    ValidationError on a malformed id - same convention as
    delete_activity - so routes.py can turn that into a 400/404, never
    a 500."""
    object_id = _to_object_id(activity_id, "activity id")
    return collection.find_one({"_id": object_id})


# ---------------------------------------------------------------------------
# Small path/field helpers - duplicated verbatim from
# cv_ingest/detection_data.py (trivial one-liners, kept in sync by hand)
# ---------------------------------------------------------------------------

def _kit_index_field(cam_id):
    return f"current_kit_index_{cam_id}"


def _get_part_count(doc, cam_id, kit_index, part_name):
    """DUPLICATED from cv_ingest/detection_data.py's get_part_count() -
    reads the same fast-path counter, off a frozen history document
    instead of a live one (identical shape, no live-mutation dependency
    either way)."""
    return (
        doc.get(f"part_counts_{cam_id}", {})
        .get(str(kit_index), {})
        .get(part_name, 0)
    )


def _neglected_part_names(doc, cam_id):
    """DUPLICATED from cv_ingest/detection_data.py's
    _neglected_part_names() - camera-scoped neglect list, so a
    neglected-on-cam1 part detected on cam2 is still a genuine
    wrong_part there."""
    return {
        p.get("part_name")
        for p in doc.get("neglect_parts", [])
        if p.get("camera") == cam_id
    }


# ---------------------------------------------------------------------------
# Switch-independent issue recomputation - DUPLICATED from
# cv_ingest/detection_data.py's _find_validation_issues(), same logic,
# unchanged: computes missing/undercount/overcount from raw
# parts_configured + part_counts, regardless of whether
# alert_validation_error was on when this kit actually ran.
# ---------------------------------------------------------------------------

def _validation_issues_switch_independent(doc, cam_id, kit_index):
    issues = []
    for part in doc.get("parts_configured", []):
        if part.get("camera") != cam_id:
            continue

        part_name = part.get("part_name")
        required = part.get("quantity_required", 0)
        found = _get_part_count(doc, cam_id, kit_index, part_name)

        if part.get("alert_missing") and found == 0:
            issues.append({"part_name": part_name, "issue": ISSUE_MISSING, "required": required, "found": found})
        elif part.get("alert_undercount") and 0 < found < required:
            issues.append({"part_name": part_name, "issue": ISSUE_UNDERCOUNT, "required": required, "found": found})
        elif part.get("alert_overcount") and found > required:
            issues.append({"part_name": part_name, "issue": ISSUE_OVERCOUNT, "required": required, "found": found})

    return issues


def _wrong_part_events(doc, cam_id, kit_index):
    """Every detection event in this kit tagged outcome == "wrong_part"
    - present regardless of whether alert_wrong_part_error was on (see
    module docstring above). Neglected-part detections are tagged
    "neglected", not "wrong_part", so they're automatically excluded
    here without any extra filtering - the tag itself already respects
    the neglect list at write time."""
    kit_data = doc.get("detections", {}).get(cam_id, {}).get(str(kit_index), {})
    events = kit_data.get("events", []) or []
    return [e for e in events if e.get("outcome") == "wrong_part"]


def _logged_errors_for_kit(doc, cam_id, kit_index):
    """detections.<cam>.<kit_index>.errors, as-is - every entry here
    exists ONLY because the relevant alert switch was on when it
    happened (see module docstring's core insight)."""
    kit_data = doc.get("detections", {}).get(cam_id, {}).get(str(kit_index), {})
    return kit_data.get("errors", []) or []


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

def _iso_diff_seconds(later_iso, earlier_iso):
    """later - earlier, in seconds. Returns None if either timestamp is
    missing/malformed - callers treat None as "not computable" (e.g. a
    kit with no detections yet has no first_part_detected_time), never
    as zero."""
    if not later_iso or not earlier_iso:
        return None
    try:
        later = datetime.fromisoformat(later_iso)
        earlier = datetime.fromisoformat(earlier_iso)
    except (TypeError, ValueError):
        return None
    return (later - earlier).total_seconds()


def _kit_timing(doc, cam_id, kit_index):
    """Total Kit Time and Active Time both come from timestamps stored
    on THIS SAME kit index's own timing record - confirmed against
    cv_ingest/detection_data.py directly: actual_kit_start_time for kit
    N is stamped either at activity creation (kit 1) or at the moment
    kit N-1 was validated (kit 2+), but EITHER WAY it's written onto
    kit N's own record at that moment - there is no cross-kit lookup
    needed here, deliberately verified before building this rather than
    assumed.

    Total Kit Time = validated_at - actual_kit_start_time (this kit)
    Active Time     = validated_at - first_part_detected_time (this kit)

    Both are None if this kit was never validated (e.g. the last kit on
    a manually-stopped activity, mid-progress) - a card for an
    unvalidated kit shows blank/dash timing rather than a misleading
    zero or a crash.
    """
    timing = (
        doc.get("detections", {})
        .get(cam_id, {})
        .get(str(kit_index), {})
        .get("timing", {})
        or {}
    )
    validated_at = timing.get("validated_at")
    start_time = timing.get("actual_kit_start_time")
    first_detected = timing.get("first_part_detected_time")

    return {
        "total_kit_time_sec": _iso_diff_seconds(validated_at, start_time),
        "active_time_sec": _iso_diff_seconds(validated_at, first_detected),
    }


def _avg_detection_gap_seconds(doc, cam_id, kit_index):
    """Mean gap between consecutive detection events (by created_at),
    within this one kit index only - never averaged across kit
    boundaries. Returns None with fewer than 2 events (no gap to
    measure)."""
    kit_data = doc.get("detections", {}).get(cam_id, {}).get(str(kit_index), {})
    events = kit_data.get("events", []) or []

    timestamps = []
    for e in events:
        created_at = e.get("created_at")
        if not created_at:
            continue
        try:
            timestamps.append(datetime.fromisoformat(created_at))
        except (TypeError, ValueError):
            continue

    if len(timestamps) < 2:
        return None

    timestamps.sort()
    gaps = [
        (timestamps[i] - timestamps[i - 1]).total_seconds()
        for i in range(1, len(timestamps))
    ]
    return sum(gaps) / len(gaps)


# ---------------------------------------------------------------------------
# Per-kit-per-camera card - the core derivation
# ---------------------------------------------------------------------------

def _issue_matches_logged(issue, logged_errors):
    """True if this specific (part_name, issue type) pair is covered by
    ANY logged error's own "issues" list for this kit - i.e. the alert
    fired for this exact problem. Matched on (part_name, issue) since
    that's the pair _find_validation_issues() itself keys on, and it's
    exactly what a logged validation_error's own "issues" list contains
    verbatim (resolve_error() stores the SAME issues list that was
    computed at raise-time, unchanged) - confirmed by reading
    detection_data.py's validate_kit directly, not assumed."""
    part_name = issue.get("part_name")
    issue_type = issue.get("issue")
    for err in logged_errors:
        for logged_issue in err.get("issues", []) or []:
            if logged_issue.get("part_name") == part_name and logged_issue.get("issue") == issue_type:
                return True
    return False


def _has_logged_wrong_part_error(logged_errors):
    """True if a wrong_part-type logged error exists for this kit at
    all. Unlike validation issues (matched per-part), wrong_part errors
    aren't matched per-event here - client's own confirmed data model
    only ever raises/logs ONE active wrong_part error at a time per
    kit+camera (the camera locks immediately on the first occurrence,
    per detection_data.py's should_raise_wrong_part path), so "does a
    wrong_part error exist for this kit" is the meaningful question, not
    "does THIS specific event have its own logged twin"."""
    return any(err.get("error_type") == "wrong_part" for err in logged_errors)


def _kit_camera_card(doc, cam_id, kit_index):
    """Builds one card's full data: color, every badge (logged AND
    silent), and the three timing numbers. This is the one function
    that implements the whole color/badge rule confirmed with the
    client:

      RED    - >=1 logged error exists (either type) - alert was on,
               fired, operator resolved it as system_error/process_error.
      PURPLE - no logged error, but a silent wrong_part occurred, OR a
               silent missing/overcount validation issue occurred
               (alert was off for that specific thing).
      YELLOW - no logged error, but a silent UNDERCOUNT occurred.
      GREEN  - none of the above.

    Border color precedence: RED > PURPLE > YELLOW > GREEN (confirmed -
    purple wins over yellow when a kit has both a silent undercount AND
    a silent wrong-part/missing/overcount at once, since the client
    judged wrong-part/validation-type silent issues more severe than
    pure undercount).

    Badges are independent of the border color - every distinct issue
    found (logged or silent) gets its own badge, so a purple-bordered
    card can still show a yellow-tagged undercount badge alongside its
    purple badge(s).
    """
    logged_errors = _logged_errors_for_kit(doc, cam_id, kit_index)
    all_issues = _validation_issues_switch_independent(doc, cam_id, kit_index)
    wrong_part_events = _wrong_part_events(doc, cam_id, kit_index)

    badges = []
    has_purple_condition = False
    has_yellow_condition = False

    # Logged errors -> one badge each, tagged with resolution
    for err in logged_errors:
        resolution = err.get("resolution") or {}
        badges.append({
            "kind": "logged",
            "error_type": err.get("error_type"),
            "chosen_option": resolution.get("chosen_option"),
            "issues": err.get("issues", []),
        })

    # Silent validation-type issues (missing/undercount/overcount) not
    # covered by any logged error
    for issue in all_issues:
        if _issue_matches_logged(issue, logged_errors):
            continue
        if issue["issue"] == ISSUE_UNDERCOUNT:
            has_yellow_condition = True
            badges.append({"kind": "silent_undercount", "part_name": issue["part_name"],
                            "required": issue["required"], "found": issue["found"]})
        else:  # missing or overcount
            has_purple_condition = True
            badges.append({"kind": "silent_validation", "issue_type": issue["issue"],
                            "part_name": issue["part_name"],
                            "required": issue["required"], "found": issue["found"]})

    # Silent wrong-part - only relevant if NO wrong_part error is
    # already logged for this kit (if one is, it's already covered by
    # the "logged" badges above, and re-flagging every individual event
    # as ALSO silent would double-count against a single resolved error).
    if wrong_part_events and not _has_logged_wrong_part_error(logged_errors):
        has_purple_condition = True
        badges.append({
            "kind": "silent_wrong_part",
            "count": len(wrong_part_events),
            "part_names": sorted({e.get("detected_part") for e in wrong_part_events if e.get("detected_part")}),
        })

    if logged_errors:
        color = CARD_COLOR_RED
    elif has_purple_condition:
        color = CARD_COLOR_PURPLE
    elif has_yellow_condition:
        color = CARD_COLOR_YELLOW
    else:
        color = CARD_COLOR_GREEN

    timing = _kit_timing(doc, cam_id, kit_index)

    return {
        "cam_id": cam_id,
        "kit_index": kit_index,
        "color": color,
        "badges": badges,
        "chip_badge": _chip_badge_label(logged_errors),
        "total_kit_time_sec": timing["total_kit_time_sec"],
        "active_time_sec": timing["active_time_sec"],
        "avg_detection_gap_sec": _avg_detection_gap_seconds(doc, cam_id, kit_index),
    }


def _chip_badge_label(logged_errors):
    """Derives the small hanging S/P badge label shown on the kit
    circle (NEW - circle-grid redesign). Only ever computed from LOGGED
    errors - silent issues have no resolution/chosen_option to count,
    so purple/yellow/green circles never get this badge (confirmed
    scope).

    Rule (confirmed with client):
      - 0 logged errors -> None (no badge at all - circle isn't red).
      - Exactly 1 logged error -> just the single letter ("S" or "P"),
        no "+N" suffix.
      - 2+ logged errors -> "P" wins the DISPLAYED letter whenever at
        least one process_error resolution exists among them (even if
        outnumbered by system_error), count shown is total_logged - 1
        (client's exact example: 2 system + 1 process -> "P+2", i.e.
        total=3, minus the one already represented by the letter
        itself = +2). If none are process (all system, or a logged
        error somehow has no resolution at all - defensive only, see
        module docstring on this never actually happening), the letter
        is "S".
    """
    total = len(logged_errors)
    if total == 0:
        return None

    has_process = any(
        (err.get("resolution") or {}).get("chosen_option") == "process_error"
        for err in logged_errors
    )
    letter = "P" if has_process else "S"

    if total == 1:
        return letter

    return f"{letter}+{total - 1}"


def _all_kit_indices(doc, cam_id):
    """Every kit_index that has a record under detections.<cam>, sorted
    numerically (Mongo stores the key as a string - see
    cv_ingest/detection_data.py's own note on this: "this module always
    re-casts with str(kit_index) on read")."""
    cam_data = doc.get("detections", {}).get(cam_id, {}) or {}
    return sorted((int(k) for k in cam_data.keys()), key=int)


# ---------------------------------------------------------------------------
# Summary aggregation
# ---------------------------------------------------------------------------

def _empty_timing_stats():
    return {"avg_sec": None, "min_sec": None, "max_sec": None}


def _aggregate_timing(values):
    values = [v for v in values if v is not None]
    if not values:
        return _empty_timing_stats()
    return {
        "avg_sec": sum(values) / len(values),
        "min_sec": min(values),
        "max_sec": max(values),
    }


def _build_summary(cards):
    """Aggregates across ALL cards (both cameras) for activity-wide
    stats, and separately per camera - both views requested by the
    client ("cam-wise and activity wise")."""
    summary = {
        "error_counts": {
            "total": 0,
            "by_camera": {"cam1": {"validation_error": 0, "wrong_part": 0},
                           "cam2": {"validation_error": 0, "wrong_part": 0}},
            "system_error": 0,
            "process_error": 0,
        },
        "timing": {
            "activity": {"total_kit_time": _empty_timing_stats(), "active_time": _empty_timing_stats()},
            "cam1": {"total_kit_time": _empty_timing_stats(), "active_time": _empty_timing_stats()},
            "cam2": {"total_kit_time": _empty_timing_stats(), "active_time": _empty_timing_stats()},
        },
    }

    total_kit_times = {"cam1": [], "cam2": [], "activity": []}
    active_times = {"cam1": [], "cam2": [], "activity": []}

    for card in cards:
        cam_id = card["cam_id"]

        for badge in card["badges"]:
            if badge["kind"] != "logged":
                continue
            error_type = badge.get("error_type")
            if error_type in ("validation_error", "wrong_part"):
                summary["error_counts"]["total"] += 1
                summary["error_counts"]["by_camera"][cam_id][error_type] += 1
            chosen = badge.get("chosen_option")
            if chosen == "system_error":
                summary["error_counts"]["system_error"] += 1
            elif chosen == "process_error":
                summary["error_counts"]["process_error"] += 1

        if card["total_kit_time_sec"] is not None:
            total_kit_times[cam_id].append(card["total_kit_time_sec"])
            total_kit_times["activity"].append(card["total_kit_time_sec"])
        if card["active_time_sec"] is not None:
            active_times[cam_id].append(card["active_time_sec"])
            active_times["activity"].append(card["active_time_sec"])

    for scope in ("activity", "cam1", "cam2"):
        summary["timing"][scope]["total_kit_time"] = _aggregate_timing(total_kit_times[scope])
        summary["timing"][scope]["active_time"] = _aggregate_timing(active_times[scope])

    return summary


# ---------------------------------------------------------------------------
# Top-level assembler
# ---------------------------------------------------------------------------

def build_activity_report(doc):
    """Builds the full Activity Report from one activity_history
    document - no additional DB queries, everything needed is already
    embedded on this one document (same "one find_one, complete
    picture" principle used throughout this codebase)."""
    header = {
        "id": str(doc["_id"]),
        "created_at": doc.get("created_at"),
        "stopped_at": doc.get("stopped_at"),
        "table_id": doc.get("table_id"),
        "table_name": doc.get("table_name"),
        "kit_name": doc.get("kit_name"),
        "edp_number": doc.get("edp_number"),
        "order_number": doc.get("order_number"),
        "quantity_required": doc.get("quantity_required"),
        "status": doc.get("status"),
        "stop_reason": doc.get("stop_reason"),
    }

    cards = []
    for cam_id in CAM_IDS:
        for kit_index in _all_kit_indices(doc, cam_id):
            cards.append(_kit_camera_card(doc, cam_id, kit_index))

    summary = _build_summary(cards)

    return {
        "activity": header,
        "summary": summary,
        "cards": cards,
    }


# ---------------------------------------------------------------------------
# Kit detail - single kit, single camera drill-down (NEW this round)
#
# Reached by clicking a circle on the Activity Report. Same "one
# find_one, complete picture" principle - everything needed is already
# on the activity_history document; no extra queries.
#
# Confirmed section order (client): Header -> Analytics -> Wrong-Part
# section (if any) -> Errors & Anomalies (if any, i.e. logged
# validation_error OR silent validation-type issues) -> per-part cards.
# ---------------------------------------------------------------------------

def _image_url(image_path):
    """Builds the URL for a saved detection frame, matching
    cv_ingest/routes.py's own string-interpolation convention exactly
    (not url_for - this is a different blueprint, and the route is a
    fixed, known path: /api/detection-image/<path:subpath>). Returns
    None if there's no image_path to build from - callers render "no
    image" rather than a broken <img> tag."""
    if not image_path:
        return None
    return f"/api/detection-image/{image_path}"


def _part_card_color(found, required, alert_missing, alert_undercount, alert_overcount, is_logged):
    """Same 4-state rule as the kit circle, applied at the PART level
    instead of the whole-kit level - a part's own card is red if ITS
    specific issue was logged, purple/yellow if silent, green if clean.
    "is_logged" is whether this exact part+issue pair is covered by a
    logged error's own issues list (see _issue_matches_logged) -
    reused here at the part level rather than only the kit level."""
    if found == required:
        return CARD_COLOR_GREEN
    if is_logged:
        return CARD_COLOR_RED
    if found == 0 or found > required:
        return CARD_COLOR_PURPLE  # missing or overcount, silent
    return CARD_COLOR_YELLOW  # undercount, silent


def _events_for_part(doc, cam_id, kit_index, part_name):
    """Every detection event tagged with this exact part_name - both
    "matched" outcomes (the normal case) and any "wrong_part" outcome
    that happens to share this part_name (shouldn't normally overlap
    with a configured part_name, but included defensively rather than
    assumed impossible)."""
    kit_data = doc.get("detections", {}).get(cam_id, {}).get(str(kit_index), {})
    events = kit_data.get("events", []) or []
    return [e for e in events if e.get("detected_part") == part_name]


def build_kit_detail(doc, cam_id, kit_index):
    """Assembles the full kit-detail view for one (camera, kit_index)
    pair on this activity. Raises ValidationError if this kit_index has
    no record at all for this camera (bad url / stale link) - routes.py
    turns this into a 404, never a 500."""
    kit_data = doc.get("detections", {}).get(cam_id, {}).get(str(kit_index))
    if kit_data is None:
        raise ValidationError(f"No data recorded for {cam_id} kit {kit_index} on this activity.")

    logged_errors = _logged_errors_for_kit(doc, cam_id, kit_index)
    all_issues = _validation_issues_switch_independent(doc, cam_id, kit_index)
    wrong_part_events = _wrong_part_events(doc, cam_id, kit_index)
    timing = _kit_timing(doc, cam_id, kit_index)

    header = {
        "cam_id": cam_id,
        "kit_index": kit_index,
        "table_id": doc.get("table_id"),
        "table_name": doc.get("table_name"),
        "kit_name": doc.get("kit_name"),
        "edp_number": doc.get("edp_number"),
        "order_number": doc.get("order_number"),
    }

    analytics = {
        "total_kit_time_sec": timing["total_kit_time_sec"],
        "active_time_sec": timing["active_time_sec"],
        "avg_detection_gap_sec": _avg_detection_gap_seconds(doc, cam_id, kit_index),
    }

    # Wrong-part section - one entry per DISTINCT detected_part among
    # wrong_part-outcome events (grouped, not one row per raw event -
    # client's own established convention elsewhere in this app groups
    # repeat detections of the same unrecognized part). Each entry
    # carries every image for that part_name, its own resolution if a
    # wrong_part error was logged for this kit (there is at most one
    # active wrong_part error per kit+camera - see
    # cv_ingest/detection_data.py's own confirmed model).
    wrong_part_error = next((e for e in logged_errors if e.get("error_type") == "wrong_part"), None)
    wrong_part_groups = {}
    for event in wrong_part_events:
        name = event.get("detected_part")
        wrong_part_groups.setdefault(name, []).append(event)

    wrong_part_section = []
    for part_name, events in wrong_part_groups.items():
        wrong_part_section.append({
            "part_name": part_name,
            "is_logged": wrong_part_error is not None,
            "resolution": (wrong_part_error or {}).get("resolution"),
            "images": [
                {"url": _image_url(e.get("image_path")), "detected_at": e.get("created_at")}
                for e in sorted(events, key=lambda e: e.get("created_at") or "")
                if e.get("image_path")
            ],
        })

    # Errors & Anomalies - the validation-type issues (missing/
    # undercount/overcount), logged or silent, EXCLUDING undercount from
    # this red section per the established color rule (undercount alone,
    # silent, is yellow-tier, not red/purple) - but a LOGGED validation
    # error covers whatever issues it was raised for regardless of type,
    # so a logged undercount still appears here as part of that entry.
    validation_error = next((e for e in logged_errors if e.get("error_type") == "validation_error"), None)
    anomalies_section = None
    if validation_error or any(
        issue["issue"] in (ISSUE_MISSING, ISSUE_OVERCOUNT) for issue in all_issues
    ) or any(
        issue["issue"] == ISSUE_UNDERCOUNT and not _issue_matches_logged(issue, logged_errors)
        for issue in all_issues
    ):
        if validation_error:
            issues_to_show = validation_error.get("issues", [])
            resolution = validation_error.get("resolution")
            image_url = _image_url(validation_error.get("image_path"))
            detected_at = validation_error.get("detected_at")
        else:
            # Silent-only case - no logged error exists, but raw data
            # shows a real issue anyway (alert was off). No resolution,
            # no dedicated error image (none was ever captured, since
            # no red-screen ever fired for this).
            issues_to_show = [i for i in all_issues if not _issue_matches_logged(i, logged_errors)]
            resolution = None
            image_url = None
            detected_at = None

        anomalies_section = {
            "is_logged": validation_error is not None,
            "issues": issues_to_show,
            "resolution": resolution,
            "image_url": image_url,
            "detected_at": detected_at,
        }

    # Per-part cards - one per part_configured on this camera (client's
    # own confirmed source of truth for what a kit is supposed to
    # contain), each with every one of its own detection-event images.
    part_cards = []
    for part in doc.get("parts_configured", []):
        if part.get("camera") != cam_id:
            continue

        part_name = part.get("part_name")
        required = part.get("quantity_required", 0)
        found = _get_part_count(doc, cam_id, kit_index, part_name)

        matching_issue = next(
            (i for i in all_issues if i["part_name"] == part_name), None
        )
        is_logged = matching_issue is not None and _issue_matches_logged(matching_issue, logged_errors)

        color = _part_card_color(
            found, required,
            part.get("alert_missing"), part.get("alert_undercount"), part.get("alert_overcount"),
            is_logged,
        )

        events = _events_for_part(doc, cam_id, kit_index, part_name)
        images = [
            {"url": _image_url(e.get("image_path")), "detected_at": e.get("created_at")}
            for e in sorted(events, key=lambda e: e.get("created_at") or "")
            if e.get("image_path")
        ]

        part_cards.append({
            "part_name": part_name,
            "required": required,
            "found": found,
            "color": color,
            "images": images,
        })

    return {
        "header": header,
        "analytics": analytics,
        "wrong_part_section": wrong_part_section,
        "anomalies_section": anomalies_section,
        "part_cards": part_cards,
    }
