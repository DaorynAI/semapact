"""Deterministic identity rules for immutable governance approval records."""

from __future__ import annotations

import uuid

from semapact.approval.models import ApprovalRecord
from semapact.utils.deterministic import deterministic_uuid5


SEMAPACT_APPROVAL_RECORD_NAMESPACE = uuid.UUID(
    "c0e1984e-8674-5705-bbfd-2784f6e90e6a"
)


def compute_approval_record_id(record: ApprovalRecord) -> str:
    """Return the stable UUIDv5 identity for one canonical approval event."""
    if not isinstance(record, ApprovalRecord):
        raise TypeError(
            f"record must be ApprovalRecord, got {type(record).__name__}"
        )
    return deterministic_uuid5(
        SEMAPACT_APPROVAL_RECORD_NAMESPACE,
        {
            "decisionId": record.decision_id,
            "changeSetId": record.change_set_id,
            "releasePlanId": record.release_plan_id,
            "versionResolutionId": record.version_resolution_id,
            "operation": record.operation.value,
            "action": record.action.value,
            "actorReference": record.actor_reference,
            "recordedAt": record.recorded_at.isoformat(),
            "scopeReference": record.scope_reference,
            "capabilityReference": record.capability_reference,
            "comment": record.comment,
            "evidenceReferences": list(record.evidence_references),
        },
    )


def validate_approval_record_identity(record: ApprovalRecord) -> None:
    """Fail if approval_id does not match the complete canonical event payload."""
    expected = compute_approval_record_id(record)
    if expected != record.approval_id:
        raise ValueError("approval_id does not match deterministic approval identity")
