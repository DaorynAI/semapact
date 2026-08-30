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

_ASSET_FIELDS = {
    "catalog_name",
    "schema_name",
    "name",
    "full_name",
    "table_type",
    "data_source_format",
    "owner",
    "comment",
    "columns",
    "table_constraints",
    "tags",
    "view_dependencies",
}
_COLUMN_FIELDS = {
    "name",
    "logical_type",
    "type_text",
    "type_name",
    "nullable",
    "required",
    "position",
    "comment",
    "tags",
}


def observe_unity_table(
    *,
    table_fqn: str,
    workspace_url: str,
    token: str,
    captured_at: datetime | None = None,
    fetcher: UnityMetadataFetcher | None = None,
) -> ObservedContractState:
    """Observe one Unity Catalog table without creating or mutating ODCS state."""
    if not table_fqn:
        raise ValueError("table_fqn is required for Unity Catalog observation")
    if not workspace_url:
        raise ValueError("workspace_url is required for Unity Catalog observation")
    if not token:
        raise ValueError("token is required for Unity Catalog observation")

    observed_at = captured_at or datetime.now(timezone.utc)
    _require_aware_datetime(observed_at)

    metadata_fetcher = fetcher or fetch_unity_table_metadata
    metadata = metadata_fetcher(workspace_url, token, table_fqn)
    return map_unity_table_metadata(
        metadata,
        source_identifier=workspace_url.rstrip("/"),
        table_fqn=table_fqn,
        captured_at=observed_at,
    )


def fetch_unity_table_metadata(
    workspace_url: str,
    token: str,
    table_fqn: str,
) -> Mapping[str, Any]:
    """Fetch one Unity Catalog ``TableInfo`` object."""
    endpoint = (
        f"{workspace_url.rstrip('/')}/api/2.1/unity-catalog/tables/"
        f"{quote(table_fqn, safe='')}"
    )
    request = Request(
        endpoint,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
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
    """Map a Unity Catalog ``TableInfo`` payload to observed runtime state."""
    _require_aware_datetime(captured_at)
    identity = _asset_identity(metadata, table_fqn=table_fqn)
    constraints, relationships = _constraints_and_relationships(metadata)

    asset = ObservedAsset(
        identity=identity,
        asset_type=_text(metadata.get("table_type")),
        data_source_format=_text(metadata.get("data_source_format")),
        owner=_text(metadata.get("owner")),
        comment=_text(metadata.get("comment")),
        properties=_properties(metadata.get("columns"), identity=identity),
        constraints=constraints,
        relationships=relationships,
        tags=_tags(metadata.get("tags")),
        metadata=_metadata_entries(metadata, excluded=_ASSET_FIELDS),
    )
    return ObservedContractState(
        platform=UNITY_CATALOG_PLATFORM,
        source_identifier=source_identifier.rstrip("/"),
        assets=(asset,),
        captured_at=captured_at,
        fingerprint=None,
        evidence=_runtime_evidence(metadata.get("view_dependencies")),
    )


def _asset_identity(
    metadata: Mapping[str, Any], *, table_fqn: str | None
) -> ObservedAssetIdentity:
    catalog = _text(metadata.get("catalog_name"))
    schema = _text(metadata.get("schema_name"))
    asset = _text(metadata.get("name"))

    full_name = _text(metadata.get("full_name") or table_fqn)
    fallback = _split_table_fqn(full_name) if full_name else None
    if fallback:
        catalog = catalog or fallback[0]
        schema = schema or fallback[1]
        asset = asset or fallback[2]

    if not catalog or not schema or not asset:
        raise ValueError("Unity metadata must identify catalog, schema, and table name")

    return ObservedAssetIdentity(
        platform=UNITY_CATALOG_PLATFORM,
        catalog=catalog,
        schema=schema,
        asset=asset,
    )


def _split_table_fqn(value: str) -> tuple[str, str, str] | None:
    parts = tuple(part.strip() for part in value.split("."))
    if len(parts) != 3 or not all(parts):
        return None
    return parts


def _properties(
    value: Any, *, identity: ObservedAssetIdentity
) -> tuple[ObservedProperty, ...]:
    if not isinstance(value, list):
        return ()

    properties: list[ObservedProperty] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        name = _text(item.get("name"))
        if not name:
            continue

        nullable = item.get("nullable") if isinstance(item.get("nullable"), bool) else None
        explicit_required = (
            item.get("required") if isinstance(item.get("required"), bool) else None
        )
        required = (
            explicit_required
            if explicit_required is not None
            else None if nullable is None else not nullable
        )
        position = item.get("position")
        if isinstance(position, bool) or not isinstance(position, int):
            position = None

        properties.append(
            ObservedProperty(
                identity=ObservedPropertyIdentity(asset=identity, property=name),
                logical_type=_text(item.get("logical_type")),
                physical_type=_text(item.get("type_text") or item.get("type_name")),
                nullable=nullable,
                required=required,
                position=position,
                comment=_text(item.get("comment")),
                tags=_tags(item.get("tags")),
                metadata=_metadata_entries(item, excluded=_COLUMN_FIELDS),
            )
        )

    properties.sort(
        key=lambda item: (
            item.position is None,
            item.position if item.position is not None else 0,
            item.identity.property.casefold(),
        )
    )
    return tuple(properties)


def _constraints_and_relationships(
    metadata: Mapping[str, Any],
) -> tuple[tuple[ObservedConstraint, ...], tuple[ObservedRelationship, ...]]:
    value = metadata.get("table_constraints")
    if not isinstance(value, list):
        return (), ()

    constraints: list[ObservedConstraint] = []
    relationships: list[ObservedRelationship] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue

        primary = item.get("primary_key_constraint")
        if isinstance(primary, Mapping):
            constraints.append(
                ObservedConstraint(
                    constraint_type="PRIMARY_KEY",
                    name=_text(primary.get("name")),
                    columns=_string_tuple(primary.get("child_columns")),
                    metadata=_metadata_entries(
                        primary,
                        excluded={"name", "child_columns"},
                    ),
                )
            )
            continue

        foreign = item.get("foreign_key_constraint")
        if isinstance(foreign, Mapping):
            relationships.append(
                ObservedRelationship(
                    relationship_type="FOREIGN_KEY",
                    source_columns=_string_tuple(foreign.get("child_columns")),
                    target_reference=_text(foreign.get("parent_table")),
                    target_columns=_string_tuple(foreign.get("parent_columns")),
                    constraint_name=_text(foreign.get("name")),
                    metadata=_metadata_entries(
                        foreign,
                        excluded={
                            "name",
                            "child_columns",
                            "parent_table",
                            "parent_columns",
                        },
                    ),
                )
            )
            continue

        constraints.append(
            ObservedConstraint(
                constraint_type="UNKNOWN",
                metadata=(RuntimeMetadata(key="raw", value_json=_canonical_json(item)),),
            )
        )

    constraints.sort(
        key=lambda item: (
            item.constraint_type,
            (item.name or "").casefold(),
            tuple(column.casefold() for column in item.columns),
            tuple(entry.value_json for entry in item.metadata),
        )
    )
    relationships.sort(
        key=lambda item: (
            (item.constraint_name or "").casefold(),
            (item.target_reference or "").casefold(),
            tuple(column.casefold() for column in item.source_columns),
        )
    )
    return tuple(constraints), tuple(relationships)


def _runtime_evidence(value: Any) -> tuple[RuntimeEvidence, ...]:
    if not isinstance(value, Mapping):
        return ()
    dependencies = value.get("dependencies")
    if not isinstance(dependencies, list):
        return ()

    evidence: list[RuntimeEvidence] = []
    for item in dependencies:
        if not isinstance(item, Mapping):
            continue
        table = item.get("table")
        function = item.get("function")
        if isinstance(table, Mapping):
            reference = _text(table.get("table_full_name"))
            if reference:
                evidence.append(
                    RuntimeEvidence(
                        kind="view_table_dependency",
                        reference=reference,
                        metadata=_metadata_entries(
                            table,
                            excluded={"table_full_name"},
                        ),
                    )
                )
        elif isinstance(function, Mapping):
            reference = _text(function.get("function_full_name"))
            if reference:
                evidence.append(
                    RuntimeEvidence(
                        kind="view_function_dependency",
                        reference=reference,
                        metadata=_metadata_entries(
                            function,
                            excluded={"function_full_name"},
                        ),
                    )
                )

    evidence.sort(key=lambda item: (item.kind, item.reference.casefold()))
    return tuple(evidence)


def _tags(value: Any) -> tuple[RuntimeTag, ...]:
    if not isinstance(value, Mapping):
        return ()
    tags = tuple(
        RuntimeTag(key=str(key), value=str(tag_value))
        for key, tag_value in sorted(value.items(), key=lambda pair: str(pair[0]).casefold())
    )
    return tags


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


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(text for item in value if (text := _text(item)) is not None)
    return ()


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _require_aware_datetime(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
