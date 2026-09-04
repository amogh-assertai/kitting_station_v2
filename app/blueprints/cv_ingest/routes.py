import os

from flask import current_app, jsonify, request, send_from_directory, url_for
from pymongo.errors import PyMongoError

from app.extensions import socketio
from . import cv_ingest_bp
from . import detection_data


# ---------------------------------------------------------------------------
# Collection / config accessors - same "pull through app.config" convention
# already used in every other blueprint's routes.py
# ---------------------------------------------------------------------------

def _activities_collection():
    db = current_app.config["MONGO_DB"]
    name = current_app.config["SETTINGS"]["mongodb"]["collections"]["live_activities"]
    return db[name]


def _live_kitting_settings():
    return current_app.config["SETTINGS"]["live_kitting"]


def _room_for_activity(activity_id):
    """Socket.IO room name - one room per activity, joined by every
    browser tab currently viewing that activity's monitor page (see
    monitor.js). Keeps events scoped to viewers of THIS activity only,
    not broadcast app-wide."""
    return f"activity:{activity_id}"


def _audio_url_for(table_id, slot_id):
    """Builds the URL to the audio file for one slot, reusing the
    EXISTING file-serving route from the configuration blueprint
    (configuration.table_settings_audio_file) rather than duplicating
    file-serving logic here - one source of truth for how audio files
    are read off disk (data/audio/table_<id>/<slot_id><ext>, per
    configuration/routes.py)."""
    if not slot_id:
        return None
    return url_for(
        "configuration.table_settings_audio_file",
        table_id=table_id,
        slot_id=slot_id,
    )


# ---------------------------------------------------------------------------
# POST /api/detection-update
# ---------------------------------------------------------------------------

@cv_ingest_bp.route("/api/detection-update", methods=["POST"])
def detection_update():
    """Receives one part-detection event from the local DeepStream
    application. multipart/form-data:
      tableid, camid, detectedpart, Aidetectedpartname, avg_threshold,
      tracking_id, kitname  (fields)
      image                  (file, optional - frequency TBD per client)

    Always returns JSON, never a 500 - PyMongoError and ValidationError
    are both caught and turned into a clean error response, same
    contract as every other AJAX endpoint in this app.
    """
    form = request.form
    image_file = request.files.get("image")

    try:
        settings = _live_kitting_settings()
        image_path = detection_data.save_detection_image(
            base_dir=current_app.config["BASE_DIR"],
            detection_image_dir=settings["detection_image_dir"],
            table_id=int(form.get("tableid")) if form.get("tableid") else None,
            file_storage=image_file,
            allowed_extensions=settings["allowed_image_extensions"],
        )
    except detection_data.ValidationError as exc:
        return jsonify(success=False, error=str(exc)), 400
    except (TypeError, ValueError):
        return jsonify(success=False, error="tableid is required and must be an integer."), 400

    try:
        result = detection_data.record_detection(
            _activities_collection(),
            form,
            image_path,
        )
    except detection_data.ValidationError as exc:
        return jsonify(success=False, error=str(exc)), 400
    except PyMongoError:
        return jsonify(success=False, error="Could not connect to the database."), 500

    image_url = None
    if result["image_path"]:
        image_url = f"/api/detection-image/{result['image_path']}"

    audio_url = _audio_url_for(result["table_id"], result["audio_slot_id"])

    room = _room_for_activity(result["activity_id"])
    if result["matched"]:
        socketio.emit(
            "detection:green",
            {
                "cam_id": result["cam_id"],
                "part_name": result["part_name"],
                "count": result["count"],
                "quantity_required": result["quantity_required"],
                "kit_index": result["kit_index"],
                "image_url": image_url,
                "detected_at": result["detected_at"],
                "popup_uptime_sec": _live_kitting_settings()["green_popup_uptime_sec"],
                "audio_url": audio_url,
            },
            room=room,
        )
    else:
        # Red-popup path: full-box image+metadata treatment, same as
        # green (client's explicit call) - alert-TYPE differentiation
        # (Validation Error vs Wrong Part Error) is still deferred, this
        # is only the visual pop-up, not the alert-rules engine.
        socketio.emit(
            "detection:red",
            {
                "cam_id": result["cam_id"],
                "detected_part": result["part_name"],
                "kit_index": result["kit_index"],
                "image_url": image_url,
                "detected_at": result["detected_at"],
                "popup_uptime_sec": _live_kitting_settings()["red_popup_uptime_sec"],
                "audio_url": audio_url,
            },
            room=room,
        )

    return jsonify(success=True, matched=result["matched"], count=result["count"])


# ---------------------------------------------------------------------------
# POST /api/validate-kit
# ---------------------------------------------------------------------------

@cv_ingest_bp.route("/api/validate-kit", methods=["POST"])
def validate_kit():
    """Receives a validate_now signal from the DeepStream application:
    tableid, camid, message=validate_now (fields), image (file, optional).

    Advances that camera's kit index forward by 1. Full validation rules
    (pass/fail a kit before advancing) are explicitly deferred - this
    build just advances the counter and clears the UI for that camera.
    """
    form = request.form
    image_file = request.files.get("image")

    try:
        settings = _live_kitting_settings()
        # Image on validate_now is saved for audit purposes if sent, but
        # not otherwise used (no image_path is attached to the kit-advance
        # event - there's no detection_events document for this action).
        detection_data.save_detection_image(
            base_dir=current_app.config["BASE_DIR"],
            detection_image_dir=settings["detection_image_dir"],
            table_id=int(form.get("tableid")) if form.get("tableid") else None,
            file_storage=image_file,
            allowed_extensions=settings["allowed_image_extensions"],
        )
    except detection_data.ValidationError as exc:
        return jsonify(success=False, error=str(exc)), 400
    except (TypeError, ValueError):
        return jsonify(success=False, error="tableid is required and must be an integer."), 400

    try:
        result = detection_data.validate_kit(_activities_collection(), form)
    except detection_data.ValidationError as exc:
        return jsonify(success=False, error=str(exc)), 400
    except PyMongoError:
        return jsonify(success=False, error="Could not connect to the database."), 500

    room = _room_for_activity(result["activity_id"])
    socketio.emit(
        "kit:advanced",
        {
            "cam_id": result["cam_id"],
            "new_kit_index": result["new_kit_index"],
        },
        room=room,
    )

    return jsonify(success=True, new_kit_index=result["new_kit_index"])


# ---------------------------------------------------------------------------
# POST /api/toggle-sound - flips the green sound toggle for one camera on
# the table's current live activity. Called from the monitor page's UI
# (next to "Kit #N" - see monitor.html/monitor.js), NOT from the
# DeepStream application. Red sound has no toggle - always follows the
# table_settings snapshot's saved default (see
# detection_data.resolve_sound_for_detection).
# ---------------------------------------------------------------------------

@cv_ingest_bp.route("/api/toggle-sound", methods=["POST"])
def toggle_sound():
    body = request.get_json(silent=True) or {}

    try:
        table_id = int(body.get("table_id"))
    except (TypeError, ValueError):
        return jsonify(success=False, error="table_id is required and must be an integer."), 400

    try:
        cam_id = detection_data.normalize_cam_id(body.get("camid"))
    except detection_data.ValidationError as exc:
        return jsonify(success=False, error=str(exc)), 400

    try:
        result = detection_data.toggle_green_sound(_activities_collection(), table_id, cam_id)
    except detection_data.ValidationError as exc:
        return jsonify(success=False, error=str(exc)), 400
    except PyMongoError:
        return jsonify(success=False, error="Could not connect to the database."), 500

    room = _room_for_activity(result["activity_id"])
    socketio.emit(
        "sound:toggled",
        {
            "cam_id": result["cam_id"],
            "green_sound_enabled": result["green_sound_enabled"],
        },
        room=room,
    )

    return jsonify(success=True, green_sound_enabled=result["green_sound_enabled"])


# ---------------------------------------------------------------------------
# GET /api/detection-image/<table_dir>/<filename> - serves saved detection
# frames for the popup's <img> src. Path is exactly what
# save_detection_image() returned (e.g. "table_1/ab12cd34.jpg"), so this
# route mirrors that same two-segment shape rather than a wildcard path,
# to avoid any directory-traversal ambiguity.
# ---------------------------------------------------------------------------

@cv_ingest_bp.route("/api/detection-image/<table_dir>/<filename>")
def detection_image(table_dir, filename):
    settings = _live_kitting_settings()
    root = os.path.join(
        current_app.config["BASE_DIR"], settings["detection_image_dir"], table_dir
    )
    return send_from_directory(root, filename)


# ---------------------------------------------------------------------------
# Socket.IO room join - the monitor page joins this on load so it only
# receives events for the activity it's currently displaying
# ---------------------------------------------------------------------------

@socketio.on("join_activity")
def on_join_activity(data):
    activity_id = (data or {}).get("activity_id")
    if not activity_id:
        return
    from flask_socketio import join_room
    join_room(_room_for_activity(activity_id))
