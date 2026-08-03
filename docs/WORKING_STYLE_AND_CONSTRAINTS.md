# Working Style & Constraints — for continuing this project

This is a handoff note for whoever (human or another Claude session) continues this build. It captures how the client works, not just what's been built.

## Role framing
Client wants responses as if from a **senior computer vision engineer and architect** — technical, precise, no hand-holding.

## Communication style
- **Short first, depth later.** Lead with a compact summary/points; don't open with long paragraphs. Details can follow.
- **Always state assumptions explicitly** if a decision had to be made without asking — call it out as an assumption, don't bury it.
- **Don't assume the client's exact scenario.** If something is ambiguous (naming, exact behavior, exact values), ask a follow-up question before building — use short, option-based questions (2–4 choices) rather than open-ended ones where possible.

## File delivery convention
- **≤3 files changed** → send them individually, each with a clear note: file path, and whether it's **new** or should **replace** an existing file.
- **>3 files changed** → zip, but the **zip must contain only the changed/new files** (preserving their relative folder paths), never the whole project — client applies these into their existing local copy manually.
- Every delivery should include a compact table: `File | Change | Key Decision`, followed by a short summary of what to verify. No long prose.
- Test everything (server-side at minimum; note if browser/visual testing wasn't possible) before delivering — client has caught at least one silent failure (missing JS file) this way already, so treat "did I verify this actually works" as mandatory, not optional.

## Build philosophy (stated up front by client, still holds)
- Incremental, confirm-scope-first builds. Don't jump ahead to features not yet requested.
- Keep files small and single-purpose — split CSS/JS/templates by concern rather than growing one large file.
- No hardcoded values anywhere in code — runtime config goes in `config.yaml`, secrets in `.env`.
- Config-driven over code-driven where the client's source data might change shape (e.g. PQPR sheet/column layout is entirely config, not hardcoded, because the client said the layout might change).
- Tech stack (Flask/Blueprints, Jinja2, Flask-SocketIO, MongoDB, plain CSS, vanilla JS, YAML+.env config) is **fixed — do not change without asking**.

## Interaction patterns already established
- Client uploads real data files (e.g. the actual PQPR Excel) — always test against the real uploaded file when available, not just synthetic data.
- Client reviews screenshots/behavior and reports issues directly ("not getting suggestions") — when debugging a reported issue, check both the likely server-side cause and the likely delivery/deployment-process cause (e.g. a new file not actually copied in), and hardening (error handling, explicit fallback UI) is welcome even if the deployment issue turns out to be the real cause.
- HMI framing matters: this app is used on both laptops and larger fixed monitors — no page-level scrolling, everything should "fit to screen," any new page should follow the same `.app-main` scroll-contained pattern already in place.

## Open questions to ask before extending, if not already answered
- Any new file-upload feature: overwrite-only or version history? AJAX or reload? Allowed extensions?
- Any new search/list feature: type-ahead only, or also explicit search trigger? What should "not found" look like?
- Any new data-driven feature reading client files: confirm exact sheet/column layout from a real sample file rather than guessing.
