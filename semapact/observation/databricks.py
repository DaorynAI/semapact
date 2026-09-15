"""Databricks observation adapter backed by the official Databricks SDK.

The adapter consumes the same ``WorkspaceClient.tables.get(...) -> TableInfo``
boundary used by datacontract-cli, but projects that source metadata into
SemaPact's platform-neutral observation model instead of into ODCS.

Authentication and credential resolution are caller concerns. This module
accepts an already initialized/authenticated ``WorkspaceClient`` and must not
resolve PATs, OAuth credentials, Azure identity, profiles, service principals,
or other authentication mechanisms itself.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Protocol

from semapact.observation.fingerprint import with_observed_state_fingerprint
from semapact.observation.models import (
    ObservedAsset,
    ObservedAssetIdentity,
    ObservedConstraint,
    ObservedConstraintKind,
    ObservedPlatformState,
    ObservedProperty,
    ObservedPropertyIdentity,
    ObservedRelationship,
    ObservedRelationshipKind,
    ObservedTag,
)

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.catalog import TableInfo

DATABRICKS_PLATFORM = "databricks"
UNITY_CATALOG_PROVENANCE = "unity_catalog"


class _SdkObjectLike(Protocol):
    def as_dict(self) -> dict[str, Any]: ...


class _TablesApiLike(Protocol):
    def get(self, full_name: str) -> _SdkObjectLike: ...


class _EntityTagAssignmentsApiLike(Protocol):
    def list(self, entity_type: str, entity_name: str) -> Iterable[_SdkObjectLike]: ...


class _WorkspaceClientLike(Protocol):
    tables: _TablesApiLike
    entity_tag_assignments: _EntityTagAssignmentsApiLike


def observe_databricks_table(
    *,
    client: WorkspaceClient | _WorkspaceClientLike,
    table_fqn: str,
    source_identifier: str,
    captured_at: datetime | None = None,
) -> ObservedPlatformState:
    """Observe one Databricks table without generating or mutating an ODCS contract.

    ``client`` is expected to be an already initialized/authenticated official
    ``databricks.sdk.WorkspaceClient`` in production. Authentication method and
    credential resolution are intentionally outside this adapter's scope.
    The client is injectable so core observation tests require no live
    Databricks workspace.

    Tag assignments are read through the official SDK when that API is exposed
    by the supplied client. Read errors are not suppressed: an observation must
    not silently represent unreadable governance evidence as absent evidence.
    """
    if not table_fqn:
        raise ValueError("table_fqn is required for Databricks observation")
    if not source_identifier:
        raise ValueError("source_identifier is required for Databricks observation")

    observed_at = captured_at or datetime.now(timezone.utc)
    _require_aware_datetime(observed_at)

    table = client.tables.get(table_fqn)
    metadata = _sdk_mapping(table, context="Databricks TableInfo")
    identity = _asset_identity(metadata, table_fqn=table_fqn)
    canonical_table_fqn = ".".join((*identity.namespace, identity.asset))

    table_tags = _read_entity_tags(
        client,
        entity_type="tables",
        entity_name=canonical_table_fqn,
    )
    column_tags = {
        column_name: _read_entity_tags(
            client,
            entity_type="columns",
            entity_name=f"{canonical_table_fqn}.{column_name}",
        )
        for column_name in _column_names(metadata.get("columns"))
    }

    return map_databricks_table_info(
        table,
        source_identifier=source_identifier,
        captured_at=observed_at,
        table_fqn=table_fqn,
        table_tags=table_tags,
        column_tags=column_tags,
    )


def map_databricks_table_info(
    table: TableInfo | _SdkObjectLike,
    *,
    source_identifier: str,
    captured_at: datetime,
    table_fqn: str | None = None,
    table_tags: tuple[ObservedTag, ...] = (),
    column_tags: Mapping[str, tuple[ObservedTag, ...]] | None = None,
) -> ObservedPlatformState:
    """Project an SDK ``TableInfo`` into fingerprinted platform-neutral state."""
    _require_aware_datetime(captured_at)
    if not source_identifier:
        raise ValueError("source_identifier is required for Databricks observation")

    metadata = _sdk_mapping(table, context="Databricks TableInfo")
    identity = _asset_identity(metadata, table_fqn=table_fqn)
    constraints, relationships = _governance_structure(
        metadata.get("table_constraints"),
        source_identity=identity,
    )
    asset = ObservedAsset(
        identity=identity,
        asset_type=_text(metadata.get("table_type")),
        owner=_text(metadata.get("owner")),
        comment=_text(metadata.get("comment")),
        tags=_normalize_tags(table_tags),
        properties=_properties(
            metadata.get("columns"),
            identity=identity,
            column_tags=column_tags or {},
        ),
        constraints=constraints,
        relationships=relationships,
    )

    state = ObservedPlatformState(
        platform=DATABRICKS_PLATFORM,
        source_identifier=source_identifier.rstrip("/"),
        assets=(asset,),
        captured_at=captured_at,
        fingerprint=None,
    )
    return with_observed_state_fingerprint(state)


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
        raise ValueError("Databricks TableInfo must identify catalog, schema, and table name")

    return ObservedAssetIdentity(
        platform=DATABRICKS_PLATFORM,
        namespace=(catalog, schema),
        asset=asset,
    )


def _split_table_fqn(value: str) -> tuple[str, str, str] | None:
    parts = tuple(part.strip() for part in value.split("."))
    if len(parts) != 3 or not all(parts):
        return None
    return parts


def _properties(
    value: Any,
    *,
    identity: ObservedAssetIdentity,
    column_tags: Mapping[str, tuple[ObservedTag, ...]],
) -> tuple[ObservedProperty, ...]:
    if not isinstance(value, list):
        return ()

    observed: list[tuple[int | None, ObservedProperty]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue

        name = _text(item.get("name"))
        if not name:
            continue

        nullable = item.get("nullable") if isinstance(item.get("nullable"), bool) else None
        position = item.get("position")
        if isinstance(position, bool) or not isinstance(position, int):
            position = None

        observed.append(
            (
                position,
                ObservedProperty(
                    identity=ObservedPropertyIdentity(asset=identity, property=name),
                    physical_type=_text(item.get("type_text") or item.get("type_name")),
                    nullable=nullable,
                    comment=_text(item.get("comment")),
                    tags=_normalize_tags(column_tags.get(name, ())),
                ),
            )
        )

    observed.sort(key=_positioned_property_sort_key)
    return tuple(item[1] for item in observed)


def _positioned_property_sort_key(
    item: tuple[int | None, ObservedProperty],
) -> tuple[bool, int, str]:
    position, prop = item
    return (
        position is None,
        position if position is not None else 0,
        prop.identity.property.casefold(),
    )


def _governance_structure(
    value: Any,
    *,
    source_identity: ObservedAssetIdentity,
) -> tuple[tuple[ObservedConstraint, ...], tuple[ObservedRelationship, ...]]:
    if not isinstance(value, list):
        return (), ()

    constraints: dict[tuple[object, ...], ObservedConstraint] = {}
    relationships: dict[tuple[object, ...], ObservedRelationship] = {}
    for item in value:
        if not isinstance(item, Mapping):
            continue

        primary_key = item.get("primary_key_constraint")
        if isinstance(primary_key, Mapping):
            constraint = ObservedConstraint(
                kind=ObservedConstraintKind.PRIMARY_KEY,
                properties=_string_tuple(primary_key.get("child_columns")),
                name=_text(primary_key.get("name")),
                provenance=UNITY_CATALOG_PROVENANCE,
            )
            constraints[_constraint_key(constraint)] = constraint

        unique = item.get("unique_constraint")
        if isinstance(unique, Mapping):
            constraint = ObservedConstraint(
                kind=ObservedConstraintKind.UNIQUE,
                properties=_string_tuple(unique.get("child_columns")),
                name=_text(unique.get("name")),
                provenance=UNITY_CATALOG_PROVENANCE,
            )
            constraints[_constraint_key(constraint)] = constraint

        named = item.get("named_table_constraint")
        if isinstance(named, Mapping):
            constraint = ObservedConstraint(
                kind=ObservedConstraintKind.NAMED,
                name=_text(named.get("name")),
                provenance=UNITY_CATALOG_PROVENANCE,
            )
            constraints[_constraint_key(constraint)] = constraint

        foreign_key = item.get("foreign_key_constraint")
        if isinstance(foreign_key, Mapping):
            relationship = _foreign_key_relationship(
                foreign_key,
                source_identity=source_identity,
            )
            relationships[_relationship_key(relationship)] = relationship

    return (
        tuple(sorted(constraints.values(), key=_constraint_key)),
        tuple(sorted(relationships.values(), key=_relationship_key)),
    )


def _foreign_key_relationship(
    value: Mapping[str, Any],
    *,
    source_identity: ObservedAssetIdentity,
) -> ObservedRelationship:
    target_reference = _text(value.get("parent_table"))
    target_asset = None
    if target_reference:
        target_parts = _split_table_fqn(target_reference)
        if target_parts is not None:
            target_asset = ObservedAssetIdentity(
                platform=DATABRICKS_PLATFORM,
                namespace=(target_parts[0], target_parts[1]),
                asset=target_parts[2],
            )

    return ObservedRelationship(
        kind=ObservedRelationshipKind.FOREIGN_KEY,
        source_asset=source_identity,
        source_properties=_string_tuple(value.get("child_columns")),
        target_asset=target_asset,
        target_properties=_string_tuple(value.get("parent_columns")),
        target_reference=target_reference,
        name=_text(value.get("name")),
        provenance=UNITY_CATALOG_PROVENANCE,
    )


def _constraint_key(constraint: ObservedConstraint) -> tuple[object, ...]:
    return (
        constraint.kind.value,
        tuple(item.casefold() for item in constraint.properties),
        (constraint.name or "").casefold(),
        constraint.provenance or "",
    )


def _relationship_key(relationship: ObservedRelationship) -> tuple[object, ...]:
    return (
        relationship.kind.value,
        relationship.source_asset.canonical_key,
        tuple(item.casefold() for item in relationship.source_properties),
        relationship.target_asset.canonical_key if relationship.target_asset else (),
        tuple(item.casefold() for item in relationship.target_properties),
        (relationship.target_reference or "").casefold(),
        relationship.direction.value,
        (relationship.name or "").casefold(),
        relationship.provenance or "",
    )


def _read_entity_tags(
    client: WorkspaceClient | _WorkspaceClientLike,
    *,
    entity_type: str,
    entity_name: str,
) -> tuple[ObservedTag, ...]:
    api = getattr(client, "entity_tag_assignments", None)
    if api is None:
        return ()

    tags = []
    for assignment in api.list(entity_type=entity_type, entity_name=entity_name):
        metadata = _sdk_mapping(assignment, context="Databricks EntityTagAssignment")
        key = _text(metadata.get("tag_key"))
        if key is None:
            continue
        tags.append(
            ObservedTag(
                key=key,
                value=_text(metadata.get("tag_value")),
                provenance=UNITY_CATALOG_PROVENANCE,
            )
        )
    return _normalize_tags(tags)


def _normalize_tags(value: Iterable[ObservedTag]) -> tuple[ObservedTag, ...]:
    unique = {_tag_key(tag): tag for tag in value}
    return tuple(sorted(unique.values(), key=_tag_key))


def _tag_key(tag: ObservedTag) -> tuple[str, str, str]:
    return (tag.key, tag.value or "", tag.provenance or "")


def _column_names(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    names = {
        name
        for item in value
        if isinstance(item, Mapping)
        for name in [_text(item.get("name"))]
        if name is not None
    }
    return tuple(sorted(names, key=str.casefold))


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(text for item in value if (text := _text(item)) is not None)


def _sdk_mapping(value: object, *, context: str) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    as_dict = getattr(value, "as_dict", None)
    if not callable(as_dict):
        raise TypeError(f"{context} must expose as_dict()")
    metadata = as_dict()
    if not isinstance(metadata, Mapping):
        raise TypeError(f"{context}.as_dict() must return a mapping")
    return metadata


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _require_aware_datetime(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
