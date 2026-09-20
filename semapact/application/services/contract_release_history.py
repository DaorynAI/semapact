"""Application service for formal contract release ledger persistence."""

from __future__ import annotations

from semapact.approval import ApprovalRecord
from semapact.application.models.deployment_workflow import DeploymentBundle
from semapact.governance import DecisionResult, GovernanceOperation
from semapact.history import ContractReleaseHistoryRepository, ContractReleaseRecord
from semapact.history.integrity import compute_contract_release_record_id


class ContractReleaseHistoryService:
    """Persist one formal release fact without coupling release to runtime telemetry."""

    def __init__(self, releases: ContractReleaseHistoryRepository) -> None:
        self._releases = releases

    def record_release(
        self,
        bundle: DeploymentBundle,
        *,
        approval: ApprovalRecord | None,
    ) -> ContractReleaseRecord:
        if not bundle.release:
            raise ValueError("Non-release bundle cannot create contract release history")
        if (
            bundle.release_plan is None
            or bundle.version_resolution is None
            or bundle.release_snapshot is None
        ):
            raise ValueError("Release bundle is missing release planning artifacts")

        if bundle.decision.decision is DecisionResult.REVIEW:
            if approval is None:
                raise ValueError("REVIEW release history requires exact approval")
            if approval.operation is not GovernanceOperation.DEPLOY:
                raise ValueError("Release approval must be DEPLOY-scoped")
            if approval.scope_reference != bundle.deployment_plan.deployment_plan_id:
                raise ValueError(
                    "Release approval is not scoped to exact DeploymentPlan"
                )
            if bundle.bundle_digest not in approval.evidence_references:
                raise ValueError(
                    "Release approval does not reference exact bundle digest"
                )
        elif approval is not None:
            raise ValueError("ALLOW release does not require ApprovalRecord")

        snapshot = bundle.release_snapshot
        resolution = bundle.version_resolution
        record_id = compute_contract_release_record_id(
            contract_id=snapshot.contract_id,
            contract_version=snapshot.selected_version,
            decision_id=bundle.decision.decision_id,
            change_set_id=bundle.change_set.change_set_id,
            release_plan_id=bundle.release_plan.release_plan_id,
            version_resolution_id=resolution.version_resolution_id,
            release_snapshot_id=snapshot.release_snapshot_id,
            revision_ref=snapshot.release_revision_ref,
            released_contract_json=snapshot.released_contract_json,
        )
        record = ContractReleaseRecord(
            contract_release_id=record_id,
            contract_id=snapshot.contract_id,
            contract_version=snapshot.selected_version,
            decision_id=bundle.decision.decision_id,
            change_set_id=bundle.change_set.change_set_id,
            release_plan_id=bundle.release_plan.release_plan_id,
            version_resolution_id=resolution.version_resolution_id,
            release_snapshot_id=snapshot.release_snapshot_id,
            revision_ref=snapshot.release_revision_ref,
            released_contract_json=snapshot.released_contract_json,
        )
        self._releases.put_contract_release(record)
        return record
