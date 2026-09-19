"""Databricks implementation of the provider-neutral transition compiler."""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from semapact.deployment.compilers import TransitionCompiler
from semapact.deployment.models import NativeOperation, NativeOperationKind
from semapact.deployment.schema_transitions import (
    SchemaTransition,
    SchemaTransitionKind,
)
from semapact.exceptions import ValidationError
from semapact.platforms.databricks.target import parse_databricks_runtime_target
from semapact.schema import SchemaPropertyState, validate_simple_sql_identifier


class DatabricksTransitionCompiler(TransitionCompiler):
    """Render only Databricks-specific transition syntax.

    Column definitions are opaque target-schema compiler output retained by the
    shared schema mapper. This compiler does not re-map ODCS types/nullability.
    """

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


DATABRICKS_TRANSITION_COMPILER: TransitionCompiler = DatabricksTransitionCompiler()


def _create_table_statement(
    *,
    catalog: str,
    schema_name: str,
    table_name: str,
    columns: tuple[SchemaPropertyState, ...],
) -> str:
    rendered = ", ".join(_native_column_definition(column) for column in columns)
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
    rendered = ", ".join(_native_column_definition(column) for column in columns)
    return (
        f"ALTER TABLE {_qualified_name(catalog, schema_name, table_name)} "
        f"ADD COLUMNS ({rendered})"
    )


def _native_column_definition(column: SchemaPropertyState) -> str:
    """Validate and reuse one target-compiler-emitted column definition."""
    definition = column.native_definition
    if definition is None:
        raise ValidationError(
            f"Databricks transition requires compiled target definition for "
            f"column '{column.identity}'"
        )

    try:
        parsed = sqlglot.parse_one(
            definition,
            into=exp.ColumnDef,
            dialect="databricks",
        )
    except Exception as exc:
        raise ValidationError(
            f"Invalid compiled Databricks column definition for '{column.identity}'"
        ) from exc

    if not isinstance(parsed, exp.ColumnDef):
        raise ValidationError(
            f"Invalid compiled Databricks column definition for '{column.identity}'"
        )
    if parsed.name.casefold() != column.identity.casefold():
        raise ValidationError(
            "Compiled Databricks column definition identity does not match "
            f"'{column.identity}'"
        )

    return parsed.sql(dialect="databricks", identify=True)


def _qualified_name(catalog: str, schema_name: str, table_name: str) -> str:
    return ".".join(
        _quote_identifier(part) for part in (catalog, schema_name, table_name)
    )


def _quote_identifier(value: str) -> str:
    validate_simple_sql_identifier(value, "identifier")
    return f"`{value}`"
