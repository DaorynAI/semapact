"""Databricks implementation of the shared schema mapping contract."""

from __future__ import annotations

import re
from collections.abc import Mapping

import sqlglot
from datacontract.export.sql_exporter import to_sql_ddl
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
)
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
    SchemaPropertyState,
    SchemaSnapshot,
    compare_schema_snapshots,
    map_observed_schema_asset,
)


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_UNRESOLVED_DATABRICKS_TYPES = {
    exp.DataType.Type.UNKNOWN,
    exp.DataType.Type.USERDEFINED,
    exp.DataType.Type.NULL,
}


class DatabricksSchemaMapper:
    """Adapt datacontract-cli target DDL and Databricks runtime evidence."""

    key = "databricks"

    def map_desired_asset(
        self,
        schema: SchemaObject,
        *,
        asset_identity: str,
    ) -> SchemaAssetState:
        """Compile ODCS through datacontract-cli, then read the target schema AST."""
        desired = schema.model_copy(update={"name": asset_identity})
        contract = OpenDataContractStandard.model_construct(
            id="semapact:deployment-target",
            version="0.0.0",
            schema_=[desired],
            servers=[],
        )
        ddl = to_sql_ddl(contract, server_type="databricks")
        return _target_schema_from_databricks_ddl(
            ddl,
            asset_identity=asset_identity,
        )

    def map_observed_asset(
        self,
        observed: ObservedAsset,
        *,
        asset_identity: str,
        property_bindings: Mapping[str, str] | None = None,
    ) -> SchemaAssetState:
        return map_observed_schema_asset(
            observed,
            asset_identity=asset_identity,
            property_bindings=property_bindings,
            normalize_physical_type=_normalize_databricks_type_optional,
        )


_DATABRICKS_SCHEMA_MAPPER: SchemaMapper = DatabricksSchemaMapper()


def validate_databricks_desired_schema(
    *,
    table_name: str,
    desired: SchemaObject,
) -> None:
    """Validate target schema emitted by the shared Databricks mapper."""
    asset = _DATABRICKS_SCHEMA_MAPPER.map_desired_asset(
        desired,
        asset_identity=table_name,
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
    """Compile desired state, map runtime state, compare, then derive intent."""
    catalog, schema_name = parse_databricks_runtime_target(runtime_target)
    validate_databricks_identifier(catalog, "catalog")
    validate_databricks_identifier(schema_name, "schema")

    desired_asset = _DATABRICKS_SCHEMA_MAPPER.map_desired_asset(
        desired,
        asset_identity=table_name,
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
            _DATABRICKS_SCHEMA_MAPPER.map_observed_asset(
                observed,
                asset_identity=table_name,
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


def _target_schema_from_databricks_ddl(
    ddl: str,
    *,
    asset_identity: str,
) -> SchemaAssetState:
    """Convert datacontract-cli's Databricks target DDL into comparable state."""
    try:
        statements = [
            statement
            for statement in sqlglot.parse(ddl, read="databricks")
            if statement is not None
        ]
    except Exception as exc:
        raise ValidationError(
            "datacontract-cli emitted unsupported Databricks physicalType/DDL"
        ) from exc

    creates = [
        statement
        for statement in statements
        if isinstance(statement, exp.Create)
        and (statement.kind or "").upper() == "TABLE"
    ]
    if len(creates) != 1:
        raise ValidationError(
            "Databricks target schema compilation must emit exactly one table"
        )

    properties: list[SchemaPropertyState] = []
    seen: set[str] = set()
    for column in creates[0].find_all(exp.ColumnDef):
        name = column.name.strip()
        validate_databricks_identifier(name, "column")
        key = name.casefold()
        if key in seen:
            raise ValidationError(
                f"Duplicate physical column binding in desired schema: '{name}'"
            )
        seen.add(key)

        data_type = column.args.get("kind")
        if (
            not isinstance(data_type, exp.DataType)
            or data_type.this in _UNRESOLVED_DATABRICKS_TYPES
        ):
            raise ValidationError(
                f"Unsupported Databricks physicalType for column '{name}'"
            )

        properties.append(
            SchemaPropertyState(
                identity=name,
                physical_type=data_type.sql(dialect="databricks"),
                nullable=(
                    column.find(exp.NotNullColumnConstraint) is None
                ),
            )
        )

    if not properties:
        raise ValidationError("Databricks deployment requires at least one schema property")

    return SchemaAssetState(
        identity=asset_identity,
        properties=tuple(properties),
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


def _normalize_databricks_type_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return _normalize_databricks_type(value)


def _normalize_databricks_type(value: str) -> str:
    """Parse and canonicalize one runtime native type in the Databricks dialect."""
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
