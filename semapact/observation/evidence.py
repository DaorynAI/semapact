"""Provider-neutral evidence taxonomy and observation availability semantics."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator


class ObservedEvidenceClass(str, Enum):
    """Descriptive class for observed evidence, never a governance verdict."""

    STRUCTURAL = "STRUCTURAL"
    SEMANTIC = "SEMANTIC"
    OPERATIONAL = "OPERATIONAL"


class ObservedEvidenceKind(str, Enum):
    """Provider-neutral kinds of evidence carried by an observation."""

    PHYSICAL_SCHEMA = "PHYSICAL_SCHEMA"
    OWNER = "OWNER"
    COMMENT = "COMMENT"
    TAG = "TAG"
    CONSTRAINT = "CONSTRAINT"
    RELATIONSHIP = "RELATIONSHIP"


class ObservedEvidenceAvailabilityStatus(str, Enum):
    """Whether a provider observation could establish one evidence kind."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class ObservedEvidenceAvailability(BaseModel):
    """Availability state for one provider-neutral evidence kind."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ObservedEvidenceKind
    status: ObservedEvidenceAvailabilityStatus
    detail: str | None = None

    @field_validator("detail")
    @classmethod
    def _normalize_detail(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


def resolve_evidence_availability(
    entries: tuple[ObservedEvidenceAvailability, ...],
    kind: ObservedEvidenceKind,
) -> ObservedEvidenceAvailabilityStatus:
    """Resolve one kind, treating unspecified availability as UNKNOWN."""
    for entry in entries:
        if entry.kind is kind:
            return entry.status
    return ObservedEvidenceAvailabilityStatus.UNKNOWN
