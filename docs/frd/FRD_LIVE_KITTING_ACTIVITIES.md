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
  that camera (only one card ever carries this tag at a time).

### Live detection pop-up

When the detection system reports a part was seen on a camera, that
camera's **entire half of the page** — the Back button row, the shared
header, and that camera's panel — is replaced for a few seconds by a
large pop-up showing the part's photo (if sent), a line reading
**"Detected: `<part name>` | Qty: `<count>` / `<required>`"** (or just
**"Detected: `<part name>`"** for an unexpected part), and the detection
time. Green for an expected part, red for an unexpected one. Each color
has its own separately-configurable display duration. While one
camera's pop-up is showing, the other camera's half is completely
unaffected.

Unexpected-part detections are recorded, but no further alert-handling
behavior is built yet — full alert-type rules (matching the per-part
and per-camera alert settings from Current Kits Configuration) are a
later build.

### Sound

Each camera can play a short sound on detection, using the audio files
configured in Configuration → Table Settings → Audio Settings.

- **Expected-part sound (green):** plays once per detection, only if
  that camera's sound toggle (the speaker icon next to "Kit #N") is
  currently on. Starts at the table's saved default and can be switched
  on/off during the activity, taking effect immediately — no need to
  finish or restart the kit. **This toggle is visible and synced to
  everyone currently viewing that activity's monitor page** — if one
  person switches it, everyone else sees it flip too.
- **Unexpected-part sound (red):** always follows the table's saved
  default — there is no per-activity toggle for this one.

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
silently accepted or failing generically.

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
- Some other input problem (missing/invalid field)
- The database is unreachable

## Out of scope (not yet built)

- Full alert-type rules for unexpected/wrong-part detections (only the
  visual red pop-up exists)
- A screen to browse a completed kit's recorded detection history and
  timing (the data is captured — when each kit started, when its first
  part was detected, when it was validated, and every individual
  detection's own timestamp — but there's no viewer for it yet)
- "See current settings" and "History" button behavior
- Table 2 / Table 3 activities
- Expected Client IPs and Push Notification settings captured in the
  activity snapshot are not yet used anywhere — reserved for a future
  iteration
- Pass/fail validation rules for a kit before it's allowed to advance
  (today, a validate signal always just advances the counter)
