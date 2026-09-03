# TSD — Configuration

Technical spec for the Configuration blueprint: **table registry/selection**, **Current Kits Configuration** (MongoDB-backed), **PQPR Analytics** (filesystem-backed), and **Table Settings** (MongoDB + filesystem-backed).

## File map

| File | Role |
|---|---|
| `app/blueprints/configuration/routes.py` | All HTTP routes — landing/table selection, Current Kits, PQPR Analytics, Table Settings. Every route except the landing page takes `table_id` as a URL path parameter. |
| `app/blueprints/configuration/current_kits_data.py` | MongoDB data access + validation for Current Kits (`current_kit_configurations` collection) |
| `app/blueprints/configuration/table_settings_data.py` | MongoDB data access + validation for Table Settings (`table_configuration` collection) |
| `app/blueprints/configuration/pqpr_parser.py` | Excel → JSON parser for PQPR |
| `app/templates/configuration/landing.html` | Table-selection cards |
| `app/templates/configuration/table_placeholder.html` | "Not yet built" page for an unbuilt table |
| `app/templates/configuration/_subnav.html` | Current Kits / PQPR Analytics / Table Settings tabs, "← Tables" link, table-name label |
| `app/templates/configuration/current_kits.html` | Kit list page |
| `app/templates/configuration/kit_form.html` | Shared create/edit kit page (fields, parts, neglect parts, camera alert config) |
| `app/templates/configuration/_kit_row.html` | Kit table row partial (server prefill; mirrored in JS for search results) |
| `app/templates/configuration/_part_row.html` | Part row partial (server prefill; mirrored in JS) |
| `app/templates/configuration/_neglect_row.html` | Neglect-part row partial (server prefill; mirrored in JS) |
| `app/templates/configuration/pqpr_analytics.html` | PQPR upload + search page |
| `app/templates/configuration/table_settings.html` | Audio Settings + Expected Client IPs + Push Notification Settings page |
| `app/static/css/config-landing.css` | Landing page cards + table placeholder (loaded via `extra_css`) |
| `app/static/css/kits-table.css`, `kit-form.css` | Current Kits styling (kit-form.css also covers Camera Alert Configuration's table + radios) |
| `app/static/css/upload-widget.css`, `split-panels.css` | PQPR styling |
| `app/static/css/table-settings.css` | Table Settings styling (loaded via `extra_css`) |
| `app/static/js/current-kits.js` | List page: search, delete, row rendering (incl. Total Parts to Neglect column) |
| `app/static/js/kit-form.js` | Create/edit page: dynamic part/neglect rows, camera alert config, AJAX save |
| `app/static/js/pqpr-upload.js`, `pqpr-search.js` | PQPR upload + search |
| `app/static/js/table-settings.js` | Deferred audio save + local preview, staged IP list, staged email list + notification toggles |

---

## Table registry

`config.yaml`'s `configuration.tables` (see `TSD_APP.md`) is the source of truth:
```yaml
configuration:
  tables:
    - id: 1
      name: "HVGKC-CELL"
      built: true
    - id: 2
      name: "Truck Cell 1"
      built: false
    - id: 3
      name: "Truck Cell 2"
      built: false
```

`routes.py` helpers:
- `_get_tables()` → the list above, straight from `current_app.config["SETTINGS"]["configuration"]["tables"]`.
- `_get_table(table_id)` → the matching entry, or `None`.
- `_require_built_table(table_id)` → `abort(404)` if the table doesn't exist or `built` is `False`; otherwise returns the table dict. Called at the top of every Current Kits / PQPR / Table Settings route — these routes should never be reached for an unbuilt table since the UI never links to them, so a 404 here means a stale/crafted URL, not a normal user path.

## Routes

### Landing / table selection
| Method | Path | Purpose |
|---|---|---|
| GET | `/configuration` | Landing page — renders a card per table from the registry |
| GET | `/configuration/table/<int:table_id>` | Unknown `table_id` → redirect to landing. Unbuilt → render `table_placeholder.html`. Built → redirect to that table's PQPR Analytics (default sub-tab) |

### Current Kits Configuration (table-scoped)
| Method | Path | Purpose |
|---|---|---|
| GET | `/configuration/table/<int:table_id>/current-kits` | List page. Catches `PyMongoError` → renders a "could not connect" message instead of crashing. |
| GET | `/configuration/table/<int:table_id>/current-kits/search` | `?q=` → `{success, results: [...]}`, same shape as the list, scoped to this table |
| GET | `/configuration/table/<int:table_id>/current-kits/new` | Create form (blank), includes `camera_alert_rows` defaulting both cameras to Enabled |
| GET | `/configuration/table/<int:table_id>/current-kits/<kit_id>/edit` | Edit form (pre-filled). Not-found/bad-id/wrong-table/DB-down all silently redirect to the list — there's no flash-message system yet. |
| POST | `/configuration/table/<int:table_id>/current-kits/create` | Body: kit JSON (incl. `camerawise_alert_config`) → `{success, id}` or `{success:false, error}` (400 validation / 500 DB) |
| POST | `/configuration/table/<int:table_id>/current-kits/<kit_id>/update` | Same contract as create |
| POST | `/configuration/table/<int:table_id>/current-kits/<kit_id>/delete` | `{success}` or `{success:false, error}` |

All of these follow the PQPR-established contract: **always return valid JSON**, wrapped in try/except, so the frontend's `response.json()` never breaks.

### PQPR Analytics (table-scoped)
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/configuration/table/<int:table_id>/pqpr-analytics` | — | Page render |
| POST | `/configuration/table/<int:table_id>/pqpr-analytics/upload` | multipart file | `{success, meta}` or `{success:false, error}` |
| GET | `/configuration/table/<int:table_id>/pqpr-analytics/download` | — | The stored file, original filename |
| GET | `/configuration/table/<int:table_id>/pqpr-analytics/search-kits` | `q` | `{results: [{edp, kit_name, is_top10}]}` (max 20) |
| GET | `/configuration/table/<int:table_id>/pqpr-analytics/kit-details` | `edp` | `{success, edp, kit_name, is_top10, components}` |
| GET | `/configuration/table/<int:table_id>/pqpr-analytics/search-components` | `q` | `{results: [...]}` (max 20) |
| GET | `/configuration/table/<int:table_id>/pqpr-analytics/component-details` | `component` | `{success, component, kits}`, top10 kits sorted first |

All wrapped in `try/except Exception`, always return valid JSON.

### Table Settings (table-scoped)
| Method | Path | Purpose |
|---|---|---|
| GET | `/configuration/table/<int:table_id>/table-settings` | Page render — Audio Settings rows, Expected Client IPs, notification rows, push-notification emails |
| POST | `/configuration/table/<int:table_id>/table-settings/audio/save` | multipart form: `audio_<slot_id>` (optional file per slot) + `default_<slot_id>` (`enabled`/`disabled`) for all 4 slots → `{success, audio_settings}` |
| GET | `/configuration/table/<int:table_id>/table-settings/audio/<slot_id>/file` | Serves the stored MP3 for that slot (`audio/mpeg`, inline — used for Preview). 404 if the slot is unknown or has no stored file. |
| POST | `/configuration/table/<int:table_id>/table-settings/ips/save` | Body: `{"ips": [...]}` → replaces the whole list → `{success, ips}` |
| POST | `/configuration/table/<int:table_id>/table-settings/push-notifications/save` | Body: `{"emails": [...], "notifications": {...}}` → `{success, emails, notifications}` |

---

## Current Kits Configuration

### MongoDB

- Database: `mongodb.db_name` in `config.yaml` (`kitting_station_v2`)
- Collection: `mongodb.collections.current_kits` in `config.yaml` (`current_kit_configurations`)
- Connection: `app/config/db.py`'s `init_mongo()`, lazy `MongoClient` from `secrets.mongo_uri` (`.env` → `MONGO_URI`)

### Document shape

```json
{
  "_id": ObjectId,
  "table_id": 1,
  "serial_number": 1,
  "kit_name": "1675KIT48",
  "edp_number": "0241276",
  "parts": [
    {
      "part_name": "A75C",
      "quantity_required": 2,
      "camera": "cam1",
      "alert_missing": true,
      "alert_undercount": false,
      "alert_overcount": true,
      "class_resemblance": "0.9"
    }
  ],
  "neglect_parts": [
    {"part_name": "PKG-BAG", "camera": "cam1"}
  ],
  "camerawise_alert_config": [
    {"camera": "cam1", "alert_validation_error": true, "alert_wrong_part_error": true},
    {"camera": "cam2", "alert_validation_error": true, "alert_wrong_part_error": true}
  ],
  "created_at": "2026-08-04T10:00:00+00:00",
  "updated_at": "2026-08-04T10:00:00+00:00"
}
```

`camera` is always `"cam1"` or `"cam2"` (validated server-side, never stored as anything else). `table_id` is required on every document — see "Multi-table scoping" below. `camerawise_alert_config` is always normalized to exactly 2 entries (one per camera, `cam1` then `cam2`) on every save, regardless of what was submitted.

### Multi-table scoping

- Every query is scoped with `{"table_id": table_id}`.
- `serial_number` / `edp_number` **uniqueness is checked per table**, not globally — two different tables may legitimately reuse the same serial number.
- `get_kit(collection, kit_id, table_id=...)` returns `None` (not the raw doc) if the kit belongs to a different table — this is what makes editing/deleting across table boundaries impossible even via a crafted URL.
- There is **no fallback for a missing `table_id` field** — every document is expected to have one (existing pre-multi-table documents were backfilled with `table_id: 1` directly in Mongo during the migration to this schema). A document without `table_id` will not appear under any table.

### Data access layer (`current_kits_data.py`)

Mirrors `pqpr_parser.py`'s separation from `routes.py` — no Mongo queries or payload shaping happen in `routes.py` directly.

| Function | Purpose |
|---|---|
| `list_kits(collection, table_id)` | All kits for this table, summary shape, sorted by `serial_number` ascending |
| `search_kits(collection, table_id, query_text)` | Case-insensitive `$regex` `$or` across `kit_name`, `edp_number`, `parts.part_name`, scoped to this table; empty query falls back to `list_kits` |
| `get_kit(collection, kit_id, table_id=None)` | Full document by id, for the edit form. If `table_id` given, returns `None` on a cross-table match. |
| `create_kit(collection, table_id, payload)` | Validates, checks `serial_number` + `edp_number` uniqueness **within this table**, sets `table_id`, inserts |
| `update_kit(collection, table_id, kit_id, payload)` | Validates the kit belongs to this table first, then checks uniqueness excluding self, `$set`s the document |
| `delete_kit(collection, table_id, kit_id)` | Validates the kit belongs to this table first, then deletes by id |

`ValidationError` is raised for any bad input and caught in `routes.py` → turned into a 400 JSON response, never a 500. Uniqueness checks use a generic `_value_taken(collection, field, value, table_id, exclude_object_id=None)` helper, shared by both `serial_number` and `edp_number`, always scoped by `table_id`.

`_validate_camera_alert_config(payload)` normalizes `camerawise_alert_config` to exactly one entry per camera (`ALLOWED_CAMERAS` order), defaulting a missing camera's entry to `{alert_validation_error: True, alert_wrong_part_error: True}` — so a payload built outside the UI (or an old payload predating this field) still produces a valid, complete document.

The list/search summary shape (`_kit_summary()`) derives `total_parts`, `cam1_count`, `cam2_count`, `total_neglect_parts`, `neglect_cam1_count`, `neglect_cam2_count` from the `parts` / `neglect_parts` arrays at query time — not stored redundantly.

### Frontend

**`current-kits.js`** — debounced (250ms) live search; on response, re-renders `#kits-table-body` via `kitRowHtml()` (mirrors `_kit_row.html`, including the Total Parts to Neglect column); row numbers (`#` column) are recalculated client-side after every render/delete, since they're just display position, not stored data. Delete uses **event delegation** on the table body (not per-row listeners), so it works for both server-rendered rows and rows rendered from search results.

**`kit-form.js`** — "Add Part"/"Add Neglect Part" append blank rows via `insertAdjacentHTML`, mirroring the server-rendered partials (`_part_row.html`/`_neglect_row.html` render the same structure for prefill on edit — keep both in sync if fields change, noted in comments in all four files). The Camera Alert Configuration table's rows are entirely server-rendered (2 fixed rows, cam1/cam2) — no client-side row add/remove needed there, just radio state. On Save, the whole form (fields + parts + neglect parts + `collectCameraAlertConfig()`) is collected into one JSON payload and POSTed to create or update depending on whether `data-kit-id` is set.

**URL passing convention:** every `url_for()` call for Current Kits routes includes `table_id` alongside `kit_id` where relevant. For rows rendered by search (client-side), the table element carries `data-edit-url-template`/`data-delete-url-template` containing a `__KIT_ID__` placeholder (`table_id` already baked in server-side, only `kit_id` is templated client-side) — since `url_for()` can't be called from JS, this keeps URL generation server-side without hardcoding a path pattern in JS.

---

## PQPR Analytics

Filesystem-backed, config-driven parsing, now namespaced per table.

### Storage layout

`data/pqpr/table_<id>/` — `pqpr_current.<ext>` (the uploaded file), `pqpr_meta.json` (original filename + upload timestamp), `pqpr_parsed.json` (cached parse). One active file per table, overwrite-only (client's explicit choice, unchanged from the original single-table design).

**One-time legacy migration:** `_migrate_legacy_pqpr_if_needed(table_id)` — if `table_id == 1` and a file exists directly under `data/pqpr/` (the pre-multi-table location) but not yet under `data/pqpr/table_1/`, it's moved automatically the first time `table_1`'s PQPR directory is accessed. No-op once migrated, never applies to tables 2/3.

### Data flow

1. **Upload** (`POST .../pqpr-analytics/upload`): validates extension, overwrites `data/pqpr/table_<id>/pqpr_current.*`, writes `pqpr_meta.json`, parses and caches to `pqpr_parsed.json`.
2. **Download** (`GET .../pqpr-analytics/download`): serves the stored file with its original filename.
3. **Parsing** (`pqpr_parser.py`, unchanged): everything about sheet layout comes from `pqpr_parsing` config (sheet name, header row, kit/EDP columns, component start column) — a layout change is a config change, not a code change. A cell is quantity `1` if it's literally `"x"` (case-insensitive), else parsed as int if possible, else skipped. `is_top10` is purely positional (`row_index <= top10_row_count`).
4. **On-demand fallback:** `_load_parsed_data(table_id)` re-parses from the stored Excel file if the cache is missing.

### Search endpoints

Same 4 endpoints as before (see route table above), each now taking `table_id` and operating only on that table's parsed data — no cross-table leakage possible since each table has its own `data/pqpr/table_<id>/` directory and Mongo isn't involved here at all.

---

## Table Settings

### MongoDB

- Collection: `mongodb.collections.table_configuration` in `config.yaml` (`table_configuration`) — **separate collection from Current Kits**, one document per table.

### Document shape

```json
{
  "_id": ObjectId,
  "table_id": 1,
  "audio_settings": {
    "camera_1_green": {
      "original_filename": "chime.mp3",
      "stored_filename": "camera_1_green.mp3",
      "uploaded_at": "2026-09-01T12:00:00+00:00",
      "default_enabled": true
    },
    "camera_1_red": { "...": "..." },
    "camera_2_green": { "...": "..." },
    "camera_2_red": { "...": "..." }
  },
  "expected_client_ips": ["10.0.0.5", "10.0.0.10"],
  "push_notification_emails": ["ops@dormont.com", "alerts@dormont.com"],
  "push_notifications": {
    "start_stop_events_notification": {"enabled": true},
    "error_rate_threshold_notification": {"enabled": true, "threshold_percent": 15.0},
    "continuous_object_detected_notification": {"enabled": false},
    "activity_creation_error_notification": {"enabled": false}
  },
  "created_at": "2026-09-01T10:00:00+00:00",
  "updated_at": "2026-09-01T12:00:00+00:00"
}
```

The document is created lazily on first Save (any of the three sections) via `upsert=True` — visiting Table Settings before ever saving anything does **not** write a document; `get_table_config()` returns an empty-but-shaped skeleton instead so the page still renders correctly.

### Fixed enums (`table_settings_data.py`, code-level, not config.yaml — same reasoning as `ALLOWED_CAMERAS` in `current_kits_data.py`: a stable set, not client source data whose shape might change)

```python
AUDIO_SLOTS = [
    {"id": "camera_1_green", "label": "Camera 1 — Green Audio"},
    {"id": "camera_1_red", "label": "Camera 1 — Red Audio"},
    {"id": "camera_2_green", "label": "Camera 2 — Green Audio"},
    {"id": "camera_2_red", "label": "Camera 2 — Red Audio"},
]
DEFAULT_ENABLED = True  # audio default

NOTIFICATION_TYPES = [
    {"id": "start_stop_events_notification", "label": "Start/Stop Events Notification", "has_threshold": False},
    {"id": "error_rate_threshold_notification", "label": "Error Rate Threshold Notification", "has_threshold": True},
    {"id": "continuous_object_detected_notification", "label": "Continuous Object Detected Notification", "has_threshold": False},
    {"id": "activity_creation_error_notification", "label": "Activity Creation Error Notification", "has_threshold": False},
]
NOTIFICATION_DEFAULT_ENABLED = False  # notification default (opposite of audio)
```

### Data access layer (`table_settings_data.py`)

| Function | Purpose |
|---|---|
| `get_table_config(collection, table_id)` | Returns the doc, or an empty-but-shaped skeleton if none exists yet. Never writes. |
| `save_audio_settings(collection, table_id, slot_updates)` | `slot_updates`: `{slot_id: {"default_enabled": bool, "file": {"original_filename", "stored_filename"} or None}}`. `file: None` leaves that slot's stored file untouched — only the default changes. Merges into the existing `audio_settings` dict, upserts. |
| `save_expected_ips(collection, table_id, ips)` | Replaces `expected_client_ips` atomically. Trims, drops blanks, dedupes (order-preserving). No format validation. |
| `save_push_notifications(collection, table_id, emails, notifications)` | Replaces `push_notification_emails` (same cleaning as IPs) and `push_notifications` atomically. `_validate_notifications()` normalizes to exactly one entry per `NOTIFICATION_TYPES` id, defaulting missing/malformed entries to Disabled. |

`_validate_notifications()` threshold rule: for `error_rate_threshold_notification`, `threshold_percent` is **required and validated to be a number in [0, 100]** only when `enabled: True` is submitted for that entry; raises `ValidationError` otherwise. When `enabled: False`, whatever threshold value was submitted is kept if parseable, else stored as `None` — no strict requirement while disabled.

`ValidationError` (this module's own class, same pattern as `current_kits_data.ValidationError`) is caught in `routes.py` and turned into a 400 JSON response.

### Audio file storage

`data/audio/table_<id>/<slot_id>.mp3` — one file per slot per table, overwrite-only (same convention as PQPR). `_find_stored_audio_path(table_id, slot_id)` checks each allowed extension in turn and returns the first that exists (currently only `.mp3` is allowed, per `storage.audio_allowed_extensions` in `config.yaml`).

### Frontend

**`table-settings.js`** has three independent initializers, all wired on `DOMContentLoaded`:

- **`initAudioSettings()`** — file selection is staged in a `pendingFiles` JS object keyed by slot id; **nothing uploads until "Save Audio Settings" is clicked** (deferred save — the one save-timing decision in this app that differs from PQPR's immediate-upload-on-select). Preview plays `URL.createObjectURL(pendingFile)` if a new file is staged for that slot, otherwise fetches the saved server file via the slot's `data-audio-url`. On Save, builds a single `FormData` with `audio_<slot_id>` (only for slots with a pending file) and `default_<slot_id>` for all 4 slots, POSTs multipart to `.../table-settings/audio/save`, then reconciles the UI from the response's `audio_settings`.
- **`initIpList()`** — staged array (`ips`), add/edit/delete all operate on the in-memory array and re-render; nothing reaches the server until "Save IP List" is clicked, which POSTs the whole array as JSON.
- **`initPushNotifications()`** — same staged-array pattern for `emails`; the 4 notification radios (plus the conditional threshold input, which enables/disables itself based on its own row's radio via a `change` listener) are read fresh at Save time (not staged in JS state) and combined with the staged `emails` array into one POST to `.../table-settings/push-notifications/save`.

All three reuse the same `escapeHtml()`/`setStatus()`/`postJson()` helpers at the top of the file, following the error-handling conventions established by `pqpr-search.js` and `current-kits.js` (always parse JSON defensively, always show a visible error rather than failing silently).

**CSS reuse:** the Push Notification email list reuses the `.ip-list-table` / `.ip-edit-input` / `.ip-list__add-row` / `.ip-list__empty` classes directly (same visual pattern, no duplicate CSS) rather than defining parallel `.email-*` classes.

## Known gaps

- Part-name search uses an unindexed `parts.part_name` regex — fine at current scale; add a Mongo index/text index if the kit count grows large and search feels slow.
- No flash-message system — a missing/bad kit id on the edit route redirects silently rather than showing why.
- PQPR storage and Table Settings' audio storage both remain overwrite-only by client's explicit choice.
- `app/config/loader.py`'s fail-fast validation may not yet cover `configuration.tables` or the `table_configuration` collection name — confirm and extend if desired.
- Tables 2 and 3 have no Current Kits Configuration, PQPR Analytics, or Table Settings data/routes/templates built — every data-layer function and route here already takes `table_id` as a parameter, so extending to another table is a matter of flipping `built: true` in `config.yaml` and confirming the existing routes work for that table_id (they should, since nothing is Table-1-specific except the one-time PQPR legacy-migration check).
