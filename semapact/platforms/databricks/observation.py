"""Databricks observation adapter backed by the official Databricks SDK.

This module contains Databricks/Unity Catalog extraction only. It maps provider
metadata into SemaPact's canonical platform-neutral observation model; shared
classification, metrics, canonicalization, and fingerprint semantics remain in
``semapact.observation``.

Authentication and credential resolution are caller concerns. Callers supply an
already initialized/authenticated ``WorkspaceClient``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Protocol, cast

from semapact.observation.canonical import (
    canonical_constraint_key,
    canonical_relationship_key,
    normalize_observed_tags,
)
from semapact.observation.evidence import (
    ObservedEvidenceAvailability,
    ObservedEvidenceAvailabilityStatus,
    ObservedEvidenceKind,
)
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


def databricks_evidence_availability(
    client: WorkspaceClient | _WorkspaceClientLike,
) -> tuple[ObservedEvidenceAvailability, ...]:
    """Describe which canonical evidence kinds this client can observe."""
    tag_status = (
        ObservedEvidenceAvailabilityStatus.AVAILABLE
        if _entity_tag_assignments_api(client) is not None
        else ObservedEvidenceAvailabilityStatus.UNAVAILABLE
    )
    return _table_info_evidence_availability(tag_status=tag_status)


def observe_databricks_table(
    *,
    client: WorkspaceClient | _WorkspaceClientLike,
    table_fqn: str,
    source_identifier: str,
    captured_at: datetime | None = None,
) -> ObservedPlatformState:
    """Observe one Unity Catalog table without mutating governed contract state."""
    table_fqn = table_fqn.strip()
    source_identifier = source_identifier.strip()
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
    tag_api = _entity_tag_assignments_api(client)

    table_tags = _read_entity_tags(
        tag_api,
        entity_type="tables",
        entity_name=canonical_table_fqn,
    )
    column_tags = {
        column_name: _read_entity_tags(
            tag_api,
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
        evidence_availability=_table_info_evidence_availability(
            tag_status=(
                ObservedEvidenceAvailabilityStatus.AVAILABLE
                if tag_api is not None
                else ObservedEvidenceAvailabilityStatus.UNAVAILABLE
            )
        ),
    )


def map_databricks_table_info(
    table: TableInfo | _SdkObjectLike,
    *,
    source_identifier: str,
    captured_at: datetime,
    table_fqn: str | None = None,
    table_tags: tuple[ObservedTag, ...] = (),
    column_tags: Mapping[str, tuple[ObservedTag, ...]] | None = None,
    evidence_availability: tuple[ObservedEvidenceAvailability, ...] | None = None,
) -> ObservedPlatformState:
    """Project one SDK ``TableInfo`` into canonical platform-neutral state."""
    _require_aware_datetime(captured_at)
    source_identifier = source_identifier.strip()
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
        tags=normalize_observed_tags(table_tags),
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
        evidence_availability=(
            evidence_availability
            if evidence_availability is not None
            else _table_info_evidence_availability(
                tag_status=ObservedEvidenceAvailabilityStatus.UNKNOWN
            )
        ),
        fingerprint=None,
    )
    return with_observed_state_fingerprint(state)


def _table_info_evidence_availability(
    *,
    tag_status: ObservedEvidenceAvailabilityStatus,
) -> tuple[ObservedEvidenceAvailability, ...]:
    statuses = {
        ObservedEvidenceKind.PHYSICAL_SCHEMA: ObservedEvidenceAvailabilityStatus.AVAILABLE,
        ObservedEvidenceKind.OWNER: ObservedEvidenceAvailabilityStatus.AVAILABLE,
        ObservedEvidenceKind.COMMENT: ObservedEvidenceAvailabilityStatus.AVAILABLE,
        ObservedEvidenceKind.TAG: tag_status,
        ObservedEvidenceKind.CONSTRAINT: ObservedEvidenceAvailabilityStatus.AVAILABLE,
        ObservedEvidenceKind.RELATIONSHIP: ObservedEvidenceAvailabilityStatus.AVAILABLE,
    }
    return tuple(
        ObservedEvidenceAvailability(kind=kind, status=statuses[kind])
        for kind in ObservedEvidenceKind
    )


def _entity_tag_assignments_api(
    client: WorkspaceClient | _WorkspaceClientLike,
) -> _EntityTagAssignmentsApiLike | None:
    api = getattr(client, "entity_tag_assignments", None)
    if api is None:
        return None
    if not callable(getattr(api, "list", None)):
        raise TypeError("Databricks entity_tag_assignments must expose list()")
    return cast(_EntityTagAssignmentsApiLike, api)


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
                    tags=normalize_observed_tags(column_tags.get(name, ())),
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
            constraints[canonical_constraint_key(constraint)] = constraint

        unique = item.get("unique_constraint")
        if isinstance(unique, Mapping):
            constraint = ObservedConstraint(
                kind=ObservedConstraintKind.UNIQUE,
                properties=_string_tuple(unique.get("child_columns")),
                name=_text(unique.get("name")),
                provenance=UNITY_CATALOG_PROVENANCE,
            )
            constraints[canonical_constraint_key(constraint)] = constraint

        named = item.get("named_table_constraint")
        if isinstance(named, Mapping):
            constraint = ObservedConstraint(
                kind=ObservedConstraintKind.NAMED,
                name=_text(named.get("name")),
                provenance=UNITY_CATALOG_PROVENANCE,
            )
            constraints[canonical_constraint_key(constraint)] = constraint

        foreign_key = item.get("foreign_key_constraint")
        if isinstance(foreign_key, Mapping):
            relationship = _foreign_key_relationship(
                foreign_key,
                source_identity=source_identity,
            )
            relationships[canonical_relationship_key(relationship)] = relationship

    return (
        tuple(sorted(constraints.values(), key=canonical_constraint_key)),
        tuple(sorted(relationships.values(), key=canonical_relationship_key)),
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


def _read_entity_tags(
    api: _EntityTagAssignmentsApiLike | None,
    *,
    entity_type: str,
    entity_name: str,
) -> tuple[ObservedTag, ...]:
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
    return normalize_observed_tags(tags)


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
