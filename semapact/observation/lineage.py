"""Platform-neutral lineage evidence for runtime governance observation.

Lineage is event evidence spanning assets, not canonical contract identity and not
part of the point-in-time physical-state fingerprint. Providers normalize their
native lineage records into these immutable models without mutating ODCS state.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Iterable

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from semapact.observation.evidence import ObservedEvidenceAvailabilityStatus
from semapact.observation.models import ObservedAssetIdentity


class ObservedLineageEvidenceType(str, Enum):
    """Kinds of lineage evidence that must remain distinguishable."""

    TABLE = "TABLE"
    COLUMN = "COLUMN"
    QUERY = "QUERY"


class ObservedLineageCaptureContext(BaseModel):
    """Provider-neutral execution context attached to one lineage event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_reference: str | None = None
    recorded_at: datetime | None = None
    actor_reference: str | None = None
    execution_reference: str | None = None
    direct: bool | None = None

    @field_validator("event_reference", "actor_reference", "execution_reference")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("recorded_at")
    @classmethod
    def _require_aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("lineage recorded_at must be timezone-aware")
        return value


class ObservedLineageEvidence(BaseModel):
    """One normalized lineage edge or query/transformation evidence record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_type: ObservedLineageEvidenceType
    source_asset: ObservedAssetIdentity | None = None
    source_reference: str | None = None
    source_property: str | None = None
    target_asset: ObservedAssetIdentity | None = None
    target_reference: str | None = None
    target_property: str | None = None
    statement_reference: str | None = None
    statement_text: str | None = None
    statement_type: str | None = None
    capture_context: ObservedLineageCaptureContext = ObservedLineageCaptureContext()
    provenance: str | None = None

    @field_validator(
        "source_reference",
        "source_property",
        "target_reference",
        "target_property",
        "statement_reference",
        "statement_text",
        "statement_type",
        "provenance",
    )
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def _validate_semantics(self) -> ObservedLineageEvidence:
        if self.source_asset is None and self.source_reference is None and self.target_asset is None and self.target_reference is None:
            raise ValueError("lineage evidence must identify a source or target")
        if self.evidence_type is ObservedLineageEvidenceType.TABLE:
            if self.source_property is not None or self.target_property is not None:
                raise ValueError("table lineage must not carry property identity")
        elif self.evidence_type is ObservedLineageEvidenceType.COLUMN:
            if self.source_property is None and self.target_property is None:
                raise ValueError("column lineage must identify a source or target property")
        elif self.evidence_type is ObservedLineageEvidenceType.QUERY:
            if self.statement_reference is None and self.statement_text is None:
                raise ValueError("query lineage must identify a statement reference or text")
        return self


class ObservedLineageAvailability(BaseModel):
    """Availability of one lineage evidence kind for a provider read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_type: ObservedLineageEvidenceType
    status: ObservedEvidenceAvailabilityStatus
    detail: str | None = None

    @field_validator("detail")
    @classmethod
    def _normalize_detail(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ObservedLineageResult(BaseModel):
    """Deterministic auxiliary lineage evidence collected for one runtime asset."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    platform: str
    source_identifier: str
    target_reference: str
    captured_at: datetime
    evidence: tuple[ObservedLineageEvidence, ...] = ()
    availability: tuple[ObservedLineageAvailability, ...] = ()

    @field_validator("platform", "source_identifier", "target_reference")
    @classmethod
    def _require_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("lineage result identity fields must not be empty")
        return cleaned

    @field_validator("captured_at")
    @classmethod
    def _require_aware_capture_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("lineage captured_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_platform_and_availability(self) -> ObservedLineageResult:
        platform = self.platform.casefold()
        for item in self.evidence:
            for asset in (item.source_asset, item.target_asset):
                if asset is not None and asset.platform.casefold() != platform:
                    raise ValueError("lineage asset platform must match result platform")
        kinds = [item.evidence_type for item in self.availability]
        if len(kinds) != len(set(kinds)):
            raise ValueError("lineage availability must contain each evidence type at most once")
        return self


def canonical_lineage_evidence_payload(item: ObservedLineageEvidence) -> dict[str, object]:
    """Return provider-neutral canonical content for one lineage record."""

    source_asset = item.source_asset
    target_asset = item.target_asset
    context = item.capture_context
    return {
        "evidence_type": item.evidence_type.value,
        "source_asset": list(source_asset.canonical_key) if source_asset is not None else None,
        "source_reference": None if source_asset is not None else _normalize_reference(item.source_reference),
        "source_property": _normalize_identifier(item.source_property),
        "target_asset": list(target_asset.canonical_key) if target_asset is not None else None,
        "target_reference": None if target_asset is not None else _normalize_reference(item.target_reference),
        "target_property": _normalize_identifier(item.target_property),
        "statement_reference": _normalize_text(item.statement_reference),
        "statement_text": _normalize_text(item.statement_text),
        "statement_type": _normalize_identifier(item.statement_type),
        "capture_context": {
            "event_reference": _normalize_text(context.event_reference),
            "recorded_at": context.recorded_at.isoformat() if context.recorded_at is not None else None,
            "actor_reference": _normalize_text(context.actor_reference),
            "execution_reference": _normalize_text(context.execution_reference),
            "direct": context.direct,
        },
        "provenance": _normalize_text(item.provenance),
    }


def canonical_lineage_evidence_key(item: ObservedLineageEvidence) -> str:
    return json.dumps(
        canonical_lineage_evidence_payload(item),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def normalize_lineage_evidence(
    evidence: Iterable[ObservedLineageEvidence],
) -> tuple[ObservedLineageEvidence, ...]:
    """Deduplicate and deterministically order normalized lineage evidence."""

    unique = {canonical_lineage_evidence_key(item): item for item in evidence}
    return tuple(unique[key] for key in sorted(unique))


def serialize_observed_lineage_result(result: ObservedLineageResult) -> str:
    """Serialize lineage evidence deterministically without redefining state fingerprinting."""

    evidence = [canonical_lineage_evidence_payload(item) for item in result.evidence]
    evidence.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    availability = sorted(
        (
            {
                "evidence_type": item.evidence_type.value,
                "status": item.status.value,
                "detail": item.detail,
            }
            for item in result.availability
        ),
        key=lambda item: str(item["evidence_type"]),
    )
    payload = {
        "platform": result.platform.casefold(),
        "source_identifier": result.source_identifier.rstrip("/"),
        "target_reference": _normalize_reference(result.target_reference),
        "captured_at": result.captured_at.isoformat(),
        "evidence": evidence,
        "availability": availability,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _normalize_reference(value: str | None) -> str | None:
    cleaned = _normalize_text(value)
    return cleaned.casefold() if cleaned is not None else None


def _normalize_identifier(value: str | None) -> str | None:
    cleaned = _normalize_text(value)
    return cleaned.casefold() if cleaned is not None else None


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
