"""Lossless projection from durable ApprovalRecord to M2 review evidence."""

from __future__ import annotations

from semapact.approval.integrity import validate_approval_record_identity
from semapact.approval.models import ApprovalRecord
from semapact.contractops.models import ReviewAuthorizationEvidence


def project_review_authorization_evidence(
    record: ApprovalRecord,
) -> ReviewAuthorizationEvidence:
    """Project one selected durable approval into the existing M2 evidence contract.

    Selection/routing/quorum policy is deliberately outside this function. M2 remains
    responsible for matching this evidence against the exact requested release context.
    """
    if not isinstance(record, ApprovalRecord):
        raise TypeError(
            f"record must be ApprovalRecord, got {type(record).__name__}"
        )
    validate_approval_record_identity(record)
    return ReviewAuthorizationEvidence(
        evidence_reference=record.approval_id,
        decision_id=record.decision_id,
        change_set_id=record.change_set_id,
        release_plan_id=record.release_plan_id,
        version_resolution_id=record.version_resolution_id,
        operation=record.operation,
        action=record.action,
        scope_reference=record.scope_reference,
    )
