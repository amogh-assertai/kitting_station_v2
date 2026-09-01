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

# Assumption: an audio slot with no default set yet (brand new table)
# defaults to Enabled.
DEFAULT_ENABLED = True


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
