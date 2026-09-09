#!/usr/bin/env python3
"""
test_kitting_v2_api.py

Standalone CLI script simulating the local DeepStream application's calls
to the Kitting Station v2 ingest APIs. Does not import anything from the
Flask app - talks over plain HTTP so it exercises the real endpoints
exactly as the DeepStream box will.

Usage - detection event (uploads a REAL image, see "Image resolution" below):
    python test_kitting_v2_api.py --tableid 1 --camid 1 --object_detected "Bracket A"

Usage - validate/advance kit (uploads cam{N}validation.jpg):
    python test_kitting_v2_api.py --tableid 1 --camid 1 --validate

Every other field the API expects (Aidetectedpartname, avg_threshold,
tracking_id, kitname) is randomly generated for --object_detected calls,
per the client's instruction ("all other you generate randomly").

Image resolution (real images, not placeholders):
- All images live in an "all_images" folder in the SAME directory as
  this script (client's explicit call - not a separate --images-dir
  argument, not the current working directory).
- --object_detected "<name>" looks for an EXACT match on the name,
  trying extensions in order .jpg, then .png, then .jpeg (first one
  found wins) - e.g. --object_detected "Bracket A" looks for
  "all_images/Bracket A.jpg", then "all_images/Bracket A.png", then
  "all_images/Bracket A.jpeg".
- If none of those three exist, falls back to "all_images/default.jpg"
  (client's explicit call) - the request still goes out, never skipped
  and never sent without an image, so a missing/misnamed file doesn't
  silently break the test run.
- --validate always uploads a FIXED filename depending on camera:
  "all_images/cam1validation.jpg" for --camid 1, or
  "all_images/cam2validation.jpg" for --camid 2 - not looked up by any
  detected-part name, since a validate call has no such name.
- If default.jpg itself, or the camN validation.jpg for the camera
  being called, is missing, this is a genuine setup error - the script
  exits with a clear message rather than silently sending no image or
  crashing on a confusing traceback from deep inside `requests`.

Requires: requests (Pillow no longer needed - this script now always
uploads a real image file rather than generating a placeholder JPG in
memory; kept as a doc note here in case anything else in this project
still depends on Pillow being installed for a different purpose).
"""

import argparse
import os
import random
import string
import sys

try:
    import requests
except ImportError:
    sys.exit("Missing dependency: pip install requests")


DEFAULT_BASE_URL = "http://localhost:7000"

DEFAULT_BASE_URL = "http://3.101.116.148:7000"

# All images live alongside this script, not the current working
# directory - resolved once via __file__ so the script behaves
# identically no matter where it's invoked from.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(SCRIPT_DIR, "all_images")

DEFAULT_IMAGE_NAME = "default.jpg"
# Extensions tried in order for an --object_detected exact-name match -
# first one that exists on disk wins (client's explicit call).
OBJECT_IMAGE_EXTENSIONS = (".jpg", ".png", ".jpeg")


def resolve_object_image_path(object_detected):
    """Exact-match lookup for a detection image: all_images/<object_detected>.<ext>,
    trying .jpg, .png, .jpeg in that order. Falls back to
    all_images/default.jpg if none of the three exist (client's
    explicit call) - exits with a clear error only if default.jpg
    ITSELF is also missing, since at that point there is truly nothing
    to send."""
    for ext in OBJECT_IMAGE_EXTENSIONS:
        candidate = os.path.join(IMAGES_DIR, f"{object_detected}{ext}")
        if os.path.isfile(candidate):
            return candidate

    default_path = os.path.join(IMAGES_DIR, DEFAULT_IMAGE_NAME)
    if os.path.isfile(default_path):
        print(
            f'  note: no image found for "{object_detected}" '
            f"(tried {', '.join(OBJECT_IMAGE_EXTENSIONS)}) - using {DEFAULT_IMAGE_NAME}"
        )
        return default_path

    sys.exit(
        f'No image found for "{object_detected}" (tried '
        f"{', '.join(OBJECT_IMAGE_EXTENSIONS)}), and the fallback "
        f"{default_path} does not exist either. Add a matching image "
        f"or a default.jpg to {IMAGES_DIR}."
    )


def resolve_validation_image_path(cam_id):
    """Validate calls always use a FIXED filename per camera - never
    looked up by part name, since there's no detected-part name on a
    validate call."""
    filename = f"cam{cam_id}validation.jpg"
    path = os.path.join(IMAGES_DIR, filename)
    if not os.path.isfile(path):
        sys.exit(f"Expected validation image not found: {path}")
    return path


def random_ai_part_name(object_detected):
    """Simulates the raw AI model output potentially differing slightly
    from the mapped/ground-truth detectedpart label."""
    suffix = "".join(random.choices(string.ascii_uppercase, k=3))
    return f"{object_detected}_raw_{suffix}"


def random_tracking_id():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=12))


def random_threshold():
    return round(random.uniform(0.55, 0.99), 4)


def random_kit_name():
    return random.choice(["KIT-ALPHA", "KIT-BRAVO", "KIT-CHARLIE", "KIT-DELTA"])


def send_detection_update(base_url, table_id, cam_id, object_detected):
    url = f"{base_url}/api/detection-update"
    fields = {
        "tableid": str(table_id),
        "camid": str(cam_id),
        "detectedpart": object_detected,
        "Aidetectedpartname": random_ai_part_name(object_detected),
        "avg_threshold": str(random_threshold()),
        "tracking_id": random_tracking_id(),
        "kitname": random_kit_name(),
    }

    image_path = resolve_object_image_path(object_detected)
    print(f"POST {url}")
    print(f"  fields: {fields}")
    print(f"  image:  {image_path}")

    with open(image_path, "rb") as image_file:
        files = {"image": (os.path.basename(image_path), image_file, "image/jpeg")}
        response = requests.post(url, data=fields, files=files, timeout=10)
    _print_response(response)


def send_validate_kit(base_url, table_id, cam_id):
    url = f"{base_url}/api/validate-kit"
    fields = {
        "tableid": str(table_id),
        "camid": str(cam_id),
        "message": "validate_now",
    }

    image_path = resolve_validation_image_path(cam_id)
    print(f"POST {url}")
    print(f"  fields: {fields}")
    print(f"  image:  {image_path}")

    with open(image_path, "rb") as image_file:
        files = {"image": (os.path.basename(image_path), image_file, "image/jpeg")}
        response = requests.post(url, data=fields, files=files, timeout=10)
    _print_response(response)


def _print_response(response):
    print(f"  status: {response.status_code}")
    try:
        print(f"  body:   {response.json()}")
    except ValueError:
        print(f"  body:   {response.text}")


def main():
    parser = argparse.ArgumentParser(description="Kitting Station v2 - CV ingest API test tool")
    parser.add_argument("--tableid", type=int, required=True, help="Table id, e.g. 1")
    parser.add_argument("--camid", type=int, required=True, choices=[1, 2], help="Camera id: 1 or 2")
    parser.add_argument("--object_detected", type=str, default=None, help="Part name detected (sends a detection-update)")
    parser.add_argument("--validate", action="store_true", help="Send a validate_now / advance-kit call instead of a detection")
    parser.add_argument("--base-url", type=str, default=DEFAULT_BASE_URL, help=f"API base URL (default: {DEFAULT_BASE_URL})")

    args = parser.parse_args()

    if args.validate and args.object_detected:
        parser.error("Use either --object_detected or --validate, not both.")
    if not args.validate and not args.object_detected:
        parser.error("One of --object_detected or --validate is required.")

    if args.validate:
        send_validate_kit(args.base_url, args.tableid, args.camid)
    else:
        send_detection_update(args.base_url, args.tableid, args.camid, args.object_detected)


if __name__ == "__main__":
    main()
