"""Versioned, category-owned vocabulary; no document-category assumptions."""

from copy import deepcopy
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator

DEFAULT = {
    "version": 1,
    "category": {"id": "generic", "version": "1", "roles": [], "anchors": [], "schemas": {}},
    "selection": {"filename_regex": None},
    "capture": {"render_width": 1100, "max_pixels": 24000000},
    "ocr": {"mode": "auto", "languages": ["en-US"], "timeout_seconds": 90},
    "layout": {"provider": "none", "artifacts_path": None, "threshold": 0.3, "threads": 2},
    "grouping": {"distance_threshold": 0.16, "grid_size": 8, "anchor_weight": 0.15},
}

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["version", "category", "selection", "capture", "ocr", "layout", "grouping"],
    "properties": {
        "version": {"const": 1},
        "category": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "version", "roles", "anchors", "schemas"],
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "version": {"type": "string", "minLength": 1},
                "roles": {"type": "array", "uniqueItems": True, "items": {"type": "string", "minLength": 1}},
                "schemas": {"type": "object", "additionalProperties": {
                    "type": "object", "additionalProperties": False,
                    "required": ["format", "uri"], "properties": {
                        "format": {"enum": ["json-schema", "xml-schema", "other"]},
                        "uri": {"type": "string", "minLength": 1},
                        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    },
                }},
                "anchors": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["id", "pattern"], "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "pattern": {"type": "string", "minLength": 1},
                        "role": {"type": ["string", "null"]},
                        "schema_ref": {"type": ["string", "null"]},
                    },
                }},
            },
        },
        "selection": {"type": "object", "additionalProperties": False, "properties": {
            "filename_regex": {"type": ["string", "null"]}}, "required": ["filename_regex"]},
        "capture": {"type": "object", "additionalProperties": False,
            "required": ["render_width", "max_pixels"], "properties": {
                "render_width": {"type": "integer", "minimum": 100, "maximum": 8000},
                "max_pixels": {"type": "integer", "minimum": 10000, "maximum": 100000000}}},
        "ocr": {"type": "object", "additionalProperties": False,
            "required": ["mode", "languages", "timeout_seconds"], "properties": {
                "mode": {"enum": ["auto", "always", "never"]},
                "languages": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
                "timeout_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 3600}}},
        "layout": {"type": "object", "additionalProperties": False,
            "required": ["provider", "artifacts_path", "threshold", "threads"], "properties": {
                "provider": {"enum": ["none", "docling"]},
                "artifacts_path": {"type": ["string", "null"]},
                "threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "threads": {"type": "integer", "minimum": 1, "maximum": 32}}},
        "grouping": {"type": "object", "additionalProperties": False,
            "required": ["distance_threshold", "grid_size", "anchor_weight"], "properties": {
                "distance_threshold": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
                "grid_size": {"type": "integer", "minimum": 4, "maximum": 32},
                "anchor_weight": {"type": "number", "minimum": 0, "maximum": 1}}},
    },
}


def load_config(value=None):
    """Apply explicit overrides to defaults, reject typos and broken references."""
    if isinstance(value, (str, Path)):
        value = json.loads(Path(value).read_text())
    result = deepcopy(DEFAULT)
    for key, item in (value or {}).items():
        if isinstance(item, dict) and isinstance(result.get(key), dict):
            result[key].update(item)
        else:
            result[key] = item
    Draft202012Validator(SCHEMA).validate(result)
    category = result["category"]
    ids = set()
    for anchor in category["anchors"]:
        if anchor["id"] in ids:
            raise ValueError("Duplicate anchor id")
        ids.add(anchor["id"])
        re.compile(anchor["pattern"], re.IGNORECASE)
        if anchor.get("role") and anchor["role"] not in category["roles"]:
            raise ValueError("Anchor role is absent from category roles")
        if anchor.get("schema_ref") and anchor["schema_ref"] not in category["schemas"]:
            raise ValueError("Anchor schema_ref is absent from category schemas")
    if result["selection"]["filename_regex"]:
        re.compile(result["selection"]["filename_regex"])
    return result
