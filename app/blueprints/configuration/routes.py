import os
import json
from datetime import datetime, timezone

from flask import (
    render_template,
    request,
    jsonify,
    send_file,
    current_app,
    redirect,
    url_for,
)
from werkzeug.utils import secure_filename
from pymongo.errors import PyMongoError

from . import configuration_bp
from .pqpr_parser import parse_pqpr_workbook
from . import current_kits_data as kits_data

META_FILENAME = "pqpr_meta.json"
PARSED_FILENAME = "pqpr_parsed.json"
STORED_BASENAME = "pqpr_current"


def _pqpr_dir():
    settings = current_app.config["SETTINGS"]
    base_dir = current_app.config["BASE_DIR"]
    pqpr_dir = os.path.join(base_dir, settings["storage"]["pqpr_dir"])
    os.makedirs(pqpr_dir, exist_ok=True)
    return pqpr_dir


def _allowed_extensions():
    return current_app.config["SETTINGS"]["storage"]["pqpr_allowed_extensions"]


def _meta_path():
    return os.path.join(_pqpr_dir(), META_FILENAME)


def _read_meta():
    meta_path = _meta_path()
    if not os.path.exists(meta_path):
        return None
    with open(meta_path, "r") as f:
        return json.load(f)


def _write_meta(meta):
    with open(_meta_path(), "w") as f:
        json.dump(meta, f)


def _stored_file_path(extension):
    return os.path.join(_pqpr_dir(), f"{STORED_BASENAME}{extension}")


def _parsed_path():
    return os.path.join(_pqpr_dir(), PARSED_FILENAME)


def _parse_and_cache(filepath):
    settings = current_app.config["SETTINGS"]
    parsed = parse_pqpr_workbook(filepath, settings["pqpr_parsing"])
    with open(_parsed_path(), "w") as f:
        json.dump(parsed, f)
    return parsed


def _load_parsed_data():
    """Returns parsed PQPR data, parsing on demand if the cache is missing
    (e.g. file was uploaded before this feature existed)."""
    meta = _read_meta()
    if not meta:
        return None

    parsed_path = _parsed_path()
    if os.path.exists(parsed_path):
        with open(parsed_path, "r") as f:
            return json.load(f)

    stored_path = _stored_file_path(meta["stored_extension"])
    if not os.path.exists(stored_path):
        return None
    return _parse_and_cache(stored_path)


def _clear_existing_stored_files():
    for ext in _allowed_extensions():
        path = _stored_file_path(ext)
        if os.path.exists(path):
            os.remove(path)


@configuration_bp.route("/configuration")
def index():
    return redirect(url_for("configuration.pqpr_analytics"))


def _kits_collection():
    settings = current_app.config["SETTINGS"]
    collection_name = settings["mongodb"]["collections"]["current_kits"]
    return current_app.config["MONGO_DB"][collection_name]


@configuration_bp.route("/configuration/current-kits")
def current_kits():
    db_error = None
    kits = []
    try:
        kits = kits_data.list_kits(_kits_collection())
    except PyMongoError:
        current_app.logger.exception("Failed to load current kits")
        db_error = "Could not connect to the database. Is MongoDB running?"

    return render_template(
        "configuration/current_kits.html",
        active_page="configuration",
        active_subtab="current_kits",
        kits=kits,
        db_error=db_error,
    )


@configuration_bp.route("/configuration/current-kits/search")
def current_kits_search():
    try:
        query_text = request.args.get("q", "")
        kits = kits_data.search_kits(_kits_collection(), query_text)
        return jsonify({"success": True, "results": kits})
    except PyMongoError:
        current_app.logger.exception("current_kits_search failed")
        return jsonify(
            {"success": False, "results": [], "error": "Search failed. Is MongoDB running?"}
        ), 500
    except Exception:
        current_app.logger.exception("current_kits_search failed")
        return jsonify({"success": False, "results": [], "error": "Search failed."}), 500


@configuration_bp.route("/configuration/current-kits/new")
def current_kits_new():
    return render_template(
        "configuration/kit_form.html",
        active_page="configuration",
        active_subtab="current_kits",
        kit=None,
    )


@configuration_bp.route("/configuration/current-kits/<kit_id>/edit")
def current_kits_edit(kit_id):
    try:
        kit = kits_data.get_kit(_kits_collection(), kit_id)
    except kits_data.ValidationError:
        kit = None
    except PyMongoError:
        current_app.logger.exception("Failed to load kit %s for edit", kit_id)
        kit = None

    if not kit:
        # Bad id / not found / DB unreachable - no flash-message system
        # exists yet in this app, so fall back to the list page rather
        # than a broken edit form.
        return redirect(url_for("configuration.current_kits"))

    return render_template(
        "configuration/kit_form.html",
        active_page="configuration",
        active_subtab="current_kits",
        kit=kit,
    )


@configuration_bp.route("/configuration/current-kits/create", methods=["POST"])
def current_kits_create():
    try:
        payload = request.get_json(force=True, silent=True) or {}
        kit_id = kits_data.create_kit(_kits_collection(), payload)
        return jsonify({"success": True, "id": kit_id})
    except kits_data.ValidationError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except PyMongoError:
        current_app.logger.exception("current_kits_create failed")
        return jsonify(
            {"success": False, "error": "Could not save kit. Is MongoDB running?"}
        ), 500
    except Exception:
        current_app.logger.exception("current_kits_create failed")
        return jsonify({"success": False, "error": "Unexpected error saving kit."}), 500


@configuration_bp.route(
    "/configuration/current-kits/<kit_id>/update", methods=["POST"]
)
def current_kits_update(kit_id):
    try:
        payload = request.get_json(force=True, silent=True) or {}
        kits_data.update_kit(_kits_collection(), kit_id, payload)
        return jsonify({"success": True})
    except kits_data.ValidationError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except PyMongoError:
        current_app.logger.exception("current_kits_update failed")
        return jsonify(
            {"success": False, "error": "Could not save kit. Is MongoDB running?"}
        ), 500
    except Exception:
        current_app.logger.exception("current_kits_update failed")
        return jsonify({"success": False, "error": "Unexpected error saving kit."}), 500


@configuration_bp.route(
    "/configuration/current-kits/<kit_id>/delete", methods=["POST"]
)
def current_kits_delete(kit_id):
    try:
        kits_data.delete_kit(_kits_collection(), kit_id)
        return jsonify({"success": True})
    except kits_data.ValidationError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except PyMongoError:
        current_app.logger.exception("current_kits_delete failed")
        return jsonify(
            {"success": False, "error": "Could not delete kit. Is MongoDB running?"}
        ), 500
    except Exception:
        current_app.logger.exception("current_kits_delete failed")
        return jsonify(
            {"success": False, "error": "Unexpected error deleting kit."}
        ), 500


@configuration_bp.route("/configuration/pqpr-analytics")
def pqpr_analytics():
    meta = _read_meta()
    return render_template(
        "configuration/pqpr_analytics.html",
        active_page="configuration",
        active_subtab="pqpr_analytics",
        pqpr_meta=meta,
    )


@configuration_bp.route("/configuration/pqpr-analytics/upload", methods=["POST"])
def pqpr_upload():
    if "pqpr_file" not in request.files:
        return jsonify({"success": False, "error": "No file provided."}), 400

    file = request.files["pqpr_file"]
    if file.filename == "":
        return jsonify({"success": False, "error": "No file selected."}), 400

    original_filename = secure_filename(file.filename)
    extension = os.path.splitext(original_filename)[1].lower()
    allowed = _allowed_extensions()

    if extension not in allowed:
        return jsonify(
            {
                "success": False,
                "error": f"Invalid file type. Allowed: {', '.join(allowed)}",
            }
        ), 400

    _clear_existing_stored_files()
    stored_path = _stored_file_path(extension)
    file.save(stored_path)

    meta = {
        "original_filename": original_filename,
        "stored_extension": extension,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_meta(meta)

    try:
        _parse_and_cache(stored_path)
    except ValueError as exc:
        # File saved, but the expected sheet/layout wasn't found - surface
        # this clearly rather than silently leaving stale/no search data.
        return jsonify({"success": False, "error": str(exc)}), 400

    return jsonify({"success": True, "meta": meta})


@configuration_bp.route("/configuration/pqpr-analytics/download")
def pqpr_download():
    meta = _read_meta()
    if not meta:
        return jsonify({"success": False, "error": "No PQPR file uploaded yet."}), 404

    stored_path = _stored_file_path(meta["stored_extension"])
    if not os.path.exists(stored_path):
        return jsonify({"success": False, "error": "Stored file missing."}), 404

    return send_file(
        stored_path,
        as_attachment=True,
        download_name=meta["original_filename"],
    )


SEARCH_RESULT_LIMIT = 20


@configuration_bp.route("/configuration/pqpr-analytics/search-kits")
def pqpr_search_kits():
    try:
        query = request.args.get("q", "").strip().lower()
        data = _load_parsed_data()
        if not data or not query:
            return jsonify({"results": []})

        matches = [
            {"edp": k["edp"], "kit_name": k["kit_name"], "is_top10": k["is_top10"]}
            for k in data["kits"]
            if query in k["kit_name"].lower() or query in k["edp"].lower()
        ]
        return jsonify({"results": matches[:SEARCH_RESULT_LIMIT]})
    except Exception:
        current_app.logger.exception("pqpr_search_kits failed")
        return jsonify({"results": [], "error": "Search failed."}), 500


@configuration_bp.route("/configuration/pqpr-analytics/kit-details")
def pqpr_kit_details():
    try:
        edp = request.args.get("edp", "").strip()
        data = _load_parsed_data()
        if not data:
            return jsonify({"success": False, "error": "No PQPR data available."}), 404

        kit = next((k for k in data["kits"] if k["edp"] == edp), None)
        if not kit:
            return jsonify({"success": False, "error": "Kit not found."}), 404

        components = [
            {"name": name, "qty": qty} for name, qty in kit["components"].items()
        ]
        components.sort(key=lambda c: c["name"])

        return jsonify(
            {
                "success": True,
                "edp": kit["edp"],
                "kit_name": kit["kit_name"],
                "is_top10": kit["is_top10"],
                "components": components,
            }
        )
    except Exception:
        current_app.logger.exception("pqpr_kit_details failed")
        return jsonify({"success": False, "error": "Could not load kit details."}), 500


@configuration_bp.route("/configuration/pqpr-analytics/search-components")
def pqpr_search_components():
    try:
        query = request.args.get("q", "").strip().lower()
        data = _load_parsed_data()
        if not data or not query:
            return jsonify({"results": []})

        matches = [c for c in data["components"] if query in c.lower()]
        return jsonify({"results": matches[:SEARCH_RESULT_LIMIT]})
    except Exception:
        current_app.logger.exception("pqpr_search_components failed")
        return jsonify({"results": [], "error": "Search failed."}), 500


@configuration_bp.route("/configuration/pqpr-analytics/component-details")
def pqpr_component_details():
    try:
        component = request.args.get("component", "").strip()
        data = _load_parsed_data()
        if not data:
            return jsonify({"success": False, "error": "No PQPR data available."}), 404

        if component not in data["components"]:
            return jsonify({"success": False, "error": "Component not found."}), 404

        kits = [
            {
                "edp": k["edp"],
                "kit_name": k["kit_name"],
                "is_top10": k["is_top10"],
                "qty": k["components"][component],
            }
            for k in data["kits"]
            if component in k["components"]
        ]
        # Top-10 kits surfaced first; original sheet order preserved within
        # each group (top10 vs rest), since that order already reflects
        # the source file's own importance ordering.
        kits.sort(key=lambda k: (not k["is_top10"],))

        return jsonify({"success": True, "component": component, "kits": kits})
    except Exception:
        current_app.logger.exception("pqpr_component_details failed")
        return jsonify({"success": False, "error": "Could not load component details."}), 500
