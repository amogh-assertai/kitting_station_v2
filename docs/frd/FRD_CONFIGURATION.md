# FRD — Configuration

Functional requirements for the Configuration section: **table selection**, **Current Kits Configuration**, **PQPR Analytics**, and **Table Settings**.

## Table selection (landing page)

- Entering "Configuration" from the top nav shows a card per registered table (see the table registry in `TSD_CONFIGURATION.md`) — currently Table 1 (HVGKC-CELL), Table 2 (Truck Cell 1), Table 3 (Truck Cell 2).
- Each card shows the table id and name. An unbuilt table's card also shows a "Not yet configured" note.
- Clicking a card enters that table:
  - **Built** table (currently only Table 1) → lands on its default sub-tab (PQPR Analytics), with the full sub-nav (Current Kits Configuration · PQPR Analytics · Table Settings) available.
  - **Unbuilt** table (2 or 3) → shows "Configuration for `<table name>` not yet built." — no sub-nav, no further functionality.
- Everything described below (Current Kits Configuration, PQPR Analytics, Table Settings) currently applies **to Table 1 (HVGKC-CELL) only**.

## Sub-navigation (within a built table)

**Current Kits Configuration · PQPR Analytics · Table Settings** — active tab highlighted, styled as buttons (see `FRD_BASE_LAYOUT.md`). A "← Tables" link returns to the table-selection landing page; the current table's name is shown alongside it. A **table badge** ("Table `<id>` — `<name>`") also appears next to the global Back button on every page in this section.

---

## Current Kits Configuration

### List page

- Page title "Current Kits Configuration", with a search bar and a **Create New Kit** button on the same header row — search bar sits between the title and the button.
- Search: type-ahead, live (debounced), case-insensitive substring match across **kit name, EDP number, or any part name** in the kit. Empty search shows the full list. No-match shows "No kits match your search."
- Table columns: **# · Serial No. · Kit Name · EDP Number · Total Parts · Total Parts to Neglect · Last Updated · Actions**
  - Total Parts shows the count, with "Cam1: X · Cam2: Y" as a sub-line.
  - **Total Parts to Neglect** shows the count of parts in that kit's Parts to Neglect table, with the same "Cam1: X · Cam2: Y" sub-line breakdown.
  - Table is sorted by **Serial Number**, ascending, numerically (so 2 sorts before 10).
  - Actions: **Edit** (opens the kit for editing) and **Delete** (confirms, then removes the kit).
- If no kits exist yet for this table: "No kits configured yet. Click 'Create New Kit' to add one."
- If the database is unreachable: a plain message is shown instead of a broken page ("Could not connect to the database. Is MongoDB running?").
- All of the above is scoped to the current table — a kit belongs to exactly one table and never appears under another table's list/search.

### Create / Edit kit page

One shared layout for both create and edit (edit is pre-filled). Sections, top to bottom:

1. **Kit fields:** Serial Number (required, unique **within this table**, numeric), Kit Name (required), EDP Number (required, unique **within this table**).
2. **Parts Configuration table:** one row per part —
   - Part Name (required)
   - Quantity Required (required, whole number > 0)
   - Camera (dropdown: Camera 1 / Camera 2)
   - Alert Configuration — three checkboxes: **Alert if missing**, **Alert if undercount**, **Alert if overcount**
   - Class Resemblance (free text)
   - Delete-row button
   - "Add Part" button above the table adds a new blank row.
3. **Parts to Neglect table:** separate table below Parts Configuration —
   - Part Name (required)
   - Camera (dropdown: Camera 1 / Camera 2)
   - Delete-row button
   - "Add Part" button above the table adds a new blank row.
4. **Camera Alert Configuration table:** one row per camera (Camera 1, Camera 2) —
   - **Validation Error Alert** — radio: Enabled / Disabled (default: Enabled)
   - **Wrong Part Error Alert** — radio: Enabled / Disabled (default: Enabled)
   - This is per-kit, per-camera — it configures whether that kit raises these two alert types on that camera, independent of the per-part alert checkboxes in section 2.
- **Save Kit** / **Cancel** at the bottom, saving all four sections together in one action. A global **Back** button (see `FRD_BASE_LAYOUT.md`) is at the top of the page.
- On save, invalid input (missing required field, duplicate Serial Number/EDP Number within the table, bad camera value, non-numeric quantity, bad camera value in the alert config) shows a clear inline error and does not save.

### Validation rules

| Field | Rule |
|---|---|
| Serial Number | Required, whole number, unique **within this table** |
| Kit Name | Required |
| EDP Number | Required, unique **within this table** |
| Part → Part Name | Required |
| Part → Quantity Required | Required, whole number > 0 |
| Part → Camera | Must be Camera 1 or Camera 2 |
| Neglect Part → Part Name | Required |
| Neglect Part → Camera | Must be Camera 1 or Camera 2 |
| Camera Alert Config → Camera | Must be Camera 1 or Camera 2; exactly one entry per camera is always stored (a camera missing from the save request defaults to both alerts Enabled) |

---

## PQPR Analytics

### What PQPR is

An Excel workbook the client maintains, **one per table**. The sheet **"PQPR - FG -- Copy"** is the one this app reads:
- Column **Description** = kit name
- Column **EDP #** = unique kit identifier
- Columns **H onward** = one column per component. A cell containing `x` means qty 1; a number means that quantity; blank means not used.
- **Top 10** = the first 10 data rows in the sheet, taken as-is — not a computed ranking.

### File upload/replace/download

- If no file uploaded yet for this table: "No PQPR file uploaded yet" + **Upload File** button.
- Accepts `.xlsx` and `.xls`. Only one file kept at a time **per table** — uploading a new one **overwrites** the previous one for that table (no version history).
- Once a file exists: shows filename + upload timestamp, **Download** button (returns the exact file, original filename), and **Replace File** button.
- Upload/replace happens via AJAX — no page reload.

### Search — two panels, side by side

**Left: "Find components in a kit"** — type a kit name or EDP number, live suggestions, Enter/Search jumps to a single match, exact "not present" message on zero matches. Shows kit name, EDP #, TOP 10 badge (if applicable), and every component with quantity.

**Right: "Find kits using a component"** — same suggestion/search behavior. Shows every kit using the component, with quantity, **Top 10 kits listed first and flagged**.

### No data yet

Before any file is uploaded for this table, the search panels are hidden with a prompt to upload a file first.

---

## Table Settings

Per-table configuration that isn't tied to a specific kit — Audio Settings, Expected Client IP Addresses, and Push Notification Settings, each in its own section on one page.

### Audio Settings

A table with one row per audio option:
- **Camera 1 — Green Audio**
- **Camera 1 — Red Audio**
- **Camera 2 — Green Audio**
- **Camera 2 — Red Audio**

Columns: **Audio · File · Preview · Default**
- **File**: shows the current filename ("No file uploaded" if none) and an Upload/Replace button (label reads "Upload" when empty, "Replace" once a file exists). Accepts `.mp3` only.
- **Preview**: a Play/Pause button that plays the audio inline. If a new file was just picked but not yet saved, Preview plays that local file (so you can check it before committing); otherwise it plays the currently-saved file. Disabled if there's neither a saved file nor a pending pick.
- **Default**: radio — Enabled / Disabled (default: **Enabled**). Governs whether this audio plays by default.
- **Saving is deferred**: picking a file does *not* upload it immediately — it's staged. One **Save Audio Settings** button at the bottom of the table saves every row's file (if changed) and Default selection together in one action.

### Expected Client IP Addresses

- A list of IP addresses (free text, no format validation) with **Edit** (inline text field) and **Delete** per row, plus an "Add IP" input + button to append a new one.
- Changes (add/edit/delete) are staged locally; nothing is saved until **Save IP List** is clicked, which replaces the whole list at once.
- Duplicate/blank entries are silently cleaned up on save (trimmed, deduplicated).

### Push Notification Settings

Below Expected Client IP Addresses on the same page.

**Notification Emails** — same list pattern as Expected Client IPs: add/edit/delete, staged locally, free text (no format validation).

**Notification Types** — a table with one row per notification, each with an Enabled/Disabled radio (**default: Disabled** — opposite of Audio Settings' default):
1. **Start/Stop Events Notification**
2. **Error Rate Threshold Notification** — when set to **Enabled**, an additional **Threshold %** field appears/becomes editable (e.g. 15, 30) and is **required** while this notification is enabled. The field is disabled/greyed out while this notification is Disabled.
3. **Continuous Object Detected Notification**
4. **Activity Creation Error Notification**

Notification Emails and Notification Types share **one Save button** ("Save Push Notification Settings") — both are part of the same feature and save together.

### Scope

Everything on this page is per-table (currently Table 1 / HVGKC-CELL only) and lives in MongoDB, not the filesystem, except the audio MP3 files themselves (filesystem, one per slot per table — see `TSD_CONFIGURATION.md`).
