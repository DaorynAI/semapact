"""Databricks observation adapter backed by the official Databricks SDK.

The adapter consumes the same ``WorkspaceClient.tables.get(...) -> TableInfo``
boundary used by datacontract-cli, but projects that source metadata into
SemaPact's platform-neutral observation model instead of into ODCS.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Mapping, Protocol

from semapact.observation.models import (
    ObservedAsset,
    ObservedAssetIdentity,
    ObservedPlatformState,
    ObservedProperty,
    ObservedPropertyIdentity,
)

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.catalog import TableInfo

DATABRICKS_PLATFORM = "databricks"


class _TableInfoLike(Protocol):
    def as_dict(self) -> dict[str, Any]: ...


class _TablesApiLike(Protocol):
    def get(self, full_name: str) -> _TableInfoLike: ...


class _WorkspaceClientLike(Protocol):
    tables: _TablesApiLike


def observe_databricks_table(
    *,
    client: WorkspaceClient | _WorkspaceClientLike,
    table_fqn: str,
    source_identifier: str,
    captured_at: datetime | None = None,
) -> ObservedPlatformState:
    """Observe one Databricks table without generating or mutating an ODCS contract.

    ``client`` is expected to be an official ``databricks.sdk.WorkspaceClient``
    in production. It is injectable so core observation tests require no live
    Databricks workspace.
    """
    if not table_fqn:
        raise ValueError("table_fqn is required for Databricks observation")
    if not source_identifier:
        raise ValueError("source_identifier is required for Databricks observation")

    observed_at = captured_at or datetime.now(timezone.utc)
    _require_aware_datetime(observed_at)

    table = client.tables.get(table_fqn)
    return map_databricks_table_info(
        table,
        source_identifier=source_identifier,
        captured_at=observed_at,
        table_fqn=table_fqn,
    )


def map_databricks_table_info(
    table: TableInfo | _TableInfoLike,
    *,
    source_identifier: str,
    captured_at: datetime,
    table_fqn: str | None = None,
) -> ObservedPlatformState:
    """Project an SDK ``TableInfo`` into the platform-neutral observation model."""
    _require_aware_datetime(captured_at)
    if not source_identifier:
        raise ValueError("source_identifier is required for Databricks observation")

    metadata = table.as_dict()
    if not isinstance(metadata, Mapping):
        raise TypeError("Databricks TableInfo.as_dict() must return a mapping")

    identity = _asset_identity(metadata, table_fqn=table_fqn)
    asset = ObservedAsset(
        identity=identity,
        asset_type=_text(metadata.get("table_type")),
        properties=_properties(metadata.get("columns"), identity=identity),
    )

    return ObservedPlatformState(
        platform=DATABRICKS_PLATFORM,
        source_identifier=source_identifier.rstrip("/"),
        assets=(asset,),
        captured_at=captured_at,
        fingerprint=None,
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
    value: Any, *, identity: ObservedAssetIdentity
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
                ),
            )
        )

    observed.sort(
        key=lambda item: (
            item[0] is None,
            item[0] if item[0] is not None else 0,
            item[1].identity.property.casefold(),
        )
    )
    return tuple(item[1] for item in observed)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _require_aware_datetime(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
