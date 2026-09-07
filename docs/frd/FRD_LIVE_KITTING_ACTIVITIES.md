# FRD — Live Kitting Activities

Functional requirements for the Live Kitting Activities section:
**landing page**, **create activity flow (station → camera check)**, the
**monitor page**, and **live detection ingest**. Currently applies to
**Table 1 (HVGKC-CELL) only**.

## Concept

A **kitting activity** is one run of packing a specific kit, on a
specific table, against a specific order. Only **one live activity per
table** is allowed at a time.

Part counts on the monitor page update live from a local camera/AI
detection system (DeepStream) mounted at each table, one camera per
side (Cam 1, Cam 2). Everything camera-related — progress, timers,
sound, completion — happens **independently per camera**, unless stated
otherwise.

## Landing page

Unchanged from the original build — see the app-wide FRD/TSD index for
card contents, Complete Manually flow, etc.

## Create activity flow

Unchanged functionally, with one addition: when an activity is created,
the table's current **Table Settings** (Audio Settings, Expected Client
IPs, Push Notification settings) are captured as a snapshot belonging to
that activity. Audio Settings drives detection sound immediately (see
below); the rest is captured for a future iteration and not yet
surfaced anywhere in the UI. Editing Table Settings later does not
change an already-running activity's snapshot.

## Monitor page

Full-width, full-height page. Header shows a status pill, both
cameras' progress bars, a "Total time" clock, and Order/Kit/EDP detail.
Below that, two camera panels side by side.

### Header

- **Status pill** reflects the activity's real status.
- **Cam 1 / Cam 2 progress bars** show kits completed out of the
  target, e.g. "3/10 · 30%" — capped at 100% even if a camera's
  internal counter ever sits one step past the target (see
  "Completion," below); never shows something like "120%."
- **Total time** counts up from when the activity was created, and
  **freezes permanently** the moment BOTH cameras finish all their
  kits — it does not keep counting after the activity is effectively
  done.
- **Order / Kit name / EDP** — read-only summary.
- **"See current settings"** — placeholder, behavior not yet defined.

### Per-camera panels (Cam 1 left, Cam 2 right)

Each panel shows:
- Camera label
- **Kit timer** — how long the camera has been working on its
  **current** kit. This is separate from "Total time": it resets to
  **0:00:00** every time that camera's kit is validated, so it's always
  showing time-on-this-kit, not time-on-the-whole-activity. Once that
  camera finishes all its kits, this timer disappears entirely — there's
  no "current kit" left for it to measure.
- **"Kit #N"** label, with a small speaker icon next to it (see "Sound,"
  below)
- A **History** button (placeholder)
- **Completed** and **Pending** sections, each showing part cards with
  name and "Qty: X / Y." A part moves from Pending to Completed the
  moment its detected quantity reaches what's required, and is tagged
  **"Last detected"** if it was the most recent successful detection on
  that camera (only one card ever carries this tag at a time). The
  Completed section can also contain **Neglected** and **Wrong-part**
  cards (red-tinted, see "Detection outcomes and alert types," below)
  — these never appear in Pending, and disappear automatically the
  moment that camera's kit advances (they belong to the kit that just
  finished, not the new one starting).

### Live detection pop-up

When the detection system reports a part was seen on a camera, that
camera's **entire half of the page** — the Back button row, the shared
header, and that camera's panel — is replaced by a large pop-up showing
the part's photo (if sent), a line describing what was detected, and
the detection time. **Two outcomes now exist for a green pop-up** (see
below), and unmatched detections split into two further outcomes
depending on configuration — see "Detection outcomes and alert types."

While one camera's pop-up is showing, the other camera's half is
completely unaffected.

### Detection outcomes and alert types

Every detection now resolves to exactly one of four outcomes:

| Outcome | Trigger | Pop-up | Card in Completed |
|---|---|---|---|
| **Matched** | Part is in this camera's configured parts list | Green, brief | Normal green card, Qty X/Y |
| **Neglected** | Part is on this camera's "Parts to Neglect" list (Current Kits Configuration) | Green, brief — same as a matched part | Red-tinted "Neglected" card, Qty X/0 (grouped by name, count keeps incrementing on repeat detections) |
| **Wrong Part Error** | Part is neither configured nor neglected, **and** this camera's Wrong Part Error alert is enabled (Camera Alert Configuration, per kit) | Red, **blocking** — stays on screen until resolved | Red-tinted "Wrong-part" card, one new card per occurrence (never grouped — each has its own resolution) |
| **Wrong Part (silent)** | Same as above, but this camera's Wrong Part Error alert is **disabled** for this kit | Red, brief (same as the old behavior) | Same "Wrong-part" card as above — still recorded, just doesn't block |

**Neglected parts are treated as expected, not unexpected** — client's
explicit reversal of the original design: a part on the neglect list
was previously invisible entirely; it now counts, sounds, and shows a
card, just visually flagged so an operator can see it was detected but
intentionally not alerted on.

**Validation Error** (the second alert type) is checked at a different
point — see "Kit advance and validation checks" below, not at
detection time.

**Both alert types are gated by a per-kit, per-camera master switch**
(Camera Alert Configuration, in Current Kits Configuration) —
independent of the per-part missing/undercount/overcount checkboxes.
If a switch is off, the underlying issue is still detected and recorded
(so nothing is silently lost), but no red-screen interrupts the
operator and the camera is not locked.

### The blocking red-screen

When either alert type actually fires (master switch on), the pop-up
becomes a **blocking red-screen** instead of the old brief pop-up:

- Stays on screen — no auto-hide timer — until the operator resolves it
- Shows the part's photo (if available), the issue(s) detected (e.g.
  "Part A required 2 found 0 (missing)"), and two buttons: **System
  Error** and **Process Error**
- An optional free-text comment box
- **Submit** is disabled until one of the two options is selected
- The camera's whole panel is **locked** while this is showing — the
  detection system can keep sending events, but they are ignored
  (logged server-side only) until the operator resolves the current
  one
- Red audio (if enabled in Table Settings → Audio Settings) **loops**
  for as long as the red-screen is showing, instead of playing once
- **Every viewer currently on the monitor page sees the same
  red-screen and can resolve it** — resolving from any one viewer's
  tab clears it for everyone
- A viewer who opens (or refreshes) the monitor page **while** a
  red-screen is already active on some other client sees the same
  locked/red state immediately — it is not lost on a page load

**Resolving** the red-screen behaves differently depending on which
alert type it was:

- **Wrong Part Error** → the camera simply unlocks. The kit does
  **not** advance — the detection system must still send its own
  separate kit-advance signal afterward, same as normal.
- **Validation Error** → resolving **is** the kit advance. The kit
  moves forward in the same action as the operator's submit — there is
  no separate advance signal needed for this case.

The operator's choice (System Error / Process Error) and any comment
are permanently recorded against that specific kit, alongside a small
**"S" or "P" badge** shown hanging off the top-right corner of the
resolved wrong-part card, so anyone looking at the kit's card history
can see how it was resolved without opening anything else.

### Kit advance and validation checks

When the detection system signals a camera's current kit is done
("validate"), **Validation Error checks now run first**, before the
kit is allowed to advance:

For every part configured on that camera, using each part's own
Missing / Undercount / Overcount alert checkboxes (Current Kits
Configuration):

- **Missing** — alert enabled, and the part was detected zero times →
  issue
- **Undercount** — alert enabled, and the part was detected some but
  fewer than required times → issue
- **Overcount** — alert enabled, and the part was detected more than
  required times → issue

**All qualifying issues across every part on that camera are combined
into ONE Validation Error** — never split into separate red-screens for
one validate action, even if several parts have problems at once.

If the camera's Validation Error master switch is on and at least one
issue was found: the red-screen described above appears, showing every
issue on one screen, and the kit does **not** advance until the
operator resolves it (resolving **is** the advance — see above).

If the switch is off, or no issues were found: the kit advances exactly
as before — Completed/Pending list resets, Kit timer resets to
0:00:00. The other camera is not affected either way. Everything
detected for the finished kit stays on record — nothing is deleted, it
just stops being shown live once a new kit starts, **except** any
neglected-part or wrong-part cards for that finished kit, which are
cleared from the live view the moment the kit advances (their
permanent record still exists — see TSD for where).

### Sound

Each camera can play a short sound on detection, using the audio files
configured in Configuration → Table Settings → Audio Settings.

- **Expected-part sound (green):** plays once per detection, only if
  that camera's sound toggle (the speaker icon next to "Kit #N") is
  currently on. Starts at the table's saved default and can be switched
  on/off during the activity, taking effect immediately — no need to
  finish or restart the kit. **This toggle is visible and synced to
  everyone currently viewing that activity's monitor page** — if one
  person switches it, everyone else sees it flip too. **Neglected-part
  detections now use this same green rule** (see "Detection outcomes,"
  above) — they are no longer silent.
- **Unexpected-part sound (red):** always follows the table's saved
  default — there is no per-activity toggle for this one. Plays **once**
  for a non-blocking wrong-part pop-up (switch off), same as before.
  Plays **on a loop** for the duration of a blocking red-screen (either
  alert type, switch on) — stops the moment the operator resolves it.

If a camera's slot has no audio file uploaded, no sound plays for that
camera/color regardless of the enabled/disabled setting.

### Kit advance ("validate")

When the detection system signals a camera's current kit is done, that
camera's kit index moves forward by one (e.g. "Kit #3" → "Kit #4"), its
Completed/Pending list resets to a fresh, empty state, and its Kit
timer resets to 0:00:00. The other camera is not affected. Everything
detected for the finished kit stays on record — nothing is deleted, it
just stops being shown live once a new kit starts.

### Completion — one camera

Once a camera finishes packing its final kit (the count it's tracking
reaches the required total), its panel switches to a **"Kits
Completed"** state: the Completed/Pending sections and cards disappear,
replaced by a checkmark and "Kits Completed" text. Its Kit timer
disappears. Its progress bar at the top shows 100%. If someone tries to
send it another detection or another kit-advance signal after this
point, that request is rejected with a clear reason rather than
silently accepted or failing generically. The same is true while a
camera is **locked** by an active red-screen — rejected with its own
distinct reason, so the detection system (or anyone reading the API
response) can tell "this camera is permanently done" apart from "this
camera is waiting on an operator right now."

This can happen to one camera well before the other — they're
completely independent. The other camera keeps working normally.

### Completion — whole activity

Once **both** cameras have reached "Kits Completed," the activity as a
whole is finished:
- "Total time" freezes at that exact moment.
- The activity is automatically moved out of the live list and into
  history, marked as completed — no manual "Complete" action needed.
- Anyone currently viewing the monitor page sees a brief "Activity
  Completed" confirmation, then is automatically returned to the Live
  Kitting Activities landing page after a couple of seconds.

## API feedback (for the detection system / any other caller)

Every ingest call returns a clear success/failure result, and on
failure, a specific reason — not just a generic error:
- The table has no active kitting run at all
- This camera has already finished all its kits
- This camera is currently locked by an active, unresolved red-screen
- Some other input problem (missing/invalid field)
- The database is unreachable

## Out of scope (not yet built)

- A screen to browse a completed kit's recorded detection history and
  timing (the data is captured — when each kit started, when its first
  part was detected, when it was validated, every individual
  detection's own timestamp, and now every alert raised and how it was
  resolved — but there's no viewer for it yet)
- "See current settings" and "History" button behavior
- Table 2 / Table 3 activities
- Expected Client IPs and Push Notification settings captured in the
  activity snapshot are not yet used anywhere — reserved for a future
  iteration
