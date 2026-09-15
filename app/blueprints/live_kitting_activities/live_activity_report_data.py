"""
live_activity_report_data.py

Powers the monitor page's per-camera "History" button - a modal
showing that CAMERA's progress on the CURRENTLY RUNNING activity so
far: the same color-coded kit circle grid and Kit Detail drill-down
already built for the completed-activity History section, but reading
live_activity_details instead of activity_history, scoped to ONE
camera, and additionally showing the camera's CURRENT in-progress kit
(which activity_history never has, since history only ever contains
fully-finished activities).

DUPLICATED from history/history_data.py, not imported - same
independence convention already used twice elsewhere in this project
(history_data.py itself duplicates cv_ingest/detection_data.py's
sanitizer and validation-issue logic rather than importing). This is a
deliberate THIRD copy of the color/badge/timing derivation logic,
living here in live_kitting_activities instead of history, because:
  1. This project's established convention favors duplication over
     cross-blueprint imports for exactly this kind of shared-but-
     blueprint-scoped logic.
  2. Live and completed documents genuinely differ in one meaningful
     way (an in-progress kit with no validated_at yet, which history
     never has to handle) - keeping this copy separate means that
     difference doesn't have to be threaded as a flag through the
     history-side code.

If the underlying detection_data.py logic this mirrors
(_find_validation_issues, event "outcome" tagging, error schema) ever
changes, check ALL THREE copies (cv_ingest/detection_data.py itself,
history/history_data.py, and this file) - flagged here on purpose,
same as the other two files' own cross-reference comments.
"""

from datetime import datetime, timezone

CAM_IDS = ("cam1", "cam2")

ISSUE_MISSING = "missing"
ISSUE_UNDERCOUNT = "undercount"
ISSUE_OVERCOUNT = "overcount"

CARD_COLOR_RED = "red"
CARD_COLOR_PURPLE = "purple"
CARD_COLOR_YELLOW = "yellow"
CARD_COLOR_GREEN = "green"
CARD_COLOR_IN_PROGRESS = "in_progress"  # NEW - live-only state, never
# appears in the completed-activity History section, since a document
# only ever reaches activity_history once every kit is finished.


class ValidationError(Exception):
    pass


# ---------------------------------------------------------------------------
# Small helpers - duplicated verbatim from history/history_data.py /
# cv_ingest/detection_data.py
# ---------------------------------------------------------------------------

def _get_part_count(doc, cam_id, kit_index, part_name):
    return (
        doc.get(f"part_counts_{cam_id}", {})
        .get(str(kit_index), {})
        .get(part_name, 0)
    )


def _neglected_part_names(doc, cam_id):
    return {
        p.get("part_name")
        for p in doc.get("neglect_parts", [])
        if p.get("camera") == cam_id
    }


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
    kit_data = doc.get("detections", {}).get(cam_id, {}).get(str(kit_index), {})
    events = kit_data.get("events", []) or []
    return [e for e in events if e.get("outcome") == "wrong_part"]


def _logged_errors_for_kit(doc, cam_id, kit_index):
    kit_data = doc.get("detections", {}).get(cam_id, {}).get(str(kit_index), {})
    return kit_data.get("errors", []) or []


def _issue_matches_logged(issue, logged_errors):
    part_name = issue.get("part_name")
    issue_type = issue.get("issue")
    for err in logged_errors:
        for logged_issue in err.get("issues", []) or []:
            if logged_issue.get("part_name") == part_name and logged_issue.get("issue") == issue_type:
                return True
    return False


def _has_logged_wrong_part_error(logged_errors):
    return any(err.get("error_type") == "wrong_part" for err in logged_errors)


def _iso_diff_seconds(later_iso, earlier_iso):
    if not later_iso or not earlier_iso:
        return None
    try:
        later = datetime.fromisoformat(later_iso)
        earlier = datetime.fromisoformat(earlier_iso)
    except (TypeError, ValueError):
        return None
    return (later - earlier).total_seconds()


def _kit_timing(doc, cam_id, kit_index):
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


def _chip_badge_label(logged_errors):
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


def _events_for_part(doc, cam_id, kit_index, part_name):
    kit_data = doc.get("detections", {}).get(cam_id, {}).get(str(kit_index), {})
    events = kit_data.get("events", []) or []
    return [e for e in events if e.get("detected_part") == part_name]


def _image_url(image_path):
    if not image_path:
        return None
    return f"/api/detection-image/{image_path}"


def _part_card_color(found, required, is_logged):
    if found == required:
        return CARD_COLOR_GREEN
    if is_logged:
        return CARD_COLOR_RED
    if found == 0 or found > required:
        return CARD_COLOR_PURPLE
    return CARD_COLOR_YELLOW


# ---------------------------------------------------------------------------
# Kit card - one FINISHED kit (has a validated_at). Identical logic to
# history_data.py's _kit_camera_card - see that file for the full
# reasoning writeup on the color/badge rule.
# ---------------------------------------------------------------------------

def _finished_kit_card(doc, cam_id, kit_index):
    logged_errors = _logged_errors_for_kit(doc, cam_id, kit_index)
    all_issues = _validation_issues_switch_independent(doc, cam_id, kit_index)
    wrong_part_events = _wrong_part_events(doc, cam_id, kit_index)

    badges = []
    has_purple_condition = False
    has_yellow_condition = False

    for err in logged_errors:
        resolution = err.get("resolution") or {}
        badges.append({
            "kind": "logged",
            "error_type": err.get("error_type"),
            "chosen_option": resolution.get("chosen_option"),
            "issues": err.get("issues", []),
        })

    for issue in all_issues:
        if _issue_matches_logged(issue, logged_errors):
            continue
        if issue["issue"] == ISSUE_UNDERCOUNT:
            has_yellow_condition = True
            badges.append({"kind": "silent_undercount", "part_name": issue["part_name"],
                            "required": issue["required"], "found": issue["found"]})
        else:
            has_purple_condition = True
            badges.append({"kind": "silent_validation", "issue_type": issue["issue"],
                            "part_name": issue["part_name"],
                            "required": issue["required"], "found": issue["found"]})

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


def _in_progress_kit_card(cam_id, kit_index):
    """The camera's CURRENT kit - no validated_at yet, so none of the
    color/badge logic above applies (it all keys off a finished kit's
    complete data). Shown as a distinct 5th state so an operator can
    see at a glance which kit is actively being worked, without it
    being misleadingly colored green/red before it's actually done."""
    return {
        "cam_id": cam_id,
        "kit_index": kit_index,
        "color": CARD_COLOR_IN_PROGRESS,
        "badges": [],
        "chip_badge": None,
        "total_kit_time_sec": None,
        "active_time_sec": None,
        "avg_detection_gap_sec": None,
    }


def _all_kit_indices(doc, cam_id):
    cam_data = doc.get("detections", {}).get(cam_id, {}) or {}
    return sorted((int(k) for k in cam_data.keys()), key=int)


# ---------------------------------------------------------------------------
# Summary aggregation - ONLY over finished kits (an in-progress kit has
# no timing/error data to contribute either way).
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


def _build_camera_summary(cards):
    """Single-camera version of history_data.py's _build_summary - one
    scope only (no activity-wide rollup needed, since this whole view
    is already scoped to one camera)."""
    error_counts = {"validation_error": 0, "wrong_part": 0, "system_error": 0, "process_error": 0}
    total_kit_times = []
    active_times = []

    for card in cards:
        for badge in card["badges"]:
            if badge["kind"] != "logged":
                continue
            error_type = badge.get("error_type")
            if error_type in ("validation_error", "wrong_part"):
                error_counts[error_type] += 1
            chosen = badge.get("chosen_option")
            if chosen == "system_error":
                error_counts["system_error"] += 1
            elif chosen == "process_error":
                error_counts["process_error"] += 1

        if card["total_kit_time_sec"] is not None:
            total_kit_times.append(card["total_kit_time_sec"])
        if card["active_time_sec"] is not None:
            active_times.append(card["active_time_sec"])

    return {
        "error_counts": error_counts,
        "timing": {
            "total_kit_time": _aggregate_timing(total_kit_times),
            "active_time": _aggregate_timing(active_times),
        },
    }


# ---------------------------------------------------------------------------
# Top-level assemblers
# ---------------------------------------------------------------------------

def build_live_camera_report(doc, cam_id):
    """The per-camera modal's full content: header, summary (finished
    kits only), and the circle grid INCLUDING the current in-progress
    kit as its own distinct-colored card at the end."""
    current_index = doc.get(f"current_kit_index_{cam_id}", 1)

    finished_indices = [k for k in _all_kit_indices(doc, cam_id) if k < current_index]
    cards = [_finished_kit_card(doc, cam_id, k) for k in finished_indices]

    quantity_required = doc.get("quantity_required")
    camera_completed = quantity_required is not None and current_index > quantity_required
    if not camera_completed:
        cards.append(_in_progress_kit_card(cam_id, current_index))

    header = {
        "cam_id": cam_id,
        "table_id": doc.get("table_id"),
        "table_name": doc.get("table_name"),
        "kit_name": doc.get("kit_name"),
        "edp_number": doc.get("edp_number"),
        "order_number": doc.get("order_number"),
        "quantity_required": quantity_required,
        "current_kit_index": current_index,
        "camera_completed": camera_completed,
    }

    summary = _build_camera_summary([c for c in cards if c["color"] != CARD_COLOR_IN_PROGRESS])

    return {"header": header, "summary": summary, "cards": cards}


def build_live_kit_detail(doc, cam_id, kit_index):
    """Same shape as history_data.py's build_kit_detail, but works for
    EITHER a finished kit OR the current in-progress kit (which simply
    has no validated_at yet - every helper above already tolerates
    None timing gracefully, so no special-casing is needed here beyond
    what's already defensive in _kit_timing/_avg_detection_gap_seconds)."""
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
        else:
            issues_to_show = [i for i in all_issues if not _issue_matches_logged(i, logged_errors)]
            resolution = None
            image_url = None

        anomalies_section = {
            "is_logged": validation_error is not None,
            "issues": issues_to_show,
            "resolution": resolution,
            "image_url": image_url,
        }

    part_cards = []
    for part in doc.get("parts_configured", []):
        if part.get("camera") != cam_id:
            continue

        part_name = part.get("part_name")
        required = part.get("quantity_required", 0)
        found = _get_part_count(doc, cam_id, kit_index, part_name)

        matching_issue = next((i for i in all_issues if i["part_name"] == part_name), None)
        is_logged = matching_issue is not None and _issue_matches_logged(matching_issue, logged_errors)

        color = _part_card_color(found, required, is_logged)

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
