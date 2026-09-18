"""Pure Databricks schema-evolution planning.

This module owns provider-specific translation from one desired ODCS schema plus
one observed Databricks asset into a safe native operation. It performs no
runtime observation, authorization, or mutation.

The initial supported capability surface is deliberately narrow:
- missing table -> CREATE managed Delta table
- missing nullable governed columns -> ALTER TABLE ADD COLUMNS
- already satisfied governed shape -> NO_OP

Existing type/nullability mutations, required-column additions without a safe
migration strategy, non-managed assets, and unsupported physical types fail
closed.
"""

from __future__ import annotations

import re

from open_data_contract_standard.model import SchemaObject, SchemaProperty

from semapact.deployment.models import NativeOperation, NativeOperationKind
from semapact.exceptions import ValidationError
from semapact.observation.models import ObservedAsset


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_DECIMAL_RE = re.compile(r"^DECIMAL\((\d{1,2}),(\d{1,2})\)$")
_CHAR_RE = re.compile(r"^(CHAR|VARCHAR)\((\d+)\)$")
_PRIMITIVE_TYPES = {
    "BIGINT",
    "BINARY",
    "BOOLEAN",
    "BYTE",
    "DATE",
    "DOUBLE",
    "FLOAT",
    "INT",
    "INTEGER",
    "LONG",
    "REAL",
    "SHORT",
    "SMALLINT",
    "STRING",
    "TIMESTAMP",
    "TIMESTAMP_NTZ",
    "TINYINT",
}


def validate_databricks_desired_schema(
    *,
    table_name: str,
    desired: SchemaObject,
) -> None:
    """Validate one desired schema against the supported Databricks slice."""
    validate_databricks_identifier(table_name, "asset")
    _desired_columns(desired)


def plan_databricks_schema_evolution(
    *,
    catalog: str,
    schema_name: str,
    governed_asset: str,
    table_name: str,
    desired: SchemaObject,
    observed: ObservedAsset | None,
) -> NativeOperation:
    """Compile one desired-vs-observed schema comparison into a safe operation."""
    validate_databricks_identifier(catalog, "catalog")
    validate_databricks_identifier(schema_name, "schema")
    validate_databricks_desired_schema(table_name=table_name, desired=desired)

    if observed is not None:
        if observed.identity.platform.casefold() != "databricks":
            raise ValidationError(
                "Databricks schema evolution requires Databricks runtime evidence"
            )
        expected_namespace = (catalog.casefold(), schema_name.casefold())
        actual_namespace = tuple(
            part.casefold() for part in observed.identity.namespace
        )
        if actual_namespace != expected_namespace:
            raise ValidationError(
                "Observed asset is outside the requested Databricks namespace"
            )
        if observed.identity.asset.casefold() != table_name.casefold():
            raise ValidationError(
                "Observed asset does not match the requested Databricks table"
            )

    if observed is None:
        return NativeOperation(
            kind=NativeOperationKind.CREATE,
            governed_asset=governed_asset,
            statement=_create_table_statement(
                catalog=catalog,
                schema_name=schema_name,
                table_name=table_name,
                desired=desired,
            ),
        )

    additions = _required_additions(desired, observed)
    if additions:
        return NativeOperation(
            kind=NativeOperationKind.ALTER,
            governed_asset=governed_asset,
            statement=_add_columns_statement(
                catalog=catalog,
                schema_name=schema_name,
                table_name=table_name,
                additions=additions,
            ),
        )

    return NativeOperation(
        kind=NativeOperationKind.NO_OP,
        governed_asset=governed_asset,
    )


def validate_databricks_identifier(value: str, role: str) -> None:
    """Reject identifiers outside the explicitly supported SQL rendering subset."""
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValidationError(
            f"Unsupported Databricks {role} identifier for schema evolution: '{value}'"
        )


def _desired_columns(
    desired: SchemaObject,
) -> tuple[tuple[str, str, bool], ...]:
    columns: list[tuple[str, str, bool]] = []
    seen: set[str] = set()
    for prop in desired.properties or []:
        physical_name = _property_physical_name(prop)
        validate_databricks_identifier(physical_name, "column")
        key = physical_name.casefold()
        if key in seen:
            raise ValidationError(
                f"Duplicate physical column binding in desired schema: '{physical_name}'"
            )
        seen.add(key)

        physical_type = getattr(prop, "physicalType", None)
        if physical_type is None or not str(physical_type).strip():
            raise ValidationError(
                f"Databricks deployment requires physicalType for column '{physical_name}'"
            )
        rendered_type = _render_type(str(physical_type))
        columns.append(
            (
                physical_name,
                rendered_type,
                bool(getattr(prop, "required", False)),
            )
        )

    if not columns:
        raise ValidationError(
            "Databricks deployment requires at least one schema property"
        )
    return tuple(columns)


def _required_additions(
    desired: SchemaObject,
    observed: ObservedAsset,
) -> tuple[tuple[str, str, bool], ...]:
    if (observed.asset_type or "").strip().casefold() != "managed":
        raise ValidationError(
            "Existing Databricks asset must be a MANAGED table for deployment mutation"
        )

    observed_columns = {
        prop.identity.property.casefold(): prop for prop in observed.properties
    }
    additions: list[tuple[str, str, bool]] = []
    for name, desired_type, required in _desired_columns(desired):
        current = observed_columns.get(name.casefold())
        if current is None:
            if required:
                raise ValidationError(
                    f"Cannot add required column '{name}' without a safe default"
                )
            additions.append((name, desired_type, required))
            continue

        if current.physical_type is None:
            raise ValidationError(f"Observed type is unknown for column '{name}'")
        current_type = _render_type(current.physical_type)
        if current_type != desired_type:
            raise ValidationError(
                f"Unsupported existing column type mutation for '{name}': "
                f"{current_type} -> {desired_type}"
            )

        if current.nullable is None:
            raise ValidationError(
                f"Observed nullability is unknown for column '{name}'"
            )
        desired_nullable = not required
        if current.nullable is not desired_nullable:
            raise ValidationError(
                f"Unsupported existing column nullability mutation for '{name}'"
            )

    return tuple(additions)


def _property_physical_name(prop: SchemaProperty) -> str:
    physical = getattr(prop, "physicalName", None)
    if physical is not None and str(physical).strip():
        return str(physical).strip()

    name = getattr(prop, "name", None)
    if name is None or not str(name).strip():
        raise ValidationError("Schema property name is required for deployment binding")
    return str(name).strip()


def _create_table_statement(
    *,
    catalog: str,
    schema_name: str,
    table_name: str,
    desired: SchemaObject,
) -> str:
    columns = []
    for name, physical_type, required in _desired_columns(desired):
        suffix = " NOT NULL" if required else ""
        columns.append(f"{_quote_identifier(name)} {physical_type}{suffix}")
    column_sql = ", ".join(columns)
    return (
        f"CREATE TABLE {_qualified_name(catalog, schema_name, table_name)} "
        f"({column_sql}) USING DELTA"
    )


def _add_columns_statement(
    *,
    catalog: str,
    schema_name: str,
    table_name: str,
    additions: tuple[tuple[str, str, bool], ...],
) -> str:
    columns = ", ".join(
        f"{_quote_identifier(name)} {physical_type}"
        for name, physical_type, _required in additions
    )
    return (
        f"ALTER TABLE {_qualified_name(catalog, schema_name, table_name)} "
        f"ADD COLUMNS ({columns})"
    )


def _qualified_name(catalog: str, schema_name: str, table_name: str) -> str:
    return ".".join(
        _quote_identifier(part) for part in (catalog, schema_name, table_name)
    )


def _quote_identifier(value: str) -> str:
    validate_databricks_identifier(value, "identifier")
    return f"`{value}`"


def _render_type(value: str) -> str:
    normalized = re.sub(r"\s+", "", value.strip().upper())
    if normalized in _PRIMITIVE_TYPES:
        return normalized

    decimal = _DECIMAL_RE.fullmatch(normalized)
    if decimal:
        precision = int(decimal.group(1))
        scale = int(decimal.group(2))
        if 1 <= precision <= 38 and 0 <= scale <= precision:
            return f"DECIMAL({precision},{scale})"
        raise ValidationError(f"Unsupported Databricks DECIMAL type: '{value}'")

    char_type = _CHAR_RE.fullmatch(normalized)
    if char_type:
        length = int(char_type.group(2))
        if length > 0:
            return f"{char_type.group(1)}({length})"

    raise ValidationError(f"Unsupported Databricks physicalType: '{value}'")
