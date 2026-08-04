# FRD — Kitting Station v2 (Whole App)

Functional requirements at the app level. For the shared shell (nav, theming, back button), see `FRD_BASE_LAYOUT.md`. For Configuration tab detail, see `FRD_CONFIGURATION.md`.

## Product identity

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

Active page/tab is visually highlighted. Every page also has a global **Back** button (top of the main content area) that returns to wherever the user came from — see `FRD_BASE_LAYOUT.md`.

## Page-by-page status

| Page | Status | User goal |
|---|---|---|
| Home | Shell only | Landing page |
| Live Kitting Activities | Placeholder — needs Flask-SocketIO | View a real-time feed of kitting activity on the floor |
| History | Placeholder — needs MongoDB | Look up past kitting activity/records |
| Configuration → Current Kits Configuration | **Built** | Create, edit, search, and delete kit definitions (parts, cameras, alert rules) |
| Configuration → PQPR Analytics | **Built** | Upload the PQPR Excel workbook; look up which components are in a kit, or which kits use a component |

## Out of scope (not yet built)

- Real-time kitting activity feed (needs Flask-SocketIO wiring)
- History browsing/audit trail (needs MongoDB integration for that blueprint)
- Any authentication/authorization

## Where to look for more

- Shell (header, nav, theming, back button, fit-to-screen behavior): `FRD_BASE_LAYOUT.md`
- Configuration tab (both sub-tabs, full functional detail): `FRD_CONFIGURATION.md`
