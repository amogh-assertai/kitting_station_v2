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

Card contents, Complete Manually flow, etc. — see the app-wide FRD/TSD
index. **One change this round:** each card's "Started" timestamp now
shows the full date alongside the time it already showed (e.g. "Started
Sep 9, 2026, 8:50 PM `<timezone>`") — previously time-only. The
underlying start time and timezone-detection logic are unchanged; this
was a display-only fix.

## Create activity flow

Unchanged functionally, with one addition: when an activity is created,
the table's current **Table Settings** (Audio Settings, Expected Client
IPs, Push Notification settings) are captured as a snapshot belonging to
that activity. Audio Settings drives detection sound immediately (see
below); the rest is captured for a future iteration and not yet
surfaced anywhere in the UI. Editing Table Settings later does not
change an already-running activity's snapshot.

### Order Number auto-suffix (NEW this session)

If the Order Number typed on the create-activity form already matches
an order number this table used on a PAST completed activity **today**,
the field is silently auto-filled with the next free suffix (`_2`,
`_3`, ...) — the operator does not need to notice or do anything; it
just happens on Enter or when the field loses focus, before EDP lookup.
Checked only against History (already-completed activities), not
against a currently-live activity — a table only ever has one live
activity at a time already, so there's no separate collision to check
there. If the check itself fails (e.g. a network hiccup), the operator's
typed value is left as-is rather than blocking them from continuing.

## Editing a kit while it's running (NEW this round)

An activity's parts/neglect-list/camera-alert-configuration used to be
a one-time snapshot, captured at creation and never touched again — the
explicit rule was "editing a kit later does not retroactively affect an
already-running activity." **This is now reversed for the one specific
case where it's actually useful:** if an operator (or the client) edits
**the exact same kit** an activity is currently running, in Current
Kits Configuration, the change now propagates immediately to that
running activity too — no restart needed.

- Matched by the **specific kit** that was edited, not by table. Editing
  a different kit on the same table never affects an activity currently
  running some other kit.
- Only affects activities that are still **live** — a completed or
  manually-stopped activity's historical record is never touched by a
  later kit edit.
- Propagates all three config pieces together: the parts list (with
  their quantities and alert flags), the neglect list, and the Camera
  Alert Configuration master switches.
- Takes effect **immediately** for anything the detection system sends
  from that point on — no page refresh needed for the new rules to
  apply server-side.
- Anyone currently viewing that activity's monitor page is notified the
  config changed (today: informational only — there's no on-screen
  element that visually reflects the config itself, so nothing moves or
  flashes, but the change is confirmed to have happened).
- Table Settings (Audio Settings, Expected Client IPs, Push
  Notifications) are **NOT** part of THIS specific propagation — but
  see the next section, which covers the same idea applied to Table
  Settings on its own terms.

## Editing Table Settings while a kit is running (NEW, a round after the above)

The same reversal as above, extended to Table Settings — client's ask:
"for table settings as well, if its updated, it should check if any
live activity is there and update there as well like kitting
configuration." Saving any of the three Table Settings sections (Audio
Settings, Expected Client IPs, or Push Notification Settings) now
propagates immediately to any live activity on that table.

- Matched by **table**, not by kit — since Table Settings belongs to
  the table as a whole, not to any specific kit. Every currently-live
  activity on that table picks up the change (in practice, at most one,
  since only one live activity is allowed per table at a time).
- Only affects activities that are still **live** — same rule as kit
  config propagation.
- All three sections propagate independently — saving just the Expected
  Client IPs, for instance, updates only that part of a live activity's
  Table Settings snapshot; the other two sections' most-recently-saved
  values are preserved, not reset.
- Takes effect immediately — an in-progress activity's detection sound
  now uses the newly-saved audio file (or the newly-changed enabled/
  disabled default) on its very next detection, with no restart needed.
- Same live-viewer notification as kit config propagation (informational
  only today).
- The "See current settings" modal (above) always reflects whichever
  Table Settings values are currently on the activity's own snapshot —
  so after this propagation runs, the modal's next open shows the new
  values immediately, same as it already does for kit-config changes.

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
- **"See current settings"** — opens a modal showing a fresh-from-the-
  database snapshot of this activity's own running configuration: kit
  info, and per camera — current kit index, camera lock state,
  green-sound toggle state, every configured part with its alert flags,
  the neglect list, and the Camera Alert Configuration master switches.
  **A round after this modal was first built, it was extended to also
  show the activity's Table Settings snapshot** — Audio Settings (per
  slot: filename and whether it's enabled), Expected Client IPs, and
  Push Notification settings (emails and each notification type's
  enabled state, with its threshold % where applicable). **Always reads
  the LIVE ACTIVITY's own snapshot, never the master configuration
  tables** — for both kit config and Table Settings, the running
  snapshot can differ from what's currently saved in Configuration
  (see "Editing a kit while it's running" and "Editing Table Settings
  while a kit is running," below), and this modal is specifically meant
  to show what THIS run is actually using right now. Re-fetched fresh
  from the database every time the button is clicked — never cached
  from a previous open or from the page's own initial load.

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
| **Wrong Part (alert disabled)** | Same as above, but this camera's Wrong Part Error alert is **disabled** for this kit | **Green, brief** — corrected this round; previously showed red | Same "Wrong-part" card as above (still red-tinted, still individual/uncounted) — the DATABASE record always says "wrong part" regardless of which color the operator saw |

**Neglected parts are treated as expected, not unexpected** — client's
explicit reversal of the original design: a part on the neglect list
was previously invisible entirely; it now counts, sounds, and shows a
card, just visually flagged so an operator can see it was detected but
intentionally not alerted on.

**A genuinely wrong (unrecognized) part with its alert disabled is ALSO
now treated as visually expected** — a second, later correction: this
used to show the brief red pop-up regardless of the switch, which
looked like an alert even though it wasn't blocking anything. It now
plays the same green pop-up/sound a matched or neglected part would,
while the permanent record still correctly says "wrong part" — so an
operator sees a calm green confirmation in the moment, but a supervisor
reviewing the kit's history later can still see exactly what happened
and that it was an unrecognized part, not a real one. **Unlike a
neglected part, a switch-disabled wrong part is never grouped or
counted** — every occurrence still gets its own individual card, since
(if the switch were ever turned back on) each occurrence would need its
own independent operator resolution.

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
  detections, and now a switch-disabled wrong-part detection too, use
  this same green rule** (see "Detection outcomes," above) — neither is
  silent or red anymore.
- **Unexpected-part sound (red):** always follows the table's saved
  default — there is no per-activity toggle for this one. Only plays at
  all now for a genuine **blocking** red-screen (Wrong Part Error or
  Validation Error, master switch on) — **on a loop** for as long as
  the red-screen is showing, stopping the moment the operator resolves
  it. A wrong-part detection with its alert disabled no longer triggers
  red audio at all (it plays green audio instead — see above).

If a camera's slot has no audio file uploaded, no sound plays for that
camera/color regardless of the enabled/disabled setting.

### Kit advance ("validate") confirmation pop-up

Added this round: when the detection system signals a camera's current
kit is done and **no Validation Error red-screen was raised** (see
above), the camera's panel now shows a brief confirmation pop-up before
reverting to normal — previously this was silent, giving no on-screen
feedback that the validate actually registered.

Two variants:

- **Normal advance** (this camera still has kits left to pack): green
  pop-up reading "Kit `<N>` completed | Next: Kit `<N+1>`", showing the
  validation image if the detection system sent one with its
  `validate_now` signal.
- **Final advance** (this WAS the camera's last kit): a distinct
  **blue** pop-up — the image area is replaced with solid blue and
  centered text reading "All kits in Cam`<N>` completed." There is no
  "next kit" to name.

Both variants stay on screen for a separately-configurable duration
(shorter than a full "read this carefully" red-screen, since there's
nothing to act on), then the panel reverts — to its normal Completed/
Pending view for a mid-activity advance, or to the existing "Kits
Completed" state for the final one.

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
- "History" button behavior (per-kit detection/timing/alert history
  viewer — "See current settings" is now built, see above; "History" is
  a separate, still-unbuilt feature)
- Table 2 / Table 3 activities
- Expected Client IPs and Push Notification settings captured in the
  activity snapshot are not yet used anywhere — reserved for a future
  iteration
