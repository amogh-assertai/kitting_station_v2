# TSD — Configuration

Technical spec for the Configuration blueprint: **Current Kits Configuration** (MongoDB-backed) and **PQPR Analytics** (filesystem-backed).

## File map

| File | Role |
|---|---|
| `app/blueprints/configuration/routes.py` | All HTTP routes for both sub-features |
| `app/blueprints/configuration/current_kits_data.py` | MongoDB data access + validation for Current Kits |
| `app/blueprints/configuration/pqpr_parser.py` | Excel → JSON parser for PQPR |
| `app/templates/configuration/current_kits.html` | Kit list page |
| `app/templates/configuration/kit_form.html` | Shared create/edit kit page |
| `app/templates/configuration/_kit_row.html` | Kit table row partial (server prefill; mirrored in JS for search results) |
| `app/templates/configuration/_part_row.html` | Part row partial (server prefill; mirrored in JS) |
| `app/templates/configuration/_neglect_row.html` | Neglect-part row partial (server prefill; mirrored in JS) |
| `app/templates/configuration/pqpr_analytics.html` | PQPR upload + search page |
| `app/static/css/kits-table.css`, `kit-form.css` | Current Kits styling |
| `app/static/css/upload-widget.css`, `split-panels.css` | PQPR styling |
| `app/static/js/current-kits.js` | List page: search, delete, row rendering |
| `app/static/js/kit-form.js` | Create/edit page: dynamic rows, AJAX save |
| `app/static/js/pqpr-upload.js`, `pqpr-search.js` | PQPR upload + search |

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
  "created_at": "2026-08-04T10:00:00+00:00",
  "updated_at": "2026-08-04T10:00:00+00:00"
}
```

`camera` is always `"cam1"` or `"cam2"` (validated server-side, never stored as anything else).

### Data access layer (`current_kits_data.py`)

Mirrors `pqpr_parser.py`'s separation from `routes.py` — no Mongo queries or payload shaping happen in `routes.py` directly.

| Function | Purpose |
|---|---|
| `list_kits(collection)` | All kits, summary shape, sorted by `serial_number` ascending |
| `search_kits(collection, query_text)` | Case-insensitive `$regex` `$or` across `kit_name`, `edp_number`, `parts.part_name`; empty query falls back to `list_kits` |
| `get_kit(collection, kit_id)` | Full document by id, for the edit form |
| `create_kit(collection, payload)` | Validates, checks `serial_number` + `edp_number` uniqueness, inserts |
| `update_kit(collection, kit_id, payload)` | Validates, checks uniqueness excluding self, `$set`s the document |
| `delete_kit(collection, kit_id)` | Deletes by id |

`ValidationError` is raised for any bad input and caught in `routes.py` → turned into a 400 JSON response, never a 500. Uniqueness checks use a generic `_value_taken(collection, field, value, exclude_object_id=None)` helper, shared by both `serial_number` and `edp_number`.

The list/search summary shape (`_kit_summary()`) derives `total_parts`, `cam1_count`, `cam2_count` from the `parts` array at query time — not stored redundantly.

### Routes

| Method | Path | Purpose |
|---|---|---|
| GET | `/configuration/current-kits` | List page. Catches `PyMongoError` → renders a "could not connect" message instead of crashing. |
| GET | `/configuration/current-kits/search` | `?q=` → `{success, results: [...]}`, same shape as the list |
| GET | `/configuration/current-kits/new` | Create form (blank) |
| GET | `/configuration/current-kits/<kit_id>/edit` | Edit form (pre-filled). Not-found/bad-id/DB-down all silently redirect to the list — there's no flash-message system yet. |
| POST | `/configuration/current-kits/create` | Body: kit JSON → `{success, id}` or `{success:false, error}` (400 validation / 500 DB) |
| POST | `/configuration/current-kits/<kit_id>/update` | Same contract as create |
| POST | `/configuration/current-kits/<kit_id>/delete` | `{success}` or `{success:false, error}` |

All of these follow the PQPR-established contract: **always return valid JSON**, wrapped in try/except, so the frontend's `response.json()` never breaks.

### Frontend

**`current-kits.js`** — debounced (250ms) live search; on response, re-renders `#kits-table-body` via `kitRowHtml()` (mirrors `_kit_row.html`); row numbers (`#` column) are recalculated client-side after every render/delete, since they're just display position, not stored data. Delete uses **event delegation** on the table body (not per-row listeners), so it works for both server-rendered rows and rows rendered from search results.

**`kit-form.js`** — "Add Part"/"Add Neglect Part" append blank rows via `insertAdjacentHTML`, mirroring the server-rendered partials (`_part_row.html`/`_neglect_row.html` render the same structure for prefill on edit — keep both in sync if fields change, noted in comments in all four files). On Save, the whole form (fields + all current DOM rows) is collected into one JSON payload and POSTed to create or update depending on whether `data-kit-id` is set.

**URL passing convention:** the kit table's edit/delete URLs for *server-rendered* rows use `url_for()` directly per row. For rows rendered by search (client-side), the table element carries `data-edit-url-template`/`data-delete-url-template` containing a `__KIT_ID__` placeholder (itself built via `url_for()`), and JS does a string replace — since `url_for()` can't be called from JS, this keeps URL generation server-side without hardcoding a path pattern in JS.

---

## PQPR Analytics

Unchanged from the original build — filesystem-backed, config-driven parsing.

### Data flow

1. **Upload** (`POST /configuration/pqpr-analytics/upload`): validates extension, overwrites `data/pqpr/pqpr_current.*`, writes `pqpr_meta.json`, parses and caches to `pqpr_parsed.json`.
2. **Download** (`GET /configuration/pqpr-analytics/download`): serves the stored file with its original filename.
3. **Parsing** (`pqpr_parser.py`): everything about sheet layout comes from `pqpr_parsing` config (sheet name, header row, kit/EDP columns, component start column) — a layout change is a config change, not a code change. A cell is quantity `1` if it's literally `"x"` (case-insensitive), else parsed as int if possible, else skipped. `is_top10` is purely positional (`row_index <= top10_row_count`).
4. **On-demand fallback:** `_load_parsed_data()` re-parses from the stored Excel file if the cache is missing.

### Search endpoints

| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/configuration/pqpr-analytics/search-kits` | `q` | `{results: [{edp, kit_name, is_top10}]}` (max 20) |
| GET | `/configuration/pqpr-analytics/kit-details` | `edp` | `{success, edp, kit_name, is_top10, components}` |
| GET | `/configuration/pqpr-analytics/search-components` | `q` | `{results: [...]}` (max 20) |
| GET | `/configuration/pqpr-analytics/component-details` | `component` | `{success, component, kits}`, top10 kits sorted first |

All wrapped in `try/except Exception`, always return valid JSON.

## Known gaps

- Part-name search uses an unindexed `parts.part_name` regex — fine at current scale; add a Mongo index/text index if the kit count grows large and search feels slow.
- No flash-message system — a missing/bad kit id on the edit route redirects silently rather than showing why.
- PQPR storage remains overwrite-only by client's explicit choice.
