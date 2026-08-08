from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from open_data_contract_standard.model import (
    CustomProperty,
    OpenDataContractStandard,
    Relationship,
    SchemaObject,
)

from semapact.constants import (
    UNITY_CONSTRAINT_NAME_KEY,
    UNITY_RELATIONSHIPS_COUNT_KEY,
    UNITY_RELATIONSHIPS_IMPORTED_KEY,
    UNITY_RELATIONSHIPS_REASON_KEY,
)


@dataclass(slots=True)
class UnityForeignKey:
    source_columns: list[str]
    target_table: str
    target_columns: list[str]
    constraint_name: str | None = None


def enrich_unity_contract_relationships(
    contract: OpenDataContractStandard,
    *,
    table_fqn: str,
    workspace_url: str,
    token: str,
    fetcher: Callable[[str, str, str], dict[str, Any]] | None = None,
) -> OpenDataContractStandard:
    """Best-effort Unity relationship enrichment using table metadata.

    If Unity relationship metadata is unavailable, this function does not fail import.
    Instead it records fallback metadata on the contract customProperties.
    """
    table_metadata_fetcher = fetcher or _fetch_unity_table_metadata
    try:
        metadata = table_metadata_fetcher(workspace_url, token, table_fqn)
        foreign_keys = _extract_foreign_keys(metadata)
        imported_count = _apply_foreign_keys(
            contract, table_fqn=table_fqn, foreign_keys=foreign_keys
        )
        _upsert_contract_custom_property(
            contract, UNITY_RELATIONSHIPS_IMPORTED_KEY, "true"
        )
        _upsert_contract_custom_property(
            contract, UNITY_RELATIONSHIPS_COUNT_KEY, str(imported_count)
        )
    except Exception as exc:  # pragma: no cover - behavior validated via unit tests
        import logging

        logging.getLogger(__name__).debug(f"Failed to fetch unity relationships: {exc}")
        _upsert_contract_custom_property(
            contract, UNITY_RELATIONSHIPS_IMPORTED_KEY, "false"
        )
        _upsert_contract_custom_property(
            contract, UNITY_RELATIONSHIPS_REASON_KEY, str(exc)
        )
    return contract


def _fetch_unity_table_metadata(
    workspace_url: str, token: str, table_fqn: str
) -> dict[str, Any]:
    if not workspace_url or not token:
        raise ValueError(
            "workspace_url and token are required for Unity relationship import"
        )

    base_url = workspace_url.rstrip("/")
    endpoint = f"{base_url}/api/2.1/unity-catalog/tables/{quote(table_fqn, safe='')}"
    request = Request(
        endpoint,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=8) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        from semapact.exceptions import StorageError

        raise StorageError(
            f"Unity table metadata request failed: HTTP {exc.code}"
        ) from exc
    except URLError as exc:
        from semapact.exceptions import StorageError

        raise StorageError(
            f"Unity table metadata request failed: {exc.reason}"
        ) from exc

    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise RuntimeError("Unity table metadata response is not a JSON object")
    return parsed


def _extract_foreign_keys(metadata: dict[str, Any]) -> list[UnityForeignKey]:
    constraints = _constraint_items(metadata)
    foreign_keys: list[UnityForeignKey] = []
    for item in constraints:
        record = _parse_constraint_record(item)
        if record is not None:
            foreign_keys.append(record)
    return foreign_keys


def _constraint_items(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for key in (
        "table_constraints",
        "tableConstraints",
        "constraints",
        "foreign_keys",
        "foreignKeys",
    ):
        value = metadata.get(key)
        if isinstance(value, list):
            merged.extend(item for item in value if isinstance(item, dict))
    return merged


def _parse_constraint_record(item: dict[str, Any]) -> UnityForeignKey | None:
    constraint_type = str(
        item.get("constraint_type")
        or item.get("constraintType")
        or item.get("type")
        or item.get("kind")
        or ""
    ).lower()
    if "foreign" not in constraint_type and "reference" not in constraint_type:
        return None

    source_columns = _to_string_list(
        item.get("columns")
        or item.get("column_names")
        or item.get("columnNames")
        or item.get("from_columns")
        or item.get("fromColumns")
        or item.get("child_columns")
        or item.get("childColumns")
        or item.get("from")
    )
    target_columns = _to_string_list(
        item.get("referenced_columns")
        or item.get("referencedColumns")
        or item.get("to_columns")
        or item.get("toColumns")
        or item.get("parent_columns")
        or item.get("parentColumns")
        or item.get("to")
    )
    target_table = _to_string(
        item.get("referenced_table")
        or item.get("referencedTable")
        or item.get("to_table")
        or item.get("toTable")
        or item.get("parent_table")
        or item.get("parentTable")
    )

    if not source_columns or not target_columns or not target_table:
        return None

    return UnityForeignKey(
        source_columns=source_columns,
        target_table=target_table,
        target_columns=target_columns,
        constraint_name=_to_string(item.get("name")),
    )


def _to_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        return [part for part in parts if part]
    if isinstance(value, list):
        return [item for item in (_to_string(item) for item in value) if item]
    return []


def _apply_foreign_keys(
    contract: OpenDataContractStandard,
    *,
    table_fqn: str,
    foreign_keys: Sequence[UnityForeignKey],
) -> int:
    schema_obj = _resolve_target_schema(contract, table_fqn=table_fqn)
    if schema_obj is None:
        return 0

    imported_count = 0
    fields = {
        item.name.lower(): item for item in (schema_obj.properties or []) if item.name
    }

    for record in foreign_keys:
        custom_props = _constraint_custom_props(record.constraint_name)
        if len(record.source_columns) == 1 and len(record.target_columns) == 1:
            source_key = record.source_columns[0].lower()
            property_obj = fields.get(source_key)
            if property_obj is not None:
                relationship = Relationship(
                    type="foreignKey",
                    to=f"{record.target_table}.{record.target_columns[0]}",
                    customProperties=custom_props,
                )
                property_obj.relationships = _merge_relationships(
                    property_obj.relationships, [relationship]
                )
                imported_count += 1
                continue

        to_values = [f"{record.target_table}.{item}" for item in record.target_columns]
        schema_relationship = Relationship(
            type="foreignKey",
            **{"from": list(record.source_columns)},
            to=to_values,
            customProperties=custom_props,
        )
        schema_obj.relationships = _merge_relationships(
            schema_obj.relationships, [schema_relationship]
        )
        imported_count += 1

    return imported_count


def _resolve_target_schema(
    contract: OpenDataContractStandard, *, table_fqn: str
) -> SchemaObject | None:
    schema_items = contract.schema_ or []
    if not schema_items:
        return None
    short_name = table_fqn.split(".")[-1].strip().lower()
    for item in schema_items:
        if (item.physicalName or "").strip().lower() == short_name:
            return item
    for item in schema_items:
        if (item.name or "").strip().lower() == short_name:
            return item
    return schema_items[0]


def _constraint_custom_props(name: str | None) -> list[CustomProperty] | None:
    if not name:
        return None
    return [CustomProperty(property=UNITY_CONSTRAINT_NAME_KEY, value=name)]


def _merge_relationships(
    existing: Iterable[Relationship] | None, additions: Iterable[Relationship] | None
) -> list[Relationship]:
    merged: list[Relationship] = list(existing or [])
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


def _upsert_contract_custom_property(
    contract: OpenDataContractStandard, key: str, value: Any
) -> None:
    items = list(contract.customProperties or [])
    lowered = key.lower()
    for item in items:
        if (item.property or "").strip().lower() == lowered:
            item.value = value
            contract.customProperties = items
            return
    items.append(CustomProperty(property=key, value=value))
    contract.customProperties = items
