from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from deltalake import DeltaTable
from datacontract.imports.importer import Importer
from open_data_contract_standard.model import (
    CustomProperty,
    Description,
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
    Relationship,
)
import sqlglot
from sqlglot import expressions as exp


class DeltaTableImporter(Importer):
    """Datacontract-compatible importer for Delta tables (delta-rs)."""

    def import_source(self, source: str, import_args: dict) -> OpenDataContractStandard:
        import_args = import_args or {}
        table_uris = _resolve_table_uris(source, import_args)
        storage_options = import_args.get("storage_options")
        oauth_bearer_token = import_args.get("oauth_bearer_token")
        dataset_name = import_args.get("dataset_name") or import_args.get(
            "contract_name"
        )
        contract_id = import_args.get("contract_id")
        contract_version = import_args.get("contract_version")

        return _build_imported_contract(
            table_uris=table_uris,
            storage_options=storage_options,
            oauth_bearer_token=oauth_bearer_token,
            dataset_name=dataset_name,
            contract_id=contract_id,
            contract_version=contract_version,
        )


def _build_imported_contract(
    *,
    table_uris: List[str],
    storage_options: Optional[Dict[str, str]],
    oauth_bearer_token: Optional[str],
    dataset_name: Optional[str],
    contract_id: Optional[str],
    contract_version: Optional[str],
) -> OpenDataContractStandard:
    logger = logging.getLogger("DeltaTableImporter")
    logger.info("Importing Delta tables: %s", ", ".join(table_uris))

    if not dataset_name:
        dataset_name = _derive_contract_name(table_uris)
    if not contract_id:
        contract_id = _to_contract_id(dataset_name)

    schema_objects: List[SchemaObject] = []
    contract_description: Optional[str] = None

    for table_uri in table_uris:
        normalized_options = _normalize_storage_options(
            table_uri=table_uri,
            storage_options=storage_options,
            oauth_bearer_token=oauth_bearer_token,
        )
        table = DeltaTable(table_uri, storage_options=normalized_options)
        table_name = _derive_dataset_name(table_uri)
        table_id = _to_contract_id(table_name)
        delta_version = str(table.version())
        metadata = table.metadata()
        description = _extract_table_description(metadata)
        partition_positions = _extract_partition_positions(metadata)
        fields = _extract_delta_fields(table, partition_positions)
        property_relationships = _extract_delta_relationships(metadata)

        # Attach relationships to individual properties
        if property_relationships and fields:
            for prop in fields:
                prop_name = prop.name or prop.id
                if prop_name and prop_name in property_relationships:
                    rels = property_relationships[prop_name]
                    if rels:
                        prop.relationships = rels

        if len(table_uris) == 1:
            contract_description = description

        schema_objects.append(
            SchemaObject(
                id=table_id,
                name=table_name,
                physicalName=table_name,
                logicalType="object",
                physicalType="table",
                properties=fields,
                description=description,
                customProperties=[
                    CustomProperty(
                        property="semapact.table.location", value=table_uri
                    ),
                ],
            )
        )

    if contract_version is None:
        contract_version = "1.0.0"

    contract_model = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id=contract_id,
        name=dataset_name,
        version=contract_version,
        status="draft",
        schema=schema_objects,
        description=Description(usage=contract_description)
        if contract_description
        else None,
        customProperties=[
            CustomProperty(property="semapact.source", value="delta"),
        ],
    )
    return contract_model


def _resolve_table_uris(source: str, import_args: dict) -> List[str]:
    table_uris = import_args.get("table_uris") or import_args.get("tables") or []
    if isinstance(table_uris, str):
        table_uris = [item.strip() for item in table_uris.split(",") if item.strip()]
    if not isinstance(table_uris, list):
        raise ValueError("table_uris must be a list of table URIs")

    normalized = [item for item in table_uris if isinstance(item, str) and item.strip()]
    if source:
        normalized.insert(0, source)

    if not normalized:
        raise ValueError("Delta importer requires at least one table URI")
    return normalized


def _derive_contract_name(table_uris: List[str]) -> str:
    if not table_uris:
        return "delta_dataset"

    segments: List[List[str]] = []
    for uri in table_uris:
        parsed = urlparse(uri)
        path = parsed.path if parsed.scheme else uri
        parts = [part for part in Path(path).parts if part not in {"/", ""}]
        segments.append(parts)

    if not segments:
        return _derive_dataset_name(table_uris[0])

    prefix: List[str] = []
    for items in zip(*segments):
        if all(item == items[0] for item in items):
            prefix.append(items[0])
        else:
            break

    if prefix:
        return prefix[-1]

    return _derive_dataset_name(table_uris[0])


def _derive_dataset_name(table_uri: str) -> str:
    parsed = urlparse(table_uri)
    if parsed.scheme and parsed.path:
        name = Path(parsed.path.rstrip("/")).name
    else:
        name = Path(table_uri.rstrip("/")).name
    return name or "delta_dataset"


def _normalize_storage_options(
    *,
    table_uri: str,
    storage_options: Optional[Dict[str, str]],
    oauth_bearer_token: Optional[str],
) -> Optional[Dict[str, str]]:
    if not storage_options and not oauth_bearer_token:
        return storage_options

    normalized = dict(storage_options or {})
    token_keys = {"azure_storage_token", "bearer_token", "token"}
    if oauth_bearer_token and not token_keys.intersection(normalized):
        normalized["azure_storage_token"] = oauth_bearer_token

    account_keys = {
        "azure_storage_account_name",
        "storage_account_name",
        "account_name",
    }
    if oauth_bearer_token and not account_keys.intersection(normalized):
        account_name = _extract_account_name_from_uri(table_uri)
        if account_name:
            normalized["azure_storage_account_name"] = account_name

    return normalized or None


def _extract_account_name_from_uri(table_uri: str) -> Optional[str]:
    parsed = urlparse(table_uri)
    if not parsed.netloc:
        return None

    host = parsed.netloc
    if "@" in host:
        host = host.split("@", 1)[1]

    for suffix in (
        ".dfs.core.windows.net",
        ".blob.core.windows.net",
        ".dfs.fabric.microsoft.com",
    ):
        if host.endswith(suffix):
            return host[: -len(suffix)]

    return None


def _to_contract_id(dataset_name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", dataset_name).strip("-")
    return cleaned.lower() or "delta-dataset"


def _extract_delta_relationships(
    metadata: Any,
) -> Optional[Dict[str, List[Relationship]]]:
    if metadata is None:
        return None

    if isinstance(metadata, dict):
        configuration = metadata.get("configuration", {})
    else:
        configuration = getattr(metadata, "configuration", {}) or {}

    if not isinstance(configuration, dict):
        return None

    relationships = {}
    for key, value in configuration.items():
        if isinstance(key, str):
            prefix = None
            if key.startswith("semapact.fk."):
                prefix = "semapact.fk."
            elif key.startswith("semapact.fk."):
                prefix = "semapact.fk."

            if prefix:
                from_field = key[len(prefix) :]
                to_fields = [item.strip() for item in str(value).split(",") if item.strip()]

            rels = []
            for to_field in to_fields:
                rels.append(Relationship(type="foreignKey", to=to_field))
            if rels:
                relationships[from_field] = rels

    return relationships if relationships else None


def _extract_table_description(metadata: Any) -> Optional[str]:
    if metadata is None:
        return None

    if isinstance(metadata, dict):
        raw_description = metadata.get("description")
        configuration = metadata.get("configuration", {})
    else:
        raw_description = getattr(metadata, "description", None)
        configuration = getattr(metadata, "configuration", {}) or {}

    if raw_description:
        return str(raw_description)

    if isinstance(configuration, dict):
        for key in ("description", "comment", "delta.table.description"):
            value = configuration.get(key)
            if value:
                return str(value)
    return None


def _extract_partition_positions(metadata: Any) -> Dict[str, int]:
    if metadata is None:
        return {}

    partition_columns: Any = None
    if isinstance(metadata, dict):
        partition_columns = metadata.get("partition_columns") or metadata.get(
            "partitionColumns"
        )
    else:
        partition_columns = (
            getattr(metadata, "partition_columns", None)
            or getattr(metadata, "partitionColumns", None)
            or getattr(metadata, "partitionColumns", None)
        )

    if not isinstance(partition_columns, list):
        return {}

    positions: Dict[str, int] = {}
    for idx, column in enumerate(partition_columns, start=1):
        if isinstance(column, str) and column.strip():
            positions[column.strip().lower()] = idx
    return positions


def _extract_delta_fields(
    table: DeltaTable, partition_positions: Dict[str, int]
) -> List[SchemaProperty]:
    schema_obj = table.schema()
    schema_json = None
    if hasattr(schema_obj, "to_json"):
        schema_json = schema_obj.to_json()
    elif hasattr(schema_obj, "json"):
        schema_json = schema_obj.json()

    if isinstance(schema_json, str):
        schema_payload = json.loads(schema_json)
    elif isinstance(schema_json, dict):
        schema_payload = schema_json
    else:
        schema_payload = {}

    fields_payload = schema_payload.get("fields", [])
    fields: List[SchemaProperty] = []
    for field in fields_payload:
        if not isinstance(field, dict):
            continue
        property_obj = _schema_property_from_delta_field(
            field, partition_positions=partition_positions
        )
        if property_obj is not None:
            fields.append(property_obj)

    return fields


def _delta_type_to_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if value.get("type") == "decimal":
            precision = value.get("precision", 38)
            scale = value.get("scale", 0)
            return f"decimal({precision},{scale})"
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    return str(value)


def _schema_property_from_delta_field(
    field: Dict[str, Any],
    *,
    partition_positions: Dict[str, int],
) -> Optional[SchemaProperty]:
    name = str(field.get("name") or "").strip()
    if not name:
        return None

    type_value = field.get("type")
    physical_type = _delta_type_to_string(type_value)
    nullable = bool(field.get("nullable", True))
    metadata = field.get("metadata")

    description = None
    if isinstance(metadata, dict):
        comment = metadata.get("comment") or metadata.get("description")
        if comment:
            description = str(comment)

    logical_opts, physical_opts = _extract_type_options(type_value, physical_type)
    nested_properties = _extract_nested_properties(type_value)
    items = _extract_items(type_value)
    partition_key_position = partition_positions.get(name.lower())

    return SchemaProperty(
        id=_to_contract_id(name),
        name=name,
        physicalName=name,
        logicalType=_map_delta_type_to_odcs(physical_type),
        physicalType=physical_type,
        logicalTypeOptions=logical_opts,
        required=not nullable,
        description=description,
        partitioned=partition_key_position is not None,
        partitionKeyPosition=partition_key_position,
        properties=nested_properties,
        items=items,
    )


def _extract_type_options(
    type_value: Any, physical_type: str
) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    logical: Dict[str, Any] = {}
    physical: Dict[str, Any] = {}

    decimal_match = re.match(r"decimal\((\d+),\s*(\d+)\)", physical_type.lower())
    if decimal_match:
        physical["precision"] = int(decimal_match.group(1))
        physical["scale"] = int(decimal_match.group(2))

    if isinstance(type_value, dict) and str(type_value.get("type")).lower() == "map":
        key_type = type_value.get("keyType")
        if key_type is not None:
            logical["keyType"] = _delta_type_to_string(key_type)

    parsed_data_type = _parse_sql_data_type(physical_type)
    if parsed_data_type is not None:
        p_sql, l_sql = _extract_type_options_from_data_type(parsed_data_type)
        physical.update({k: v for k, v in p_sql.items() if k not in physical})
        logical.update({k: v for k, v in l_sql.items() if k not in logical})

    return logical or None, physical or None


def _extract_type_options_from_data_type(
    data_type: exp.DataType,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    logical: Dict[str, Any] = {}
    physical: Dict[str, Any] = {}
    type_name = _data_type_name(data_type)
    if type_name == "DECIMAL":
        params = [
            p.this for p in data_type.expressions if isinstance(p, exp.DataTypeParam)
        ]
        if len(params) >= 1 and isinstance(params[0], exp.Literal):
            physical["precision"] = int(str(params[0]))
        if len(params) >= 2 and isinstance(params[1], exp.Literal):
            physical["scale"] = int(str(params[1]))
    if type_name == "MAP" and data_type.expressions:
        logical["keyType"] = data_type.expressions[0].sql(dialect="spark")
    return physical, logical


def _extract_nested_properties(type_value: Any) -> Optional[List[SchemaProperty]]:
    if isinstance(type_value, dict) and str(type_value.get("type")).lower() == "struct":
        nested_fields = type_value.get("fields")
        if not isinstance(nested_fields, list):
            return None

        properties: List[SchemaProperty] = []
        for nested_field in nested_fields:
            if not isinstance(nested_field, dict):
                continue
            property_obj = _schema_property_from_delta_field(
                nested_field, partition_positions={}
            )
            if property_obj is not None:
                properties.append(property_obj)
        return properties or None

    parsed_data_type = _parse_sql_data_type(_delta_type_to_string(type_value))
    if parsed_data_type is None or _data_type_name(parsed_data_type) != "STRUCT":
        return None

    properties: List[SchemaProperty] = []
    for child in parsed_data_type.expressions or []:
        if not isinstance(child, exp.ColumnDef):
            continue
        child_name = child.this.name if child.this is not None else None
        if not child_name:
            continue
        child_kind = child.args.get("kind")
        child_required = not _column_def_nullable(child)
        properties.append(
            _schema_property_from_sql_data_type(
                name=child_name,
                data_type=child_kind if isinstance(child_kind, exp.DataType) else None,
                required=child_required,
                description=None,
            )
        )
    return properties or None


def _extract_items(type_value: Any) -> Optional[SchemaProperty]:
    if isinstance(type_value, dict):
        type_name = str(type_value.get("type")).lower()
        if type_name == "array":
            element_type = type_value.get("elementType")
            contains_null = bool(type_value.get("containsNull", True))
            return _schema_property_from_any_type(
                element_type,
                required=not contains_null,
            )
        if type_name == "map":
            value_type = type_value.get("valueType")
            value_contains_null = bool(type_value.get("valueContainsNull", True))
            return _schema_property_from_any_type(
                value_type,
                required=not value_contains_null,
            )

    parsed_data_type = _parse_sql_data_type(_delta_type_to_string(type_value))
    if parsed_data_type is None:
        return None

    type_name = _data_type_name(parsed_data_type)
    if type_name == "ARRAY" and parsed_data_type.expressions:
        element_type = parsed_data_type.expressions[0]
        if isinstance(element_type, exp.DataType):
            return _schema_property_from_sql_data_type(
                name=None,
                data_type=element_type,
                required=False,
                description=None,
            )
    if type_name == "MAP" and len(parsed_data_type.expressions) >= 2:
        value_type = parsed_data_type.expressions[1]
        if isinstance(value_type, exp.DataType):
            return _schema_property_from_sql_data_type(
                name=None,
                data_type=value_type,
                required=False,
                description=None,
            )

    return None


def _schema_property_from_any_type(
    type_value: Any, *, required: bool
) -> Optional[SchemaProperty]:
    if type_value is None:
        return None
    if isinstance(type_value, dict) and "name" in type_value:
        return _schema_property_from_delta_field(type_value, partition_positions={})

    physical_type = _delta_type_to_string(type_value)
    data_type = _parse_sql_data_type(physical_type)
    if data_type is not None:
        return _schema_property_from_sql_data_type(
            name=None,
            data_type=data_type,
            required=required,
            description=None,
        )

    return SchemaProperty(
        logicalType=_map_delta_type_to_odcs(physical_type),
        physicalType=physical_type,
        required=required,
    )


def _schema_property_from_sql_data_type(
    *,
    name: Optional[str],
    data_type: Optional[exp.DataType],
    required: bool,
    description: Optional[str],
) -> SchemaProperty:
    physical_type = (
        data_type.sql(dialect="spark") if data_type is not None else "string"
    )
    return SchemaProperty(
        id=_to_contract_id(name or physical_type),
        name=name,
        physicalName=name,
        logicalType=_map_delta_type_to_odcs(physical_type),
        physicalType=physical_type,
        logicalTypeOptions=_extract_type_options_from_data_type(data_type)[1]
        if data_type is not None
        else None,
        required=required,
        description=description,
        properties=_extract_nested_properties(data_type)
        if data_type is not None
        else None,
        items=_extract_items(data_type) if data_type is not None else None,
    )


def _column_def_nullable(column: exp.ColumnDef) -> bool:
    if column.find(exp.NotNullColumnConstraint) is not None:
        return False
    if column.find(exp.PrimaryKeyColumnConstraint) is not None:
        return False
    return True


def _parse_sql_data_type(type_str: str) -> Optional[exp.DataType]:
    try:
        parsed = sqlglot.parse_one(type_str, read="spark", into=exp.DataType)
    except sqlglot.errors.ParseError:
        return None
    except Exception as exc:
        import logging

        logging.getLogger(__name__).debug(
            f"Failed to parse sql data type {type_str}: {exc}"
        )
        return None
    return parsed if isinstance(parsed, exp.DataType) else None


def _data_type_name(data_type: exp.DataType) -> str:
    token = data_type.this
    if hasattr(token, "name"):
        return str(token.name).upper()
    return str(token).replace("Type.", "").upper()


def _map_delta_type_to_odcs(delta_type: str) -> str:
    normalized = delta_type.lower()
    if normalized.startswith(("string", "varchar", "char")):
        return "string"
    if normalized.startswith(("int", "bigint", "smallint", "tinyint", "long", "short")):
        return "integer"
    if normalized.startswith(("decimal", "double", "float", "numeric")):
        return "number"
    if normalized.startswith(("bool", "boolean")):
        return "boolean"
    if normalized.startswith("date"):
        return "date"
    if normalized.startswith(("timestamp", "datetime")):
        return "timestamp"
    if normalized.startswith(("binary", "varbinary", "bytes")):
        return "string"
    if normalized.startswith("array"):
        return "array"
    if normalized.startswith(("map", "struct", "{")):
        return "object"
    return "string"
