from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import sqlglot
from datacontract.imports import sql_importer as upstream_sql_importer
from datacontract.imports.importer import Importer
from open_data_contract_standard.model import (
    CustomProperty,
    OpenDataContractStandard,
    Relationship,
    SchemaObject,
    SchemaProperty,
)
from sqlglot import expressions as exp


class SQLFolderImporter(Importer):
    """Datacontract-compatible importer for SQL folders (one table per file)."""

    def import_source(self, source: str, import_args: dict) -> OpenDataContractStandard:
        dialect = _resolve_sql_dialect(import_args)
        folder_path = Path(source).expanduser().resolve()
        if not folder_path.is_dir():
            raise ValueError(f"Folder does not exist: {folder_path}")

        sql_files = sorted(folder_path.glob("*.sql"))
        if not sql_files:
            raise ValueError(f"No .sql files found under folder: {folder_path}")

        dataset_name = folder_path.name
        contract_id = _to_contract_id(dataset_name)
        schema_objects: List[SchemaObject] = []

        for sql_file in sql_files:
            logging.getLogger("SQLFolderImporter").info(
                "Parsing SQL file: %s", sql_file
            )
            sql_text = upstream_sql_importer.remove_variable_tokens(
                sql_file.read_text(encoding="utf-8")
            )
            statements = sqlglot.parse(sql_text, read=dialect)
            for statement in statements:
                if statement is None:
                    continue
                schema_object = _create_schema_object_from_statement(
                    statement, dialect=dialect  # type: ignore[arg-type]
                )
                if schema_object is not None:
                    schema_objects.append(schema_object)

        if not schema_objects:
            raise ValueError(
                f"No CREATE TABLE statements found under folder: {folder_path}"
            )

        contract_model = OpenDataContractStandard(
            apiVersion="v3.1.0",
            kind="DataContract",
            id=contract_id,
            name=dataset_name,
            version="1.0.0",
            status="draft",
            schema=schema_objects,
            customProperties=[
                CustomProperty(property="semapact.source", value=self.import_format)
            ],
        )
        return contract_model


def _to_contract_id(dataset_name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", dataset_name).strip("-")
    return cleaned.lower() or "sql-dataset"


def _resolve_sql_dialect(import_args: dict | None) -> Any:
    parsed_dialect = upstream_sql_importer.to_dialect(import_args or {})
    return parsed_dialect or "spark"


def _create_schema_object_from_statement(
    statement: exp.Expression, *, dialect: Any
) -> Optional[SchemaObject]:
    if not isinstance(statement, exp.Create):
        return None
    if str(statement.args.get("kind") or "").upper() != "TABLE":
        return None

    table_expression = statement.find(exp.Table)
    if table_expression is None:
        return None

    table_name, table_physical_name = _get_table_name_info(
        table_expression, dialect=dialect
    )
    if not table_name:
        return None

    (
        table_description,
        table_physical_type,
        table_custom_properties,
        partition_positions,
    ) = _extract_table_metadata(statement)
    primary_key_positions, unique_columns = _extract_key_constraints(
        statement, table_name
    )
    columns = _extract_columns(
        statement,
        table_name=table_name,
        dialect=dialect,
        primary_key_positions=primary_key_positions,
        unique_columns=unique_columns,
        partition_positions=partition_positions,
    )
    if not columns:
        return None
    schema_relationships = _extract_table_foreign_key_relationships(
        statement,
        table_name=table_name,
        dialect=dialect,
        columns=columns,
    )

    return SchemaObject(
        id=_to_contract_id(table_physical_name),
        name=table_name,
        physicalName=table_physical_name,
        logicalType="object",
        physicalType=table_physical_type,
        description=table_description,
        customProperties=table_custom_properties or None,
        relationships=schema_relationships or None,
        properties=columns,
    )


def _get_table_name_info(
    table_expression: exp.Table, *, dialect: Any
) -> Tuple[str, str]:
    logical_name = table_expression.name or ""
    physical_name = table_expression.sql(dialect=dialect)
    return logical_name, physical_name


def _extract_table_metadata(
    statement: exp.Create,
) -> Tuple[Optional[str], str, List[CustomProperty], Dict[str, int]]:
    description: Optional[str] = None
    physical_type = "table"
    custom_properties: List[CustomProperty] = []
    partition_positions: Dict[str, int] = {}

    properties = statement.args.get("properties")
    if not isinstance(properties, exp.Properties):
        return description, physical_type, custom_properties, partition_positions

    for property_expr in properties.expressions:
        if isinstance(property_expr, exp.ExternalProperty):
            physical_type = "external-table"
            custom_properties.append(
                CustomProperty(property="semapact.table.external", value="true")
            )
        elif (
            isinstance(property_expr, exp.SchemaCommentProperty)
            and property_expr.this is not None
        ):
            description = str(property_expr.this).strip("'\"")
        elif (
            isinstance(property_expr, exp.LocationProperty)
            and property_expr.this is not None
        ):
            custom_properties.append(
                CustomProperty(
                    property="semapact.table.location",
                    value=str(property_expr.this).strip("'\""),
                )
            )
        elif (
            isinstance(property_expr, exp.FileFormatProperty)
            and property_expr.this is not None
        ):
            custom_properties.append(
                CustomProperty(
                    property="semapact.table.format",
                    value=str(property_expr.this).strip("'\""),
                )
            )
        elif isinstance(property_expr, exp.PartitionedByProperty):
            partition_columns = _extract_partition_columns(property_expr)
            for idx, column_name in enumerate(partition_columns, start=1):
                partition_positions[column_name.lower()] = idx

    return description, physical_type, custom_properties, partition_positions


def _extract_partition_columns(
    partition_property: exp.PartitionedByProperty,
) -> List[str]:
    partition_columns: List[str] = []
    partition_schema = partition_property.args.get("this")
    if not isinstance(partition_schema, exp.Schema):
        return partition_columns

    for item in partition_schema.expressions:
        if isinstance(item, exp.Identifier):
            partition_columns.append(item.name)
    return partition_columns


def _extract_key_constraints(
    statement: exp.Create, table_name: str
) -> Tuple[Dict[str, int], Set[str]]:
    primary_key_positions: Dict[str, int] = {}
    unique_columns: Set[str] = set()

    for constraint in statement.find_all(exp.Constraint):
        expressions = constraint.args.get("expressions") or []
        for constraint_expr in expressions:
            if isinstance(constraint_expr, exp.PrimaryKey):
                for idx, item in enumerate(constraint_expr.expressions or [], start=1):
                    if isinstance(item, exp.Identifier):
                        primary_key_positions[item.name.lower()] = idx
            elif isinstance(constraint_expr, exp.UniqueColumnConstraint):
                schema_expr = constraint_expr.args.get("this")
                if isinstance(schema_expr, exp.Schema):
                    for item in schema_expr.expressions:
                        if isinstance(item, exp.Identifier):
                            unique_columns.add(item.name.lower())

    # Support inline PRIMARY KEY / UNIQUE on top-level columns.
    inline_pk_idx = len(primary_key_positions)
    for column in statement.find_all(exp.ColumnDef):
        parent_table = _get_parent_table_name(column)
        if parent_table and parent_table.lower() != table_name.lower():
            continue
        column_name = column.this.name if column.this is not None else None
        if not column_name:
            continue
        normalized = column_name.lower()
        if (
            normalized not in primary_key_positions
            and column.find(exp.PrimaryKeyColumnConstraint) is not None
        ):
            inline_pk_idx += 1
            primary_key_positions[normalized] = inline_pk_idx
        if column.find(exp.UniqueColumnConstraint) is not None:
            unique_columns.add(normalized)

    return primary_key_positions, unique_columns


def _extract_columns(
    statement: exp.Create,
    table_name: str,
    dialect: Any,
    primary_key_positions: Dict[str, int],
    unique_columns: Set[str],
    partition_positions: Dict[str, int],
) -> List[SchemaProperty]:
    columns: List[SchemaProperty] = []

    for column in statement.find_all(exp.ColumnDef):
        parent_table = _get_parent_table_name(column)
        if parent_table and parent_table.lower() != table_name.lower():
            continue

        column_name = column.this.name if column.this is not None else None
        if not column_name:
            continue

        kind = column.args.get("kind")
        data_type = _column_type(column, dialect=dialect)
        nullable = _column_nullable(column)
        comment = _column_comment(column)
        normalized_name = column_name.lower()
        primary_key_position = primary_key_positions.get(normalized_name)
        partition_key_position = partition_positions.get(normalized_name)

        columns.append(
            _schema_property_from_data_type(
                name=column_name,
                column=column,
                dialect=dialect,
                kind=kind,
                physical_type=data_type,
                required=not nullable,
                description=comment,
                primary_key_position=primary_key_position,
                unique=normalized_name in unique_columns,
                partition_key_position=partition_key_position,
            )
        )
        _attach_inline_reference_relationship(columns[-1], column, dialect=dialect)

    return columns


def _get_parent_table_name(column: exp.ColumnDef) -> Optional[str]:
    parent = column.parent
    if isinstance(parent, exp.Schema) and isinstance(parent.this, exp.Table):
        return parent.this.name
    return None


def _column_type(column: exp.ColumnDef, *, dialect: Any) -> str:
    sql_type = upstream_sql_importer.to_col_type(column, dialect)
    return sql_type or "string"


def _column_nullable(column: exp.ColumnDef) -> bool:
    if column.find(exp.NotNullColumnConstraint) is not None:
        return False
    if column.find(exp.PrimaryKeyColumnConstraint) is not None:
        return False
    return True


def _column_comment(column: exp.ColumnDef) -> Optional[str]:
    return upstream_sql_importer.get_description(column)


def _attach_inline_reference_relationship(
    property_obj: SchemaProperty, column: exp.ColumnDef, *, dialect: Any
) -> None:
    reference: exp.Reference | None = None
    for column_constraint in column.args.get("constraints") or []:
        kind = column_constraint.args.get("kind")
        if isinstance(kind, exp.Reference):
            reference = kind
            break
    if reference is None:
        return

    target_table, target_columns = _extract_reference_target(reference, dialect=dialect)
    if not target_table or len(target_columns) != 1:
        return
    relationship = Relationship(
        type="foreignKey", to=f"{target_table}.{target_columns[0]}"
    )
    property_obj.relationships = _merge_relationships(
        property_obj.relationships, [relationship]
    )


def _extract_table_foreign_key_relationships(
    statement: exp.Create,
    *,
    table_name: str,
    dialect: Any,
    columns: List[SchemaProperty],
) -> List[Relationship]:
    schema_relationships: List[Relationship] = []
    columns_by_name = {item.name.lower(): item for item in columns if item.name}

    for constraint in statement.find_all(exp.Constraint):
        for constraint_expr in constraint.args.get("expressions") or []:
            if not isinstance(constraint_expr, exp.ForeignKey):
                continue

            source_columns = [
                item.name
                for item in constraint_expr.expressions or []
                if isinstance(item, exp.Identifier)
            ]
            if not source_columns:
                continue

            reference = constraint_expr.args.get("reference")
            if not isinstance(reference, exp.Reference):
                continue

            target_table, target_columns = _extract_reference_target(
                reference, dialect=dialect
            )
            if not target_table or not target_columns:
                continue

            if len(source_columns) == 1 and len(target_columns) == 1:
                source_name = source_columns[0].lower()
                source_property = columns_by_name.get(source_name)
                if source_property is not None:
                    source_property.relationships = _merge_relationships(
                        source_property.relationships,
                        [
                            Relationship(
                                type="foreignKey",
                                to=f"{target_table}.{target_columns[0]}",
                            )
                        ],
                    )
                continue

            to_values = [
                f"{target_table}.{target_column}" for target_column in target_columns
            ]
            schema_relationships.append(
                Relationship(
                    type="foreignKey",
                    **{"from": source_columns},  # type: ignore[arg-type]
                    to=to_values,
                )
            )

    return _merge_relationships(None, schema_relationships)


def _extract_reference_target(
    reference: exp.Reference, *, dialect: Any
) -> Tuple[Optional[str], List[str]]:
    schema_or_table = reference.args.get("this")
    if isinstance(schema_or_table, exp.Schema):
        table_expr = schema_or_table.args.get("this")
        if isinstance(table_expr, exp.Table):
            table_name = table_expr.sql(dialect=dialect)
        else:
            table_name = None
        target_columns = [
            item.name
            for item in schema_or_table.expressions or []
            if isinstance(item, exp.Identifier) and item.name
        ]
        return table_name, target_columns

    if isinstance(schema_or_table, exp.Table):
        return schema_or_table.sql(dialect=dialect), []

    return None, []


def _merge_relationships(
    existing: List[Relationship] | None,
    additions: List[Relationship] | None,
) -> List[Relationship]:
    merged: List[Relationship] = list(existing or [])
    seen = {_relationship_key(item) for item in merged}
    for item in additions or []:
        key = _relationship_key(item)
        if key in seen:
            continue
        merged.append(item)
        seen.add(key)
    return merged


def _relationship_key(item: Relationship) -> Tuple[Any, Any, Any]:
    from_value = item.from_
    to_value = item.to
    normalized_from = tuple(from_value) if isinstance(from_value, list) else from_value
    normalized_to = tuple(to_value) if isinstance(to_value, list) else to_value
    return item.type, normalized_from, normalized_to


def _schema_property_from_data_type(
    *,
    name: Optional[str],
    column: exp.ColumnDef | None,
    dialect: Any,
    kind: Any,
    physical_type: str,
    required: bool,
    description: Optional[str],
    primary_key_position: Optional[int],
    unique: bool,
    partition_key_position: Optional[int],
) -> SchemaProperty:
    data_type = kind if isinstance(kind, exp.DataType) else None
    logical_type, format_hint = _sql_type_details(physical_type)

    logical_type_options: Optional[Dict[str, Any]] = None
    nested_properties: Optional[List[SchemaProperty]] = None
    items: Optional[SchemaProperty] = None

    if data_type is not None:
        logical_type_options = _extract_logical_type_options(
            data_type, column=column, physical_type=physical_type
        )
        nested_properties = _extract_nested_properties(data_type, dialect=dialect)
        items = _extract_items(data_type, dialect=dialect)
    elif format_hint:
        logical_type_options = {"format": format_hint}

    return SchemaProperty(
        id=_to_contract_id(name or physical_type),
        name=name,
        physicalName=name,
        logicalType=logical_type,
        physicalType=physical_type,
        logicalTypeOptions=logical_type_options,
        required=required,
        description=description,
        primaryKey=primary_key_position is not None,
        primaryKeyPosition=primary_key_position,
        unique=unique if unique else None,
        partitioned=partition_key_position is not None,
        partitionKeyPosition=partition_key_position,
        properties=nested_properties,
        items=items,
    )


def _extract_logical_type_options(
    data_type: exp.DataType,
    *,
    column: exp.ColumnDef | None = None,
    physical_type: str | None = None,
) -> Optional[Dict[str, Any]]:
    options: Dict[str, Any] = {}
    type_name = _data_type_name(data_type)

    if column is not None:
        max_length = upstream_sql_importer.get_max_length(column)
        if max_length is not None:
            options["maxLength"] = max_length

        precision, scale = upstream_sql_importer.get_precision_scale(column)
        if precision is not None:
            options["precision"] = precision
        if scale is not None:
            options["scale"] = scale

    _, format_hint = _sql_type_details(physical_type or data_type.sql(dialect="spark"))
    if format_hint:
        options["format"] = format_hint

    if type_name == "DECIMAL":
        params = [
            p.this for p in data_type.expressions if isinstance(p, exp.DataTypeParam)
        ]
        if (
            len(params) >= 1
            and "precision" not in options
            and isinstance(params[0], exp.Literal)
        ):
            options["precision"] = int(str(params[0]))
        if (
            len(params) >= 2
            and "scale" not in options
            and isinstance(params[1], exp.Literal)
        ):
            options["scale"] = int(str(params[1]))

    if type_name == "MAP":
        key_type = (
            data_type.expressions[0].sql(dialect="spark")
            if data_type.expressions
            else None
        )
        if key_type:
            options["keyType"] = key_type

    return options or None


def _extract_nested_properties(
    data_type: exp.DataType, *, dialect: Any
) -> Optional[List[SchemaProperty]]:
    if _data_type_name(data_type) != "STRUCT":
        return None

    nested_properties: List[SchemaProperty] = []
    for child in data_type.expressions or []:
        if not isinstance(child, exp.ColumnDef):
            continue
        child_name = child.this.name if child.this is not None else None
        child_kind = child.args.get("kind")
        child_physical_type = _column_type(child, dialect=dialect)
        child_required = not _column_nullable(child)
        child_description = _column_comment(child)
        nested_properties.append(
            _schema_property_from_data_type(
                name=child_name,
                column=child,
                dialect=dialect,
                kind=child_kind,
                physical_type=child_physical_type,
                required=child_required,
                description=child_description,
                primary_key_position=None,
                unique=False,
                partition_key_position=None,
            )
        )
    return nested_properties or None


def _extract_items(
    data_type: exp.DataType, *, dialect: Any
) -> Optional[SchemaProperty]:
    type_name = _data_type_name(data_type)
    if type_name == "ARRAY" and data_type.expressions:
        item_type = data_type.expressions[0]
        if isinstance(item_type, exp.DataType):
            return _schema_property_from_data_type(
                name=None,
                column=None,
                dialect=dialect,
                kind=item_type,
                physical_type=item_type.sql(dialect=dialect),
                required=False,
                description=None,
                primary_key_position=None,
                unique=False,
                partition_key_position=None,
            )

    if type_name == "MAP" and len(data_type.expressions) >= 2:
        value_type = data_type.expressions[1]
        if isinstance(value_type, exp.DataType):
            return _schema_property_from_data_type(
                name=None,
                column=None,
                dialect=dialect,
                kind=value_type,
                physical_type=value_type.sql(dialect=dialect),
                required=False,
                description=None,
                primary_key_position=None,
                unique=False,
                partition_key_position=None,
            )

    return None


def _sql_type_details(sql_type: str) -> Tuple[str, Optional[str]]:
    logical_type, format_hint = upstream_sql_importer.map_type_from_sql(sql_type)
    normalized = (sql_type or "").lower().strip()

    if normalized.startswith("array"):
        return "array", None
    if normalized.startswith(("map", "struct")):
        return "object", None
    if logical_type == "string" and format_hint == "binary":
        return "binary", None
    if logical_type == "object" and normalized not in {"json"}:
        return "string", None
    return logical_type, format_hint


def _map_sql_type_to_odcs(sql_type: str) -> str:
    return _sql_type_details(sql_type)[0]


def _data_type_name(data_type: exp.DataType) -> str:
    token = data_type.this
    if hasattr(token, "name"):
        return str(token.name).upper()
    return str(token).replace("Type.", "").upper()
