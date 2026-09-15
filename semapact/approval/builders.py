"""Canonical construction of immutable approval records."""

from __future__ import annotations

from datetime import datetime

from semapact.approval.integrity import compute_approval_record_id
from semapact.approval.models import ApprovalRecord
from semapact.contractops.models import ReviewEvidenceAction
from semapact.governance.gate import GovernanceOperation


def build_approval_record(
    *,
    decision_id: str,
    change_set_id: str,
    release_plan_id: str,
    version_resolution_id: str,
    operation: GovernanceOperation,
    action: ReviewEvidenceAction,
    actor_reference: str,
    recorded_at: datetime,
    scope_reference: str | None = None,
    capability_reference: str | None = None,
    comment: str | None = None,
    evidence_references: tuple[str, ...] = (),
) -> ApprovalRecord:
    """Build one canonical approval event and derive its deterministic identity."""
    provisional = ApprovalRecord(
        approval_id="pending",
        decision_id=decision_id,
        change_set_id=change_set_id,
        release_plan_id=release_plan_id,
        version_resolution_id=version_resolution_id,
        operation=operation,
        action=action,
        actor_reference=actor_reference,
        recorded_at=recorded_at,
        scope_reference=scope_reference,
        capability_reference=capability_reference,
        comment=comment,
        evidence_references=evidence_references,
    )
    approval_id = compute_approval_record_id(provisional)
    payload = provisional.model_dump(exclude={"approval_id"})
    return ApprovalRecord(approval_id=approval_id, **payload)
