# FRD — History

Functional requirements for the History section: the listing page, the
Activity Report (per-activity kit-by-kit analytics), the Kit Detail
drill-down, filters, and the delete action. Listing page built first
session; Activity Report and Kit Detail built a following session —
previously a placeholder ("Historical records/reporting will be built
in a later task.").

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

- **View Detailed Report** — **built** (was a placeholder). Opens the
  Activity Report — see its own section below. No longer disabled.
- **Download Report** — still a placeholder (button present,
  disabled/no-op). Separate future task.
- **Delete** — permanently removes the activity record from History.
  **Also deletes every saved image for that activity** (both cameras,
  every kit made during the run) — a history record and its images are
  deleted together, since a record with no way to view its images, or
  orphaned images with no record, are both useless. This is a hard
  delete, not an archive/soft-delete — there is no way to recover a
  deleted activity. Confirmation is required before deleting.

## Activity Report

Reached by clicking **View Report** on any listing row. One page,
scrolling, no pagination — everything about one completed activity in
one place: header, aggregate stats, and a kit-by-kit visual breakdown.

### Header

Kit name as the page title, plus a labeled grid: Table (id + name),
Order #, EDP Number, Qty Required, Status (Completed / Completed
Manually, same badge styling as the listing page), Started (local
time, 12-hour clock + timezone, same format as the Live Kitting
Activities card), and — only if the activity was stopped manually —
Stopped time and Stop Reason.

### Summary

Split into two side-by-side columns, **Camera 1 left / Camera 2
right** (client's explicit ask, after an earlier single shared-column
version felt too cramped once activities started running 70–240
kits):

- Each column: that camera's own Validation Error count, Wrong Part
  Error count, and a small timing table (Avg / Min / Max, for both
  Total Kit Time and Active Time — see "Kit-level timing" below for
  what these mean).
- Below both columns, a shared strip: total System Errors, total
  Process Errors, and Total Logged (all errors, both cameras combined).

### Legend

A small key block explaining the four kit-color states used
throughout the Kits section and the S/P badges — see "Kit color rules"
below. Shown once, near the top of the Kits section.

### Kits — the circle grid

**Not a table, not big cards** (an earlier round shipped larger kit
cards; client's explicit follow-up request replaced them with small
circles once real activities started running 70–240 kits and the
cards took up far too much scrolling). Same **Camera 1 left / Camera 2
right** column split as Summary.

Each kit is one small circle, numbered, color-coded:

| Color | Meaning |
|---|---|
| 🟢 Green | Clean — no issues at all |
| 🟡 Yellow | A part was undercounted, but the undercount alert was OFF for that part at the time — so no red screen ever fired, but the shortfall is real and visible here |
| 🟣 Purple | A part was missing, overcounted, or an unrecognized ("wrong") part was detected — again with the relevant alert OFF, so nothing was ever logged as an error, but the issue happened |
| 🔴 Red | An actual logged error exists — the relevant alert was ON, a red screen fired, and the operator resolved it (System Error or Process Error) |

**A kit can show BOTH a yellow-type and a purple-type issue at once**
(e.g. one part silently undercounted, a different part silently wrong)
— when that happens, the circle's border shows **purple** (judged more
severe), but nothing about the yellow issue is hidden; it still counts
and still shows in the kit's own detail page.

**S/P badge** — hangs off the top-right corner of a **red** circle
only (silent/yellow/purple kits never get this badge — there's no
resolution to report). Shows which way the operator resolved the
kit's error(s):
- One logged error total → just the letter: **S** (System Error) or
  **P** (Process Error).
- Two or more logged errors on the same kit → the letter for **P**
  wins if ANY of them were resolved as Process Error (even if
  outnumbered by System Error resolutions), shown as `P+N` where N is
  the total count minus one — e.g. 2 System + 1 Process resolutions on
  one kit shows **P+2**, not S+2 or S+1.

Circles and their font are sized roughly 40% larger than the very
first shipped version, after the first version was judged too small to
read comfortably.

Clicking a circle opens that kit's own **Kit Detail** page (see
below).

## Kit Detail

Reached by clicking any kit circle on the Activity Report. One kit, one
camera, full detail.

### Layout, top to bottom (confirmed order)

1. **Header** — breadcrumb-style: which camera, Kit #, Order #, Kit
   Name. A "← Back to Report" link returns to the Activity Report.
2. **Analytics** — this one kit's own Total Kit Time, Active Time, and
   Avg Detection Gap (see "Kit-level timing" below).
3. **Wrong Parts Detected** — shown only if this kit had an
   unrecognized-part detection. One entry per distinct wrong part name
   (grouped, not one row per individual detection), with every image
   captured of that wrong part, and its resolution (System/Process) if
   the wrong-part alert was on and it was actually logged.
4. **Errors & Anomalies** — shown only if this kit had a
   missing/undercount/overcount issue, logged or silent. Shows which
   part(s), the issue type(s), the resolution if one was logged, and
   the validation snapshot image if one exists (only present when the
   issue was actually logged — a purely silent issue never had a
   red-screen moment to capture an image from).
5. **Parts** — one card per part configured for this kit on this
   camera, each showing: the part name, a found/required count badge
   (colored using the same 4-state rule as the kit circles, but judged
   at the PART level instead of the whole-kit level), and every
   detection-event image captured for that specific part. A part with
   no detections at all shows "No images captured" rather than an
   empty gap.

### Images — click to view full-size

Every image thumbnail on the Kit Detail page (wrong-part section,
anomalies section, and every part card) opens a full-screen viewer on
click:

- **Zoom** — click the image to toggle a larger view, or use the mouse
  scroll wheel to zoom continuously in/out.
- **Navigate** — Left/Right arrow keys, or on-screen prev/next arrows,
  move through **every image on the whole page** as one continuous
  sequence — not just the images inside the card you clicked into.
  Reaching the last image and pressing Next wraps back around to the
  first (and vice versa for Prev), rather than stopping dead at either
  end.
- **Close** — the × button top-right, clicking outside the image, or
  the Escape key.

### Kit-level timing — what each number means

- **Total Kit Time** — from when this kit's clock actually started
  (either activity creation, for kit 1, or the moment the PREVIOUS kit
  was validated, for kit 2+) to when THIS kit was validated. Includes
  any idle time before the operator even started placing parts.
- **Active Time** — from the FIRST part detected in this kit to when
  it was validated. Always ≤ Total Kit Time; the gap between the two
  is exactly that idle time.
- **Avg Detection Gap** — the average time between one detection and
  the next, within this one kit only (never averaged across a kit
  boundary).
- A kit that was never validated (e.g. the very last, in-progress kit
  of a manually-stopped activity) shows blank/dash timing rather than
  a misleading zero.

## Out of scope (not yet built)

- **Download Report** — button exists, still a disabled placeholder.
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
