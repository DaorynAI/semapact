"""Application service for formal contract release ledger persistence."""

from __future__ import annotations

from semapact.approval import ApprovalRecord
from semapact.application.models.release import ReleaseBundle
from semapact.contractops import ContractRelease
from semapact.contractops.integrity import compute_contract_release_id
from semapact.governance import DecisionResult, GovernanceOperation
from semapact.history import ContractReleaseHistoryRepository


class ContractReleaseHistoryService:
    """Persist one target-neutral formal release fact."""

    def __init__(self, releases: ContractReleaseHistoryRepository) -> None:
        self._releases = releases

    def record_release(
        self,
        bundle: ReleaseBundle,
        *,
        approval: ApprovalRecord | None,
    ) -> ContractRelease:
        """Persist one finalized release, idempotently, after exact review validation."""
        if bundle.decision.decision is DecisionResult.REVIEW:
            if approval is None:
                raise ValueError("REVIEW release history requires exact approval")
            if approval.operation is not GovernanceOperation.PUBLISH:
                raise ValueError("Release approval must be PUBLISH-scoped")
            if approval.scope_reference != bundle.release_snapshot.release_snapshot_id:
                raise ValueError(
                    "Release approval is not scoped to exact ReleaseSnapshot"
                )
            if bundle.bundle_digest not in approval.evidence_references:
                raise ValueError(
                    "Release approval does not reference exact ReleaseBundle digest"
                )
        elif approval is not None:
            raise ValueError("ALLOW release does not require ApprovalRecord")

        snapshot = bundle.release_snapshot
        resolution = bundle.version_resolution
        record_id = compute_contract_release_id(
            contract_id=snapshot.contract_id,
            contract_version=snapshot.selected_version,
            decision_id=bundle.decision.decision_id,
            change_set_id=bundle.change_set.change_set_id,
            release_plan_id=bundle.release_plan.release_plan_id,
            version_resolution_id=resolution.version_resolution_id,
            release_snapshot_id=snapshot.release_snapshot_id,
            source_revision_ref=snapshot.release_revision_ref,
            released_contract_json=snapshot.released_contract_json,
        )
        record = ContractRelease(
            contract_release_id=record_id,
            contract_id=snapshot.contract_id,
            contract_version=snapshot.selected_version,
            decision_id=bundle.decision.decision_id,
            change_set_id=bundle.change_set.change_set_id,
            release_plan_id=bundle.release_plan.release_plan_id,
            version_resolution_id=resolution.version_resolution_id,
            release_snapshot_id=snapshot.release_snapshot_id,
            source_revision_ref=snapshot.release_revision_ref,
            released_contract_json=snapshot.released_contract_json,
        )
        self._releases.put_contract_release(record)
        return record
