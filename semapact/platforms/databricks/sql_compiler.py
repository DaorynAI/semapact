"""Compile semantic schema transitions into Databricks native operations."""

from __future__ import annotations

from semapact.deployment.models import NativeOperation, NativeOperationKind
from semapact.deployment.schema_transitions import (
    SchemaTransition,
    SchemaTransitionKind,
)
from semapact.schema import SchemaPropertyState
from semapact.platforms.databricks.schema_evolution import (
    validate_databricks_identifier,
)


def compile_databricks_schema_transition(
    *,
    catalog: str,
    schema_name: str,
    transition: SchemaTransition,
) -> NativeOperation:
    """Render one semantic transition as an exact Databricks SQL operation."""
    validate_databricks_identifier(catalog, "catalog")
    validate_databricks_identifier(schema_name, "schema")
    validate_databricks_identifier(transition.physical_name, "asset")

    if transition.kind is SchemaTransitionKind.NO_OP:
        return NativeOperation(
            kind=NativeOperationKind.NO_OP,
            governed_asset=transition.governed_asset,
        )

    if transition.kind is SchemaTransitionKind.CREATE_ASSET:
        statement = _create_table_statement(
            catalog=catalog,
            schema_name=schema_name,
            table_name=transition.physical_name,
            columns=transition.columns,
        )
        return NativeOperation(
            kind=NativeOperationKind.CREATE,
            governed_asset=transition.governed_asset,
            statement=statement,
        )

    statement = _add_columns_statement(
        catalog=catalog,
        schema_name=schema_name,
        table_name=transition.physical_name,
        columns=transition.columns,
    )
    return NativeOperation(
        kind=NativeOperationKind.ALTER,
        governed_asset=transition.governed_asset,
        statement=statement,
    )


def _create_table_statement(
    *,
    catalog: str,
    schema_name: str,
    table_name: str,
    columns: tuple[SchemaPropertyState, ...],
) -> str:
    rendered = ", ".join(
        f"{_quote_identifier(column.identity)} {column.physical_type}"
        + ("" if column.nullable else " NOT NULL")
        for column in columns
    )
    return (
        f"CREATE TABLE {_qualified_name(catalog, schema_name, table_name)} "
        f"({rendered}) USING DELTA"
    )


def _add_columns_statement(
    *,
    catalog: str,
    schema_name: str,
    table_name: str,
    columns: tuple[SchemaPropertyState, ...],
) -> str:
    rendered = ", ".join(
        f"{_quote_identifier(column.identity)} {column.physical_type}"
        for column in columns
    )
    return (
        f"ALTER TABLE {_qualified_name(catalog, schema_name, table_name)} "
        f"ADD COLUMNS ({rendered})"
    )


def _qualified_name(catalog: str, schema_name: str, table_name: str) -> str:
    return ".".join(
        _quote_identifier(part) for part in (catalog, schema_name, table_name)
    )


def _quote_identifier(value: str) -> str:
    validate_databricks_identifier(value, "identifier")
    return f"`{value}`"
