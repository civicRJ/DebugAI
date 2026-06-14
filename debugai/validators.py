"""Reusable validators for diagnosis and SDK runtime checks."""

from __future__ import annotations

import json
from typing import Any


def validate_json_schema(output: str, schema: dict | None) -> list[str]:
    """Validate a JSON response against a small JSON Schema subset.

    This intentionally stays stdlib-only. It covers the checks DebugAI needs for
    structured-output debugging without forcing a jsonschema dependency:
    JSON parseability, top-level type, required properties, and property types.
    """
    if not schema:
        return []
    try:
        data = json.loads((output or "").strip())
    except json.JSONDecodeError as e:
        return [f"Output is not valid JSON: {e}"]

    violations: list[str] = []
    schema_type = schema.get("type")
    if schema_type:
        expected = _type_map().get(schema_type)
        if expected and not isinstance(data, expected):
            violations.append(
                f"Expected JSON {schema_type}, got {type(data).__name__}"
            )

    if isinstance(data, dict):
        for req in schema.get("required", []):
            if req not in data:
                violations.append(f"Missing required property: '{req}'")
        for prop, prop_schema in schema.get("properties", {}).items():
            if prop in data and isinstance(prop_schema, dict):
                ptype = prop_schema.get("type")
                expected = _type_map().get(ptype)
                if expected and not isinstance(data[prop], expected):
                    violations.append(
                        f"Property '{prop}' should be {ptype}, got {type(data[prop]).__name__}"
                    )
                enum = prop_schema.get("enum")
                if enum is not None and data[prop] not in enum:
                    violations.append(f"Property '{prop}' must be one of {enum!r}")
    return violations


def _type_map() -> dict[str, Any]:
    return {
        "object": dict,
        "array": list,
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
    }
