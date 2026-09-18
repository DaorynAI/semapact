"""Databricks normalization and semantic schema-transition planning."""

from __future__ import annotations

import re

from datacontract.export.sql_type_converter import convert_to_databricks
from open_data_contract_standard.model import SchemaObject, SchemaProperty

from semapact.deployment.schema_transitions import (
    SchemaColumnState,
    SchemaTransition,
    plan_additive_schema_transition,
)
from semapact.exceptions import ValidationError
from semapact.observation.models import ObservedAsset
from semapact.platforms.databricks.target import parse_databricks_runtime_target


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
    """Validate and normalize one desired schema against the supported slice."""
    validate_databricks_identifier(table_name, "asset")
    _desired_columns(desired)


def plan_databricks_schema_evolution(
    *,
    runtime_target: str,
    governed_asset: str,
    table_name: str,
    desired: SchemaObject,
    observed: ObservedAsset | None,
) -> SchemaTransition:
    """Produce a semantic transition before any Databricks SQL is rendered."""
    catalog, schema_name = parse_databricks_runtime_target(runtime_target)
    validate_databricks_identifier(catalog, "catalog")
    validate_databricks_identifier(schema_name, "schema")
    validate_databricks_desired_schema(table_name=table_name, desired=desired)

    if observed is not None:
        if observed.identity.platform.casefold() != "databricks":
            raise ValidationError(
                "Databricks schema evolution requires Databricks runtime evidence"
            )
        expected_namespace = (catalog.casefold(), schema_name.casefold())
        actual_namespace = tuple(part.casefold() for part in observed.identity.namespace)
        if actual_namespace != expected_namespace:
            raise ValidationError(
                "Observed asset is outside the requested Databricks namespace"
            )
        if observed.identity.asset.casefold() != table_name.casefold():
            raise ValidationError(
                "Observed asset does not match the requested Databricks table"
            )
        if (observed.asset_type or "").strip().casefold() != "managed":
            raise ValidationError(
                "Existing Databricks asset must be a MANAGED table for deployment mutation"
            )

    return plan_additive_schema_transition(
        governed_asset=governed_asset,
        physical_name=table_name,
        desired_columns=_desired_columns(desired),
        observed_columns=None if observed is None else _observed_columns(observed),
    )


def validate_databricks_identifier(value: str, role: str) -> None:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValidationError(
            f"Unsupported Databricks {role} identifier for schema evolution: '{value}'"
        )


def _desired_columns(desired: SchemaObject) -> tuple[SchemaColumnState, ...]:
    columns: list[SchemaColumnState] = []
    seen: set[str] = set()
    for prop in desired.properties or []:
        name = _property_physical_name(prop)
        validate_databricks_identifier(name, "column")
        key = name.casefold()
        if key in seen:
            raise ValidationError(
                f"Duplicate physical column binding in desired schema: '{name}'"
            )
        seen.add(key)

        physical_type = getattr(prop, "physicalType", None)
        if physical_type is None or not str(physical_type).strip():
            raise ValidationError(
                f"Databricks deployment requires physicalType for column '{name}'"
            )

        columns.append(
            SchemaColumnState(
                name=name,
                physical_type=_map_desired_type(prop),
                nullable=not bool(getattr(prop, "required", False)),
            )
        )

    if not columns:
        raise ValidationError("Databricks deployment requires at least one schema property")
    return tuple(columns)


def _observed_columns(observed: ObservedAsset) -> tuple[SchemaColumnState, ...]:
    columns: list[SchemaColumnState] = []
    for prop in observed.properties:
        if prop.physical_type is None:
            raise ValidationError(
                f"Observed type is unknown for column '{prop.identity.property}'"
            )
        if prop.nullable is None:
            raise ValidationError(
                f"Observed nullability is unknown for column '{prop.identity.property}'"
            )
        columns.append(
            SchemaColumnState(
                name=prop.identity.property,
                physical_type=_map_type_text(prop.physical_type),
                nullable=prop.nullable,
            )
        )
    return tuple(columns)


def _map_desired_type(prop: SchemaProperty) -> str:
    raw = str(prop.physicalType).strip()
    if _CHAR_RE.fullmatch(re.sub(r"\s+", "", raw.upper())):
        return _validate_safe_type(raw)

    mapped = convert_to_databricks(prop)
    return _validate_safe_type(mapped or raw)


def _map_type_text(value: str) -> str:
    synthetic = SchemaProperty(
        name="_observed",
        logicalType="string",
        physicalType=value,
    )
    return _map_desired_type(synthetic)


def _validate_safe_type(value: str) -> str:
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


def _property_physical_name(prop: SchemaProperty) -> str:
    physical = getattr(prop, "physicalName", None)
    if physical is not None and str(physical).strip():
        return str(physical).strip()
    name = getattr(prop, "name", None)
    if name is None or not str(name).strip():
        raise ValidationError("Schema property name is required for deployment binding")
    return str(name).strip()
