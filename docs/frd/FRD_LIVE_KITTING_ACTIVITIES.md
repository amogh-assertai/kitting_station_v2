# FRD — Live Kitting Activities

Functional requirements for the Live Kitting Activities section: **landing page**, **create activity flow (station → camera check)**, and the **monitor page**. Currently applies to **Table 1 (HVGKC-CELL) only** — same multi-table constraint as Configuration, since Tables 2/3 have no kit data to create an activity from.

## Concept

A **kitting activity** is one run of packing a specific kit, on a specific table, against a specific order. Only **one live activity per table** is allowed at a time — a table must be completed (or completed manually) before a new activity can start on it.

## Landing page

- Header: "Live Kitting Activities" (left), **Create New Kitting Activity** button (top area).
- Below: a card per currently-**live** activity, across all tables. No "View Past Jobs" link (out of scope — History section covers that separately).
- Empty state: "No active kitting activities."
- If the database is unreachable: a plain message is shown instead of a broken page, same convention as Configuration's list pages.

### Activity card contents

- Table number + name
- Kit name
- Order number, EDP number
- Cam 1 / Cam 2 progress, shown as "current kit index / target quantity" (e.g. "10/70")
- Activity start time — formatted in the **viewer's local browser timezone**, 12-hour clock, with a timezone label (e.g. "Started 8:00 PM India Time"). Stored server-side in UTC; every viewer sees their own local time regardless of where the table physically is.
- **View Monitor** button — opens the Monitor page for this activity.
- **Complete Manually** button (styled as a warning/danger action) — opens an inline confirmation (Yes/No + optional free-text reason) directly on the card. Confirming moves the activity to history with status `completed-manually`, records when it was stopped and why (if a reason was given), and the card is removed from the list. The table becomes free for a new activity immediately.

## Create activity flow

Two steps, no data is written to the database until the very end.

### Step 1 — Start New Activity

Fields, top to bottom:
1. **Select Station** — dropdown of built tables only.
2. **Order Number** — free text, no format validation. Pressing Enter moves focus to EDP Number (supports barcode-scanner-style entry).
3. **EDP Number** — free text. Pressing Enter looks up the kit by **exact EDP match, scoped to the selected table** (no fuzzy suggestions). Not found → inline error, "EDP number not found on this station."
4. **Kit Name** — read-only, auto-filled from the successful EDP lookup.
5. **Units to Pack** — numeric, defaults to 70, editable.

**Next** is disabled until a kit has been successfully resolved. Clicking **Next** checks whether the selected table already has a live activity — if so, navigation is blocked with an inline message naming the order currently occupying that table. **Cancel** returns to the landing page.

### Step 2 — Camera Check

- Shows two camera preview images, one per camera (currently static placeholders — real per-camera capture is a separate, later build).
- Shows the kit name, order number, and EDP number carried from Step 1.
- **Create Activity** button finalizes: table-busy is re-checked at this point too (protects against two people racing the same table from two tabs/sessions). On success, the browser is taken directly to the new activity's **Monitor page** — not back to the landing list.
- **Cancel** returns to the landing page without creating anything.

## Monitor page

Full-width, full-height page (breaks out of the app's normal centered/bordered content area — see TSD for why). No page-level scroll; only the two camera panels scroll internally if their content overflows.

### Header

- **Back** button (top-left, standard app convention).
- Table badge ("Table `<id>` — `<name>`"), standard convention for table-scoped pages.
- **Status pill** — reflects the activity's actual status (`live`, `completed`, `completed-manually`) from the database, not a hardcoded label.
- **Cam 1 / Cam 2 progress bars**, side by side — same "current kit index / target" numbers and percentage as the landing page card, shown as a mini progress bar.
- **Total time** — elapsed time since the activity was created, ticking live, computed against the viewer's local clock (UTC-based under the hood — see TSD).
- **Order / Kit name / EDP** — read-only summary.
- **See current settings** button — placeholder for now; behavior to be defined later.

### Per-camera panels (Cam 1 left, Cam 2 right)

Each panel shows:
- Camera label, a timer (currently the same activity-level elapsed time as the header's Total Time — true per-kit timing is a known future gap, see TSD), a **History** button (placeholder), and the current kit index ("Kit #N").
- **Completed** section — parts whose detected count has reached its required quantity for the current kit.
- **Pending** section — all other parts, each flagged with a warning marker.
- Each part card shows the part name and "Qty: `<count>` / `<required>`".
- **Current build note:** detected counts are not yet wired to real camera events — every part starts at count 0 (all pending) until that wiring is done in a later build. The UI, layout, and completed/pending split are final; only the live count-updating is pending.

## Out of scope (not yet built)

- Real detection-driven part counts (camera/model integration)
- Per-kit timing (a timer that resets each time a camera's kit index advances) — currently shows the whole activity's elapsed time on both cameras
- "See current settings" and "History" button behavior
- Table 2 / Table 3 activities (no kit data exists for them yet)
- Any real-time push (Flask-SocketIO) — the monitor page's live-looking elements (timers, progress) currently update via client-side JavaScript against static server-rendered data, not a live socket feed
