# FRD — Configuration

Functional requirements for the Configuration section: **Current Kits Configuration** and **PQPR Analytics**.

## Sub-navigation

**Current Kits Configuration · PQPR Analytics** — active tab highlighted. `/configuration` redirects to PQPR Analytics.

---

## Current Kits Configuration

### List page

- Page title "Current Kits Configuration", with a search bar and a **Create New Kit** button on the same header row — search bar sits between the title and the button.
- Search: type-ahead, live (debounced), case-insensitive substring match across **kit name, EDP number, or any part name** in the kit. Empty search shows the full list. No-match shows "No kits match your search."
- Table columns: **# · Serial No. · Kit Name · EDP Number · Total Parts · Last Updated · Actions**
  - Total Parts shows the count, with "Cam1: X · Cam2: Y" as a sub-line.
  - Table is sorted by **Serial Number**, ascending, numerically (so 2 sorts before 10).
  - Actions: **Edit** (opens the kit for editing) and **Delete** (confirms, then removes the kit).
- If no kits exist yet: "No kits configured yet. Click 'Create New Kit' to add one."
- If the database is unreachable: a plain message is shown instead of a broken page ("Could not connect to the database. Is MongoDB running?").

### Create / Edit kit page

One shared layout for both create and edit (edit is pre-filled).

- **Kit fields:** Serial Number (required, unique, numeric), Kit Name (required), EDP Number (required, unique).
- **Parts Configuration table:** one row per part —
  - Part Name (required)
  - Quantity Required (required, whole number > 0)
  - Camera (dropdown: Camera 1 / Camera 2)
  - Alert Configuration — three checkboxes: **Alert if missing**, **Alert if undercount**, **Alert if overcount**
  - Class Resemblance (free text)
  - Delete-row button
  - "Add Part" button above the table adds a new blank row.
- **Parts to Neglect table:** separate table below Parts Configuration —
  - Part Name (required)
  - Camera (dropdown: Camera 1 / Camera 2)
  - Delete-row button
  - "Add Part" button above the table adds a new blank row.
- **Save Kit** / **Cancel** at the bottom. A global **Back** button (see `FRD_BASE_LAYOUT.md`) is at the top of the page.
- On save, invalid input (missing required field, duplicate Serial Number/EDP Number, bad camera value, non-numeric quantity) shows a clear inline error and does not save.

### Validation rules

| Field | Rule |
|---|---|
| Serial Number | Required, whole number, unique across all kits |
| Kit Name | Required |
| EDP Number | Required, unique across all kits |
| Part → Part Name | Required |
| Part → Quantity Required | Required, whole number > 0 |
| Part → Camera | Must be Camera 1 or Camera 2 |
| Neglect Part → Part Name | Required |
| Neglect Part → Camera | Must be Camera 1 or Camera 2 |

---

## PQPR Analytics

### What PQPR is

An Excel workbook the client maintains. The sheet **"PQPR - FG -- Copy"** is the one this app reads:
- Column **Description** = kit name
- Column **EDP #** = unique kit identifier
- Columns **H onward** = one column per component. A cell containing `x` means qty 1; a number means that quantity; blank means not used.
- **Top 10** = the first 10 data rows in the sheet, taken as-is — not a computed ranking.

### File upload/replace/download

- If no file uploaded yet: "No PQPR file uploaded yet" + **Upload File** button.
- Accepts `.xlsx` and `.xls`. Only one file kept at a time — uploading a new one **overwrites** the previous one (no version history).
- Once a file exists: shows filename + upload timestamp, **Download** button (returns the exact file, original filename), and **Replace File** button.
- Upload/replace happens via AJAX — no page reload.

### Search — two panels, side by side

**Left: "Find components in a kit"** — type a kit name or EDP number, live suggestions, Enter/Search jumps to a single match, exact "not present" message on zero matches. Shows kit name, EDP #, TOP 10 badge (if applicable), and every component with quantity.

**Right: "Find kits using a component"** — same suggestion/search behavior. Shows every kit using the component, with quantity, **Top 10 kits listed first and flagged**.

### No data yet

Before any file is uploaded, the search panels are hidden with a prompt to upload a file first.
