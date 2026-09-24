from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence, Tuple

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
    table_metadata: Mapping[str, Mapping[str, Any]],
) -> OpenDataContractStandard:
    """Project SDK-returned Unity foreign keys for an entire data product.

    Relationship extraction is best effort per table. A contract-level summary
    records the total imported relationships and any table-specific failures.
    No second HTTP client or bearer-token path is introduced here.
    """
    imported_count = 0
    failures: list[str] = []

    for table_fqn in sorted(table_metadata, key=lambda value: (value.casefold(), value)):
        try:
            foreign_keys = _extract_foreign_keys(table_metadata[table_fqn])
            imported_count += _apply_foreign_keys(
                contract,
                table_fqn=table_fqn,
                foreign_keys=foreign_keys,
            )
        except Exception as exc:  # pragma: no cover - validated through unit tests
            failures.append(f"{table_fqn}: {exc}")

    _upsert_contract_custom_property(
        contract,
        UNITY_RELATIONSHIPS_IMPORTED_KEY,
        "false" if failures else "true",
    )
    _upsert_contract_custom_property(
        contract,
        UNITY_RELATIONSHIPS_COUNT_KEY,
        str(imported_count),
    )
    if failures:
        _upsert_contract_custom_property(
            contract,
            UNITY_RELATIONSHIPS_REASON_KEY,
            "; ".join(failures),
        )
    return contract

def _extract_foreign_keys(metadata: Mapping[str, Any]) -> list[UnityForeignKey]:
    foreign_keys: list[UnityForeignKey] = []
    for item in _constraint_items(metadata):
        record = _parse_constraint_record(item)
        if record is not None:
            foreign_keys.append(record)
    return foreign_keys


def _constraint_items(metadata: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = metadata.get("table_constraints")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _parse_constraint_record(item: Mapping[str, Any]) -> UnityForeignKey | None:
    value = item.get("foreign_key_constraint")
    if not isinstance(value, Mapping):
        return None

    source_columns = _to_string_list(value.get("child_columns"))
    target_columns = _to_string_list(value.get("parent_columns"))
    target_table = _to_string(value.get("parent_table"))
    if not source_columns or not target_columns or not target_table:
        return None

    return UnityForeignKey(
        source_columns=source_columns,
        target_table=target_table,
        target_columns=target_columns,
        constraint_name=_to_string(value.get("name")),
    )


def _to_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (_to_string(item) for item in value) if item]


def _apply_foreign_keys(
    contract: OpenDataContractStandard,
    *,
    table_fqn: str,
    foreign_keys: Sequence[UnityForeignKey],
) -> int:
    schema_obj = _resolve_target_schema(contract, table_fqn=table_fqn)
    if schema_obj is None:
        if foreign_keys:
            raise ValueError(
                f"Unity relationship metadata has no matching governed asset: {table_fqn}"
            )
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
    return None


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
