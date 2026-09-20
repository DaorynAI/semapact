"""Resolve exact deployment approval evidence from immutable approval history."""

from __future__ import annotations

from semapact.approval import ApprovalRecord
from semapact.application.models.deployment_workflow import DeploymentBundle
from semapact.contractops import ReviewEvidenceAction
from semapact.governance import GovernanceOperation
from semapact.history import ApprovalHistoryRepository


class DeploymentApprovalResolver:
    """Select exact APPROVE evidence for one immutable DeploymentBundle.

    History persistence remains storage-only. This resolver owns the deployment-specific
    selection rule: an approval must match the exact ContractOps context, DEPLOY scope,
    deployment plan, and bundle digest. Multiple exact approvals are equivalent for
    authorization; selection is deterministic by canonical approval identity.
    """

    def __init__(self, approvals: ApprovalHistoryRepository) -> None:
        self._approvals = approvals

    def resolve(self, bundle: DeploymentBundle) -> ApprovalRecord | None:
        records = self._approvals.list_approval_records_for_context(
            decision_id=bundle.decision.decision_id,
            change_set_id=bundle.change_set.change_set_id,
            release_plan_id=bundle.release_plan.release_plan_id,
            version_resolution_id=bundle.version_resolution.version_resolution_id,
            operation=GovernanceOperation.DEPLOY,
        )
        matches = tuple(
            record
            for record in records
            if record.action is ReviewEvidenceAction.APPROVE
            and record.scope_reference
            == bundle.deployment_plan.deployment_plan_id
            and bundle.bundle_digest in record.evidence_references
        )
        if not matches:
            return None
        return min(matches, key=lambda record: record.approval_id)
