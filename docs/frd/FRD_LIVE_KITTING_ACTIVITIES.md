# FRD — Live Kitting Activities

Functional requirements for the Live Kitting Activities section:
**landing page**, **create activity flow (station → camera check)**, the
**monitor page**, and **live detection ingest** (new this revision).
Currently applies to **Table 1 (HVGKC-CELL) only**.

## Concept

A **kitting activity** is one run of packing a specific kit, on a
specific table, against a specific order. Only **one live activity per
table** is allowed at a time.

**New this revision:** part counts on the monitor page are no longer
static — they update live from a local camera/AI detection system
(DeepStream) mounted at each table, one camera per side (Cam 1, Cam 2).

## Landing page

Unchanged from prior revision — see previous section for card contents,
Complete Manually flow, etc.

## Create activity flow

Unchanged functionally, with one addition: when an activity is created,
the table's current **Table Settings** (Audio Settings, Expected Client
IPs, Push Notification settings) are captured as a snapshot belonging to
that activity. This snapshot is used immediately for detection sound
(see below); the rest is captured for a future iteration and not yet
surfaced anywhere in the UI. Editing Table Settings later does not
change an already-running activity's snapshot.

## Monitor page

Full-width, full-height page, unchanged base layout. **New: live
detection pop-ups and per-camera sound**, described below.

### Header

Unchanged — Back button, table badge, status pill, Cam 1/Cam 2 progress
bars, Total time, Order/Kit/EDP, "See current settings" placeholder.

### Per-camera panels (Cam 1 left, Cam 2 right)

Each panel shows, as before: camera label, activity timer, History
button (placeholder), current kit index ("Kit #N"), Completed/Pending
part cards.

**New: sound toggle**, immediately to the right of "Kit #N" — a small
speaker icon button. Tapping it turns that camera's **detection sound**
on or off for the rest of this activity (see "Detection sound" below).
This does **not** change the table's saved default in Configuration →
Table Settings — it only affects the current activity, and reverts to
the table's saved default the next time a new activity is created on
that table.

### Live detection pop-up

When the local detection system reports that a part was seen on a
camera, that camera's **entire half of the page** — the Back button
row, the shared status/progress header, and that camera's panel — is
replaced for a few seconds by a large pop-up showing:

- The part's photo (if the detection system sent one)
- A line reading **"Detected: `<part name>` | Qty: `<count>` /
  `<required>`"** for an expected part, or **"Detected: `<part name>`"**
  for an unexpected one
- The time of detection

The pop-up is colored **green** for an expected part (one that's
configured for that camera in this kit) and **red** for an unexpected
one. It disappears automatically after a short, separately-configurable
duration for each color, reverting to the normal Completed/Pending view.
While a pop-up is showing on one camera, the other camera's half of the
page is completely unaffected — each camera's pop-up never crosses into
the other's side.

Underneath the pop-up, the relevant part card is updated immediately: an
expected part's count goes up, and once it reaches the required
quantity the card moves from Pending to Completed, tagged **"Last
detected"**. Only the single most-recently-detected part carries this
tag at any time.

**Unexpected parts** (red pop-up): the event is recorded, but no further
alert-handling behavior is built yet — full alert-type rules (matching
the per-part "Alert if missing/undercount/overcount" and per-camera
"Wrong Part Error" settings from Current Kits Configuration) are a later
build.

### Detection sound

Each camera can play a short sound when a detection happens, using the
audio files already configured in **Configuration → Table Settings →
Audio Settings** (Camera 1/2, Green/Red).

- **Expected-part sound (green):** plays once per detection, but only
  if that camera's sound toggle (next to "Kit #N," see above) is
  currently on. This toggle starts at whatever the table's saved
  default is (from Table Settings), and can be freely switched on/off
  during the activity — the change takes effect immediately, for the
  part currently being packed, with no need to finish or restart the
  kit.
- **Unexpected-part sound (red):** always follows the table's saved
  default from Table Settings — there is no per-activity toggle for
  this one.

If a camera's slot has no audio file uploaded in Table Settings, no
sound plays for that camera/color, regardless of the enabled/disabled
setting.

**Sound toggle state is shared across every screen currently viewing
this activity** — if one person switches Cam 1's sound off, everyone
else watching that same activity's monitor page sees the toggle flip
too, immediately.

### Kit advance ("validate")

When the local detection system signals that a camera's current kit is
done, that camera's kit index moves forward by one (e.g. "Kit #3" →
"Kit #4") and its Completed/Pending list resets to a fresh, empty state
for the new kit. The other camera is not affected. Everything detected
for the finished kit remains on record — nothing is deleted, it simply
stops being shown live once a new kit starts. Full pass/fail validation
rules for a kit before advancing are not built yet; today the signal
just advances the counter.

## Out of scope (not yet built)

- Full alert-type rules for unexpected/wrong-part detections (only the
  visual red pop-up exists)
- Per-kit timing (both cameras still show the whole activity's elapsed
  time)
- "See current settings" and "History" button behavior
- Table 2 / Table 3 activities
- A UI to browse a completed kit's detection history (the data is
  recorded and retained, but there's no screen to view it yet)
- Expected Client IPs and Push Notification settings captured in the
  activity snapshot are not yet used anywhere — reserved for a future
  iteration
