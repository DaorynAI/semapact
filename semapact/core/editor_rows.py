"""Dict-based row adapters for Streamlit editor tables.

These helpers intentionally operate on dict/list payloads because they model
editable rows exchanged with `st.data_editor` and `st.session_state`, not
canonical contract semantics.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from semapact.constants import (
    DEFAULT_QUALITY_SEVERITY,
    DEFAULT_QUALITY_TYPE,
    TABLE_RULE_COLUMN,
)
from semapact.core.editor_semantics import (
    set_field_examples,
    set_field_lifecycle_status,
    set_mapping_text,
)


def tags_to_text(tags: Any) -> str:
    """Render tags as a comma-separated string."""
    from semapact.core.editor_semantics import normalize_tags

    return ", ".join(normalize_tags(tags))


def text_to_tags(value: str) -> list[str]:
    """Parse tags from a comma-separated string."""
    from semapact.core.editor_semantics import normalize_tags

    return normalize_tags(value.split(","))


def is_blank_quick_field_row(row: dict[str, Any]) -> bool:
    """Return True when a quick-edit row is effectively empty."""
    return not any(
        [
            str(row.get("name", "")).strip(),
            str(row.get("type", "")).strip(),
            str(row.get("description", "")).strip(),
            bool(row.get("required", False)),
        ]
    )


def is_blank_quality_row(row: dict[str, Any]) -> bool:
    """Return True when a quality row is effectively empty."""
    return not any(
        [
            str(row.get("rule_name", "")).strip(),
            str(row.get("condition", "")).strip(),
            str(row.get("column", "")).strip(),
        ]
    )


def rule_condition(rule: dict[str, Any]) -> tuple[str, str]:
    """Resolve a readable condition field for a quality rule."""
    for key in (
        "condition",
        "mustBe",
        "mustBeGreaterThan",
        "mustBeLessThan",
        "query",
        "rule",
    ):
        if key in rule:
            value = rule.get(key)
            return key, "" if value is None else str(value)
    return "condition", ""


def optional_int(value: Any) -> int | None:
    """Convert a nullable dataframe value to an int."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        import pandas as pd

        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def apply_quick_field_rows(
    schema_obj: dict[str, Any], edited_rows: list[dict[str, Any]]
) -> None:
    """Write quick-edit business fields back to the selected schema."""
    original_fields = schema_obj.get("properties", []) or []
    updated_fields: list[dict[str, Any]] = []

    for row in edited_rows:
        if is_blank_quick_field_row(row):
            continue
        original_index = optional_int(row.get("__original_index"))
        base_field = (
            deepcopy(original_fields[original_index])
            if original_index is not None and 0 <= original_index < len(original_fields)
            else {}
        )
        set_mapping_text(base_field, "description", str(row.get("description", "")))
        set_mapping_text(base_field, "businessName", str(row.get("businessName", "")))
        set_field_lifecycle_status(base_field, row.get("lifecycleStatus", "draft"))
        if "physicalName" not in base_field:
            base_field["physicalName"] = base_field.get("name", "")
        updated_fields.append(base_field)

    schema_obj["properties"] = updated_fields


def apply_field_detail(
    field_obj: dict[str, Any],
    *,
    lifecycle_status: str,
    business_name: str,
    description: str,
    examples_text: str,
    tags_text: str,
    classification: str,
    transform_description: str,
) -> None:
    """Apply editable business metadata from the detail panel."""
    set_field_lifecycle_status(field_obj, lifecycle_status)
    set_mapping_text(field_obj, "businessName", business_name)
    set_mapping_text(field_obj, "description", description)
    set_field_examples(field_obj, examples_text)
    field_obj["tags"] = text_to_tags(tags_text)
    set_mapping_text(field_obj, "classification", classification)
    set_mapping_text(field_obj, "transformDescription", transform_description)
    if "physicalName" not in field_obj:
        field_obj["physicalName"] = field_obj.get("name", "")


def add_field(schema_obj: dict[str, Any]) -> None:
    """Append a blank field to the selected schema."""
    fields = schema_obj.setdefault("properties", [])
    field_number = len(fields) + 1
    fields.append(
        {
            "name": f"field_{field_number}",
            "physicalName": f"field_{field_number}",
            "logicalType": "string",
            "physicalType": "string",
            "required": False,
            "status": "draft",
            "customProperties": [{"property": "lifecycleStatus", "value": "draft"}],
        }
    )


def field_by_name(schema_obj: dict[str, Any], field_name: str) -> dict[str, Any] | None:
    """Return a field by name."""
    target_name = field_name.strip()
    for field_obj in schema_obj.get("properties", []) or []:
        if (
            isinstance(field_obj, dict)
            and str(field_obj.get("name", "")).strip() == target_name
        ):
            return field_obj
    return None


def selected_schema_field_names(schema_obj: dict[str, Any]) -> list[str]:
    """Return field names for the selected schema."""
    return [
        str(field_obj.get("name", "")).strip()
        for field_obj in schema_obj.get("properties", []) or []
        if isinstance(field_obj, dict) and str(field_obj.get("name", "")).strip()
    ]


def quality_row(
    rule: dict[str, Any], *, scope: str, rule_index: int, property_name: str
) -> dict[str, Any]:
    """Create a quality rule editor row."""
    condition_key, condition_value = rule_condition(rule)
    return {
        "rule_name": str(rule.get("name") or rule.get("metric") or "").strip(),
        "type": str(rule.get("type") or DEFAULT_QUALITY_TYPE).strip()
        or DEFAULT_QUALITY_TYPE,
        "column": property_name if scope == "field" else TABLE_RULE_COLUMN,
        "condition": condition_value,
        "severity": str(rule.get("severity") or DEFAULT_QUALITY_SEVERITY).strip()
        or DEFAULT_QUALITY_SEVERITY,
        "__scope": scope,
        "__rule_index": rule_index,
        "__property_name": property_name,
        "__condition_key": condition_key,
    }


def quality_rows(schema_obj: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten quality rules for the selected schema."""
    rows: list[dict[str, Any]] = []

    for index, rule in enumerate(schema_obj.get("quality", []) or []):
        if isinstance(rule, dict):
            rows.append(
                quality_row(rule, scope="table", rule_index=index, property_name="")
            )

    for field_obj in schema_obj.get("properties", []) or []:
        if not isinstance(field_obj, dict):
            continue
        field_name = str(field_obj.get("name", "")).strip()
        for index, rule in enumerate(field_obj.get("quality", []) or []):
            if isinstance(rule, dict):
                rows.append(
                    quality_row(
                        rule, scope="field", rule_index=index, property_name=field_name
                    )
                )

    return rows


def apply_quality_rows(
    schema_obj: dict[str, Any], edited_rows: list[dict[str, Any]]
) -> None:
    """Write edited quality rows back to the selected schema."""
    schema_obj["quality"] = []
    for field_obj in schema_obj.get("properties", []) or []:
        if isinstance(field_obj, dict):
            field_obj.pop("quality", None)

    for row in edited_rows:
        if is_blank_quality_row(row):
            continue
        rule = {
            "name": str(row.get("rule_name", "")).strip(),
            "type": str(row.get("type", DEFAULT_QUALITY_TYPE)).strip()
            or DEFAULT_QUALITY_TYPE,
            "severity": str(row.get("severity", DEFAULT_QUALITY_SEVERITY)).strip()
            or DEFAULT_QUALITY_SEVERITY,
        }
        condition_key = (
            str(row.get("__condition_key", "condition")).strip() or "condition"
        )
        condition_value = str(row.get("condition", "")).strip()
        if condition_value:
            rule[condition_key] = condition_value

        target_column = (
            str(row.get("column", TABLE_RULE_COLUMN)).strip() or TABLE_RULE_COLUMN
        )
        if target_column == TABLE_RULE_COLUMN:
            schema_obj.setdefault("quality", []).append(rule)
            continue

        field_obj = field_by_name(schema_obj, target_column)
        if field_obj is not None:
            field_obj.setdefault("quality", []).append(rule)

    if not schema_obj.get("quality"):
        schema_obj.pop("quality", None)


def add_quality_rule(schema_obj: dict[str, Any]) -> None:
    """Append a blank table-level rule to the selected schema."""
    schema_obj.setdefault("quality", []).append(
        {
            "name": "",
            "type": DEFAULT_QUALITY_TYPE,
            "severity": DEFAULT_QUALITY_SEVERITY,
            "condition": "",
        }
    )
