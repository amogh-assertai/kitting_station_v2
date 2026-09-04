#!/usr/bin/env python3
"""
test_kitting_v2_api.py

Standalone CLI script simulating the local DeepStream application's calls
to the Kitting Station v2 ingest APIs. Does not import anything from the
Flask app - talks over plain HTTP so it exercises the real endpoints
exactly as the DeepStream box will.

Usage - detection event:
    python test_kitting_v2_api.py --tableid 1 --camid 1 --object_detected "Bracket A"

Usage - validate/advance kit:
    python test_kitting_v2_api.py --tableid 1 --camid 1 --validate

Every other field the API expects (Aidetectedpartname, avg_threshold,
tracking_id, kitname) is randomly generated for --object_detected calls,
per the client's instruction ("all other you generate randomly").

A placeholder image is generated on the fly (solid-color JPG, no
external asset dependency) and attached to every call, since image
frequency/rules are still TBD per the requirements discussion - sending
one every time is the safest default for exercising the endpoint during
this build.

Requires: requests, Pillow (pip install requests Pillow)
"""

import argparse
import io
import random
import string
import sys

try:
    import requests
except ImportError:
    sys.exit("Missing dependency: pip install requests")

try:
    from PIL import Image
except ImportError:
    sys.exit("Missing dependency: pip install Pillow")


DEFAULT_BASE_URL = "http://localhost:7000"


def build_placeholder_image():
    """Generates a small solid-color JPG in memory - no external asset
    file needed to run this script from any directory."""
    color = (
        random.randint(0, 255),
        random.randint(0, 255),
        random.randint(0, 255),
    )
    img = Image.new("RGB", (320, 240), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    return buf


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
    image = build_placeholder_image()
    files = {"image": ("placeholder.jpg", image, "image/jpeg")}

    print(f"POST {url}")
    print(f"  fields: {fields}")

    response = requests.post(url, data=fields, files=files, timeout=10)
    _print_response(response)


def send_validate_kit(base_url, table_id, cam_id):
    url = f"{base_url}/api/validate-kit"
    fields = {
        "tableid": str(table_id),
        "camid": str(cam_id),
        "message": "validate_now",
    }
    image = build_placeholder_image()
    files = {"image": ("placeholder.jpg", image, "image/jpeg")}

    print(f"POST {url}")
    print(f"  fields: {fields}")

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
