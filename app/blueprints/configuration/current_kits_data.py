"""
Current Kits Configuration - MongoDB data access + validation.

Keeps DB queries and payload shaping out of routes.py, same separation
pqpr_parser.py already gives the PQPR feature. routes.py only translates
HTTP <-> these functions.

Document shape (collection: mongodb.collections.current_kits):
{
  "serial_number": int,
  "kit_name": str,
  "edp_number": str,
  "parts": [
    {
      "part_name": str,
      "quantity_required": int,
      "camera": "cam1" | "cam2",
      "alert_missing": bool,
      "alert_undercount": bool,
      "alert_overcount": bool,
      "class_resemblance": str,
    }
  ],
  "neglect_parts": [
    {"part_name": str, "camera": "cam1" | "cam2"}
  ],
  "created_at": iso str,
  "updated_at": iso str,
}
"""

import re
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

ALLOWED_CAMERAS = ("cam1", "cam2")


class ValidationError(Exception):
    """Raised on bad input - caught in routes.py and turned into a 400
    JSON response, never a 500."""


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _to_object_id(kit_id):
    try:
        return ObjectId(kit_id)
    except (InvalidId, TypeError):
        raise ValidationError("Invalid kit id.")


def _validate_part(part, index):
    name = (part.get("part_name") or "").strip()
    if not name:
        raise ValidationError(f"Part #{index + 1}: part name is required.")

    try:
        qty = int(part.get("quantity_required"))
    except (TypeError, ValueError):
        raise ValidationError(
            f'Part #{index + 1} ("{name}"): quantity must be a whole number.'
        )
    if qty <= 0:
        raise ValidationError(
            f'Part #{index + 1} ("{name}"): quantity must be greater than 0.'
        )

    camera = part.get("camera")
    if camera not in ALLOWED_CAMERAS:
        raise ValidationError(
            f'Part #{index + 1} ("{name}"): camera must be Camera 1 or Camera 2.'
        )

    return {
        "part_name": name,
        "quantity_required": qty,
        "camera": camera,
        "alert_missing": bool(part.get("alert_missing")),
        "alert_undercount": bool(part.get("alert_undercount")),
        "alert_overcount": bool(part.get("alert_overcount")),
        "class_resemblance": (part.get("class_resemblance") or "").strip(),
    }


def _validate_neglect_part(part, index):
    name = (part.get("part_name") or "").strip()
    if not name:
        raise ValidationError(f"Neglect part #{index + 1}: part name is required.")

    camera = part.get("camera")
    if camera not in ALLOWED_CAMERAS:
        raise ValidationError(
            f'Neglect part #{index + 1} ("{name}"): camera must be Camera 1 or Camera 2.'
        )

    return {"part_name": name, "camera": camera}


def _validate_kit_payload(payload):
    try:
        serial_number = int(payload.get("serial_number"))
    except (TypeError, ValueError):
        raise ValidationError("Serial number is required and must be a whole number.")
    if serial_number <= 0:
        raise ValidationError("Serial number must be greater than 0.")

    kit_name = (payload.get("kit_name") or "").strip()
    if not kit_name:
        raise ValidationError("Kit name is required.")

    edp_number = (payload.get("edp_number") or "").strip()
    if not edp_number:
        raise ValidationError("EDP number is required.")

    parts = [_validate_part(p, i) for i, p in enumerate(payload.get("parts") or [])]
    neglect_parts = [
        _validate_neglect_part(p, i)
        for i, p in enumerate(payload.get("neglect_parts") or [])
    ]

    return {
        "serial_number": serial_number,
        "kit_name": kit_name,
        "edp_number": edp_number,
        "parts": parts,
        "neglect_parts": neglect_parts,
    }


def _kit_summary(doc):
    """Shape used for the list table - total parts + per-camera counts
    are derived from the parts array, not stored redundantly."""
    parts = doc.get("parts", [])
    cam1_count = sum(1 for p in parts if p.get("camera") == "cam1")
    cam2_count = sum(1 for p in parts if p.get("camera") == "cam2")
    return {
        "id": str(doc["_id"]),
        "serial_number": doc.get("serial_number"),
        "kit_name": doc["kit_name"],
        "edp_number": doc["edp_number"],
        "total_parts": len(parts),
        "cam1_count": cam1_count,
        "cam2_count": cam2_count,
        "updated_at": doc.get("updated_at"),
    }


def list_kits(collection):
    docs = collection.find().sort("serial_number", 1)
    return [_kit_summary(d) for d in docs]


def search_kits(collection, query_text):
    """Case-insensitive substring match across kit name, EDP number, and
    part names (nested in the parts array). Empty/blank query returns the
    full list, same sort as list_kits."""
    query_text = (query_text or "").strip()
    if not query_text:
        return list_kits(collection)

    pattern = re.escape(query_text)
    mongo_query = {
        "$or": [
            {"kit_name": {"$regex": pattern, "$options": "i"}},
            {"edp_number": {"$regex": pattern, "$options": "i"}},
            {"parts.part_name": {"$regex": pattern, "$options": "i"}},
        ]
    }
    docs = collection.find(mongo_query).sort("serial_number", 1)
    return [_kit_summary(d) for d in docs]


def get_kit(collection, kit_id):
    doc = collection.find_one({"_id": _to_object_id(kit_id)})
    if not doc:
        return None
    doc["id"] = str(doc["_id"])
    return doc


def _value_taken(collection, field, value, exclude_object_id=None):
    query = {field: value}
    if exclude_object_id is not None:
        query["_id"] = {"$ne": exclude_object_id}
    return collection.find_one(query) is not None


def create_kit(collection, payload):
    data = _validate_kit_payload(payload)
    if _value_taken(collection, "serial_number", data["serial_number"]):
        raise ValidationError(
            f'Serial number "{data["serial_number"]}" is already used by another kit.'
        )
    if _value_taken(collection, "edp_number", data["edp_number"]):
        raise ValidationError(
            f'EDP number "{data["edp_number"]}" is already used by another kit.'
        )

    now = _now_iso()
    data["created_at"] = now
    data["updated_at"] = now
    result = collection.insert_one(data)
    return str(result.inserted_id)


def update_kit(collection, kit_id, payload):
    object_id = _to_object_id(kit_id)
    data = _validate_kit_payload(payload)
    if _value_taken(
        collection, "serial_number", data["serial_number"], exclude_object_id=object_id
    ):
        raise ValidationError(
            f'Serial number "{data["serial_number"]}" is already used by another kit.'
        )
    if _value_taken(
        collection, "edp_number", data["edp_number"], exclude_object_id=object_id
    ):
        raise ValidationError(
            f'EDP number "{data["edp_number"]}" is already used by another kit.'
        )

    data["updated_at"] = _now_iso()
    result = collection.update_one({"_id": object_id}, {"$set": data})
    if result.matched_count == 0:
        raise ValidationError("Kit not found.")


def delete_kit(collection, kit_id):
    object_id = _to_object_id(kit_id)
    result = collection.delete_one({"_id": object_id})
    if result.deleted_count == 0:
        raise ValidationError("Kit not found.")
