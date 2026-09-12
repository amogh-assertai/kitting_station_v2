# TSD — History

Technical spec for the History blueprint. For functional behavior, see
`FRD_HISTORY.md`.

## File map

| File | Role |
|---|---|
| `app/blueprints/history/__init__.py` | Defines `history_bp` (Blueprint, no `url_prefix`); unchanged this session |
| `app/blueprints/history/routes.py` | `GET /history` (listing), `POST /history/<activity_id>/delete` — replaced this session (was a single placeholder route) |
| `app/blueprints/history/history_data.py` | NEW — all MongoDB filtering/pagination/error-tally/delete logic |
| `app/templates/history/index.html` | NEW — replaced the placeholder template |
| `app/static/css/history.css` | NEW — page-scoped, loaded via `{% block extra_css %}`, no shared/global file touched |
| `app/static/js/history-list.js` | NEW — created_at formatting + delete confirm/AJAX |

**Deliberately independent** — per explicit client instruction, this
blueprint does NOT import from `live_kitting_activities` or
`cv_ingest`, even where logic is genuinely shared (see "Image-folder
deletion" below for the one place this creates a duplication that must
be kept in sync by hand). `history_data.py` has its own small
`_get_tables()`/`_get_table_name()` pair rather than reusing the
near-identical helpers already in `live_kitting_activities/routes.py`
and `configuration/routes.py`.

## MongoDB

Reads and deletes from `mongodb.collections.activity_history` only
(config key: `activity_history`, collection name in MongoDB is also
`activity_history` — see `config.yaml`). No other collection is touched
by this blueprint. History does not write new documents at all — every document arrives here exclusively via
`live_kitting_activities.activities_data.complete_activity_manually()`
(see that function for the exact copy-and-stamp logic — `stopped_at`,
`stop_reason`, and `status: "completed-manually"` added on top of a
verbatim copy of the live document's fields).

### Document shape read here

```
{
  "_id": ObjectId,
  "table_id": int, "table_name": str,
  "kit_id": ObjectId, "kit_name": str, "edp_number": str,
  "order_number": str, "quantity_required": int,
  "current_kit_index_cam1": int, "current_kit_index_cam2": int,
  "detections": {
      "cam1": {"<kit_index>": {"errors": [...], ...}, ...},
      "cam2": {"<kit_index>": {"errors": [...], ...}, ...},
  },
  "status": "completed" | "completed-manually",
  "created_at": iso str, "stopped_at": iso str (manual only),
  "stop_reason": str | None,
  ...
}
```

Each entry in `detections.<cam>.<kit_index>.errors` (populated by
`cv_ingest/detection_data.py`'s `resolve_error()`) has:
```
{
  "error_type": "validation_error" | "wrong_part",
  "resolution": {"chosen_option": "system_error" | "process_error",
                 "comment": str | None, "resolved_at": iso str} | None,
  ...
}
```

## `history_data.py` — function contracts

### Filter/param parsing (all defensive — never raise on bad input, fall back to a sane default instead)

- `default_date_range()` → `(date_from, date_to)`, last 7 days
  inclusive of today (server UTC date).
- `parse_date_param(raw)` → `date | None`. `None` on missing/malformed
  input — caller falls back to the default range.
- `parse_table_id_param(raw)` → `int | None`. `None` means "All
  Tables" (empty/missing value, or unparseable).
- `parse_per_page_param(raw)` → clamped to `(10, 25)`
  (`ALLOWED_PER_PAGE`); anything else (including malformed) falls back
  to `DEFAULT_PER_PAGE = 10`.
- `parse_page_param(raw)` → `int >= 1`; malformed/negative/zero falls
  back to `1`.

### Listing

`list_history_activities(collection, table_id, date_from, date_to,
page, per_page)` → `(rows, total_count)`.

- `table_id=None` omits the table filter entirely (All Tables).
- Date range is matched against `created_at` (the activity's OWN start
  date — confirmed scope, not `stopped_at`). Built as an inclusive UTC
  range (`datetime.combine(date_from, min.time())` through
  `datetime.combine(date_to, max.time())`), compared as ISO strings
  directly in the Mongo query (not parsed in Python per-document) —
  this keeps filtering inside Mongo itself and leaves room for an index
  later if this collection grows large.
- `query["status"] = {"$in": ["completed", "completed-manually"]}` —
  defensive; a `"live"` document should never actually exist in this
  collection, but this guards against it anyway.
- Sorted `created_at` descending. Paginated via `.skip()`/`.limit()`.
- Each row is shaped by `_row_summary(doc)` into a flat dict — see
  below.

### Row shaping

- `_camera_progress(doc, cam_id)` → `{"completed": int,
  "quantity_required": int}`. **`completed = current_kit_index_cam{N} -
  1`** — confirmed display formula: `current_kit_index` is 1-based and
  overshoots by exactly 1 once a camera finishes all its kits (the
  "completion sentinel" — see `TSD_LIVE_KITTING_ACTIVITIES.md`'s
  "Completion semantics"), so a finished 70-unit run shows `70/70`, not
  the raw stored `71/70`.
- `_tally_errors(doc)` → `{"validation_error": int, "wrong_part": int,
  "system_error": int, "process_error": int}`. Walks
  `detections.<cam>.<kit_index>.errors` for **both cameras and every
  kit index** — this is the ONLY source counted; `wrong_part_cards` is
  explicitly NOT counted here (confirmed with client — counting both
  would double-count wrong_part occurrences relative to this
  resolved-error log). `validation_error`/`wrong_part` counts are
  tallied by `error_type`; `system_error`/`process_error` are tallied
  by `resolution.chosen_option`, on the SAME array, in the SAME pass —
  not two separate queries/scans. An entry with `resolution: None`
  (should not normally exist once an activity has moved to history —
  see `resolve_error()`'s own docstring) is defensively skipped for the
  `chosen_option` tally but still counted toward its `error_type`.
- `_row_summary(doc)` assembles the full row dict returned to
  `routes.py` — `id` (stringified `ObjectId`), `created_at`, table
  info, kit/edp/order fields, `status`, `cam1`/`cam2` (from
  `_camera_progress`), `errors` (from `_tally_errors`).

### Delete

`delete_activity(collection, activity_id, images_base_dir=None,
detection_image_dir=None)`:

- Always deletes the Mongo document first via `_to_object_id()` +
  `delete_one()`. Raises `ValidationError` if the id is malformed or
  matches nothing — `routes.py` turns this into a 400, never a 500.
- **Image-folder deletion is conditional and best-effort.** Only
  attempted when BOTH `images_base_dir` and `detection_image_dir` are
  given (routes.py always passes both in production; tests that only
  care about the Mongo side can omit them — this keeps the function's
  signature backward compatible with how it was originally called).
  When given: the document is fetched with `find_one()` **before** the
  Mongo delete (so its `table_id`/`created_at`/`kit_name`/
  `order_number` are available), the Mongo delete runs, and ONLY if
  that succeeds is the image folder removed. If the Mongo delete had
  failed, images are left untouched — never destroy images for a
  record that's still in the database.
- Image-folder removal never raises on filesystem errors (permissions,
  already-gone, etc.) — logged as a warning only. The record's Mongo
  deletion has already succeeded by that point; a filesystem cleanup
  hiccup should not be reported to the operator as a failed delete.

#### Image-folder deletion — path rebuild + the sanitizer-duplication caveat

The whole activity's images live under ONE folder covering both
cameras and every kit index:
```
<base_dir>/<detection_image_dir>/table_<id>/<date>/<kit_name>_<order_number>/
```
(see `TSD_LIVE_KITTING_ACTIVITIES.md`'s "Image storage" section for the
full nested scheme under this folder — `cam<N>/<kit_index>/<filename>`
below it). Deleting history removes this ONE folder in one
`shutil.rmtree()` call, which removes both cameras' images and every
kit index at once — this is exactly why the folder was structured this
way.

`_activity_image_folder(doc, images_base_dir, detection_image_dir)`
rebuilds this path from the document's own `table_id`/`created_at`/
`kit_name`/`order_number` — it does **not** read any stored
`image_path` field off the document (those are scattered three levels
deep across `events[]`/`errors[]`/`wrong_part_cards[]` and would need
scanning an unknown/variable structure just to find one common parent;
rebuilding directly from the four source fields is simpler and was the
client's own explicit call: *"dont complicate simple things"*).

**`_sanitize_path_segment()` is DUPLICATED from
`cv_ingest/detection_data.py`, not imported** — same function, copied
verbatim, per explicit client instruction to keep History fully
independent of other blueprints. **This is a real maintenance hazard,
flagged here on purpose:** if the SAVE-side sanitization logic in
`cv_ingest/detection_data.py` is ever changed, this DELETE-side copy in
`history_data.py` must be updated in lockstep, or a delete will
silently rebuild the wrong folder name and leave orphaned images on
disk with no error raised. There is no automated guard against this
drift — both files carry a docstring comment pointing at each other,
but nothing enforces it. Check both files any time either sanitizer is
touched.

Before removal, `_delete_activity_images()` runs the same
containment check used by the detection-image serve route
(`os.path.commonpath([images_root, resolved_path]) == images_root`) —
`shutil.rmtree()` is refused if the rebuilt path resolves outside the
configured images root, even under adversarial `kit_name`/
`order_number` input. If the folder doesn't exist at all (activity had
no images saved, or was already cleaned up some other way),
`_delete_activity_images()` is a silent no-op.

## Routes

### `GET /history`

Reads `table_id`, `date_from`, `date_to`, `per_page`, `page` from query
params via the parsing helpers above (all defensive — bad/missing
values fall back to defaults, never a 400). If EITHER date bound is
missing/malformed, BOTH fall back to `default_date_range()` together —
never a mix of one explicit bound and one defaulted bound. Computes
`total_pages` and clamps the displayed `page` to it (an out-of-range
page from stale filter state comes back with an empty result set
rather than being silently "corrected" to a different one). On
`PyMongoError`, renders with an empty list and a
`db_error` message, same convention as every other blueprint.

Pagination links are built with Jinja's `url_for('history.index',
page=N, **base_params)` — `base_params` bundles the current
table/date/per_page selection so each Prev/Next link preserves the
active filters. Verified this dict-unpack pattern renders correctly in
isolation; also verified an empty-string `table_id` in the resulting
URL (the "All Tables" case) round-trips back through
`parse_table_id_param()` to `None` correctly, not a parse error.

### `POST /history/<activity_id>/delete`

AJAX only. Calls `history_data.delete_activity()` with
`images_base_dir=current_app.config["BASE_DIR"]`,
`detection_image_dir=current_app.config["SETTINGS"]["live_kitting"]["detection_image_dir"]`
— always passes both, so every delete through this route also cleans
up images. Returns `{"success": true}` or `{"success": false, "error":
str}` (400 on `ValidationError`, 500 on `PyMongoError`) — same
JSON-error-contract convention used throughout the app.

## Frontend

`history-list.js`:
- **Created-at formatting** — deliberately mirrors
  `live-activities-list.js`'s `getTimezoneLabel()` function verbatim
  (client's explicit ask: match the activity card's format exactly).
  Splits date and time onto two separate lines within the same table
  cell (`<span class="history-table__created-date">` /
  `<span class="history-table__created-time">`) — done via two
  separate `Intl`/`toLocaleDateString`/`toLocaleTimeString` calls, NOT
  by formatting one combined string and splitting it apart (the
  project's own `getTimezoneLabel()` comment already warns that
  parsing an already-formatted string is fragile across
  locales/browsers — the same reasoning applies to splitting one).
  Root cause of an earlier scrollbar bug: a blanket `white-space:
  nowrap` on every `<td>` in `history.css` forced the combined
  date+time string onto one wide line. Fixed by overriding
  `white-space: normal` specifically on `.history-table__created` and
  making each of the two spans `display: block`, rather than loosening
  `nowrap` table-wide.
- **Delete** — plain `window.confirm()` (History has no existing
  inline-confirm-card pattern of its own the way the Live Kitting
  Activities card does — a native confirm is proportionate for a
  single-purpose row delete), then `POST` to the delete route. On
  success, removes the `<tr>` client-side rather than a full page
  reload, preserving the current filter/page state.

## Known gaps / next-session TODO

- **Auto-completion still does not write to `activity_history`** — see
  `FRD_HISTORY.md`'s own "Out of scope" note and
  `TSD_LIVE_KITTING_ACTIVITIES.md`'s "Known gaps" entry for the full
  detail. This is the single most important gap affecting History
  right now — until it's built, an activity can only ever reach this
  page via manual completion.
- **View Detailed Report / Download Report are disabled placeholders**
  — buttons render, do nothing. Separate future task, explicitly out
  of scope for this round.
- **Sanitizer duplication between `history_data.py` and
  `cv_ingest/detection_data.py`** (see "Image-folder deletion" above) —
  no automated test or lint rule catches drift between the two copies;
  purely a documented, hand-maintained invariant.
- **No pagination/filter AJAX** — every filter change or page
  navigation is a full page reload (client's explicit call: simpler,
  URL-shareable state, matches this app's existing non-SPA HMI grain).
  If a future round wants in-place updates, this would need revisiting
  along with how `url_for(**base_params)` currently builds pagination
  links server-side.
