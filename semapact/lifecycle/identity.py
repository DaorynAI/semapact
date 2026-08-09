"""Canonical identity resolution for SemaPact governance layers.

All schema/property identity logic lives here. Merge, policy, and release
consume the public index builders — they do not implement identity rules
themselves.

Public interface
----------------
SchemaIdentity         = str                  e.g. "orders"
PropertyIdentity       = tuple[str, str]       e.g. ("orders", "order_id")

normalize_identity_name(name, entity_type)     -> str
schema_identity(schema)                        -> SchemaIdentity
property_identity(schema, prop)                -> PropertyIdentity
build_schema_index(contract_or_schemas)        -> dict[SchemaIdentity, SchemaObject]
build_property_index(schema)                   -> dict[PropertyIdentity, SchemaProperty]
normalize_relationship_endpoint(val)           -> str
normalize_endpoint_value(val)                  -> str
relationship_from_identity(schema, prop)       -> str
"""
from __future__ import annotations

from typing import Any

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
"""Canonical property identity: (schema_canonical_name, property_canonical_name).

Using a tuple rather than a string separator avoids any dependence on a
delimiter convention and makes schema membership explicit at the type level.
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
# Schema / property identity
# ---------------------------------------------------------------------------


def schema_identity(schema: SchemaObject) -> SchemaIdentity:
    """Return the canonical identity for a schema object.

    Identity is derived solely from ``schema.name``; ``physicalName`` is
    intentionally ignored so that physical renames do not alter governance
    decisions.
    """
    return normalize_identity_name(getattr(schema, "name", None), "Schema")


def property_identity(
    schema: SchemaObject, prop: SchemaProperty
) -> PropertyIdentity:
    """Return the canonical identity for a property within a schema.

    Returns:
        A ``(schema_canonical, property_canonical)`` tuple so that schema
        membership is explicit and no delimiter convention is required.
    """
    s_id = schema_identity(schema)
    p_id = normalize_identity_name(getattr(prop, "name", None), "Property")
    return (s_id, p_id)


# ---------------------------------------------------------------------------
# Index builders  (canonical normalization + collision validation)
# ---------------------------------------------------------------------------


def build_schema_index(
    contract_or_schemas: OpenDataContractStandard | list[SchemaObject],
) -> dict[SchemaIdentity, SchemaObject]:
    """Build a canonical ``SchemaIdentity -> SchemaObject`` index.

    Each call performs:

    1. Canonical normalization (``strip + lower``) of each schema name.
    2. Missing-name validation (raises :class:`~semapact.exceptions.ValidationError`).
    3. Duplicate canonical identity detection (raises on collision).
    4. Eager ``build_property_index`` on every schema so property-level
       violations surface at index-build time rather than later.

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
        build_property_index(schema)  # eager validation of nested properties
    return index


def build_property_index(
    schema: SchemaObject,
) -> dict[PropertyIdentity, SchemaProperty]:
    """Build a canonical ``PropertyIdentity -> SchemaProperty`` index.

    ``PropertyIdentity`` is ``(schema_canonical_name, property_canonical_name)``
    so that property keys carry their schema membership explicitly.

    Each call performs:

    1. Canonical normalization of each property name.
    2. Missing-name validation.
    3. Duplicate canonical identity detection.

    Raises:
        ValidationError: on missing property name, empty property name, or
            duplicate canonical property identity within this schema.
    """
    properties = schema.properties
    if not isinstance(properties, list):
        return {}

    s_id = schema_identity(schema)
    index: dict[PropertyIdentity, SchemaProperty] = {}
    for prop in properties:
        p_id = normalize_identity_name(getattr(prop, "name", None), "Property")
        key: PropertyIdentity = (s_id, p_id)
        if key in index:
            raise ValidationError(
                f"Duplicate canonical property identity found: '{p_id}'"
                f" in schema '{schema.name}'"
            )
        index[key] = prop
    return index


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
    normalized individually and the results are sorted and joined with
    a comma so the order is canonical.
    """
    if isinstance(val, list):
        normalized = sorted(normalize_relationship_endpoint(item) for item in val)
        return ",".join(normalized)
    return normalize_relationship_endpoint(val)


def relationship_from_identity(schema: SchemaObject, prop: SchemaProperty) -> str:
    """Return the normalized ``"schema.property"`` endpoint for a property.

    This is the canonical *from* value for property-level relationship hashes.
    For combined multi-column keys, the raw relationship attribute value
    should be passed to :func:`normalize_endpoint_value` directly instead.
    """
    s_id = schema_identity(schema)
    p_id = normalize_identity_name(getattr(prop, "name", None), "Property")
    return f"{s_id}.{p_id}"
