# TSD — Live Kitting Activities

Technical spec for the Live Kitting Activities blueprint: routes, MongoDB collections/schemas, data flow, and known gaps. For functional behavior, see `FRD_LIVE_KITTING_ACTIVITIES.md`.

## File map

```
app/blueprints/live_kitting_activities/
├── __init__.py                  # blueprint registration (unchanged since Task 1 stub)
├── routes.py                    # all HTTP routes for this blueprint
└── activities_data.py           # MongoDB data access + validation

app/templates/live_kitting_activities/
├── index.html                   # landing page - activity cards
├── create.html                  # step 1 of create flow
├── camera_check.html            # step 2 of create flow
└── monitor.html                 # single-activity monitor page

app/static/css/
├── live-activities.css          # landing + create + camera-check (shared page-specific styles)
└── monitor.css                  # monitor page only, including the full-bleed layout override

app/static/js/
├── live-activity-create.js      # step 1 page: Enter-to-advance focus, EDP AJAX lookup, busy-check on submit
├── live-activities-list.js      # landing page: local-time formatting, Complete Manually inline confirm + AJAX
└── monitor.js                   # monitor page: live-ticking elapsed-time timers
```

## MongoDB collections

Two collections, both under `mongodb.collections` in `config.yaml`:

```yaml
mongodb:
  collections:
    current_kits: "current_kit_configurations"   # existing - READ ONLY from this blueprint
    live_activities: "live_activity_details"      # new
    activity_history: "activity_history"           # new
```

### `live_activity_details` (one doc per in-progress or just-created activity)

```
{
  "table_id": int,
  "table_name": str,                 # denormalized at creation time
  "kit_id": ObjectId,                 # ref into current_kit_configurations
  "kit_name": str,                    # denormalized at creation time
  "edp_number": str,
  "order_number": str,                # free text, no format validation
  "quantity_required": int,           # "units to pack" - the activity's target, entered at creation
  "parts_configured": [ ... ],        # full parts array copied fresh from the kit doc at
                                       # creation time - never trust a parts array round-tripped
                                       # through the browser across the 2-step create flow
  "camera_images": {
      "cam1": str,                    # static placeholder path, e.g. "images/camera-check-cam1-placeholder.png"
      "cam2": str
  },
  "current_kit_index_cam1": int,      # progress counter, default 1 at creation - "N/target" card
  "current_kit_index_cam2": int,      # display. NOT yet driven by real detection events.
  "status": "live" | "completed" | "completed-manually",
  "created_at": iso str,              # UTC. Activity start time - basis for all elapsed-time display.
  "updated_at": iso str,
}
```

**Uniqueness/business rule:** only one document with `status: "live"` is allowed per `table_id` at a time. Enforced in `activities_data.py` (`is_table_busy` / `get_live_activity_for_table`), checked at two points — see "Table-busy enforcement" below.

### `activity_history` (completed / completed-manually activities)

Same shape as `live_activity_details`, plus:
```
{
  ...(all fields above, status updated)...
  "stopped_at": iso str,       # UTC, when it was moved to history
  "stop_reason": str | null,   # free text from the Complete Manually confirmation, or null if blank
}
```

`complete_activity_manually()` copies the **full source document** (not a reconstructed subset) into this collection, so any field added to `live_activity_details` later is automatically carried into history without this function needing to know about it. The original document's `_id` is dropped before insert (history gets its own `_id`) and the source document is deleted from `live_activity_details` in the same call.

## Routes

All under the `live_kitting_activities` blueprint, prefixed `/live-kitting-activities`.

| Route | Method | Purpose |
|---|---|---|
| `/live-kitting-activities` | GET | Landing page — lists all `status: "live"` activities |
| `/live-kitting-activities/create` | GET | Step 1 form |
| `/live-kitting-activities/lookup-edp` | POST (AJAX) | `{table_id, edp_number}` → `{success, kit_id, kit_name}` or `{success: false, error}`. Exact match only, scoped to `table_id`. |
| `/live-kitting-activities/check-table-busy` | POST (AJAX) | `{table_id}` → `{success, busy, order_number?}`. Called on Step 1's Next click only (not on table select) — a UX check, not the enforcement point. |
| `/live-kitting-activities/create/camera-check` | GET | Step 2 — reads Step 1's data from query params, no DB write. Guarded by `_require_built_table()`. |
| `/live-kitting-activities/create/finalize` | POST | Writes the `live_activity_details` document. Re-validates everything server-side and re-checks table-busy (race-safe). Redirects to the new activity's monitor page on success. |
| `/live-kitting-activities/<activity_id>/complete-manually` | POST (AJAX) | `{reason?}` → `{success}` or `{success: false, error}`. Moves the doc to `activity_history`. |
| `/live-kitting-activities/<activity_id>/monitor` | GET | Monitor page for one activity. 404 on malformed or nonexistent `activity_id`. |

### Table registry guard

Same contract as `configuration/routes.py`: `_get_tables()` / `_get_table(table_id)` / `_require_built_table(table_id)`, duplicated in this blueprint's `routes.py` rather than imported (blueprints stay decoupled). A JSON-friendly variant (`_require_built_table_json`, returns `None` instead of aborting) is used in AJAX endpoints so they can reply with a JSON error instead of an HTML 404 page.

## Data flow: create → finalize

1. **Step 1 (create.html)** collects station/order/EDP/units in the browser. EDP lookup and the busy-check are both AJAX calls against the live database — nothing is written yet.
2. On Next, all of Step 1's values are passed as **query parameters** to `/create/camera-check` (no DB write, no session/temp collection — plain URL state).
3. **Step 2 (camera_check.html)** re-renders those values into **hidden form fields**. Two static camera images are shown (`CAMERA_CHECK_IMAGES` constant in `routes.py`).
4. On **Create Activity**, the hidden form POSTs to `/create/finalize`. This is the only point that touches the database for creation:
   - Re-validates every field (`activities_data._validate_create_payload`) — nothing from the two-step browser flow is trusted.
   - Re-checks table-busy (protects against two browser tabs/sessions racing the same table).
   - Re-fetches the kit by `kit_id` + `table_id` from `current_kit_configurations` to get an **authoritative** `parts_configured` snapshot — never uses any parts data that might have passed through the browser.
   - Inserts the `live_activity_details` document with `current_kit_index_cam{1,2}: 1` and `status: "live"`.
   - Redirects to `/live-kitting-activities/<new_id>/monitor`.

On validation failure or a `PyMongoError` at finalize, the camera-check page is re-rendered with the same data and an inline error — nothing typed is lost (no flash-message system exists yet, same known gap as the rest of the app).

## Monitor page data shaping

`activities_data.build_monitor_view(doc)` shapes a raw `live_activity_details` document into the template's per-camera structure:

- Splits `parts_configured` by `camera` field (`cam1`/`cam2`).
- Every part's detected `count` is **hardcoded to 0** in this build — not yet wired to real detection events. A part is "completed" once `count >= quantity_required`; since count is always 0, every part currently renders as pending. This is the one deliberate stub in an otherwise-final UI — see "Known gaps" below.
- **Progress percentage is NOT derived from part quantities.** It's `current_kit_index_cam{N} / quantity_required` (the activity's overall target) — kits packed so far out of the target. This was a real bug in an earlier pass (summing individual part quantities gave misleading numbers like "0/6" instead of "0/50") — fixed to read the activity's own target field.

## Timezone and elapsed-time handling

Everything time-related is stored in UTC (`created_at`, `stopped_at`) and converted **client-side** for display, since the app can be viewed from multiple physical locations:

- **Landing page card start time** (`live-activities-list.js`, `formatLocalStartTime`): 12-hour clock via `toLocaleTimeString`, plus a timezone label resolved via `Intl.DateTimeFormat().formatToParts()` (not string-splitting a rendered string, which broke on at least one real browser during development). Tries `shortGeneric` first (gives a named zone like "India Time" or "ET"), falls back to `short` (gives a GMT offset like "GMT+5:30"), and falls back to the raw IANA zone id (e.g. "Asia/Kolkata") as a last resort that's never blank.
- **Monitor page timers** (`monitor.js`): every element with `[data-activity-timer]` (the header's "Total time" plus both camera panels' timers) independently computes `Date.now() - new Date(created_at).getTime()`, ticking every second via `setInterval`. All three currently point at the same `created_at` value — see "Known gaps."
- If `created_at` is missing or unparseable, the timer shows `--:--:--` and logs a console warning rather than silently displaying a misleading number (an earlier version of this code showed what looked like the current wall-clock time when `created_at` was invalid, which was mistaken for a bug in the timer logic itself rather than bad input data).

## Full-bleed monitor layout

The monitor page needs to fill the full viewport width/height below the top nav, but every other page in the app uses `.app-main` (from `layout.css`) which is capped at `max-width: 1200px`, centered, padded, and bordered.

Rather than edit the shared `.app-main` rule (which would affect every page), `base.html` exposes an empty `{% block main_class %}` on the `<main>` tag:
```html
<main class="app-main{% block main_class %}{% endblock %}">
```
`monitor.html` is the only template that overrides it:
```html
{% block main_class %} app-main--full-bleed{% endblock %}
```
`monitor.css` then defines `.app-main.app-main--full-bleed` to cancel the max-width/margin/padding/border, and — critically — sets `display: flex; flex-direction: column` on that combined selector so `.app-main__top-row` (the Back button row) and `.monitor-page` correctly divide the available height via flexbox. (An earlier version used `height: 100%` on `.monitor-page` without making `.app-main` a flex container; since `.app-main` is a plain block by default, `height: 100%` measured against the wrong box and ignored the top-row's own height, causing a page-level scrollbar — exactly what the HMI fit-to-screen requirement forbids. Fixed by mirroring the same flex pattern `body` already uses at the outer level.)

No other page loads `monitor.css`, and the override only fires when both classes are present, so this cannot leak into any other page's layout.

## Known gaps / next-session TODO

- **Detection counts are static (0) for every part** — the single biggest gap. Wiring this up needs a decision on transport (the original plan, before this build's scope narrowed to UI-first, was: separate CV process → HTTP POST ingest endpoint → Mongo persistence → some form of live push to the browser). Flask-SocketIO is still not wired anywhere in the app; this blueprint's live-looking elements (timers, progress bars) currently update via client-side JS against server-rendered static data, not a real push channel.
- **No per-kit timer** — both camera panels' timers and the header's Total Time all show the same activity-level elapsed time. A true per-kit timer (resetting when `current_kit_index_cam{N}` increments) needs a `kit_started_at`-style field that doesn't exist yet, deferred until detection events are wired.
- **"See current settings" and "History" buttons are unwired placeholders** — behavior not yet defined.
- **No red/success color tokens in `variables.css`** — the Complete Manually button and the monitor page's completed-section/card tinting use hardcoded hex values (`#dc2626` family for danger, `#0f6e56`/`#1d9e75` family for success) rather than a proper `--color-danger`/`--color-success` custom property, since neither exists yet. Flagged for the client to decide whether these should become real tokens.
- **No `.btn` class existed anywhere in the shared CSS chain** before this build — `live-activities.css` defines `.btn`/`.btn--primary`/`.btn--secondary`/`.btn--danger`/`.btn--small` locally. If a global button class is introduced elsewhere later, this should be reconciled to avoid duplication.
- Camera-check images are fixed static placeholders (`CAMERA_CHECK_IMAGES` constant in `routes.py`) — real per-camera capture is out of scope for this build.
