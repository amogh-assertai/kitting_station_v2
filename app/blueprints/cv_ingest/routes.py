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


def _activity_history_collection():
    db = current_app.config["MONGO_DB"]
    name = current_app.config["SETTINGS"]["mongodb"]["collections"]["activity_history"]
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
        return jsonify(success=False, reason="validation_error", message=str(exc)), 400
    except (TypeError, ValueError):
        return jsonify(success=False, reason="validation_error", message="tableid is required and must be an integer."), 400

    try:
        result = detection_data.record_detection(
            _activities_collection(),
            form,
            image_path,
        )
    except detection_data.ValidationError as exc:
        # NEW - "camera_locked" is now a possible reason here too (a
        # red-screen is already active on this camera), on top of the
        # pre-existing reason set - routes.py itself needs no branching
        # change, exc.reason already carries whichever code
        # detection_data.py raised (client's ask predates this session:
        # "API also should get appropriate feedback message"). A
        # camera-locked rejection is intentionally NOT logged to Mongo
        # (no audit value beyond "DeepStream kept sending while locked")
        # - only a server-side log line, here, for anyone debugging a
        # noisy DeepStream client during a lock.
        if exc.reason == detection_data.REASON_CAMERA_LOCKED:
            current_app.logger.info(
                "cv_ingest: detection ignored, camera locked (table=%s cam=%s)",
                form.get("tableid"), form.get("camid"),
            )
        return jsonify(success=False, reason=exc.reason, message=str(exc)), 400
    except PyMongoError:
        return jsonify(success=False, reason="database_error", message="Could not connect to the database."), 500

    image_url = None
    if result["image_path"]:
        image_url = f"/api/detection-image/{result['image_path']}"

    audio_url = _audio_url_for(result["table_id"], result["audio_slot_id"])

    room = _room_for_activity(result["activity_id"])
    if result["matched"] or result["neglected"]:
        # NEW - a neglected-part detection now ALSO takes the green
        # path (client's explicit reversal: "dont give error sound
        # instead give green sound and green pop-up"). "neglected" flag
        # tells monitor.js whether to create a NEW red-tinted "Neglected"
        # card (client card, not the live pop-up, which stays green) if
        # this is the first time this part's been seen this kit, since
        # a neglected part has no Pending-section placeholder to find
        # and flip the way a real configured part does.
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
                "neglected": result["neglected"],
            },
            room=room,
        )
    elif result["error"]:
        # NEW - this unmatched detection just raised a wrong_part
        # red-screen (the camera's alert_wrong_part_error master switch
        # was on for this kit's config). BLOCKING event, distinct from
        # the plain "detection:red" below - no popup_uptime_sec, no
        # auto-hide timer; monitor.js keeps this on screen (and the
        # audio looping/held, if enabled) until the operator resolves
        # via /api/resolve-error (client: "stay till operator choose
        # anyone").
        socketio.emit(
            "error:red",
            {
                "cam_id": result["cam_id"],
                "error": result["error"],
                "image_url": image_url,
                "audio_url": audio_url,
            },
            room=room,
        )
    else:
        # Genuinely unmatched (wrong_part) but NOT raised as a
        # red-screen - the camera's alert_wrong_part_error master
        # switch is off for this kit/camera (client: "still logged in
        # backend" via record_detection's normal audit-log push AND its
        # own individual wrong_part_cards entry - see
        # activities_data.build_monitor_view - just no red-screen).
        # Neglected-part detections NEVER reach this branch anymore
        # (client's reversal this session moved them into the
        # matched/neglected green branch above).
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

    return jsonify(success=True, matched=result["matched"], count=result["count"], message="Detection recorded.")


# ---------------------------------------------------------------------------
# POST /api/validate-kit
# ---------------------------------------------------------------------------

@cv_ingest_bp.route("/api/validate-kit", methods=["POST"])
def validate_kit():
    """Receives a validate_now signal from the DeepStream application:
    tableid, camid, message=validate_now (fields), image (file, optional).

    Advances that camera's kit index forward by 1 - UNLESS a
    validation_error red-screen was just raised for this camera (NEW
    this session - see detection_data.validate_kit's own docstring),
    in which case the advance is deferred until the operator resolves
    via /api/resolve-error instead.
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
        return jsonify(success=False, reason="validation_error", message=str(exc)), 400
    except (TypeError, ValueError):
        return jsonify(success=False, reason="validation_error", message="tableid is required and must be an integer."), 400

    try:
        result = detection_data.validate_kit(_activities_collection(), form)
    except detection_data.ValidationError as exc:
        if exc.reason == detection_data.REASON_CAMERA_LOCKED:
            current_app.logger.info(
                "cv_ingest: validate ignored, camera locked (table=%s cam=%s)",
                form.get("tableid"), form.get("camid"),
            )
        return jsonify(success=False, reason=exc.reason, message=str(exc)), 400
    except PyMongoError:
        return jsonify(success=False, reason="database_error", message="Could not connect to the database."), 500

    room = _room_for_activity(result["activity_id"])

    if result["validation_error"]:
        # NEW - this validate call just raised a validation_error
        # red-screen instead of advancing (missing/undercount/overcount
        # issues found, camera's alert_validation_error switch on).
        # BLOCKING event, same pattern as wrong_part's "error:red" -
        # audio_url resolved the same way a detection's would be
        # (red always follows the table's saved default, never
        # per-activity toggleable).
        # resolve_sound_for_detection needs the ACTIVITY document (to
        # read its table_settings snapshot), not just the activity_id
        # string returned by validate_kit() - one extra find_one by _id.
        from bson import ObjectId
        activity_doc_for_sound = _activities_collection().find_one({"_id": ObjectId(result["activity_id"])})
        sound = detection_data.resolve_sound_for_detection(activity_doc_for_sound, result["cam_id"], matched=False)
        audio_url = _audio_url_for(result["table_id"], sound["slot_id"])

        socketio.emit(
            "error:red",
            {
                "cam_id": result["cam_id"],
                "error": result["error"],
                "image_url": None,
                "audio_url": audio_url,
            },
            room=room,
        )
        return jsonify(
            success=True,
            validation_error=True,
            new_kit_index=result["new_kit_index"],
            is_completed=False,
            activity_fully_completed=False,
            message="Validation error - awaiting operator resolution.",
        )

    socketio.emit(
        "kit:advanced",
        {
            "cam_id": result["cam_id"],
            "new_kit_index": result["new_kit_index"],
            "is_completed": result["is_completed"],
            "kit_start_time": result["kit_start_time"],
        },
        room=room,
    )

    # If BOTH cameras are now completed, move the whole activity to
    # history (status "completed") and tell every viewer currently on
    # this monitor page - client's explicit requirements: freeze "Total
    # time" at the instant the SECOND camera finishes, and auto-complete
    # to history rather than requiring the manual "Complete Manually"
    # button. completed_at is the same timestamp validate_kit() just
    # used for this call, so Total time freezes at exactly this instant,
    # not a few milliseconds later when the history-move happens.
    if result["activity_fully_completed"]:
        detection_data.complete_activity_if_both_cameras_done(
            _activities_collection(),
            _activity_history_collection(),
            result["activity_id"],
            result["completed_at"],
        )
        socketio.emit(
            "activity:completed",
            {"completed_at": result["completed_at"]},
            room=room,
        )

    message = (
        f'All kits completed for camera {result["cam_id"]}.'
        if result["is_completed"]
        else f'Advanced to kit #{result["new_kit_index"]}.'
    )
    return jsonify(
        success=True,
        validation_error=False,
        new_kit_index=result["new_kit_index"],
        is_completed=result["is_completed"],
        activity_fully_completed=result["activity_fully_completed"],
        message=message,
    )


# ---------------------------------------------------------------------------
# POST /api/resolve-error - NEW. Operator submits system_error/
# process_error (+ optional comment) from the red-screen. The ONLY way
# a locked camera becomes open again.
# ---------------------------------------------------------------------------

@cv_ingest_bp.route("/api/resolve-error", methods=["POST"])
def resolve_error():
    body = request.get_json(silent=True) or {}

    try:
        table_id = int(body.get("table_id"))
    except (TypeError, ValueError):
        return jsonify(success=False, reason="validation_error", message="table_id is required and must be an integer."), 400

    try:
        cam_id = detection_data.normalize_cam_id(body.get("camid"))
    except detection_data.ValidationError as exc:
        return jsonify(success=False, reason="validation_error", message=str(exc)), 400

    chosen_option = (body.get("chosen_option") or "").strip()
    comment = body.get("comment")

    try:
        result = detection_data.resolve_error(
            _activities_collection(), table_id, cam_id, chosen_option, comment
        )
    except detection_data.ValidationError as exc:
        return jsonify(success=False, reason=exc.reason, message=str(exc)), 400
    except PyMongoError:
        return jsonify(success=False, reason="database_error", message="Could not connect to the database."), 500

    room = _room_for_activity(result["activity_id"])

    # Every viewer: hide the red-screen, stop audio, unlock the camera
    # panel. Distinct from "kit:advanced" (used for a normal
    # validate_now) so monitor.js can run the "close red-screen" UI path
    # (which also needs to stop looping audio) even on a wrong_part
    # resolve, where the kit index does NOT change.
    socketio.emit(
        "error:resolved",
        {
            "cam_id": result["cam_id"],
            "error_type": result["error_type"],
            "new_kit_index": result["new_kit_index"],
            "is_completed": result["is_completed"],
            "kit_start_time": result["kit_start_time"],
            "resolution_code": result["resolution_code"],
        },
        room=room,
    )

    if result["activity_fully_completed"]:
        detection_data.complete_activity_if_both_cameras_done(
            _activities_collection(),
            _activity_history_collection(),
            result["activity_id"],
            result["completed_at"],
        )
        socketio.emit(
            "activity:completed",
            {"completed_at": result["completed_at"]},
            room=room,
        )

    return jsonify(success=True, new_kit_index=result["new_kit_index"], message="Error resolved.")


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
        return jsonify(success=False, reason="validation_error", message="table_id is required and must be an integer."), 400

    try:
        cam_id = detection_data.normalize_cam_id(body.get("camid"))
    except detection_data.ValidationError as exc:
        return jsonify(success=False, reason="validation_error", message=str(exc)), 400

    try:
        result = detection_data.toggle_green_sound(_activities_collection(), table_id, cam_id)
    except detection_data.ValidationError as exc:
        return jsonify(success=False, reason=exc.reason, message=str(exc)), 400
    except PyMongoError:
        return jsonify(success=False, reason="database_error", message="Could not connect to the database."), 500

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
