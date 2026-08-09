from __future__ import annotations

import re
from typing import Any

from open_data_contract_standard.model import (
    CustomProperty,
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)
from semapact.exceptions import ValidationError

ACTIVE_STATUSES = {"active"}
NON_BREAKING_LIFECYCLE_STATUSES = {"draft", "deprecated"}


def normalize_status(value: Any, default: str = "draft") -> str:
    """Normalize status-like values to lowercase strings."""
    if value is None:
        return default
    text = str(value).strip().lower()
    return text or default


def is_active_contract(contract: OpenDataContractStandard) -> bool:
    """Return True when contract-level status is active."""
    value = contract.status
    if not value:
        value = lifecycle_from_custom_properties(contract.customProperties)
    return normalize_status(value, default="draft") in ACTIVE_STATUSES


def allows_breaking_changes(entity: Any) -> bool:
    """Return True when entity lifecycle status permits non-breaking updates only."""
    value = getattr(entity, "lifecycleStatus", None)
    if value is None:
        value = lifecycle_from_custom_properties(
            getattr(entity, "customProperties", None)
        )
    lifecycle_status = normalize_status(value, default="active")
    return lifecycle_status not in NON_BREAKING_LIFECYCLE_STATUSES


def schema_items(contract: OpenDataContractStandard) -> list[Any]:
    """Return schema entries for the ODCS contract."""
    return list(contract.schema_ or [])


def lifecycle_from_custom_properties(custom_properties: Any) -> Any:
    """Extract lifecycleStatus from custom properties list.

    Supports both ``CustomProperty`` model instances and raw ``dict`` items.
    """
    if not isinstance(custom_properties, list):
        return None
    for item in custom_properties:
        if isinstance(item, CustomProperty):
            key = (item.property or "").strip().lower()
            if key == "lifecyclestatus":
                return item.value
        elif isinstance(item, dict):
            key = str(item.get("property") or "").strip().lower()
            if key == "lifecyclestatus":
                return item.get("value")
    return None


# Keep the old private name as an alias for backwards compatibility within
# the package.  New code should use ``lifecycle_from_custom_properties``.
_lifecycle_from_custom_properties = lifecycle_from_custom_properties


# ---------------------------------------------------------------------------
# Decimal precision / scale comparison helpers
# ---------------------------------------------------------------------------


def decimal_precision_reduction(
    imported_physical_type: Any, existing_physical_type: Any
) -> bool:
    """Return True when the imported decimal precision is narrower than existing."""
    imported_ps = _decimal_precision_scale(imported_physical_type)
    existing_ps = _decimal_precision_scale(existing_physical_type)
    if imported_ps is None or existing_ps is None:
        return False
    return imported_ps[0] < existing_ps[0]


def decimal_scale_reduction(
    imported_physical_type: Any, existing_physical_type: Any
) -> bool:
    """Return True when the imported decimal scale is narrower than existing."""
    imported_ps = _decimal_precision_scale(imported_physical_type)
    existing_ps = _decimal_precision_scale(existing_physical_type)
    if imported_ps is None or existing_ps is None:
        return False
    return imported_ps[1] < existing_ps[1]


def _decimal_precision_scale(physical_type: Any) -> tuple[int, int] | None:
    if not isinstance(physical_type, str):
        return None
    match = re.match(
        r"\s*decimal\((\d+)\s*,\s*(\d+)\)\s*", physical_type, re.IGNORECASE
    )
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


# ---------------------------------------------------------------------------
# Canonical identity resolution helpers (Issue #75)
# ---------------------------------------------------------------------------


def normalize_identity_name(name: str | None, entity_type: str = "Entity") -> str:
    """Normalize whitespace and case, and fail on missing/empty names."""
    if name is None:
        raise ValidationError(f"{entity_type} name is missing")
    val = str(name).strip()
    if not val:
        raise ValidationError(f"{entity_type} name cannot be empty or whitespace-only")
    return val.lower()


def get_schema_identity(schema_name: str | None) -> str:
    """Return canonical schema identity: lowercase(schema.name)"""
    return normalize_identity_name(schema_name, entity_type="Schema")


def get_property_identity(schema_name: str | None, property_name: str | None) -> str:
    """Return canonical property identity: lowercase(schema.name) + '/' + lowercase(property.name)"""
    s_id = get_schema_identity(schema_name)
    p_id = normalize_identity_name(property_name, entity_type="Property")
    return f"{s_id}/{p_id}"


def schema_object_identity(schema: Any) -> str:
    """Return the canonical schema identity from a schema object."""
    return get_schema_identity(getattr(schema, "name", None))


def property_object_identity(schema_name: str | None, prop: Any) -> str:
    """Return the canonical property identity from a property object."""
    return get_property_identity(schema_name, getattr(prop, "name", None))


def build_schema_index(
    contract_or_schemas: OpenDataContractStandard | list[SchemaObject],
) -> dict[str, SchemaObject]:
    """Build a map of canonical schema identity to SchemaObject.

    Raises ValidationError if a duplicate canonical identity is found.
    """
    index: dict[str, SchemaObject] = {}
    schemas = (
        schema_items(contract_or_schemas)
        if isinstance(contract_or_schemas, OpenDataContractStandard)
        else contract_or_schemas
    )
    for schema in schemas:
        key = schema_object_identity(schema)
        if key in index:
            raise ValidationError(f"Duplicate canonical schema identity found: '{key}'")
        index[key] = schema
        # Validate properties inside the schema to prevent any silent missing/duplicate property name
        build_property_index(schema)
    return index


def build_property_index(
    schema_or_properties: SchemaObject | list[SchemaProperty],
) -> dict[str, SchemaProperty]:
    """Build a map of canonical property name to SchemaProperty.

    Raises ValidationError if a duplicate canonical property is found.
    """
    properties = (
        schema_or_properties.properties
        if isinstance(schema_or_properties, SchemaObject)
        else schema_or_properties
    )
    if not isinstance(properties, list):
        return {}
    index: dict[str, SchemaProperty] = {}
    for prop in properties:
        key = normalize_identity_name(prop.name, "Property")
        if key in index:
            schema_name_str = (
                f" in schema '{schema_or_properties.name}'"
                if isinstance(schema_or_properties, SchemaObject)
                else ""
            )
            raise ValidationError(
                f"Duplicate canonical property identity found: '{key}'{schema_name_str}"
            )
        index[key] = prop
    return index


def normalize_relationship_endpoint(val: Any) -> str:
    """Normalize a relationship endpoint string by splitting by dots, stripping, and lowercasing."""
    if val is None:
        return ""
    parts = [p.strip().lower() for p in str(val).split(".")]
    return ".".join(parts)


def normalize_endpoint_value(val: Any) -> str:
    """Normalize relationship endpoint values, supporting list and scalar types."""
    if isinstance(val, list):
        normalized_items = [normalize_relationship_endpoint(item) for item in val]
        normalized_items.sort()
        return ",".join(normalized_items)
    return normalize_relationship_endpoint(val)
