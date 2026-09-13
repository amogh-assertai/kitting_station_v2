# TSD — History

Technical spec for the History blueprint. For functional behavior, see
`FRD_HISTORY.md`.

## File map

| File | Role |
|---|---|
| `app/blueprints/history/__init__.py` | Defines `history_bp` (Blueprint, no `url_prefix`); unchanged |
| `app/blueprints/history/routes.py` | `GET /history` (listing), `POST /history/<activity_id>/delete`, `GET /history/<activity_id>/report` (Activity Report), `GET /history/<activity_id>/report/<cam_id>/<kit_index>` (Kit Detail) |
| `app/blueprints/history/history_data.py` | All MongoDB filtering/pagination/error-tally/delete logic, PLUS `build_activity_report()` and `build_kit_detail()` and their supporting functions |
| `app/templates/history/index.html` | Listing page |
| `app/templates/history/report.html` | NEW — Activity Report: header, summary stats, legend, kit circle grid |
| `app/templates/history/kit_detail.html` | NEW — Kit Detail: analytics, wrong-part section, anomalies section, per-part cards, lightbox markup |
| `app/static/css/history.css` | Listing page styling, page-scoped |
| `app/static/css/activity-report.css` | NEW — Activity Report styling: two-column summary/kit layout, circle grid, chip badges |
| `app/static/css/kit-detail.css` | NEW — Kit Detail styling: analytics strip, anomaly boxes, part cards, lightbox |
| `app/static/js/history-list.js` | Created_at formatting + delete confirm/AJAX |
| `app/static/js/activity-report.js` | NEW — duration/timestamp formatting (shared convention, reused on Kit Detail too), circle click → navigate to Kit Detail |
| `app/static/js/kit-detail.js` | NEW — image lightbox: click-to-open, wraparound prev/next across the WHOLE page, zoom (click-toggle + scroll wheel), escape/backdrop-click/× to close |

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

### Activity Report — `build_activity_report(doc)`

Takes an already-fetched `activity_history` document, returns
`{"activity": {...header fields...}, "summary": {...}, "cards": [...]}`
— everything the report page needs from ONE document, no extra Mongo
calls.

**Core insight the whole design rests on** (confirmed by reading
`cv_ingest/detection_data.py` directly): `detections.<cam>.<kit_index>.errors`
only ever gets an entry via `resolve_error()`, and `resolve_error()`
only ever runs on an issue that was raised because the relevant alert
switch was ON at that moment. There is exactly one write path into that
array, always switch-gated. **Presence/absence of a logged error entry
is therefore a complete, sufficient signal for "was the alert on or
off"** — this module never reads `camerawise_alert_config` itself to
determine card color, only ever checks whether an error was actually
logged.

Meanwhile `detections.<cam>.<kit_index>.events` always tags every
detection with `"outcome": "matched" | "neglected" | "wrong_part"`
regardless of whether the wrong-part alert was on (confirmed: even a
switched-off wrong-part still gets tagged `wrong_part` in its own event,
even though it visually plays as a normal/green detection at the time).
And `part_counts_cam{N}` / `parts_configured` are always present and
complete, letting missing/undercount/overcount be recomputed from raw
data independent of whether `alert_validation_error` was ever on.

So: recompute what SHOULD have been flagged from raw data (the
switch-independent issue list), compare against what WAS actually
logged (which only exists if the switch was on) — anything in the
"should have" set not covered by the "was logged" set is exactly the
silent/alert-off case.

**Duplicated from `cv_ingest/detection_data.py`, not imported** — same
independence convention as the image sanitizer above:
- `_validation_issues_switch_independent(doc, cam_id, kit_index)` — a
  direct port of `_find_validation_issues()`. Same elif-chain
  precedence: `alert_missing and found==0` → `missing`; `elif
  alert_undercount and 0<found<required` → `undercount`; `elif
  alert_overcount and found>required` → `overcount`. **This precedence
  matters**: a part with `quantity_required=1` can only ever go from
  1→0 when short a unit, which the missing branch catches FIRST — it
  can never be classified as `undercount`.
- `_get_part_count(doc, cam_id, kit_index, part_name)` — one-liner,
  reads `part_counts_cam{N}.<kit_index>.<part_name>`.
- `_neglected_part_names(doc, cam_id)` — camera-scoped neglect set.
- `_wrong_part_events(doc, cam_id, kit_index)` — every event tagged
  `outcome=="wrong_part"` for this kit/camera.
- `_logged_errors_for_kit(doc, cam_id, kit_index)` — raw
  `detections.<cam>.<kit_index>.errors` array, as-is.

**`_kit_camera_card(doc, cam_id, kit_index)`** — the core per-card
derivation. Builds `badges` (one entry per distinct issue, logged OR
silent) and the border `color`, using this exact precedence: **RED**
(≥1 logged error, either type) **> PURPLE** (silent wrong-part, OR
silent missing/overcount) **> YELLOW** (silent undercount) **>
GREEN**. A logged error's own `issues` list (verbatim, unchanged from
when it was raised — confirmed by reading `validate_kit`'s write path
directly) is matched against the switch-independent issue list on
`(part_name, issue)` via `_issue_matches_logged()`, so a part already
covered by a logged error is never ALSO double-counted as a silent
badge for the same issue.

**`_chip_badge_label(logged_errors)`** — the small S/P badge shown on a
red circle (client's own confirmed math, verified with dedicated
tests):
- 0 logged errors → `None` (no badge — never shown on
  purple/yellow/green cards).
- Exactly 1 logged error → bare letter, no `+N` suffix (`"S"` or
  `"P"`).
- 2+ logged errors → **`"P"` wins the DISPLAYED letter whenever at
  least one is resolved `process_error`**, even if outnumbered by
  `system_error` resolutions; count shown is `total - 1`. E.g. 2
  system + 1 process on one kit → `"P+2"`, never `"S+2"` or `"S+1"`.

**Timing** — `_kit_timing(doc, cam_id, kit_index)` reads
`actual_kit_start_time`/`first_part_detected_time`/`validated_at`,
**all three already stored on THIS SAME kit index's own timing
record** — confirmed by reading `cv_ingest/detection_data.py`'s
`validate_kit()` directly before building this: kit N's
`actual_kit_start_time` is stamped either at activity creation (kit 1)
or at the exact moment kit N-1 is validated (kit 2+), but EITHER WAY
onto kit N's OWN record at that moment. There is **no cross-kit
lookup** needed anywhere in this module, for any kit including kit 1 —
this was verified deliberately rather than assumed, after an initial
wrong assumption that kit 1 would need special-casing.
  - Total Kit Time = `validated_at − actual_kit_start_time`.
  - Active Time = `validated_at − first_part_detected_time`.
  - Both `None` (not zero) if the kit was never validated.
- `_avg_detection_gap_seconds(doc, cam_id, kit_index)` — mean of
  consecutive diffs across that kit's own sorted `events[].created_at`
  only; `None` with fewer than 2 events.

**`_build_summary(cards)`** — aggregates across all cards into
`error_counts` (total, by-camera-by-type, system/process) and `timing`
(avg/min/max for Total Kit Time and Active Time, computed BOTH per-camera
and activity-wide — client's explicit ask for both views).

### Kit Detail — `build_kit_detail(doc, cam_id, kit_index)`

Same "one document, no extra queries" principle. Raises
`ValidationError` if this `(cam_id, kit_index)` has no record on the
document at all (bad/stale URL) — `routes.py` turns this into a 404.

Returns `{"header", "analytics", "wrong_part_section",
"anomalies_section", "part_cards"}`:

- **`wrong_part_section`** — wrong-part events GROUPED by distinct
  `detected_part` name (not one entry per raw event — matches this
  app's own established convention elsewhere of grouping repeat
  detections of the same unrecognized part). Each group carries every
  image for that part name and, if a `wrong_part` error was actually
  logged for this kit, that error's resolution — client's confirmed
  data model: at most ONE active `wrong_part` error exists per
  kit+camera (the camera locks on the first occurrence), so "is a
  wrong_part error logged for this kit at all" is the right question,
  not "does this specific event have its own logged twin."
- **`anomalies_section`** — `None` if the kit is clean. Otherwise:
  if a `validation_error` was logged, shows exactly its own `issues`
  list, resolution, and `image_path` (the validation snapshot). If NO
  error was logged but a switch-independent issue exists anyway
  (silent case), shows those issues with no resolution and no image
  (nothing was ever captured, since no red screen ever fired). Silent
  undercount alone is still included here — unlike the kit-circle
  border color (which treats silent undercount as its own, lower,
  yellow tier), Kit Detail's anomalies section shows ALL validation-type
  issues together regardless of severity tier.
- **`part_cards`** — one per `parts_configured` entry for this camera,
  each with `found`/`required`, a `color` from `_part_card_color()`
  (same 4-state logic as the kit circle, applied at the PART level
  instead of whole-kit), and every one of that part's own detection
  images via `_events_for_part()`.
- **`_image_url(image_path)`** — builds `/api/detection-image/<path>`
  by plain string interpolation, matching `cv_ingest/routes.py`'s own
  convention exactly (NOT `url_for()` — this is a different blueprint,
  and the route itself is a fixed, known path). Returns `None` (not a
  broken `<img>` tag) when there's no `image_path` to build from.

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

### `GET /history/<activity_id>/report`

Single `find_one()` by id (404 on malformed id or missing document, via
`history_data.get_activity_by_id()`), then `build_activity_report(doc)`,
rendered into `history/report.html`. No extra queries.

### `GET /history/<activity_id>/report/<cam_id>/<int:kit_index>`

`cam_id` validated against `history_data.CAM_IDS` before touching
anything (404 on an invalid value). Same single `find_one()`, then
`build_kit_detail(doc, cam_id, kit_index)`, rendered into
`history/kit_detail.html`. A `ValidationError` from `build_kit_detail`
(kit_index has no data at all — bad/stale link) becomes a 404.

## Frontend

`history-list.js` (listing page only):
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

`activity-report.js` (Activity Report page; also loaded on Kit Detail
for its shared duration/timestamp formatters):
- `getTimezoneLabel()`/timestamp formatting — same convention as
  `history-list.js`, kept consistent across all three History pages.
- `formatDuration(totalSeconds)` — renders `Xs` / `Xm Ys` / `Xh Ym`
  from a plain seconds float. Applied to every `.report-duration
  [data-seconds]` element on the page. **Must explicitly guard for the
  literal string `"None"`**, not just an empty string — Jinja renders
  Python's `None` into an HTML attribute as the literal text `"None"`,
  which `parseFloat` would otherwise happily turn into `NaN` rather
  than a clean "no value" — this was tested explicitly, not assumed.
  Zero seconds renders as `"0s"`, never treated as "missing."
- Kit-circle click → `window.location.href = circle.dataset.detailUrl`
  (a real `url_for('history.kit_detail', ...)` link built server-side,
  not constructed in JS) — navigates to that kit's Kit Detail page.

`kit-detail.js` (Kit Detail page only) — image lightbox:
- Collects EVERY `.image-thumb` on the page (wrong-part section,
  anomalies section, every part card) into ONE flat array in DOM
  order. Left/Right arrow keys and the on-screen prev/next buttons
  move through this WHOLE sequence, not just the clicked card's own
  images — client's explicit scope: an operator should be able to
  arrow through every image on the kit without closing and reopening
  per card. Wraps around at both ends (Next on the last image loops to
  the first, and vice versa) rather than stopping dead.
- Zoom: click the lightbox image to toggle 1×/2×, or scroll wheel to
  zoom continuously between 1× and 4× — plain CSS `transform: scale()`,
  no external library. Zoom resets to 1× every time the lightbox is
  reopened.
- Close: × button, clicking the dimmed backdrop (not the image itself
  — clicking the image toggles zoom instead), or Escape.

**Confirmed, fixed bug — lightbox rendering open on page load:** the
lightbox `<div>` used `hidden` (the HTML boolean attribute) to start
closed, but its own CSS rule (`.lightbox { display: flex; ... }`) has
equal specificity to the browser's built-in `[hidden] { display: none
}` rule, and author stylesheets load AFTER the browser's default
styles — so `display: flex` won and the lightbox rendered fully open,
dimming the whole page, from the very first load, with the visible ×
button appearing completely unresponsive as a result (nothing was
un-hiding it on the next click either, since the underlying CSS
conflict never went away). Fixed with three layers of defense, not
just one:
  1. `.lightbox[hidden] { display: none; }` — explicit, higher-priority
     CSS rule.
  2. An inline `style="display: none;"` alongside `hidden` directly in
     `kit_detail.html`'s markup — inline styles beat any stylesheet
     rule regardless of source order, the strongest possible guarantee.
  3. `openLightbox()`/`closeLightbox()` in the JS now explicitly set
     `lightbox.style.display` too, not just the `hidden` attribute —
     removes any reliance on CSS cascade behavior at all, in any
     browser.
Flagged here explicitly since this is a real, subtle CSS trap (`hidden`
+ any `display` rule on the same selector) that could recur if a future
page reuses a `hidden`-toggled element pattern without the same
explicit-`display` discipline.

## Known gaps / next-session TODO

- **Auto-completion still does not write to `activity_history`** — see
  `FRD_HISTORY.md`'s own "Out of scope" note and
  `TSD_LIVE_KITTING_ACTIVITIES.md`'s "Known gaps" entry for the full
  detail. This is the single most important gap affecting History
  right now — until it's built, an activity can only ever reach this
  page via manual completion.
- **Download Report is still a disabled placeholder** — button
  renders, does nothing. View Report is now fully built (Activity
  Report + Kit Detail). Separate future task.
- **Sanitizer duplication between `history_data.py` and
  `cv_ingest/detection_data.py`** — TWO separate copies now, not one:
  the image-path sanitizer (`_sanitize_path_segment`, used for image
  deletion) AND the switch-independent issue-detection logic
  (`_validation_issues_switch_independent`, a port of
  `_find_validation_issues()`, used for Activity Report/Kit Detail).
  Neither is imported, both are duplicated verbatim per the client's
  explicit "keep History independent" instruction. No automated test
  or lint rule catches drift between either pair of copies — purely a
  documented, hand-maintained invariant. Check BOTH files any time
  EITHER of these pieces of logic changes in `cv_ingest/detection_data.py`.
- **No pagination/filter AJAX** on the listing page — every filter
  change or page navigation is a full page reload (client's explicit
  call: simpler, URL-shareable state, matches this app's existing
  non-SPA HMI grain). Activity Report and Kit Detail are single-page,
  no pagination of their own.
- **Kit Detail has no "next/prev kit" navigation of its own** — the
  only way back is the "← Back to Report" link; there's no direct
  kit-to-kit stepping without returning to the circle grid first. Not
  requested, just noting the gap.
