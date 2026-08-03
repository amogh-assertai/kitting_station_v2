# Kitting Station v2 — Functional Documentation

## Product

| | |
|---|---|
| Product name | Kitting Station (v2) |
| Developer | AssertAI |
| Client | Watts Water |
| Client brand | Dormont |
| App type | Server-rendered web app, styled/used like an HMI |
| Devices | Laptop monitors and larger fixed screens (fit-to-screen, no page scroll) |
| Domain | Manufacturing / kitting station monitoring |

## Navigation structure

**Top nav (all pages):** Home · Live Kitting Activities · History · Configuration

**Configuration sub-nav:** Current Kits Configuration · PQPR Analytics

Active page/tab is visually highlighted. Hover states on all nav buttons.

## Page status

| Page | Status |
|---|---|
| Home | Shell only |
| Live Kitting Activities | Placeholder (real-time feed planned, needs Flask-SocketIO) |
| History | Placeholder (needs MongoDB) |
| Configuration → Current Kits Configuration | Placeholder |
| Configuration → PQPR Analytics | **Built** — see below |

## PQPR Analytics — functional detail

### What PQPR is
An Excel workbook the client maintains. The sheet **"PQPR - FG -- Copy"** is the one this app reads:
- Column **Description** = kit name
- Column **EDP #** = unique kit identifier
- Columns **H onward** = one column per component. A cell containing `x` means qty 1; a number means that quantity of that component goes into that kit; blank means not used.
- **Top 10** = the first 10 data rows in the sheet (rows 2–11), taken as-is — this is not a computed ranking, it reflects however the client has ordered the sheet.

### File upload/replace/download
Top of the PQPR Analytics tab:
- If no file uploaded yet: shows "No PQPR file uploaded yet" + **Upload File** button.
- Accepts `.xlsx` and `.xls`.
- Only one file is kept at a time — uploading a new one **overwrites** the previous one (no version history).
- Once a file exists: shows filename + upload timestamp, **Download** button (gets back the exact file, original filename), and **Replace File** button.
- Upload/replace happens via AJAX — no page reload.

### Search — two panels, side by side

**Left: "Find components in a kit"**
- Type a kit name or EDP number.
- Live suggestions appear as you type.
- Click a suggestion, or press **Enter**/click **Search** for an immediate lookup.
- If exactly one match: jumps straight to its details.
- If nothing matches: shows *"Kit name/EDP "X" not present in the uploaded PQPR file."*
- Selecting a kit shows: kit name, EDP #, TOP 10 badge (if applicable), and a table of every component in it with quantity.

**Right: "Find kits using a component"**
- Type a component name.
- Same suggestion/Enter/Search behavior as the left panel.
- Selecting a component shows every kit that uses it, with quantity, **Top 10 kits listed first and flagged with a "TOP 10" badge** (this was explicitly called out as very important), followed by the rest.

### What happens if there's no data
Before any file is uploaded, the search panels are hidden and a note prompts the user to upload a file first.

## Theming
- Dark theme is default; user can toggle to light. Preference is remembered (cookie) so the right theme shows on first load, no flash of wrong theme.

## Branding
- Client logo (Watts) shown top-left in a white chip (works on both themes).
- App name + version shown next to it.
- Footer: "Dormont — a Watts Water brand" · "Kitting Station v2.0 — powered by AssertAI".
