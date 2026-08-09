"""Canonical identity resolution for SemaPact governance layers.

All schema/property identity logic lives here. Merge, policy, and release
consume the public index builders — they do not implement identity rules
themselves.

Public interface
----------------
SchemaIdentity  = str                    e.g. "orders"
PropertyIdentity = tuple[str, str]       e.g. ("orders", "order_id")

normalize_identity_name(name, entity_type)  -> str
schema_identity(schema)                     -> SchemaIdentity
build_schema_index(contract_or_schemas)     -> dict[SchemaIdentity, SchemaObject]
build_property_index(schema_id, properties) -> dict[PropertyIdentity, SchemaProperty]
normalize_relationship_endpoint(val)        -> str
normalize_endpoint_value(val)               -> str
"""
from __future__ import annotations

from typing import Any, Iterable

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
"""Canonical schema identity: strip + lowercase of schema.name."""

PropertyIdentity = tuple[str, str]
"""Canonical property identity: (schema_id, property_canonical_name).

Using a tuple rather than a string separator avoids any dependence on a
delimiter convention and makes schema membership explicit at the type level.
For nested properties, schema_id is the canonical name of the parent property.
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
    """Return the canonical identity for a schema object.

    Identity is derived solely from ``schema.name``; ``physicalName`` is
    intentionally ignored so that physical renames do not alter governance
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

    Property-level validation is the responsibility of callers via
    :func:`build_property_index` when they actually need the property index.

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
    schema_id: SchemaIdentity,
    properties: Iterable[SchemaProperty],
) -> dict[PropertyIdentity, SchemaProperty]:
    """Build a canonical ``PropertyIdentity -> SchemaProperty`` index.

    ``PropertyIdentity`` is ``(schema_id, property_canonical_name)`` where
    *schema_id* is the caller's canonical context key — typically the
    canonical schema name for top-level properties, or the canonical parent
    property name for nested struct fields.  This unified signature means
    the same function works for both cases without duplication.

    Each call performs:

    1. Canonical normalization of each property name.
    2. Missing-name validation.
    3. Duplicate canonical identity detection.

    Raises:
        ValidationError: on missing property name, empty property name, or
            duplicate canonical property identity within this scope.
    """
    index: dict[PropertyIdentity, SchemaProperty] = {}
    for prop in properties:
        p_id = normalize_identity_name(getattr(prop, "name", None), "Property")
        key: PropertyIdentity = (schema_id, p_id)
        if key in index:
            raise ValidationError(
                f"Duplicate canonical property identity found: '{p_id}'"
                f" in schema '{schema_id}'"
            )
        index[key] = prop
    return index


def validate_contract_identities(
    contract_or_schemas: OpenDataContractStandard | list[SchemaObject],
) -> None:
    """Validate schema and property identities across all schemas.

    Raises ValidationError on missing names or duplicate canonical identities
    at either schema or property level.
    """
    schemas = build_schema_index(contract_or_schemas)
    for schema_key, schema in schemas.items():
        build_property_index(schema_key, schema.properties or [])


# ---------------------------------------------------------------------------
# Relationship endpoint normalization
# ---------------------------------------------------------------------------


def normalize_relationship_endpoint(val: Any) -> str:
    """Normalize a single relationship endpoint string.

    Splits on ``'.'``, strips each part, lowercases, and rejoins.  This
    ensures that ``"  Orders.user_id "`` and ``"orders.user_id"`` resolve to
    the same canonical string.
    """
    if val is None:
        return ""
    parts = [p.strip().lower() for p in str(val).split(".")]
    return ".".join(parts)


def normalize_endpoint_value(val: Any) -> str:
    """Normalize a relationship endpoint value (scalar or list).

    When *val* is a list (combined/multi-column key), each element is
    normalized individually **in the original order** and joined with a
    comma.  Preserving order is intentional: composite FK column positions
    encode column mapping (``[a, b] -> [x, y]`` differs from
    ``[a, b] -> [y, x]``), so sorting would silently erase that distinction.
    """
    if isinstance(val, list):
        return ",".join(normalize_relationship_endpoint(item) for item in val)
    return normalize_relationship_endpoint(val)
