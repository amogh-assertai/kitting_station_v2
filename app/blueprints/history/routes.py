import math

from flask import current_app, jsonify, render_template, request
from pymongo.errors import PyMongoError

from . import history_bp
from . import history_data


# ---------------------------------------------------------------------------
# Table registry helper - History is explicitly independent (client's
# instruction: "dont mirror anything" from configuration/live_kitting_
# activities' own _get_tables() helpers) - this is its own minimal copy,
# reading the same config.yaml-driven registry every blueprint reads,
# but with no shared code path to any other blueprint.
# ---------------------------------------------------------------------------

def _get_tables():
    return current_app.config["SETTINGS"]["configuration"]["tables"]


def _get_table_name(table_id):
    for table in _get_tables():
        if table["id"] == table_id:
            return table["name"]
    return None


def _activity_history_collection():
    db = current_app.config["MONGO_DB"]
    collection_name = current_app.config["SETTINGS"]["mongodb"]["collections"]["activity_history"]
    return db[collection_name]


# ---------------------------------------------------------------------------
# Listing page
# ---------------------------------------------------------------------------

@history_bp.route("/history")
def index():
    tables = _get_tables()

    table_id = history_data.parse_table_id_param(request.args.get("table_id"))
    date_from = history_data.parse_date_param(request.args.get("date_from"))
    date_to = history_data.parse_date_param(request.args.get("date_to"))
    per_page = history_data.parse_per_page_param(request.args.get("per_page"))
    page = history_data.parse_page_param(request.args.get("page"))

    # Missing/malformed date params fall back to the confirmed default
    # (last 7 days) - EITHER end missing falls back to the WHOLE default
    # range, rather than mixing one explicit bound with one defaulted
    # bound (simpler to reason about, and avoids a same-side-only filter
    # that the user never actually asked for).
    if date_from is None or date_to is None:
        date_from, date_to = history_data.default_date_range()

    try:
        rows, total_count = history_data.list_history_activities(
            _activity_history_collection(),
            table_id=table_id,
            date_from=date_from,
            date_to=date_to,
            page=page,
            per_page=per_page,
        )
        db_error = None
    except PyMongoError:
        rows = []
        total_count = 0
        db_error = "Could not connect to the database. Is MongoDB running?"

    total_pages = max(1, math.ceil(total_count / per_page)) if total_count else 1
    # A page number past the end (e.g. filters just narrowed the result
    # set) is not an error - just clamp for display purposes; the query
    # itself already ran with whatever page was requested, so an
    # out-of-range page correctly comes back empty rather than being
    # silently "corrected" into a different result set.
    current_page = min(page, total_pages)

    return render_template(
        "history/index.html",
        active_page="history",
        rows=rows,
        db_error=db_error,
        tables=tables,
        selected_table_id=table_id,
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        per_page=per_page,
        allowed_per_page=history_data.ALLOWED_PER_PAGE,
        page=current_page,
        total_pages=total_pages,
        total_count=total_count,
        get_table_name=_get_table_name,
    )


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@history_bp.route("/history/<activity_id>/delete", methods=["POST"])
def delete(activity_id):
    """AJAX: -> {success} or {success: false, error}. Permanent delete -
    no soft-delete/archive, matching History's confirmed read-only +
    delete scope. Also removes the activity's saved detection images
    from disk (both cameras, all kit indices) - see
    history_data.delete_activity's own docstring."""
    settings = current_app.config["SETTINGS"]["live_kitting"]
    try:
        history_data.delete_activity(
            _activity_history_collection(),
            activity_id,
            images_base_dir=current_app.config["BASE_DIR"],
            detection_image_dir=settings["detection_image_dir"],
        )
    except history_data.ValidationError as exc:
        return jsonify(success=False, error=str(exc)), 400
    except PyMongoError:
        return jsonify(success=False, error="Could not connect to the database."), 500

    return jsonify(success=True)
