"""Platform-neutral classification and metrics for observed evidence."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from semapact.observation.evidence import (
    ObservedEvidenceAvailabilityStatus,
    ObservedEvidenceClass,
    ObservedEvidenceKind,
    resolve_evidence_availability,
)
from semapact.observation.models import ObservedPlatformState


class ObservationMetricModel(BaseModel):
    """Shared immutable base for derived observation metrics."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ObservedEvidenceCount(ObservationMetricModel):
    """Deterministic count and coverage state for one evidence kind."""

    kind: ObservedEvidenceKind
    evidence_class: ObservedEvidenceClass
    availability: ObservedEvidenceAvailabilityStatus
    count: int = Field(ge=0)


class ObservedEvidenceClassCount(ObservationMetricModel):
    """Deterministic aggregate count for one evidence class."""

    evidence_class: ObservedEvidenceClass
    count: int = Field(ge=0)


class ObservedEvidenceMetrics(ObservationMetricModel):
    """Standard evidence metrics derived from canonical observed state."""

    total: int = Field(ge=0)
    by_kind: tuple[ObservedEvidenceCount, ...]
    by_class: tuple[ObservedEvidenceClassCount, ...]


_EVIDENCE_CLASSES = {
    ObservedEvidenceKind.PHYSICAL_SCHEMA: ObservedEvidenceClass.STRUCTURAL,
    ObservedEvidenceKind.OWNER: ObservedEvidenceClass.OPERATIONAL,
    ObservedEvidenceKind.COMMENT: ObservedEvidenceClass.SEMANTIC,
    ObservedEvidenceKind.TAG: ObservedEvidenceClass.SEMANTIC,
    ObservedEvidenceKind.CONSTRAINT: ObservedEvidenceClass.STRUCTURAL,
    ObservedEvidenceKind.RELATIONSHIP: ObservedEvidenceClass.STRUCTURAL,
}


def classify_observed_evidence(kind: ObservedEvidenceKind) -> ObservedEvidenceClass:
    """Return the descriptive evidence class for one provider-neutral kind."""
    return _EVIDENCE_CLASSES[kind]


def summarize_observed_evidence(state: ObservedPlatformState) -> ObservedEvidenceMetrics:
    """Derive the same evidence metrics for every provider observation.

    ``PHYSICAL_SCHEMA`` counts one item per observed asset plus one item per
    observed property. Other kinds count their canonical evidence objects or
    populated scalar values. Availability is reported independently from count,
    so zero evidence is never confused with unsupported or unknown evidence.
    """
    counts = {kind: 0 for kind in ObservedEvidenceKind}

    for asset in state.assets:
        counts[ObservedEvidenceKind.PHYSICAL_SCHEMA] += 1 + len(asset.properties)
        if asset.owner is not None:
            counts[ObservedEvidenceKind.OWNER] += 1
        if asset.comment is not None:
            counts[ObservedEvidenceKind.COMMENT] += 1

        counts[ObservedEvidenceKind.TAG] += len(asset.tags)
        counts[ObservedEvidenceKind.CONSTRAINT] += len(asset.constraints)
        counts[ObservedEvidenceKind.RELATIONSHIP] += len(asset.relationships)

        for prop in asset.properties:
            if prop.comment is not None:
                counts[ObservedEvidenceKind.COMMENT] += 1
            counts[ObservedEvidenceKind.TAG] += len(prop.tags)

    by_kind = tuple(
        ObservedEvidenceCount(
            kind=kind,
            evidence_class=classify_observed_evidence(kind),
            availability=resolve_evidence_availability(
                state.evidence_availability,
                kind,
            ),
            count=counts[kind],
        )
        for kind in ObservedEvidenceKind
    )

    class_counts = {evidence_class: 0 for evidence_class in ObservedEvidenceClass}
    for metric in by_kind:
        class_counts[metric.evidence_class] += metric.count

    by_class = tuple(
        ObservedEvidenceClassCount(
            evidence_class=evidence_class,
            count=class_counts[evidence_class],
        )
        for evidence_class in ObservedEvidenceClass
    )

    return ObservedEvidenceMetrics(
        total=sum(counts.values()),
        by_kind=by_kind,
        by_class=by_class,
    )
