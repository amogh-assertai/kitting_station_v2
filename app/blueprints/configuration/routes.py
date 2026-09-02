import os
import json
import shutil
from datetime import datetime, timezone

from flask import (
    render_template,
    request,
    jsonify,
    send_file,
    current_app,
    redirect,
    url_for,
    abort,
)
from werkzeug.utils import secure_filename
from pymongo.errors import PyMongoError

from . import configuration_bp
from .pqpr_parser import parse_pqpr_workbook
from . import current_kits_data as kits_data
from . import table_settings_data

META_FILENAME = "pqpr_meta.json"
PARSED_FILENAME = "pqpr_parsed.json"
STORED_BASENAME = "pqpr_current"


# ---------------------------------------------------------------------------
# Table registry helpers
#
# Tables (kitting stations/cells) are config-driven - see
# `configuration.tables` in config.yaml. table_id is the stable reference
# used throughout routes, MongoDB documents, and PQPR file storage.
# `built` gates whether a table shows its real Current Kits/PQPR
# configuration or a "not yet built" placeholder.
# ---------------------------------------------------------------------------

def _get_tables():
    return current_app.config["SETTINGS"]["configuration"]["tables"]


def _get_table(table_id):
    for table in _get_tables():
        if table["id"] == table_id:
            return table
    return None


def _require_built_table(table_id):
    """404s if table_id doesn't exist or isn't built yet. Current Kits /
    PQPR routes should only ever be reached for a built table - the UI
    never links to them for an unbuilt one."""
    table = _get_table(table_id)
    if not table or not table.get("built"):
        abort(404)
    return table


# ---------------------------------------------------------------------------
# PQPR filesystem storage - now namespaced per table (data/pqpr/table_<id>/)
# ---------------------------------------------------------------------------

def _pqpr_root_dir():
    settings = current_app.config["SETTINGS"]
    base_dir = current_app.config["BASE_DIR"]
    root = os.path.join(base_dir, settings["storage"]["pqpr_dir"])
    os.makedirs(root, exist_ok=True)
    return root


def _migrate_legacy_pqpr_if_needed(table_id):
    """One-time migration: before multi-table support, the PQPR file lived
    directly under data/pqpr/. Table 1 (HVGKC-CELL) is the successor to
    that original single-table setup, so on first access move any legacy
    file into data/pqpr/table_1/ rather than losing it. No-op once
    migrated; never applies to tables 2/3 (they never had a legacy file)."""
    if table_id != 1:
        return
    root = _pqpr_root_dir()
    new_dir = os.path.join(root, f"table_{table_id}")
    legacy_meta = os.path.join(root, META_FILENAME)
    new_meta = os.path.join(new_dir, META_FILENAME)
    if os.path.exists(legacy_meta) and not os.path.exists(new_meta):
        os.makedirs(new_dir, exist_ok=True)
        for fname in os.listdir(root):
            legacy_path = os.path.join(root, fname)
            if os.path.isfile(legacy_path):
                shutil.move(legacy_path, os.path.join(new_dir, fname))


def _pqpr_dir(table_id):
    _migrate_legacy_pqpr_if_needed(table_id)
    table_dir = os.path.join(_pqpr_root_dir(), f"table_{table_id}")
    os.makedirs(table_dir, exist_ok=True)
    return table_dir


def _allowed_extensions():
    return current_app.config["SETTINGS"]["storage"]["pqpr_allowed_extensions"]


def _meta_path(table_id):
    return os.path.join(_pqpr_dir(table_id), META_FILENAME)


def _read_meta(table_id):
    meta_path = _meta_path(table_id)
    if not os.path.exists(meta_path):
        return None
    with open(meta_path, "r") as f:
        return json.load(f)


def _write_meta(table_id, meta):
    with open(_meta_path(table_id), "w") as f:
        json.dump(meta, f)


def _stored_file_path(table_id, extension):
    return os.path.join(_pqpr_dir(table_id), f"{STORED_BASENAME}{extension}")


def _parsed_path(table_id):
    return os.path.join(_pqpr_dir(table_id), PARSED_FILENAME)


def _parse_and_cache(table_id, filepath):
    settings = current_app.config["SETTINGS"]
    parsed = parse_pqpr_workbook(filepath, settings["pqpr_parsing"])
    with open(_parsed_path(table_id), "w") as f:
        json.dump(parsed, f)
    return parsed


def _load_parsed_data(table_id):
    """Returns parsed PQPR data for a table, parsing on demand if the
    cache is missing."""
    meta = _read_meta(table_id)
    if not meta:
        return None

    parsed_path = _parsed_path(table_id)
    if os.path.exists(parsed_path):
        with open(parsed_path, "r") as f:
            return json.load(f)

    stored_path = _stored_file_path(table_id, meta["stored_extension"])
    if not os.path.exists(stored_path):
        return None
    return _parse_and_cache(table_id, stored_path)


def _clear_existing_stored_files(table_id):
    for ext in _allowed_extensions():
        path = _stored_file_path(table_id, ext)
        if os.path.exists(path):
            os.remove(path)


def _kits_collection():
    settings = current_app.config["SETTINGS"]
    collection_name = settings["mongodb"]["collections"]["current_kits"]
    return current_app.config["MONGO_DB"][collection_name]


def _table_config_collection():
    settings = current_app.config["SETTINGS"]
    collection_name = settings["mongodb"]["collections"]["table_configuration"]
    return current_app.config["MONGO_DB"][collection_name]


# ---------------------------------------------------------------------------
# Table Settings - audio filesystem storage, namespaced per table
# (data/audio/table_<id>/<slot_id><ext>), single file per slot
# (overwrite-only, same convention as PQPR).
# ---------------------------------------------------------------------------

def _audio_root_dir():
    settings = current_app.config["SETTINGS"]
    base_dir = current_app.config["BASE_DIR"]
    root = os.path.join(base_dir, settings["storage"]["audio_dir"])
    os.makedirs(root, exist_ok=True)
    return root


def _audio_dir(table_id):
    table_dir = os.path.join(_audio_root_dir(), f"table_{table_id}")
    os.makedirs(table_dir, exist_ok=True)
    return table_dir


def _audio_allowed_extensions():
    return current_app.config["SETTINGS"]["storage"]["audio_allowed_extensions"]


def _audio_file_path(table_id, slot_id, extension):
    return os.path.join(_audio_dir(table_id), f"{slot_id}{extension}")


def _find_stored_audio_path(table_id, slot_id):
    for ext in _audio_allowed_extensions():
        path = _audio_file_path(table_id, slot_id, ext)
        if os.path.exists(path):
            return path
    return None


# ---------------------------------------------------------------------------
# Landing / table selection
# ---------------------------------------------------------------------------

@configuration_bp.route("/configuration")
def index():
    return render_template(
        "configuration/landing.html",
        active_page="configuration",
        tables=_get_tables(),
    )


@configuration_bp.route("/configuration/table/<int:table_id>")
def configuration_table(table_id):
    table = _get_table(table_id)
    if not table:
        return redirect(url_for("configuration.index"))

    if not table.get("built"):
        return render_template(
            "configuration/table_placeholder.html",
            active_page="configuration",
            table=table,
        )

    # Built table - land on its default sub-tab (matches the previous
    # single-table app's default of PQPR Analytics).
    return redirect(url_for("configuration.pqpr_analytics", table_id=table_id))


# ---------------------------------------------------------------------------
# Current Kits Configuration (table-scoped)
# ---------------------------------------------------------------------------

@configuration_bp.route("/configuration/table/<int:table_id>/current-kits")
def current_kits(table_id):
    table = _require_built_table(table_id)

    db_error = None
    kits = []
    try:
        kits = kits_data.list_kits(_kits_collection(), table_id)
    except PyMongoError:
        current_app.logger.exception("Failed to load current kits")
        db_error = "Could not connect to the database. Is MongoDB running?"

    return render_template(
        "configuration/current_kits.html",
        active_page="configuration",
        active_subtab="current_kits",
        table_id=table_id,
        table_name=table["name"],
        kits=kits,
        db_error=db_error,
    )


@configuration_bp.route("/configuration/table/<int:table_id>/current-kits/search")
def current_kits_search(table_id):
    _require_built_table(table_id)
    try:
        query_text = request.args.get("q", "")
        kits = kits_data.search_kits(_kits_collection(), table_id, query_text)
        return jsonify({"success": True, "results": kits})
    except PyMongoError:
        current_app.logger.exception("current_kits_search failed")
        return jsonify(
            {"success": False, "results": [], "error": "Search failed. Is MongoDB running?"}
        ), 500
    except Exception:
        current_app.logger.exception("current_kits_search failed")
        return jsonify({"success": False, "results": [], "error": "Search failed."}), 500


def _camera_alert_rows(kit):
    """Builds the 2-row (cam1, cam2) view model for the Camera Alert
    Configuration table on the kit form - defaults both alerts to Enabled
    for a new kit or for a camera with no stored entry yet."""
    by_camera = {}
    if kit:
        for entry in kit.get("camerawise_alert_config", []):
            by_camera[entry.get("camera")] = entry

    rows = []
    for camera, label in (("cam1", "Camera 1"), ("cam2", "Camera 2")):
        entry = by_camera.get(camera, {})
        rows.append(
            {
                "camera": camera,
                "label": label,
                "alert_validation_error": entry.get("alert_validation_error", True),
                "alert_wrong_part_error": entry.get("alert_wrong_part_error", True),
            }
        )
    return rows


@configuration_bp.route("/configuration/table/<int:table_id>/current-kits/new")
def current_kits_new(table_id):
    table = _require_built_table(table_id)
    return render_template(
        "configuration/kit_form.html",
        active_page="configuration",
        active_subtab="current_kits",
        table_id=table_id,
        table_name=table["name"],
        kit=None,
        camera_alert_rows=_camera_alert_rows(None),
    )


@configuration_bp.route("/configuration/table/<int:table_id>/current-kits/<kit_id>/edit")
def current_kits_edit(table_id, kit_id):
    table = _require_built_table(table_id)
    try:
        kit = kits_data.get_kit(_kits_collection(), kit_id, table_id=table_id)
    except kits_data.ValidationError:
        kit = None
    except PyMongoError:
        current_app.logger.exception("Failed to load kit %s for edit", kit_id)
        kit = None

    if not kit:
        # Bad id / not found / wrong table / DB unreachable - no
        # flash-message system exists yet, so fall back to the list page.
        return redirect(url_for("configuration.current_kits", table_id=table_id))

    return render_template(
        "configuration/kit_form.html",
        active_page="configuration",
        active_subtab="current_kits",
        table_id=table_id,
        table_name=table["name"],
        kit=kit,
        camera_alert_rows=_camera_alert_rows(kit),
    )


@configuration_bp.route(
    "/configuration/table/<int:table_id>/current-kits/create", methods=["POST"]
)
def current_kits_create(table_id):
    _require_built_table(table_id)
    try:
        payload = request.get_json(force=True, silent=True) or {}
        kit_id = kits_data.create_kit(_kits_collection(), table_id, payload)
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
    "/configuration/table/<int:table_id>/current-kits/<kit_id>/update", methods=["POST"]
)
def current_kits_update(table_id, kit_id):
    _require_built_table(table_id)
    try:
        payload = request.get_json(force=True, silent=True) or {}
        kits_data.update_kit(_kits_collection(), table_id, kit_id, payload)
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
    "/configuration/table/<int:table_id>/current-kits/<kit_id>/delete", methods=["POST"]
)
def current_kits_delete(table_id, kit_id):
    _require_built_table(table_id)
    try:
        kits_data.delete_kit(_kits_collection(), table_id, kit_id)
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


# ---------------------------------------------------------------------------
# PQPR Analytics (table-scoped)
# ---------------------------------------------------------------------------

@configuration_bp.route("/configuration/table/<int:table_id>/pqpr-analytics")
def pqpr_analytics(table_id):
    table = _require_built_table(table_id)
    meta = _read_meta(table_id)
    return render_template(
        "configuration/pqpr_analytics.html",
        active_page="configuration",
        active_subtab="pqpr_analytics",
        table_id=table_id,
        table_name=table["name"],
        pqpr_meta=meta,
    )


@configuration_bp.route(
    "/configuration/table/<int:table_id>/pqpr-analytics/upload", methods=["POST"]
)
def pqpr_upload(table_id):
    _require_built_table(table_id)

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

    _clear_existing_stored_files(table_id)
    stored_path = _stored_file_path(table_id, extension)
    file.save(stored_path)

    meta = {
        "original_filename": original_filename,
        "stored_extension": extension,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_meta(table_id, meta)

    try:
        _parse_and_cache(table_id, stored_path)
    except ValueError as exc:
        # File saved, but the expected sheet/layout wasn't found - surface
        # this clearly rather than silently leaving stale/no search data.
        return jsonify({"success": False, "error": str(exc)}), 400

    return jsonify({"success": True, "meta": meta})


@configuration_bp.route("/configuration/table/<int:table_id>/pqpr-analytics/download")
def pqpr_download(table_id):
    _require_built_table(table_id)
    meta = _read_meta(table_id)
    if not meta:
        return jsonify({"success": False, "error": "No PQPR file uploaded yet."}), 404

    stored_path = _stored_file_path(table_id, meta["stored_extension"])
    if not os.path.exists(stored_path):
        return jsonify({"success": False, "error": "Stored file missing."}), 404

    return send_file(
        stored_path,
        as_attachment=True,
        download_name=meta["original_filename"],
    )


SEARCH_RESULT_LIMIT = 20


@configuration_bp.route("/configuration/table/<int:table_id>/pqpr-analytics/search-kits")
def pqpr_search_kits(table_id):
    _require_built_table(table_id)
    try:
        query = request.args.get("q", "").strip().lower()
        data = _load_parsed_data(table_id)
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


@configuration_bp.route("/configuration/table/<int:table_id>/pqpr-analytics/kit-details")
def pqpr_kit_details(table_id):
    _require_built_table(table_id)
    try:
        edp = request.args.get("edp", "").strip()
        data = _load_parsed_data(table_id)
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


@configuration_bp.route(
    "/configuration/table/<int:table_id>/pqpr-analytics/search-components"
)
def pqpr_search_components(table_id):
    _require_built_table(table_id)
    try:
        query = request.args.get("q", "").strip().lower()
        data = _load_parsed_data(table_id)
        if not data or not query:
            return jsonify({"results": []})

        matches = [c for c in data["components"] if query in c.lower()]
        return jsonify({"results": matches[:SEARCH_RESULT_LIMIT]})
    except Exception:
        current_app.logger.exception("pqpr_search_components failed")
        return jsonify({"results": [], "error": "Search failed."}), 500


@configuration_bp.route(
    "/configuration/table/<int:table_id>/pqpr-analytics/component-details"
)
def pqpr_component_details(table_id):
    _require_built_table(table_id)
    try:
        component = request.args.get("component", "").strip()
        data = _load_parsed_data(table_id)
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


# ---------------------------------------------------------------------------
# Table Settings (table-scoped) - Audio Settings + Expected Client IPs
# ---------------------------------------------------------------------------

@configuration_bp.route("/configuration/table/<int:table_id>/table-settings")
def table_settings(table_id):
    table = _require_built_table(table_id)

    config_doc = table_settings_data.get_table_config(_table_config_collection(), table_id)
    audio_settings = config_doc.get("audio_settings", {})
    expected_ips = config_doc.get("expected_client_ips", [])

    audio_rows = []
    for slot in table_settings_data.AUDIO_SLOTS:
        slot_data = audio_settings.get(slot["id"], {})
        audio_rows.append(
            {
                "id": slot["id"],
                "label": slot["label"],
                "original_filename": slot_data.get("original_filename"),
                "uploaded_at": slot_data.get("uploaded_at"),
                "default_enabled": slot_data.get(
                    "default_enabled", table_settings_data.DEFAULT_ENABLED
                ),
            }
        )

    return render_template(
        "configuration/table_settings.html",
        active_page="configuration",
        active_subtab="table_settings",
        table_id=table_id,
        table_name=table["name"],
        audio_rows=audio_rows,
        expected_ips=expected_ips,
    )


@configuration_bp.route(
    "/configuration/table/<int:table_id>/table-settings/audio/save", methods=["POST"]
)
def table_settings_audio_save(table_id):
    _require_built_table(table_id)
    try:
        allowed = _audio_allowed_extensions()
        slot_updates = {}

        for slot in table_settings_data.AUDIO_SLOTS:
            slot_id = slot["id"]
            default_value = request.form.get(f"default_{slot_id}", "enabled")
            default_enabled = default_value == "enabled"

            file_info = None
            file = request.files.get(f"audio_{slot_id}")
            if file and file.filename:
                original_filename = secure_filename(file.filename)
                extension = os.path.splitext(original_filename)[1].lower()
                if extension not in allowed:
                    return jsonify(
                        {
                            "success": False,
                            "error": (
                                f'"{original_filename}": invalid file type. '
                                f'Allowed: {", ".join(allowed)}'
                            ),
                        }
                    ), 400

                # Single file per slot (overwrite-only) - clear any
                # previously stored file under a different allowed
                # extension before saving the new one.
                for ext in allowed:
                    old_path = _audio_file_path(table_id, slot_id, ext)
                    if os.path.exists(old_path):
                        os.remove(old_path)

                stored_path = _audio_file_path(table_id, slot_id, extension)
                file.save(stored_path)
                file_info = {
                    "original_filename": original_filename,
                    "stored_filename": os.path.basename(stored_path),
                }

            slot_updates[slot_id] = {
                "default_enabled": default_enabled,
                "file": file_info,
            }

        audio_settings = table_settings_data.save_audio_settings(
            _table_config_collection(), table_id, slot_updates
        )
        return jsonify({"success": True, "audio_settings": audio_settings})
    except table_settings_data.ValidationError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except PyMongoError:
        current_app.logger.exception("table_settings_audio_save failed")
        return jsonify(
            {"success": False, "error": "Could not save. Is MongoDB running?"}
        ), 500
    except Exception:
        current_app.logger.exception("table_settings_audio_save failed")
        return jsonify(
            {"success": False, "error": "Unexpected error saving audio settings."}
        ), 500


@configuration_bp.route(
    "/configuration/table/<int:table_id>/table-settings/audio/<slot_id>/file"
)
def table_settings_audio_file(table_id, slot_id):
    _require_built_table(table_id)
    valid_slot_ids = {s["id"] for s in table_settings_data.AUDIO_SLOTS}
    if slot_id not in valid_slot_ids:
        abort(404)

    path = _find_stored_audio_path(table_id, slot_id)
    if not path:
        abort(404)

    return send_file(path, mimetype="audio/mpeg")


@configuration_bp.route(
    "/configuration/table/<int:table_id>/table-settings/ips/save", methods=["POST"]
)
def table_settings_ips_save(table_id):
    _require_built_table(table_id)
    try:
        payload = request.get_json(force=True, silent=True) or {}
        ips = payload.get("ips")
        if not isinstance(ips, list):
            return jsonify({"success": False, "error": "Invalid payload."}), 400

        saved = table_settings_data.save_expected_ips(
            _table_config_collection(), table_id, ips
        )
        return jsonify({"success": True, "ips": saved})
    except PyMongoError:
        current_app.logger.exception("table_settings_ips_save failed")
        return jsonify(
            {"success": False, "error": "Could not save. Is MongoDB running?"}
        ), 500
    except Exception:
        current_app.logger.exception("table_settings_ips_save failed")
        return jsonify(
            {"success": False, "error": "Unexpected error saving IP list."}
        ), 500
