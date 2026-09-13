#!/usr/bin/env python3
"""
test_kitting_v2_autonomous.py

Fully autonomous end-to-end test driver for the Kitting Station v2 CV
ingest APIs. Unlike the older test_kitting_v2_api.py (one manual call
per invocation), this script:

  1. Connects DIRECTLY to MongoDB (same DB the Flask app uses) to read
     an ALREADY-RUNNING live activity's configuration - parts_configured,
     neglect_parts, quantity_required, table_id - rather than requiring
     any of that to be typed on the command line.
  2. Drives BOTH cameras independently, each in its own thread, since
     cam1/cam2 advance independently in the real app (confirmed
     scope - a camera finishing early does not wait for the other).
  3. Cycles through a fixed set of 7 test scenarios per kit (clean,
     undercount, overcount, wrong-part, neglected-part-ignored, missing,
     combined-anomaly), wrapping back to the start if more kits are
     configured than scenarios - deliberately covers every alert type
     the app supports, not just random detections.
  4. POLLS the activity document every 2 seconds after each kit's
     detections are sent, watching camera_state_cam{N}. When a red
     screen locks the camera, the script does NOT try to resolve it
     itself - it prints a clear "waiting for manual resolve" message
     and keeps polling. Once you resolve it in the UI (System Error /
     Process Error), camera_state flips back to "open" and the script
     automatically sends the validate call and moves on.
  5. Exits cleanly once BOTH cameras report current_kit_index >
     quantity_required (camera-complete sentinel - see
     TSD_LIVE_KITTING_ACTIVITIES.md's "Completion semantics").

This script does NOT create the live activity - it attaches to one
that's already running (started manually through the UI), found by
--table-id. This mirrors real usage: a human starts the run in the UI,
then kicks off this script to simulate the DeepStream box against it.

--- Images ---

All images live in an "all_images" folder next to this script (same
convention as the older test_kitting_v2_api.py). Filenames are matched
EXACTLY against whatever part_name Mongo says is configured for that
camera - e.g. a part_name of "1" needs all_images/1.jpg (or .png/.jpeg).
There is no generic/random image pool selection - which specific image
gets sent is entirely determined by which part_name (or wrong-part /
neglected-part name) the current scenario calls for, read fresh from
Mongo every kit.

cam1validation.jpg / cam2validation.jpg are used for --validate calls,
same fixed-filename convention as before.

--- Requires ---

pip install requests pymongo python-dotenv

--- Usage ---

    python test_kitting_v2_autonomous.py --table-id 1

Optional:
    --base-url http://localhost:7000     (Flask app, default shown)
    --mongo-uri mongodb://localhost:27017/   (overrides MONGO_URI env var)
    --db-name kitting_station_v2         (overrides config.yaml's value)
    --min-delay 6 --max-delay 14         (seconds between detections, default 6-14)
    --poll-interval 2                    (seconds between camera_state polls)
"""

import argparse
import os
import random
import string
import sys
import threading
import time

try:
    import requests
except ImportError:
    sys.exit("Missing dependency: pip install requests")

try:
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError
except ImportError:
    sys.exit("Missing dependency: pip install pymongo")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Optional - MONGO_URI can still be set directly in the shell
    # environment without python-dotenv installed at all.
    pass


DEFAULT_BASE_URL = "http://localhost:7000"
DEFAULT_DB_NAME = "kitting_station_v2"
DEFAULT_COLLECTION = "live_activity_details"
DEFAULT_MIN_DELAY_SEC = 6
DEFAULT_MAX_DELAY_SEC = 14
DEFAULT_POLL_INTERVAL_SEC = 2

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(SCRIPT_DIR, "all_images")
IMAGE_EXTENSIONS = (".jpg", ".png", ".jpeg")

CAMERA_STATE_LOCKED = "locked"

# Print statements from multiple threads (cam1/cam2) interleave on
# stdout - a single shared lock keeps each individual print() call from
# being torn in half, without slowing anything down materially.
_print_lock = threading.Lock()


def log(cam_id, message):
    with _print_lock:
        print(f"[{cam_id}] {message}")


# ---------------------------------------------------------------------------
# Image resolution - exact part_name match, same convention as the
# older script, just sourced from Mongo instead of a CLI argument.
# ---------------------------------------------------------------------------

def resolve_part_image_path(part_name):
    for ext in IMAGE_EXTENSIONS:
        candidate = os.path.join(IMAGES_DIR, f"{part_name}{ext}")
        if os.path.isfile(candidate):
            return candidate
    sys.exit(
        f'No image found for part_name "{part_name}" (tried '
        f"{', '.join(IMAGE_EXTENSIONS)}) in {IMAGES_DIR}. "
        f"Add a matching image before running this test."
    )


def resolve_validation_image_path(cam_id):
    filename = f"cam{cam_id}validation.jpg"
    path = os.path.join(IMAGES_DIR, filename)
    if not os.path.isfile(path):
        sys.exit(f"Expected validation image not found: {path}")
    return path


# ---------------------------------------------------------------------------
# Random field generation - unchanged conventions from the older script
# ---------------------------------------------------------------------------

def random_ai_part_name(part_name):
    suffix = "".join(random.choices(string.ascii_uppercase, k=3))
    return f"{part_name}_raw_{suffix}"


def random_tracking_id():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=12))


def random_threshold():
    return round(random.uniform(0.55, 0.99), 4)


# ---------------------------------------------------------------------------
# HTTP calls
# ---------------------------------------------------------------------------

def send_detection_update(base_url, table_id, cam_id, part_name, kit_name):
    url = f"{base_url}/api/detection-update"
    fields = {
        "tableid": str(table_id),
        "camid": f"cam{cam_id}",
        "detectedpart": part_name,
        "Aidetectedpartname": random_ai_part_name(part_name),
        "avg_threshold": str(random_threshold()),
        "tracking_id": random_tracking_id(),
        "kitname": kit_name,
    }
    image_path = resolve_part_image_path(part_name)

    with open(image_path, "rb") as image_file:
        files = {"image": (os.path.basename(image_path), image_file, "image/jpeg")}
        response = requests.post(url, data=fields, files=files, timeout=10)

    return response


def send_validate_kit(base_url, table_id, cam_id):
    url = f"{base_url}/api/validate-kit"
    fields = {
        "tableid": str(table_id),
        "camid": f"cam{cam_id}",
        "message": "validate_now",
    }
    image_path = resolve_validation_image_path(cam_id)

    with open(image_path, "rb") as image_file:
        files = {"image": (os.path.basename(image_path), image_file, "image/jpeg")}
        response = requests.post(url, data=fields, files=files, timeout=10)

    return response


# ---------------------------------------------------------------------------
# Scenario planning - the core "which parts get what treatment" logic
#
# Each scenario returns a plan: a list of (part_name, detection_count)
# tuples for configured parts, PLUS optional wrong_part_name and
# neglected_part_name to also throw in. quantity_required detections
# means "exactly right"; the scenario functions deliberately deviate
# from that for specific parts to exercise specific alert paths.
# ---------------------------------------------------------------------------

SCENARIOS = [
    "clean",
    "undercount",
    "overcount",
    "wrong_part",
    "neglected_part",
    "missing",
    "combined_anomaly",
]


def _pick_alert_enabled_part(parts, flag, min_quantity_required=1):
    """Returns one configured part dict with the given alert flag on
    AND quantity_required >= min_quantity_required, or None if no such
    part exists for this camera (scenario is then skipped gracefully
    rather than crashing - not every kit's configuration necessarily
    has a part suited to this scenario).

    min_quantity_required matters specifically for undercount: a part
    with quantity_required == 1 can only ever go from 1 -> 0 when
    "undercounted", which the real app's own _find_validation_issues()
    classifies as MISSING (found == 0), not undercount (0 < found <
    required) - confirmed by reading cv_ingest/detection_data.py
    directly. Requiring quantity_required >= 2 for the undercount
    scenario guarantees a genuine 0 < found < required case actually
    exists to send."""
    candidates = [
        p for p in parts
        if p.get(flag) and p.get("quantity_required", 1) >= min_quantity_required
    ]
    return random.choice(candidates) if candidates else None


def _pick_unconfigured_image_name(parts, neglect_names):
    """Finds a filename in IMAGES_DIR that is NEITHER a configured
    part_name for this camera NOR in its neglect list - i.e. a genuine
    wrong-part image. Returns None if no such image exists in the pool
    (scenario skipped gracefully)."""
    configured_names = {p.get("part_name") for p in parts}
    if not os.path.isdir(IMAGES_DIR):
        return None

    candidates = []
    for filename in os.listdir(IMAGES_DIR):
        stem, ext = os.path.splitext(filename)
        if ext.lower() not in IMAGE_EXTENSIONS:
            continue
        if stem in configured_names or stem in neglect_names:
            continue
        if stem in ("default", "cam1validation", "cam2validation"):
            continue
        candidates.append(stem)

    return random.choice(candidates) if candidates else None


def build_kit_plan(scenario, parts, neglect_names):
    """Returns {"detections": [(part_name, count), ...],
                "wrong_part": str|None, "neglected_part": str|None}
    for one kit, given this camera's parts_configured and neglect list.
    "detections" always includes every configured part at its correct
    quantity_required UNLESS the scenario specifically deviates that
    part's count (undercount/overcount/missing) - so a kit is only ever
    missing/wrong on the ONE part the scenario targets, everything else
    stays clean."""
    detections = [(p.get("part_name"), p.get("quantity_required", 1)) for p in parts]
    wrong_part = None
    neglected_part = None

    if scenario == "clean":
        pass  # detections list as-is - every part exact quantity

    elif scenario == "undercount":
        # Requires quantity_required >= 2 - see _pick_alert_enabled_part's
        # own docstring for why (qty=1 can only go to 0, which the real
        # app classifies as MISSING, not undercount).
        target = _pick_alert_enabled_part(parts, "alert_undercount", min_quantity_required=2)
        if target:
            name = target.get("part_name")
            required = target.get("quantity_required", 1)
            reduced = random.randint(1, required - 1)  # strictly 0 < reduced < required
            detections = [(n, reduced if n == name else c) for n, c in detections]

    elif scenario == "overcount":
        target = _pick_alert_enabled_part(parts, "alert_overcount")
        if target:
            name = target.get("part_name")
            required = target.get("quantity_required", 1)
            increased = required + random.randint(1, 3)
            detections = [(n, increased if n == name else c) for n, c in detections]

    elif scenario == "wrong_part":
        wrong_part = _pick_unconfigured_image_name(parts, neglect_names)

    elif scenario == "neglected_part":
        if neglect_names:
            neglected_part = random.choice(list(neglect_names))

    elif scenario == "missing":
        target = _pick_alert_enabled_part(parts, "alert_missing")
        if target:
            name = target.get("part_name")
            detections = [(n, 0 if n == name else c) for n, c in detections]

    elif scenario == "combined_anomaly":
        # Undercount ONE part AND throw in a wrong-part detection in
        # the same kit - confirms multiple simultaneous issues surface
        # correctly together (matches this app's own confirmed "issues
        # is a list, not a single value" schema).
        target = _pick_alert_enabled_part(parts, "alert_undercount", min_quantity_required=2)
        if target:
            name = target.get("part_name")
            required = target.get("quantity_required", 1)
            reduced = random.randint(1, required - 1)
            detections = [(n, reduced if n == name else c) for n, c in detections]
        wrong_part = _pick_unconfigured_image_name(parts, neglect_names)

    return {"detections": detections, "wrong_part": wrong_part, "neglected_part": neglected_part}


def flatten_plan_to_calls(plan):
    """Turns a kit plan into a flat, randomly-interleaved list of
    individual (part_name,) detection calls - client's explicit scope:
    detections across a camera's parts are interleaved, not sent one
    full part at a time."""
    calls = []
    for part_name, count in plan["detections"]:
        calls.extend([part_name] * max(0, count))
    if plan["wrong_part"]:
        calls.append(plan["wrong_part"])
    if plan["neglected_part"]:
        calls.append(plan["neglected_part"])

    random.shuffle(calls)
    return calls


# ---------------------------------------------------------------------------
# Mongo access
# ---------------------------------------------------------------------------

def get_activity_doc(collection, table_id):
    return collection.find_one({"table_id": table_id, "status": "live"})


def cam_parts(activity_doc, cam_id):
    return [p for p in activity_doc.get("parts_configured", []) if p.get("camera") == f"cam{cam_id}"]


def cam_neglect_names(activity_doc, cam_id):
    return {
        p.get("part_name")
        for p in activity_doc.get("neglect_parts", [])
        if p.get("camera") == f"cam{cam_id}"
    }


# ---------------------------------------------------------------------------
# Per-camera driver thread
# ---------------------------------------------------------------------------

def run_camera(cam_id, collection, table_id, base_url, min_delay, max_delay, poll_interval):
    kit_field = f"current_kit_index_cam{cam_id}"
    state_field = f"camera_state_cam{cam_id}"

    while True:
        doc = get_activity_doc(collection, table_id)
        if doc is None:
            log(cam_id, "Activity no longer live (completed/removed) - stopping.")
            return

        current_index = doc.get(kit_field, 1)
        quantity_required = doc.get("quantity_required")
        if quantity_required is not None and current_index > quantity_required:
            log(cam_id, f"Camera complete (kit index {current_index} > {quantity_required}). Stopping.")
            return

        parts = cam_parts(doc, cam_id)
        if not parts:
            log(cam_id, "No parts_configured for this camera - nothing to do. Stopping.")
            return

        neglect_names = cam_neglect_names(doc, cam_id)
        kit_name = doc.get("kit_name", "TEST-KIT")

        scenario = SCENARIOS[(current_index - 1) % len(SCENARIOS)]
        plan = build_kit_plan(scenario, parts, neglect_names)
        calls = flatten_plan_to_calls(plan)

        log(cam_id, f"Kit {current_index} - scenario: {scenario} - {len(calls)} detection(s) planned")

        for part_name in calls:
            response = send_detection_update(base_url, table_id, cam_id, part_name, kit_name)
            status_note = "OK" if response.status_code == 200 else f"HTTP {response.status_code}"
            log(cam_id, f"  detected '{part_name}' -> {status_note}")
            time.sleep(random.uniform(min_delay, max_delay))

        # After all detections for this kit are sent, poll for a
        # red-screen lock before attempting to validate. A locked
        # camera means a wrong-part or validation error is waiting on
        # a HUMAN to pick System Error / Process Error in the UI - this
        # script never resolves it itself, only waits.
        printed_waiting_message = False
        while True:
            doc = get_activity_doc(collection, table_id)
            if doc is None:
                log(cam_id, "Activity disappeared while waiting for resolve - stopping.")
                return

            state = doc.get(state_field)
            if state != CAMERA_STATE_LOCKED:
                break

            if not printed_waiting_message:
                log(cam_id, f"Kit {current_index} is LOCKED (red screen) - "
                            f"waiting for manual System Error / Process Error resolve in the UI...")
                printed_waiting_message = True
            time.sleep(poll_interval)

        log(cam_id, f"Kit {current_index} - sending validate...")
        response = send_validate_kit(base_url, table_id, cam_id)
        status_note = "OK" if response.status_code == 200 else f"HTTP {response.status_code}"
        log(cam_id, f"  validate -> {status_note}")

        # Loop back around - re-fetches the doc at the top, which will
        # show the NEW current_kit_index if the validate succeeded (or
        # the SAME index again if it didn't - e.g. validate itself hit
        # a validation_error and re-locked the camera, in which case
        # the poll-and-wait above runs again next time through).
        time.sleep(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Autonomous end-to-end test driver for the Kitting Station v2 CV ingest APIs."
    )
    parser.add_argument("--table-id", type=int, required=True, help="Table id of the ALREADY-RUNNING live activity to attach to")
    parser.add_argument("--base-url", type=str, default=DEFAULT_BASE_URL, help=f"Flask app base URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--mongo-uri", type=str, default=None, help="MongoDB URI (default: MONGO_URI env var)")
    parser.add_argument("--db-name", type=str, default=DEFAULT_DB_NAME, help=f"MongoDB database name (default: {DEFAULT_DB_NAME})")
    parser.add_argument("--min-delay", type=float, default=DEFAULT_MIN_DELAY_SEC, help=f"Min seconds between detections (default: {DEFAULT_MIN_DELAY_SEC})")
    parser.add_argument("--max-delay", type=float, default=DEFAULT_MAX_DELAY_SEC, help=f"Max seconds between detections (default: {DEFAULT_MAX_DELAY_SEC})")
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_SEC, help=f"Seconds between camera_state polls while waiting for a manual resolve (default: {DEFAULT_POLL_INTERVAL_SEC})")

    args = parser.parse_args()

    mongo_uri = args.mongo_uri or os.environ.get("MONGO_URI")
    if not mongo_uri:
        sys.exit("No Mongo URI given - set MONGO_URI in the environment/.env, or pass --mongo-uri.")

    if not os.path.isdir(IMAGES_DIR):
        sys.exit(f"Images folder not found: {IMAGES_DIR}. Create it and add the required part images.")

    try:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        db = client[args.db_name]
        collection = db[DEFAULT_COLLECTION]
        client.admin.command("ping")
    except PyMongoError as exc:
        sys.exit(f"Could not connect to MongoDB: {exc}")

    doc = get_activity_doc(collection, args.table_id)
    if doc is None:
        sys.exit(
            f"No LIVE activity found for table_id={args.table_id}. "
            f"Start one from the UI first, then re-run this script."
        )

    print(f"Attached to live activity: table {args.table_id}, kit '{doc.get('kit_name')}', "
          f"order '{doc.get('order_number')}', quantity_required={doc.get('quantity_required')}")
    print(f"Scenario cycle (per camera, independently): {', '.join(SCENARIOS)}")
    print("Starting cam1 and cam2 drivers in parallel. Ctrl+C to stop.\n")

    threads = [
        threading.Thread(
            target=run_camera,
            args=(cam_id, collection, args.table_id, args.base_url, args.min_delay, args.max_delay, args.poll_interval),
            daemon=True,
        )
        for cam_id in (1, 2)
    ]

    for t in threads:
        t.start()

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("\nInterrupted - exiting (threads are daemonized, process will terminate).")
        sys.exit(1)

    print("\nBoth cameras complete. Activity should now be eligible for completion.")


if __name__ == "__main__":
    main()
