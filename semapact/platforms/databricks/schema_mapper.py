"""Databricks implementation of the shared schema mapping contract.

This module only adapts desired Databricks target-schema compiler output and
observed Databricks runtime schema evidence into SemaPact's normalized schema
state. It does not compare schemas, plan transitions, decide deployment
capability, validate runtime targets, or render executable SQL.
"""

from __future__ import annotations

from collections.abc import Mapping

import sqlglot
from datacontract.export.sql_exporter import to_sql_ddl
from open_data_contract_standard.model import OpenDataContractStandard, SchemaObject
from sqlglot import exp

from semapact.exceptions import ValidationError
from semapact.observation.models import ObservedAsset
from semapact.schema import (
    SchemaAssetState,
    SchemaMapper,
    SchemaPropertyState,
    map_observed_schema_asset,
)


_UNRESOLVED_DATABRICKS_TYPES = {
    exp.DataType.Type.UNKNOWN,
    exp.DataType.Type.USERDEFINED,
    exp.DataType.Type.NULL,
}


class DatabricksSchemaMapper:
    """Adapt Databricks desired/observed schema state into normalized state."""

    key = "databricks"

    def map_desired_asset(
        self,
        schema: SchemaObject,
        *,
        asset_identity: str,
    ) -> SchemaAssetState:
        """Compile ODCS through datacontract-cli and adapt the target schema AST."""
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
        """Normalize Databricks runtime schema evidence into comparable state."""
        return map_observed_schema_asset(
            observed,
            asset_identity=asset_identity,
            property_bindings=property_bindings,
            normalize_physical_type=_normalize_databricks_type_optional,
        )


DATABRICKS_SCHEMA_MAPPER: SchemaMapper = DatabricksSchemaMapper()


def _target_schema_from_databricks_ddl(
    ddl: str,
    *,
    asset_identity: str,
) -> SchemaAssetState:
    """Adapt datacontract-cli's Databricks target DDL into comparable state."""
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
        if not name:
            raise ValidationError(
                "Databricks target schema contains an empty column identity"
            )
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
                nullable=column.find(exp.NotNullColumnConstraint) is None,
            )
        )

    if not properties:
        raise ValidationError(
            "Databricks target schema compilation emitted no properties"
        )

    return SchemaAssetState(
        identity=asset_identity,
        properties=tuple(properties),
    )


def _normalize_databricks_type_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return _normalize_databricks_type(value)


def _normalize_databricks_type(value: str) -> str:
    """Canonicalize one observed native type in the Databricks dialect."""
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
