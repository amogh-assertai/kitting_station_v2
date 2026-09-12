# FRD — History

Functional requirements for the History section: the listing page, its
filters, and the delete action. Built this session — previously a
placeholder ("Historical records/reporting will be built in a later
task.").

## Concept

History is a **read-only + delete** browsable record of past kitting
activities — every activity that has finished, either by hitting its
full quantity on both cameras or by being stopped early ("Complete
manually" on the Live Kitting Activities landing page). A currently
**live** activity is never shown here — it only appears once it's
finished and has moved into the `activity_history` collection.

There is no independent create/edit path for History — it has no data
of its own; every row here is a snapshot copied over at the moment an
activity completed.

## Listing page

Reached from the top nav's **History** link.

### Filters

- **Table** — dropdown, defaults to **Table 1**. Includes an **"All
  Tables"** option.
- **Date range** — From/To date pickers, defaults to the **last 7
  days** (inclusive of today). Matches against the activity's own
  **start date** (`created_at`) — NOT when it finished/was stopped.
- Filters apply via a normal page reload (Apply button) — the current
  filter selection is reflected in the URL, so a filtered view can be
  bookmarked/shared.

### Table columns

| Column | Shows |
|---|---|
| Created | Date and time the activity was started, in the viewer's local time zone, 12-hour clock — date on one line, time (+ zone) on the line below, matching the Live Kitting Activities card's own "Started" format |
| Kit / EDP | Kit name, with the EDP number shown directly below it in the same column |
| Order # | The order/PO number |
| Completion | Cam 1 and Cam 2 progress, each as "completed/required" (e.g. "Cam1: 50/70", "Cam2: 55/70") |
| Status | "Completed" or "Completed Manually" |
| Errors | Four counts, shown in two neat groups: Validation Errors / Wrong Part Errors (by error type), and System Errors / Process Errors (by how the operator resolved each error) |
| Actions | View Report, Download Report, Delete |

Rows are sorted **newest first** (latest activity at the top).

### Error counts — what they mean

- **Validation Errors** / **Wrong Part Errors** — how many of each type
  of red-screen error occurred during this activity, across both
  cameras and every kit made.
- **System Errors** / **Process Errors** — of all the errors that
  occurred, how many the operator resolved by picking "System Error" vs
  "Process Error" when clearing the red screen. These are a different
  axis than the type counts above (an error's TYPE is what it was; its
  resolution CHOICE is why the operator says it happened) — a single
  activity's four numbers don't need to add up to each other.

### Pagination

- **10 activities per page by default**, operator can choose **up to
  25 per page**.
- Standard page-number navigation (Prev / Next, current page indicator,
  total count).

### Actions

- **View Detailed Report** — placeholder for now (button present,
  disabled/no-op). Full report view is a separate future task.
- **Download Report** — placeholder for now, same as above.
- **Delete** — permanently removes the activity record from History.
  **Also deletes every saved image for that activity** (both cameras,
  every kit made during the run) — a history record and its images are
  deleted together, since a record with no way to view its images, or
  orphaned images with no record, are both useless. This is a hard
  delete, not an archive/soft-delete — there is no way to recover a
  deleted activity. Confirmation is required before deleting.

## Out of scope (not yet built)

- View Detailed Report / Download Report — buttons exist, not wired to
  a real report yet.
- Optional reviewer/inspector comment text on a history record —
  discussed, explicitly deferred to a later round.
- **Auto-completion does not yet move an activity into History.**
  Right now the ONLY way an activity reaches History is the operator
  clicking "Complete manually" on the Live Kitting Activities page.
  Hitting `quantity_required` on both cameras marks each camera
  "complete" on the live monitor page, but does **not** currently move
  that activity into `activity_history` — it stays visible (and stuck)
  on the Live Kitting Activities landing page indefinitely. This was
  scoped as part of a future round and is a known, confirmed gap — not
  an oversight to be silently worked around.
