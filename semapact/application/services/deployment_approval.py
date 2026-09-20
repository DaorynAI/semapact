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
    selection rule: evidence must match the exact ContractOps context, DEPLOY scope,
    deployment plan, and bundle digest. Conflicting exact review actions fail closed.
    Multiple exact APPROVE records are equivalent for authorization; selection is
    deterministic by canonical approval identity.
    """

    def __init__(self, approvals: ApprovalHistoryRepository) -> None:
        self._approvals = approvals

    def resolve(self, bundle: DeploymentBundle) -> ApprovalRecord | None:
        if not bundle.release:
            return None
        if bundle.release_plan is None or bundle.version_resolution is None:
            return None
        records = self._approvals.list_approval_records_for_context(
            decision_id=bundle.decision.decision_id,
            change_set_id=bundle.change_set.change_set_id,
            release_plan_id=bundle.release_plan.release_plan_id,
            version_resolution_id=bundle.version_resolution.version_resolution_id,
            operation=GovernanceOperation.DEPLOY,
        )
        scoped = tuple(
            record
            for record in records
            if record.scope_reference
            == bundle.deployment_plan.deployment_plan_id
            and bundle.bundle_digest in record.evidence_references
        )
        if not scoped:
            return None
        if any(
            record.action is not ReviewEvidenceAction.APPROVE
            for record in scoped
        ):
            return None
        return min(scoped, key=lambda record: record.approval_id)
