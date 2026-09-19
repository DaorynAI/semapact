"""Databricks implementation of the shared schema mapping contract."""

from __future__ import annotations

import re

import sqlglot
from datacontract.export.sql_type_converter import convert_to_databricks
from open_data_contract_standard.model import SchemaObject, SchemaProperty
from sqlglot import exp

from semapact.deployment.schema_transitions import (
    SchemaTransition,
    plan_additive_schema_transition,
)
from semapact.exceptions import ValidationError
from semapact.observation.models import ObservedAsset
from semapact.platforms.databricks.target import parse_databricks_runtime_target
from semapact.schema import (
    SchemaAssetState,
    SchemaMapper,
    compare_schema_snapshots,
    map_desired_schema_asset,
    map_observed_schema_asset,
)
from semapact.schema.comparison import SchemaSnapshot


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_UNRESOLVED_DATABRICKS_TYPES = {
    exp.DataType.Type.UNKNOWN,
    exp.DataType.Type.USERDEFINED,
    exp.DataType.Type.NULL,
}


class DatabricksSchemaMapper:
    """Normalize ODCS/runtime physical types into Databricks comparable state."""

    key = "databricks"

    def normalize_desired_type(self, prop: SchemaProperty) -> str | None:
        raw = getattr(prop, "physicalType", None)
        if raw is None or not str(raw).strip():
            name = getattr(prop, "physicalName", None) or getattr(prop, "name", None)
            raise ValidationError(
                f"Databricks deployment requires physicalType for column '{name}'"
            )

        raw_text = str(raw).strip()
        mapped = convert_to_databricks(prop)
        return _normalize_databricks_type(mapped or raw_text)

    def normalize_observed_type(self, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_databricks_type(value)


_DATABRICKS_SCHEMA_MAPPER: SchemaMapper = DatabricksSchemaMapper()


def validate_databricks_desired_schema(
    *,
    table_name: str,
    desired: SchemaObject,
) -> None:
    """Validate one desired schema through the shared mapping contract."""
    asset = map_desired_schema_asset(
        desired,
        asset_identity=table_name,
        mapper=_DATABRICKS_SCHEMA_MAPPER,
        use_physical_property_names=True,
    )
    _validate_databricks_asset_state(asset)


def plan_databricks_schema_transition(
    *,
    runtime_target: str,
    governed_asset: str,
    table_name: str,
    desired: SchemaObject,
    observed: ObservedAsset | None,
) -> SchemaTransition:
    """Map provider state, compare through core, then derive convergence intent."""
    catalog, schema_name = parse_databricks_runtime_target(runtime_target)
    validate_databricks_identifier(catalog, "catalog")
    validate_databricks_identifier(schema_name, "schema")

    desired_asset = map_desired_schema_asset(
        desired,
        asset_identity=table_name,
        mapper=_DATABRICKS_SCHEMA_MAPPER,
        use_physical_property_names=True,
    )
    _validate_databricks_asset_state(desired_asset)

    if observed is not None:
        _validate_databricks_observed_asset(
            observed=observed,
            catalog=catalog,
            schema_name=schema_name,
            table_name=table_name,
        )
        observed_assets = (
            map_observed_schema_asset(
                observed,
                asset_identity=table_name,
                mapper=_DATABRICKS_SCHEMA_MAPPER,
            ),
        )
    else:
        observed_assets = ()

    comparison = compare_schema_snapshots(
        SchemaSnapshot(assets=(desired_asset,)),
        SchemaSnapshot(assets=observed_assets),
    )
    return plan_additive_schema_transition(
        governed_asset=governed_asset,
        physical_name=table_name,
        desired_columns=desired_asset.properties,
        comparison=comparison,
    )


def validate_databricks_identifier(value: str, role: str) -> None:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValidationError(
            f"Unsupported Databricks {role} identifier for schema evolution: '{value}'"
        )


def _validate_databricks_asset_state(asset: SchemaAssetState) -> None:
    validate_databricks_identifier(asset.identity, "asset")
    if not asset.properties:
        raise ValidationError("Databricks deployment requires at least one schema property")
    for prop in asset.properties:
        validate_databricks_identifier(prop.identity, "column")


def _validate_databricks_observed_asset(
    *,
    observed: ObservedAsset,
    catalog: str,
    schema_name: str,
    table_name: str,
) -> None:
    if observed.identity.platform.casefold() != "databricks":
        raise ValidationError(
            "Databricks deployment planning requires Databricks runtime evidence"
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


def _normalize_databricks_type(value: str) -> str:
    """Parse and canonicalize one native type using the Databricks SQL dialect."""
    try:
        parsed = sqlglot.parse_one(
            value.strip(),
            into=exp.DataType,
            dialect="databricks",
        )
    except Exception as exc:
        raise ValidationError(
            f"Unsupported Databricks physicalType: '{value}'"
        ) from exc

    if (
        not isinstance(parsed, exp.DataType)
        or parsed.this in _UNRESOLVED_DATABRICKS_TYPES
    ):
        raise ValidationError(f"Unsupported Databricks physicalType: '{value}'")

    return parsed.sql(dialect="databricks")
