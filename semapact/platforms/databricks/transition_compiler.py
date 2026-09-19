"""Databricks implementation of the provider-neutral transition compiler."""

from __future__ import annotations

from semapact.deployment.compilers import (
    TransitionCompiler,
    require_native_definition,
)
from semapact.deployment.models import NativeOperation, NativeOperationKind
from semapact.deployment.schema_transitions import (
    SchemaTransition,
    SchemaTransitionKind,
)
from semapact.exceptions import ValidationError
from semapact.platforms.databricks.target import parse_databricks_runtime_target
from semapact.schema import SchemaPropertyState, validate_simple_sql_identifier


class DatabricksTransitionCompiler(TransitionCompiler):
    """Render Databricks-specific transition verbs around compiled target schema."""

    key = "databricks"

    def compile(
        self,
        *,
        runtime_target: str,
        transition: SchemaTransition,
    ) -> NativeOperation:
        catalog, schema_name = parse_databricks_runtime_target(runtime_target)
        validate_simple_sql_identifier(catalog, "catalog")
        validate_simple_sql_identifier(schema_name, "schema")
        validate_simple_sql_identifier(transition.physical_name, "asset")

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

        if transition.kind is SchemaTransitionKind.ADD_PROPERTIES:
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

        raise ValidationError(
            f"Unsupported Databricks schema transition: {transition.kind.value}"
        )


def _create_table_statement(
    *,
    catalog: str,
    schema_name: str,
    table_name: str,
    columns: tuple[SchemaPropertyState, ...],
) -> str:
    rendered = ", ".join(
        require_native_definition(column)
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
        require_native_definition(column)
        for column in columns
    )
    return (
        f"ALTER TABLE {_qualified_name(catalog, schema_name, table_name)} "
        f"ADD COLUMNS ({rendered})"
    )


def _qualified_name(catalog: str, schema_name: str, table_name: str) -> str:
    return ".".join(
        _quote_identifier(part)
        for part in (catalog, schema_name, table_name)
    )


def _quote_identifier(value: str) -> str:
    validate_simple_sql_identifier(value, "identifier")
    return f"`{value}`"
