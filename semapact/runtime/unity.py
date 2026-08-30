"""Unity Catalog read-side observation without ODCS contract generation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from semapact.exceptions import StorageError
from semapact.runtime.models import (
    ObservedAsset,
    ObservedAssetIdentity,
    ObservedConstraint,
    ObservedContractState,
    ObservedProperty,
    ObservedPropertyIdentity,
    ObservedRelationship,
    RuntimeEvidence,
    RuntimeMetadata,
    RuntimeTag,
)

UNITY_CATALOG_PLATFORM = "databricks-unity-catalog"
UnityMetadataFetcher = Callable[[str, str, str], Mapping[str, Any]]


def observe_unity_table(
    *,
    table_fqn: str,
    workspace_url: str,
    token: str,
    captured_at: datetime | None = None,
    fetcher: UnityMetadataFetcher | None = None,
) -> ObservedContractState:
    """Observe one Unity Catalog table without creating or mutating an ODCS contract."""
    if not workspace_url:
        raise ValueError("workspace_url is required for Unity Catalog observation")
    if not token:
        raise ValueError("token is required for Unity Catalog observation")
    if not table_fqn:
        raise ValueError("table_fqn is required for Unity Catalog observation")

    observed_at = captured_at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")

    metadata_fetcher = fetcher or fetch_unity_table_metadata
    payload = metadata_fetcher(workspace_url, token, table_fqn)
    return map_unity_table_metadata(
        payload,
        source_identifier=workspace_url.rstrip("/"),
        table_fqn=table_fqn,
        captured_at=observed_at,
    )


def fetch_unity_table_metadata(
    workspace_url: str,
    token: str,
    table_fqn: str,
) -> Mapping[str, Any]:
    """Fetch the Unity Catalog TableInfo payload for one exact table."""
    if not workspace_url or not token:
        raise ValueError("workspace_url and token are required for Unity observation")

    endpoint = (
        f"{workspace_url.rstrip('/')}/api/2.1/unity-catalog/tables/"
        f"{quote(table_fqn, safe='')}"
    )
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
        raise StorageError(
            f"Unity table observation request failed: HTTP {exc.code}"
        ) from exc
    except URLError as exc:
        raise StorageError(
            f"Unity table observation request failed: {exc.reason}"
        ) from exc

    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise StorageError("Unity table observation response is not a JSON object")
    return parsed


def map_unity_table_metadata(
    metadata: Mapping[str, Any],
    *,
    source_identifier: str,
    captured_at: datetime,
    table_fqn: str | None = None,
) -> ObservedContractState:
    """Map a Unity TableInfo-style payload into immutable observed runtime state."""
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")

    identity = _asset_identity(metadata, table_fqn=table_fqn)
    properties = _properties(metadata, identity=identity)
    constraints, relationships = _constraints_and_relationships(metadata)
    evidence = _runtime_evidence(metadata)

    asset = ObservedAsset(
        identity=identity,
        asset_type=_text(metadata.get("table_type") or metadata.get("tableType")),
        data_source_format=_text(
            metadata.get("data_source_format") or metadata.get("dataSourceFormat")
        ),
        owner=_text(metadata.get("owner")),
        comment=_text(metadata.get("comment")),
        properties=properties,
        constraints=constraints,
        relationships=relationships,
        tags=_tags(metadata.get("tags")),
        metadata=_metadata_entries(
            metadata,
            excluded={
                "catalog_name",
                "catalogName",
                "schema_name",
                "schemaName",
                "name",
                "full_name",
                "fullName",
                "table_type",
                "tableType",
                "data_source_format",
                "dataSourceFormat",
                "owner",
                "comment",
                "columns",
                "table_constraints",
                "tableConstraints",
                "constraints",
                "foreign_keys",
                "foreignKeys",
                "tags",
                "view_dependencies",
                "viewDependencies",
            },
        ),
    )

    return ObservedContractState(
        platform=UNITY_CATALOG_PLATFORM,
        source_identifier=source_identifier.rstrip("/"),
        assets=(asset,),
        captured_at=captured_at,
        fingerprint=None,
        evidence=evidence,
    )


def _asset_identity(
    metadata: Mapping[str, Any], *, table_fqn: str | None
) -> ObservedAssetIdentity:
    catalog = _text(metadata.get("catalog_name") or metadata.get("catalogName"))
    schema = _text(metadata.get("schema_name") or metadata.get("schemaName"))
    asset = _text(metadata.get("name"))

    full_name = _text(
        metadata.get("full_name") or metadata.get("fullName") or table_fqn
    )
    fallback = _split_table_fqn(full_name) if full_name else None
    if fallback is not None:
        catalog = catalog or fallback[0]
        schema = schema or fallback[1]
        asset = asset or fallback[2]

    if not catalog or not schema or not asset:
        raise ValueError(
            "Unity metadata must identify catalog, schema, and table name"
        )

    return ObservedAssetIdentity(
        platform=UNITY_CATALOG_PLATFORM,
        catalog=catalog,
        schema=schema,
        asset=asset,
    )


def _split_table_fqn(value: str) -> tuple[str, str, str] | None:
    parts = [part.strip() for part in value.split(".")]
    if len(parts) != 3 or not all(parts):
        return None
    return parts[0], parts[1], parts[2]


def _properties(
    metadata: Mapping[str, Any], *, identity: ObservedAssetIdentity
) -> tuple[ObservedProperty, ...]:
    raw_columns = metadata.get("columns")
    if not isinstance(raw_columns, list):
        return ()

    properties: list[ObservedProperty] = []
    for item in raw_columns:
        if not isinstance(item, Mapping):
            continue
        name = _text(item.get("name"))
        if not name:
            continue

        nullable = _bool_or_none(item.get("nullable"))
        explicit_required = _bool_or_none(item.get("required"))
        required = explicit_required if explicit_required is not None else (
            None if nullable is None else not nullable
        )

        properties.append(
            ObservedProperty(
                identity=ObservedPropertyIdentity(asset=identity, property=name),
                logical_type=_text(
                    item.get("logical_type") or item.get("logicalType")
                ),
                physical_type=_text(
                    item.get("type_text")
                    or item.get("typeText")
                    or item.get("type_name")
                    or item.get("typeName")
                    or item.get("type")
                ),
                nullable=nullable,
                required=required,
                position=_int_or_none(item.get("position")),
                comment=_text(item.get("comment")),
                tags=_tags(item.get("tags")),
                metadata=_metadata_entries(
                    item,
                    excluded={
                        "name",
                        "logical_type",
                        "logicalType",
                        "type_text",
                        "typeText",
                        "type_name",
                        "typeName",
                        "type",
                        "nullable",
                        "required",
                        "position",
                        "comment",
                        "tags",
                    },
                ),
            )
        )

    properties.sort(key=_property_sort_key)
    return tuple(properties)


def _property_sort_key(item: ObservedProperty) -> tuple[int, int, str]:
    if item.position is None:
        return (1, 0, item.identity.property.casefold())
    return (0, item.position, item.identity.property.casefold())


def _constraints_and_relationships(
    metadata: Mapping[str, Any],
) -> tuple[tuple[ObservedConstraint, ...], tuple[ObservedRelationship, ...]]:
    constraints: list[ObservedConstraint] = []
    relationships: list[ObservedRelationship] = []

    for item in _constraint_items(metadata):
        primary = _mapping(item.get("primary_key_constraint") or item.get("primaryKeyConstraint"))
        foreign = _mapping(item.get("foreign_key_constraint") or item.get("foreignKeyConstraint"))

        if primary is not None:
            constraints.append(
                ObservedConstraint(
                    constraint_type="PRIMARY_KEY",
                    name=_text(primary.get("name")),
                    columns=_string_tuple(
                        primary.get("child_columns") or primary.get("childColumns")
                    ),
                    metadata=_metadata_entries(
                        primary,
                        excluded={"name", "child_columns", "childColumns"},
                    ),
                )
            )
            continue

        if foreign is not None:
            relationships.append(
                ObservedRelationship(
                    relationship_type="FOREIGN_KEY",
                    source_columns=_string_tuple(
                        foreign.get("child_columns") or foreign.get("childColumns")
                    ),
                    target_reference=_text(
                        foreign.get("parent_table") or foreign.get("parentTable")
                    ),
                    target_columns=_string_tuple(
                        foreign.get("parent_columns") or foreign.get("parentColumns")
                    ),
                    constraint_name=_text(foreign.get("name")),
                    metadata=_metadata_entries(
                        foreign,
                        excluded={
                            "name",
                            "child_columns",
                            "childColumns",
                            "parent_table",
                            "parentTable",
                            "parent_columns",
                            "parentColumns",
                        },
                    ),
                )
            )
            continue

        constraint_type = _text(
            item.get("constraint_type")
            or item.get("constraintType")
            or item.get("type")
            or item.get("kind")
        )
        normalized_type = (constraint_type or "UNKNOWN").upper().replace(" ", "_")
        source_columns = _string_tuple(
            item.get("columns")
            or item.get("column_names")
            or item.get("columnNames")
            or item.get("from_columns")
            or item.get("fromColumns")
            or item.get("child_columns")
            or item.get("childColumns")
            or item.get("from")
        )
        target_reference = _text(
            item.get("referenced_table")
            or item.get("referencedTable")
            or item.get("to_table")
            or item.get("toTable")
            or item.get("parent_table")
            or item.get("parentTable")
        )
        target_columns = _string_tuple(
            item.get("referenced_columns")
            or item.get("referencedColumns")
            or item.get("to_columns")
            or item.get("toColumns")
            or item.get("parent_columns")
            or item.get("parentColumns")
            or item.get("to")
        )

        if "FOREIGN" in normalized_type or target_reference:
            relationships.append(
                ObservedRelationship(
                    relationship_type=normalized_type,
                    source_columns=source_columns,
                    target_reference=target_reference,
                    target_columns=target_columns,
                    constraint_name=_text(item.get("name")),
                    metadata=_metadata_entries(
                        item,
                        excluded=_FLAT_CONSTRAINT_KEYS,
                    ),
                )
            )
        else:
            constraints.append(
                ObservedConstraint(
                    constraint_type=normalized_type,
                    name=_text(item.get("name")),
                    columns=source_columns,
                    expression=_text(
                        item.get("expression") or item.get("check_expression")
                    ),
                    metadata=_metadata_entries(
                        item,
                        excluded=_FLAT_CONSTRAINT_KEYS | {"expression", "check_expression"},
                    ),
                )
            )

    constraints.sort(
        key=lambda item: (
            item.constraint_type,
            (item.name or "").casefold(),
            tuple(value.casefold() for value in item.columns),
        )
    )
    relationships.sort(
        key=lambda item: (
            item.relationship_type,
            (item.constraint_name or "").casefold(),
            (item.target_reference or "").casefold(),
            tuple(value.casefold() for value in item.source_columns),
        )
    )
    return tuple(constraints), tuple(relationships)


_FLAT_CONSTRAINT_KEYS = {
    "constraint_type",
    "constraintType",
    "type",
    "kind",
    "name",
    "columns",
    "column_names",
    "columnNames",
    "from_columns",
    "fromColumns",
    "child_columns",
    "childColumns",
    "from",
    "referenced_table",
    "referencedTable",
    "to_table",
    "toTable",
    "parent_table",
    "parentTable",
    "referenced_columns",
    "referencedColumns",
    "to_columns",
    "toColumns",
    "parent_columns",
    "parentColumns",
    "to",
}


def _constraint_items(metadata: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    items: list[Mapping[str, Any]] = []
    for key in (
        "table_constraints",
        "tableConstraints",
        "constraints",
        "foreign_keys",
        "foreignKeys",
    ):
        value = metadata.get(key)
        if isinstance(value, list):
            items.extend(item for item in value if isinstance(item, Mapping))
    return tuple(items)


def _runtime_evidence(metadata: Mapping[str, Any]) -> tuple[RuntimeEvidence, ...]:
    raw = metadata.get("view_dependencies") or metadata.get("viewDependencies")
    dependency_container = _mapping(raw)
    if dependency_container is None:
        return ()
    dependencies = dependency_container.get("dependencies")
    if not isinstance(dependencies, list):
        return ()

    evidence: list[RuntimeEvidence] = []
    for dependency in dependencies:
        if not isinstance(dependency, Mapping):
            continue
        table = _mapping(dependency.get("table"))
        function = _mapping(dependency.get("function"))
        if table is not None:
            reference = _text(
                table.get("table_full_name") or table.get("tableFullName")
            )
            if reference:
                evidence.append(
                    RuntimeEvidence(
                        kind="view_table_dependency",
                        reference=reference,
                        metadata=_metadata_entries(
                            table,
                            excluded={"table_full_name", "tableFullName"},
                        ),
                    )
                )
        elif function is not None:
            reference = _text(
                function.get("function_full_name")
                or function.get("functionFullName")
            )
            if reference:
                evidence.append(
                    RuntimeEvidence(
                        kind="view_function_dependency",
                        reference=reference,
                        metadata=_metadata_entries(
                            function,
                            excluded={"function_full_name", "functionFullName"},
                        ),
                    )
                )

    evidence.sort(key=lambda item: (item.kind, item.reference.casefold()))
    return tuple(evidence)


def _tags(value: Any) -> tuple[RuntimeTag, ...]:
    tags: list[RuntimeTag] = []
    if isinstance(value, Mapping):
        for key, item_value in value.items():
            tags.append(RuntimeTag(key=str(key), value=str(item_value)))
    elif isinstance(value, list):
        for item in value:
            if not isinstance(item, Mapping):
                continue
            key = _text(item.get("key") or item.get("tag_name") or item.get("tagName"))
            item_value = _text(
                item.get("value") or item.get("tag_value") or item.get("tagValue")
            )
            if key and item_value is not None:
                tags.append(RuntimeTag(key=key, value=item_value))
    tags.sort(key=lambda item: (item.key.casefold(), item.value))
    return tuple(tags)


def _metadata_entries(
    mapping: Mapping[str, Any], *, excluded: set[str]
) -> tuple[RuntimeMetadata, ...]:
    entries = [
        RuntimeMetadata(key=str(key), value_json=_canonical_json(value))
        for key, value in mapping.items()
        if key not in excluded
    ]
    entries.sort(key=lambda item: item.key.casefold())
    return tuple(entries)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        result = tuple(text for item in value if (text := _text(item)) is not None)
        return result
    return ()


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None
