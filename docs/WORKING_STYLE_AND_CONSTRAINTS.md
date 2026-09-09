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
- **When a reported bug doesn't reproduce from code review alone, ask for a live repro with a one-line temporary debug log before guessing further** — confirmed effective this session (a "red-screen audio silent" report traced to a stale activity's `table_settings` snapshot, not a code defect, once the client added one `console.log` and reported the actual runtime value). Prefer this over further static tracing once 2-3 rounds of code review haven't found the cause.
- **Client iterates on UI placement/wording after seeing it live, not before** — e.g. the S/P resolution badge moved from "beside the card" to "hanging off the top-right corner" only after the first version shipped, and a card label went from "Unrecognized" to "Wrong-part" the same way. Ship the first reasonable interpretation, expect a follow-up refinement round rather than trying to fully nail visual details from a text description alone.
- **A confirmed behavioral design can be REVERSED in a later round, not just extended** — the neglected-part feature is a real example: first built as "detected but completely invisible" (client's own original spec), later reversed to "detected, counted, green pop-up, visible red-tinted card" (client's own later spec). A LATER round reversed a second, related piece the same way: a genuinely unrecognized part with its alert switched off was originally kept on the brief RED pop-up path; a later round corrected this to GREEN too, while insisting the permanent database record still say "wrong part" regardless of the color shown. Don't assume an earlier round's confirmed design is permanent, and don't assume a correction to one part of a feature necessarily extends to a similar-looking part of the same feature — each reversal was scoped narrowly and confirmed explicitly before implementation, not inferred by analogy.
- **Multi-round features benefit from a written design summary before coding starts**, even after scope feels locked via Q&A — this project's red-screen feature took 3+ rounds of clarifying questions before implementation began; writing out the full data-flow/schema plan as a message (not just code comments) gave the client one clean checkpoint to catch a misunderstanding before any code was written.
- **Cross-blueprint changes need the EXACT file open, not an assumption based on a similar file already in hand** — when a request required editing `configuration/routes.py` (to propagate kit-config edits into `live_kitting_activities`' collection), the correct move was to explicitly ask for that specific file rather than guess its shape from `cv_ingest/routes.py`'s already-familiar patterns, even though both files share strong conventions (same `_activities_collection()`-style helper naming, same `try/except PyMongoError` shape). The two blueprints are deliberately decoupled (see TSD files' own notes on this) and a wrong guess about exact helper names, decorator patterns, or existing route bodies would have produced a diff that didn't actually apply cleanly.

## Testing patterns established
- **mongomock is the default test tool for this project** — used for every ingest/data-layer change so far, and should stay the default going forward. `test_kitting_v2_api.py` remains the separate real-server CLI tool for exercising the actual HTTP API without a real DeepStream box.
- **mongomock does NOT support MongoDB's `array_filters`** (confirmed while testing `resolve_error()`'s per-array-element update) — a genuine gap in the test tool, not in MongoDB itself. When a change needs `array_filters` (updating one specific element inside an array of embedded documents), write the query correctly per MongoDB's real syntax, but flag in both the test file and the relevant TSD section that this specific path is unverified by the project's usual mongomock suite and needs manual/real-MongoDB confirmation before being considered fully tested. Not every Mongo-touching feature hits this gap — the later live-activity config-propagation feature used only `find()`/`update_one($set)`, both fully mongomock-supported, so it was fully covered by the automated suite with no caveat needed. Check which Mongo operators a change actually uses before assuming a gap exists.
- **HTTP-header-level behavior (caching, conditional requests) needs a real Flask test client, not mongomock** — verifying `send_file`'s `Cache-Control`/`ETag`/304 behavior for the audio-caching fix required an actual `app.test_client()` round trip; mongomock has nothing to do with this kind of check since it's unrelated to MongoDB. Keep the two test approaches (mongomock for data-layer logic, a real Flask test client for HTTP-level behavior) separate and use whichever actually exercises the thing being verified.

## Open questions to ask before extending, if not already answered
- Any new file-upload feature: overwrite-only or version history? AJAX or reload? Allowed extensions?
- Any new search/list feature: type-ahead only, or also explicit search trigger? What should "not found" look like?
- Any new data-driven feature reading client files: confirm exact sheet/column layout from a real sample file rather than guessing.
