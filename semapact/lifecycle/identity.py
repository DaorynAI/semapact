"""Canonical identity resolution for SemaPact governance layers.

All schema/property identity resolution and index construction live here.
SemaPact uses schema and property names as governance keys for matching and
collision detection across versions and contracts.

Public API
----------
SchemaIdentity    = str               e.g. "orders"
PropertyIdentity  = tuple[str, str]   e.g. ("orders", "order_id")

normalize_identity_name(name, entity_type)   -> str
schema_identity(schema)                      -> SchemaIdentity
build_schema_index(contract_or_schemas)      -> dict[SchemaIdentity, SchemaObject]
build_property_index(scope_key, properties)  -> dict[PropertyIdentity, SchemaProperty]
validate_contract_identities(contract_or_schemas) -> None
"""
from __future__ import annotations

from typing import Iterable

from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.exceptions import ValidationError

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

SchemaIdentity = str
"""Canonical schema governance key: strip + lowercase of schema.name."""

PropertyIdentity = tuple[str, str]
"""Canonical property governance key: (scope_key, property_canonical_name).

Using a tuple rather than a string separator avoids any dependence on a
delimiter convention and makes governance scope explicit at the type level.
"""


# ---------------------------------------------------------------------------
# Primitive normalization
# ---------------------------------------------------------------------------


def normalize_identity_name(name: str | None, entity_type: str = "Entity") -> str:
    """Strip whitespace, lowercase, and fail on missing or blank names.

    Raises:
        ValidationError: when *name* is ``None`` or resolves to an empty string.
    """
    if name is None:
        raise ValidationError(f"{entity_type} name is missing")
    val = str(name).strip()
    if not val:
        raise ValidationError(
            f"{entity_type} name cannot be empty or whitespace-only"
        )
    return val.lower()


# ---------------------------------------------------------------------------
# Schema identity
# ---------------------------------------------------------------------------


def schema_identity(schema: SchemaObject) -> SchemaIdentity:
    """Return the canonical SemaPact governance key for a schema object.

    Governance identity is derived solely from ``schema.name``; ``physicalName``
    is intentionally ignored so that physical renames do not alter governance
    decisions.
    """
    return normalize_identity_name(getattr(schema, "name", None), "Schema")


# ---------------------------------------------------------------------------
# Index builders  (canonical normalization + collision validation)
# ---------------------------------------------------------------------------


def build_schema_index(
    contract_or_schemas: OpenDataContractStandard | list[SchemaObject],
) -> dict[SchemaIdentity, SchemaObject]:
    """Build a canonical ``SchemaIdentity -> SchemaObject`` index.

    Each call performs:
    1. Canonical normalization (``strip + lower``) of each schema name.
    2. Missing-name validation.
    3. Duplicate canonical identity detection.

    Raises:
        ValidationError: on missing schema name, empty schema name, or
            duplicate canonical schema identity.
    """
    if isinstance(contract_or_schemas, OpenDataContractStandard):
        schemas: list[SchemaObject] = list(contract_or_schemas.schema_ or [])
    else:
        schemas = list(contract_or_schemas)

    index: dict[SchemaIdentity, SchemaObject] = {}
    for schema in schemas:
        key = schema_identity(schema)
        if key in index:
            raise ValidationError(
                f"Duplicate canonical schema identity found: '{key}'"
            )
        index[key] = schema
    return index


def build_property_index(
    scope_key: SchemaIdentity,
    properties: Iterable[SchemaProperty],
) -> dict[PropertyIdentity, SchemaProperty]:
    """Build a canonical ``PropertyIdentity -> SchemaProperty`` index.

    ``PropertyIdentity`` is ``(scope_key, property_canonical_name)`` where
    *scope_key* is the caller's canonical governance scope — typically the
    canonical schema name for top-level properties, or the canonical parent
    property name for nested struct fields.

    Each call performs:
    1. Canonical normalization of each property name.
    2. Missing-name validation.
    3. Duplicate canonical identity detection within this scope.

    Raises:
        ValidationError: on missing property name, empty property name, or
            duplicate canonical property identity within this scope.
    """
    index: dict[PropertyIdentity, SchemaProperty] = {}
    for prop in properties:
        p_id = normalize_identity_name(getattr(prop, "name", None), "Property")
        key: PropertyIdentity = (scope_key, p_id)
        if key in index:
            raise ValidationError(
                f"Duplicate canonical property identity found: '{p_id}'"
                f" in schema '{scope_key}'"
            )
        index[key] = prop
    return index


# ---------------------------------------------------------------------------
# Contract identity validation
# ---------------------------------------------------------------------------


def validate_contract_identities(
    contract_or_schemas: OpenDataContractStandard | list[SchemaObject],
) -> None:
    """Validate schema and property identities recursively across all schemas.

    Raises:
        ValidationError: on missing names or duplicate canonical identities
            at schema, top-level property, or nested property levels.
    """
    schemas = build_schema_index(contract_or_schemas)
    for schema_key, schema in schemas.items():
        _validate_properties_recursive(schema_key, schema.properties or [])


def _validate_properties_recursive(
    scope_key: str,
    properties: Iterable[SchemaProperty],
) -> None:
    prop_index = build_property_index(scope_key, properties)
    for prop_key, prop in prop_index.items():
        nested_props = getattr(prop, "properties", None)
        if isinstance(nested_props, list) and nested_props:
            _validate_properties_recursive(prop_key[1], nested_props)
