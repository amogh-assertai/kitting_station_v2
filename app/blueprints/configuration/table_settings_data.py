"""
Table Settings - MongoDB data access + validation for the
`table_configuration` collection.

One document per table (keyed by table_id, not table name - see
`configuration.tables` in config.yaml). Mirrors the current_kits_data.py
separation: no Mongo queries happen in routes.py directly, and file I/O
for the audio uploads stays in routes.py (routes.py needs current_app for
BASE_DIR/settings, same as it already does for PQPR).

Document shape:
{
  "table_id": int,
  "audio_settings": {
    "camera_1_green": {
      "original_filename": str,
      "stored_filename": str,
      "uploaded_at": iso str,
      "default_enabled": bool,
    },
    "camera_1_red": {...},
    "camera_2_green": {...},
    "camera_2_red": {...},
  },
  "expected_client_ips": [str, ...],
  "created_at": iso str,
  "updated_at": iso str,
}

Audio save is deferred (client decision): file uploads and the
enabled/disabled defaults are only persisted together when the page's
"Save Audio Settings" button is clicked - not on file selection. Expected
Client IPs are staged client-side and committed as one atomic list via
"Save IP List" - free text, no format validation (client's explicit
choice).
"""

from datetime import datetime, timezone

# Fixed set of audio slots - same pattern as ALLOWED_CAMERAS in
# current_kits_data.py (a stable enum, not client source data whose shape
# might change, so it lives in code rather than config.yaml).
AUDIO_SLOTS = [
    {"id": "camera_1_green", "label": "Camera 1 — Green Audio"},
    {"id": "camera_1_red", "label": "Camera 1 — Red Audio"},
    {"id": "camera_2_green", "label": "Camera 2 — Green Audio"},
    {"id": "camera_2_red", "label": "Camera 2 — Red Audio"},
]

_AUDIO_SLOT_IDS = {slot["id"] for slot in AUDIO_SLOTS}

# NEW this round - red audio slots (client's explicit ask: "keep red
# audio enabled by default and remove option to disable for both
# camera"). Enforced HERE, server-side, not just in the template's
# disabled radio inputs - a crafted POST bypassing the UI entirely must
# not be able to actually disable red audio. table-settings.js also
# hardcodes "enabled" for these two slots before ever building its
# request, so this is defense-in-depth, not the only place the rule
# lives.
_RED_AUDIO_SLOT_IDS = {"camera_1_red", "camera_2_red"}

# Assumption: an audio slot with no default set yet (brand new table)
# defaults to Enabled.
DEFAULT_ENABLED = True

# Fixed set of push notification types, same enum pattern as AUDIO_SLOTS.
# `has_threshold` marks the one type (error rate) that carries an extra
# percent value alongside its enabled/disabled state.
NOTIFICATION_TYPES = [
    {
        "id": "start_stop_events_notification",
        "label": "Start/Stop Events Notification",
        "has_threshold": False,
    },
    {
        "id": "error_rate_threshold_notification",
        "label": "Error Rate Threshold Notification",
        "has_threshold": True,
    },
    {
        "id": "continuous_object_detected_notification",
        "label": "Continuous Object Detected Notification",
        "has_threshold": False,
    },
    {
        "id": "activity_creation_error_notification",
        "label": "Activity Creation Error Notification",
        "has_threshold": False,
    },
]

_NOTIFICATION_TYPE_BY_ID = {n["id"]: n for n in NOTIFICATION_TYPES}

# Unlike audio slots, notifications default to Disabled (client's explicit
# choice for this feature).
NOTIFICATION_DEFAULT_ENABLED = False


class ValidationError(Exception):
    """Raised on bad input - caught in routes.py and turned into a 400
    JSON response, never a 500."""


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_table_config(collection, table_id):
    """Returns the table's config doc, or an empty-but-shaped skeleton if
    none exists yet (first-ever visit to Table Settings for this table) -
    nothing is written to Mongo until an actual Save happens."""
    doc = collection.find_one({"table_id": table_id})
    if not doc:
        return {
            "table_id": table_id,
            "audio_settings": {},
            "expected_client_ips": [],
            "push_notification_emails": [],
            "push_notifications": {},
        }
    return doc


def save_audio_settings(collection, table_id, slot_updates):
    """slot_updates: dict of slot_id -> {
         "default_enabled": bool,
         "file": {"original_filename": str, "stored_filename": str} or None
       }
    A None/missing "file" means the slot's existing stored file (if any)
    is left untouched - only the default_enabled value changes."""
    for slot_id in slot_updates:
        if slot_id not in _AUDIO_SLOT_IDS:
            raise ValidationError(f"Unknown audio slot: {slot_id}")

    existing = collection.find_one({"table_id": table_id}) or {}
    audio_settings = dict(existing.get("audio_settings", {}))

    for slot_id, update in slot_updates.items():
        current = dict(audio_settings.get(slot_id, {}))
        file_info = update.get("file")
        if file_info:
            current["original_filename"] = file_info["original_filename"]
            current["stored_filename"] = file_info["stored_filename"]
            current["uploaded_at"] = _now_iso()
        if slot_id in _RED_AUDIO_SLOT_IDS:
            # Server-side enforcement of the "red is always enabled"
            # rule - ignores whatever default_enabled value was
            # actually submitted for these two slots.
            current["default_enabled"] = True
        else:
            current["default_enabled"] = bool(update.get("default_enabled", DEFAULT_ENABLED))
        audio_settings[slot_id] = current

    now = _now_iso()
    collection.update_one(
        {"table_id": table_id},
        {
            "$set": {"audio_settings": audio_settings, "updated_at": now},
            "$setOnInsert": {
                "table_id": table_id,
                "created_at": now,
                "expected_client_ips": existing.get("expected_client_ips", []),
            },
        },
        upsert=True,
    )
    return audio_settings


def save_expected_ips(collection, table_id, ips):
    """Replaces the whole expected_client_ips list atomically. Free text,
    no format validation (client's explicit choice) - only trims
    whitespace, drops blanks, and dedupes while preserving order."""
    cleaned = []
    seen = set()
    for ip in ips:
        ip = (ip or "").strip()
        if not ip or ip in seen:
            continue
        seen.add(ip)
        cleaned.append(ip)

    existing = collection.find_one({"table_id": table_id}) or {}
    now = _now_iso()
    collection.update_one(
        {"table_id": table_id},
        {
            "$set": {"expected_client_ips": cleaned, "updated_at": now},
            "$setOnInsert": {
                "table_id": table_id,
                "created_at": now,
                "audio_settings": existing.get("audio_settings", {}),
            },
        },
        upsert=True,
    )
    return cleaned


def _clean_string_list(values):
    """Trim, drop blanks, dedupe while preserving order - shared logic
    between expected_client_ips and push_notification_emails. No format
    validation (client's explicit choice for both lists)."""
    cleaned = []
    seen = set()
    for value in values or []:
        value = (value or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    return cleaned


def _validate_notifications(notifications):
    """Normalizes to exactly one entry per known notification type,
    defaulting missing/malformed entries to Disabled. The threshold
    percent on error_rate_threshold_notification is required (0-100) only
    when that notification is enabled."""
    notifications = notifications or {}
    result = {}
    for ntype in NOTIFICATION_TYPES:
        nid = ntype["id"]
        entry = notifications.get(nid) or {}
        enabled = bool(entry.get("enabled", NOTIFICATION_DEFAULT_ENABLED))
        normalized = {"enabled": enabled}

        if ntype["has_threshold"]:
            raw_threshold = entry.get("threshold_percent")
            if enabled:
                try:
                    threshold = float(raw_threshold)
                except (TypeError, ValueError):
                    raise ValidationError(
                        f'"{ntype["label"]}" is enabled but no valid threshold '
                        f"percent was provided."
                    )
                if threshold < 0 or threshold > 100:
                    raise ValidationError(
                        f'"{ntype["label"]}": threshold percent must be between 0 and 100.'
                    )
            else:
                # Not enabled - keep a previously-set value if present and
                # parseable, otherwise None. No strict validation while
                # disabled.
                try:
                    threshold = (
                        float(raw_threshold) if raw_threshold not in (None, "") else None
                    )
                except (TypeError, ValueError):
                    threshold = None
            normalized["threshold_percent"] = threshold

        result[nid] = normalized

    return result


def save_push_notifications(collection, table_id, emails, notifications):
    """Replaces the emails list and the notification settings atomically."""
    cleaned_emails = _clean_string_list(emails)
    normalized_notifications = _validate_notifications(notifications)

    existing = collection.find_one({"table_id": table_id}) or {}
    now = _now_iso()
    collection.update_one(
        {"table_id": table_id},
        {
            "$set": {
                "push_notification_emails": cleaned_emails,
                "push_notifications": normalized_notifications,
                "updated_at": now,
            },
            "$setOnInsert": {
                "table_id": table_id,
                "created_at": now,
                "audio_settings": existing.get("audio_settings", {}),
                "expected_client_ips": existing.get("expected_client_ips", []),
            },
        },
        upsert=True,
    )
    return {"emails": cleaned_emails, "notifications": normalized_notifications}


# ---------------------------------------------------------------------------
# Live-activity propagation (NEW this round)
#
# live_activity_details snapshots table_settings (audio_settings,
# expected_client_ips, push_notification_emails, push_notifications) ONCE,
# at activity creation - by design, matching the same one-time-snapshot
# rule the kit-config fields (parts_configured/neglect_parts/
# camerawise_alert_config) originally had, and which was already reversed
# for THOSE fields in current_kits_data.py's find_live_activities_for_kit/
# update_kit_live_snapshot. Client's ask this round: the same reversal for
# Table Settings too.
#
# Scoping differs from the kit-config case, deliberately: Table Settings
# belongs to a TABLE, not a specific kit, so this matches by table_id, not
# kit_id. The FRD's "only one live activity per table" rule means this
# will touch at most one document today, but the query itself doesn't
# hardcode that assumption (same reasoning as
# current_kits_data.find_live_activities_for_kit's own docstring on
# staying correct even if that constraint ever loosens).
# ---------------------------------------------------------------------------

def find_live_activities_for_table(live_activities_collection, table_id):
    """Returns every live_activity_details document currently
    status="live" for this table_id. See module docstring above for why
    this is table-scoped rather than kit-scoped."""
    return list(
        live_activities_collection.find({"table_id": table_id, "status": "live"})
    )


def update_table_settings_live_snapshot(live_activities_collection, table_id, table_config_doc):
    """Pushes the JUST-UPDATED table_configuration document's
    audio_settings/expected_client_ips/push_notification_emails/
    push_notifications onto every live activity for this table, nested
    under that activity's own "table_settings" key - the exact same
    shape create_live_activity() builds at creation time, so a viewer
    reading the activity doc afterward (e.g. the "See current settings"
    modal) sees no structural difference between a snapshot taken at
    creation and one updated by this propagation.

    table_config_doc is the FULL table_configuration document (as
    returned by get_table_config(), or read directly by the caller) -
    the three save_* functions in this module each only update PART of
    this document, so the caller is responsible for passing the
    up-to-date FULL document after whichever section was just saved,
    not just the fields that one save touched. This keeps this
    function's job simple (copy four known keys verbatim) rather than
    needing three different partial-update variants.

    Returns the list of activity_id strings that were actually updated,
    so the caller can emit a "config:updated" socket event to each one -
    reuses the SAME event name current_kits_data's kit-config
    propagation already uses (monitor.js's existing handleConfigUpdated
    listener needs no changes to also react to this).
    """
    activities = find_live_activities_for_table(live_activities_collection, table_id)
    if not activities:
        return []

    now = _now_iso()
    updated_activity_ids = []
    for activity in activities:
        live_activities_collection.update_one(
            {"_id": activity["_id"]},
            {
                "$set": {
                    "table_settings.audio_settings": table_config_doc.get("audio_settings", {}),
                    "table_settings.expected_client_ips": table_config_doc.get("expected_client_ips", []),
                    "table_settings.push_notification_emails": table_config_doc.get("push_notification_emails", []),
                    "table_settings.push_notifications": table_config_doc.get("push_notifications", {}),
                    "updated_at": now,
                }
            },
        )
        updated_activity_ids.append(str(activity["_id"]))

    return updated_activity_ids
