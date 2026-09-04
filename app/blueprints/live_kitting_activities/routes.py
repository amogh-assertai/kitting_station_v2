from flask import (
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from pymongo.errors import PyMongoError

from . import live_kitting_activities_bp
from . import activities_data

# Static placeholder camera-check images. Real per-camera capture isn't
# wired yet (camera check page's actual working is a separate, later
# build) - these two fixed files stand in until then. Swap the files in
# app/static/images/ to change what's shown; no code change needed.
CAMERA_CHECK_IMAGES = {
    "cam1": "images/camera-check-cam1-placeholder.png",
    "cam2": "images/camera-check-cam2-placeholder.png",
}

DEFAULT_UNITS_TO_PACK = 70


# ---------------------------------------------------------------------------
# Table registry helpers - same contract as configuration/routes.py
# (_get_tables / _get_table / _require_built_table), duplicated here
# rather than imported since blueprints stay decoupled from each other.
# ---------------------------------------------------------------------------

def _get_tables():
    return current_app.config["SETTINGS"]["configuration"]["tables"]


def _get_table(table_id):
    for table in _get_tables():
        if table["id"] == table_id:
            return table
    return None


def _require_built_table(table_id):
    table = _get_table(table_id)
    if table is None or not table.get("built"):
        abort(404)
    return table


def _activities_collection():
    db = current_app.config["MONGO_DB"]
    collection_name = current_app.config["SETTINGS"]["mongodb"]["collections"]["live_activities"]
    return db[collection_name]


def _kits_collection():
    db = current_app.config["MONGO_DB"]
    collection_name = current_app.config["SETTINGS"]["mongodb"]["collections"]["current_kits"]
    return db[collection_name]


def _table_settings_collection():
    db = current_app.config["MONGO_DB"]
    collection_name = current_app.config["SETTINGS"]["mongodb"]["collections"]["table_configuration"]
    return db[collection_name]


def _activity_history_collection():
    db = current_app.config["MONGO_DB"]
    collection_name = current_app.config["SETTINGS"]["mongodb"]["collections"]["activity_history"]
    return db[collection_name]


# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------

@live_kitting_activities_bp.route("/live-kitting-activities")
def index():
    try:
        activities = activities_data.list_live_activities(_activities_collection())
        db_error = None
    except PyMongoError:
        activities = []
        db_error = "Could not connect to the database. Is MongoDB running?"

    return render_template(
        "live_kitting_activities/index.html",
        active_page="live_kitting_activities",
        activities=activities,
        db_error=db_error,
    )


# ---------------------------------------------------------------------------
# Step 1: Create - station / order / EDP / units
# ---------------------------------------------------------------------------

@live_kitting_activities_bp.route("/live-kitting-activities/create", methods=["GET"])
def create():
    built_tables = [t for t in _get_tables() if t.get("built")]
    return render_template(
        "live_kitting_activities/create.html",
        active_page="live_kitting_activities",
        tables=built_tables,
        default_units_to_pack=DEFAULT_UNITS_TO_PACK,
    )


@live_kitting_activities_bp.route("/live-kitting-activities/lookup-edp", methods=["POST"])
def lookup_edp():
    """AJAX: {table_id, edp_number} -> {success, kit_id, kit_name} or
    {success: false, error}. Exact match only, scoped to the given table -
    no suggestions, per confirmed scope."""
    body = request.get_json(silent=True) or {}

    try:
        table_id = int(body.get("table_id"))
    except (TypeError, ValueError):
        return jsonify(success=False, error="A valid station must be selected."), 400

    table = _require_built_table_json(table_id)
    if table is None:
        return jsonify(success=False, error="Unknown or unbuilt station."), 400

    try:
        kit = activities_data.find_kit_by_edp(_kits_collection(), table_id, body.get("edp_number"))
    except activities_data.ValidationError as exc:
        return jsonify(success=False, error=str(exc)), 400
    except PyMongoError:
        return jsonify(success=False, error="Could not connect to the database."), 500

    if not kit:
        return jsonify(success=False, error="EDP number not found on this station."), 404

    return jsonify(success=True, kit_id=str(kit["_id"]), kit_name=kit["kit_name"])


def _require_built_table_json(table_id):
    """Same guard as _require_built_table, but returns None instead of
    aborting - AJAX endpoints reply with JSON, never an HTML 404 page."""
    table = _get_table(table_id)
    if table is None or not table.get("built"):
        return None
    return table


@live_kitting_activities_bp.route("/live-kitting-activities/check-table-busy", methods=["POST"])
def check_table_busy():
    """AJAX: {table_id} -> {success, busy, order_number?}. Called on Next
    click (confirmed scope: checked only on submit, not on table select)
    before navigating to camera-check. Re-checked again at finalize for
    race safety - this call is a UX convenience, not the enforcement
    point."""
    body = request.get_json(silent=True) or {}

    try:
        table_id = int(body.get("table_id"))
    except (TypeError, ValueError):
        return jsonify(success=False, error="A valid station must be selected."), 400

    if _require_built_table_json(table_id) is None:
        return jsonify(success=False, error="Unknown or unbuilt station."), 400

    try:
        busy_doc = activities_data.get_live_activity_for_table(_activities_collection(), table_id)
    except PyMongoError:
        return jsonify(success=False, error="Could not connect to the database."), 500

    if busy_doc:
        return jsonify(success=True, busy=True, order_number=busy_doc.get("order_number"))
    return jsonify(success=True, busy=False)


# ---------------------------------------------------------------------------
# Step 2: Camera check - carries step-1 data forward via query params
# (no DB write happens until "Create Activity" is clicked)
# ---------------------------------------------------------------------------

@live_kitting_activities_bp.route("/live-kitting-activities/create/camera-check", methods=["GET"])
def camera_check():
    table_id_raw = request.args.get("table_id", "")
    try:
        table_id = int(table_id_raw)
    except (TypeError, ValueError):
        return redirect(url_for("live_kitting_activities.create"))

    table = _require_built_table(table_id)

    # Everything here is display-only pass-through; _validate_create_payload
    # in activities_data re-validates all of it for real on finalize.
    context = {
        "active_page": "live_kitting_activities",
        "table_id": table_id,
        "table_name": table["name"],
        "order_number": request.args.get("order_number", ""),
        "edp_number": request.args.get("edp_number", ""),
        "kit_id": request.args.get("kit_id", ""),
        "kit_name": request.args.get("kit_name", ""),
        "quantity_required": request.args.get("quantity_required", DEFAULT_UNITS_TO_PACK),
        "camera_images": CAMERA_CHECK_IMAGES,
    }
    return render_template("live_kitting_activities/camera_check.html", **context)


@live_kitting_activities_bp.route("/live-kitting-activities/create/finalize", methods=["POST"])
def finalize():
    """Final step: re-validates everything server-side and writes the
    live_activity_details document. Nothing before this point is trusted -
    the 2-step flow only ever carried form/query data, never a DB write."""
    form = request.form

    payload = {
        "table_id": form.get("table_id"),
        "table_name": form.get("table_name"),
        "order_number": form.get("order_number"),
        "edp_number": form.get("edp_number"),
        "kit_id": form.get("kit_id"),
        "kit_name": form.get("kit_name"),
        "quantity_required": form.get("quantity_required"),
    }

    try:
        activity_id = activities_data.create_live_activity(
            _activities_collection(),
            _kits_collection(),
            payload,
            CAMERA_CHECK_IMAGES,
            table_settings_collection=_table_settings_collection(),
        )
    except activities_data.ValidationError as exc:
        # No flash-message system yet (same known gap as the rest of the
        # app) - re-render camera_check with the error and the same data
        # so nothing typed is lost.
        table_id = payload.get("table_id")
        try:
            table_id_int = int(table_id)
            table = _get_table(table_id_int)
        except (TypeError, ValueError):
            table = None

        return render_template(
            "live_kitting_activities/camera_check.html",
            active_page="live_kitting_activities",
            table_id=table_id,
            table_name=table["name"] if table else payload.get("table_name"),
            order_number=payload.get("order_number"),
            edp_number=payload.get("edp_number"),
            kit_id=payload.get("kit_id"),
            kit_name=payload.get("kit_name"),
            quantity_required=payload.get("quantity_required"),
            camera_images=CAMERA_CHECK_IMAGES,
            error=str(exc),
        ), 400
    except PyMongoError:
        return render_template(
            "live_kitting_activities/camera_check.html",
            active_page="live_kitting_activities",
            table_id=payload.get("table_id"),
            table_name=payload.get("table_name"),
            order_number=payload.get("order_number"),
            edp_number=payload.get("edp_number"),
            kit_id=payload.get("kit_id"),
            kit_name=payload.get("kit_name"),
            quantity_required=payload.get("quantity_required"),
            camera_images=CAMERA_CHECK_IMAGES,
            error="Could not connect to the database. Is MongoDB running?",
        ), 500

    # Monitor page now exists - land directly on the new activity's
    # monitor view instead of the landing list.
    return redirect(url_for("live_kitting_activities.monitor", activity_id=activity_id))


# ---------------------------------------------------------------------------
# Complete manually - moves a live activity into activity_history
# ---------------------------------------------------------------------------

@live_kitting_activities_bp.route(
    "/live-kitting-activities/<activity_id>/complete-manually", methods=["POST"]
)
def complete_manually(activity_id):
    """AJAX: {reason?} -> {success} or {success: false, error}. Reason is
    optional free text (confirmed scope). On success the activity moves
    from live_activity_details to activity_history with status
    "completed-manually", stopped_at, and stop_reason recorded."""
    body = request.get_json(silent=True) or {}
    reason = body.get("reason")

    try:
        activities_data.complete_activity_manually(
            _activities_collection(),
            _activity_history_collection(),
            activity_id,
            reason,
        )
    except activities_data.ValidationError as exc:
        return jsonify(success=False, error=str(exc)), 400
    except PyMongoError:
        return jsonify(success=False, error="Could not connect to the database."), 500

    return jsonify(success=True)


# ---------------------------------------------------------------------------
# Monitor page - single activity detail
# ---------------------------------------------------------------------------

@live_kitting_activities_bp.route("/live-kitting-activities/<activity_id>/monitor")
def monitor(activity_id):
    try:
        doc = activities_data.get_activity_by_id(_activities_collection(), activity_id)
    except activities_data.ValidationError:
        abort(404)
    except PyMongoError:
        abort(500)

    if not doc:
        abort(404)

    view = activities_data.build_monitor_view(doc)
    return render_template(
        "live_kitting_activities/monitor.html",
        active_page="live_kitting_activities",
        activity=view,
        table_id=view["table_id"],
        table_name=view["table_name"],
        green_popup_uptime_sec=current_app.config["SETTINGS"]["live_kitting"]["green_popup_uptime_sec"],
        red_popup_uptime_sec=current_app.config["SETTINGS"]["live_kitting"]["red_popup_uptime_sec"],
    )
