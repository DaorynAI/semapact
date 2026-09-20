"""Resolve exact formal-release approval from immutable approval history."""

from __future__ import annotations

from semapact.approval import ApprovalRecord
from semapact.application.models.release import ReleaseBundle
from semapact.contractops import ReviewEvidenceAction
from semapact.governance import GovernanceOperation
from semapact.history import ApprovalHistoryRepository


class ReleaseApprovalResolver:
    """Resolve exact PUBLISH approval for one immutable ReleaseBundle."""

    def __init__(self, approvals: ApprovalHistoryRepository) -> None:
        self._approvals = approvals

    def resolve(self, bundle: ReleaseBundle) -> ApprovalRecord | None:
        records = self._approvals.list_approval_records_for_context(
            decision_id=bundle.decision.decision_id,
            change_set_id=bundle.change_set.change_set_id,
            release_plan_id=bundle.release_plan.release_plan_id,
            version_resolution_id=bundle.version_resolution.version_resolution_id,
            operation=GovernanceOperation.PUBLISH,
        )
        scoped = tuple(
            record
            for record in records
            if record.scope_reference == bundle.release_snapshot.release_snapshot_id
            and bundle.bundle_digest in record.evidence_references
        )
        if not scoped:
            return None
        if any(record.action is not ReviewEvidenceAction.APPROVE for record in scoped):
            return None
        return min(scoped, key=lambda record: record.approval_id)
