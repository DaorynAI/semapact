"""Read-only Databricks lineage evidence adapter.

This module reads Unity Catalog system tables through an already-open SQL cursor
and maps provider records into the platform-neutral observation lineage domain.
Each evidence surface fails independently so missing system-table permissions do
not break ordinary runtime observation or other available lineage evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from semapact.observation.evidence import ObservedEvidenceAvailabilityStatus
from semapact.observation.lineage import (
    ObservedLineageAvailability,
    ObservedLineageCaptureContext,
    ObservedLineageEvidence,
    ObservedLineageEvidenceType,
    ObservedLineageResult,
    normalize_lineage_evidence,
)
from semapact.observation.models import ObservedAssetIdentity

DATABRICKS_PLATFORM = "databricks"
UNITY_LINEAGE_PROVENANCE = "unity_catalog_system_tables"


class _SqlCursorLike(Protocol):
    def execute(self, operation: str, parameters: tuple[str, ...] | None = None) -> Any: ...

    def fetchall(self) -> Any: ...


_TABLE_LINEAGE_QUERY = """
SELECT
  source_table_full_name,
  target_table_full_name,
  statement_id,
  event_time,
  event_id,
  record_id,
  created_by,
  direct_access
FROM system.access.table_lineage
WHERE source_table_full_name = ? OR target_table_full_name = ?
"""

_COLUMN_LINEAGE_QUERY = """
SELECT
  source_table_full_name,
  source_column_name,
  target_table_full_name,
  target_column_name,
  statement_id,
  event_time,
  event_id,
  record_id,
  created_by,
  direct_access
FROM system.access.column_lineage
WHERE source_table_full_name = ? OR target_table_full_name = ?
"""

_QUERY_EVIDENCE_QUERY = """
SELECT
  tl.source_table_full_name,
  tl.target_table_full_name,
  tl.statement_id,
  tl.event_time,
  tl.event_id,
  tl.record_id,
  tl.created_by,
  tl.direct_access,
  qh.statement_text,
  qh.statement_type
FROM system.access.table_lineage tl
LEFT JOIN system.query.history qh
  ON tl.statement_id = qh.statement_id
 AND tl.workspace_id = qh.workspace_id
WHERE (tl.source_table_full_name = ? OR tl.target_table_full_name = ?)
  AND tl.statement_id IS NOT NULL
"""


def observe_databricks_lineage(
    *,
    cursor: _SqlCursorLike,
    table_fqn: str,
    source_identifier: str,
    captured_at: datetime | None = None,
) -> ObservedLineageResult:
    """Collect normalized lineage evidence for one Unity Catalog table.

    Table, column, and query evidence are queried independently. A permission or
    availability failure on one system table is represented explicitly and does
    not discard evidence collected from the other surfaces.
    """

    table_fqn = table_fqn.strip()
    source_identifier = source_identifier.strip()
    if not table_fqn:
        raise ValueError("table_fqn is required for Databricks lineage observation")
    if not source_identifier:
        raise ValueError("source_identifier is required for Databricks lineage observation")

    observed_at = captured_at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")

    evidence: list[ObservedLineageEvidence] = []
    availability: list[ObservedLineageAvailability] = []

    _collect(
        cursor=cursor,
        query=_TABLE_LINEAGE_QUERY,
        table_fqn=table_fqn,
        evidence_type=ObservedLineageEvidenceType.TABLE,
        mapper=_map_table_lineage,
        evidence=evidence,
        availability=availability,
    )
    _collect(
        cursor=cursor,
        query=_COLUMN_LINEAGE_QUERY,
        table_fqn=table_fqn,
        evidence_type=ObservedLineageEvidenceType.COLUMN,
        mapper=_map_column_lineage,
        evidence=evidence,
        availability=availability,
    )
    _collect(
        cursor=cursor,
        query=_QUERY_EVIDENCE_QUERY,
        table_fqn=table_fqn,
        evidence_type=ObservedLineageEvidenceType.QUERY,
        mapper=_map_query_evidence,
        evidence=evidence,
        availability=availability,
    )

    return ObservedLineageResult(
        platform=DATABRICKS_PLATFORM,
        source_identifier=source_identifier.rstrip("/"),
        target_reference=table_fqn,
        captured_at=observed_at,
        evidence=normalize_lineage_evidence(evidence),
        availability=tuple(sorted(availability, key=lambda item: item.evidence_type.value)),
    )


def _collect(
    *,
    cursor: _SqlCursorLike,
    query: str,
    table_fqn: str,
    evidence_type: ObservedLineageEvidenceType,
    mapper: Any,
    evidence: list[ObservedLineageEvidence],
    availability: list[ObservedLineageAvailability],
) -> None:
    try:
        cursor.execute(query, (table_fqn, table_fqn))
        rows = cursor.fetchall()
    except Exception as exc:
        availability.append(
            ObservedLineageAvailability(
                evidence_type=evidence_type,
                status=ObservedEvidenceAvailabilityStatus.UNAVAILABLE,
                detail=f"Databricks lineage surface unavailable: {type(exc).__name__}",
            )
        )
        return

    evidence.extend(item for row in rows for item in [mapper(row)] if item is not None)
    availability.append(
        ObservedLineageAvailability(
            evidence_type=evidence_type,
            status=ObservedEvidenceAvailabilityStatus.AVAILABLE,
        )
    )


def _map_table_lineage(row: object) -> ObservedLineageEvidence | None:
    source_reference = _text(_row_value(row, "source_table_full_name"))
    target_reference = _text(_row_value(row, "target_table_full_name"))
    if source_reference is None and target_reference is None:
        return None
    return _lineage_evidence(
        evidence_type=ObservedLineageEvidenceType.TABLE,
        row=row,
        source_reference=source_reference,
        target_reference=target_reference,
    )


def _map_column_lineage(row: object) -> ObservedLineageEvidence | None:
    source_reference = _text(_row_value(row, "source_table_full_name"))
    target_reference = _text(_row_value(row, "target_table_full_name"))
    source_property = _text(_row_value(row, "source_column_name"))
    target_property = _text(_row_value(row, "target_column_name"))
    if source_reference is None and target_reference is None:
        return None
    if source_property is None and target_property is None:
        return None
    return _lineage_evidence(
        evidence_type=ObservedLineageEvidenceType.COLUMN,
        row=row,
        source_reference=source_reference,
        source_property=source_property,
        target_reference=target_reference,
        target_property=target_property,
    )


def _map_query_evidence(row: object) -> ObservedLineageEvidence | None:
    statement_reference = _text(_row_value(row, "statement_id"))
    statement_text = _text(_row_value(row, "statement_text"))
    if statement_reference is None and statement_text is None:
        return None
    return _lineage_evidence(
        evidence_type=ObservedLineageEvidenceType.QUERY,
        row=row,
        source_reference=_text(_row_value(row, "source_table_full_name")),
        target_reference=_text(_row_value(row, "target_table_full_name")),
        statement_reference=statement_reference,
        statement_text=statement_text,
        statement_type=_text(_row_value(row, "statement_type")),
    )


def _lineage_evidence(
    *,
    evidence_type: ObservedLineageEvidenceType,
    row: object,
    source_reference: str | None,
    target_reference: str | None,
    source_property: str | None = None,
    target_property: str | None = None,
    statement_reference: str | None = None,
    statement_text: str | None = None,
    statement_type: str | None = None,
) -> ObservedLineageEvidence:
    execution_reference = statement_reference or _text(_row_value(row, "statement_id"))
    return ObservedLineageEvidence(
        evidence_type=evidence_type,
        source_asset=_asset_identity(source_reference),
        source_reference=source_reference,
        source_property=source_property,
        target_asset=_asset_identity(target_reference),
        target_reference=target_reference,
        target_property=target_property,
        statement_reference=statement_reference,
        statement_text=statement_text,
        statement_type=statement_type,
        capture_context=ObservedLineageCaptureContext(
            event_reference=(
                _text(_row_value(row, "event_id"))
                or _text(_row_value(row, "record_id"))
            ),
            recorded_at=_datetime(_row_value(row, "event_time")),
            actor_reference=_text(_row_value(row, "created_by")),
            execution_reference=execution_reference,
            direct=_bool_or_none(_row_value(row, "direct_access")),
        ),
        provenance=UNITY_LINEAGE_PROVENANCE,
    )


def _asset_identity(reference: str | None) -> ObservedAssetIdentity | None:
    if reference is None:
        return None
    parts = tuple(part.strip() for part in reference.split("."))
    if len(parts) != 3 or not all(parts):
        return None
    return ObservedAssetIdentity(
        platform=DATABRICKS_PLATFORM,
        namespace=(parts[0], parts[1]),
        asset=parts[2],
    )


def _row_value(row: object, name: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None
