"""Application workflow for target-neutral formal contract releases."""

from __future__ import annotations

from datetime import datetime

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.approval import ApprovalRecord, build_approval_record
from semapact.approval.evidence import project_review_authorization_evidence
from semapact.application.models.release import (
    ReleaseBundle,
    build_contract_release,
    build_release_bundle,
)
from semapact.application.services.release_planning import ReleasePlanningService
from semapact.contractops import (
    ContractRelease,
    ReviewEvidenceAction,
    authorize_contract_operation,
    build_release_snapshot,
)
from semapact.exceptions import ContractOpsAuthorizationError, ValidationError
from semapact.governance import DecisionResult, GovernanceOperation


class ReleaseWorkflowService:
    """Assess and approve target-neutral formal contract releases."""

    def __init__(
        self,
        *,
        planning_service: ReleasePlanningService | None = None,
    ) -> None:
        self._planning = planning_service or ReleasePlanningService()

    def assess(
        self,
        base_contract: OpenDataContractStandard,
        candidate_contract: OpenDataContractStandard,
        *,
        base_revision_ref: str,
        candidate_revision_ref: str,
        authority_reference: str | None = None,
    ) -> ReleaseBundle:
        """Build one immutable target-neutral formal release bundle."""
        planning = self._planning.plan(
            base_contract,
            candidate_contract,
            base_revision_ref=base_revision_ref,
            candidate_revision_ref=candidate_revision_ref,
            authority_reference=authority_reference,
        )
        snapshot = build_release_snapshot(
            candidate_contract,
            candidate_revision_ref=candidate_revision_ref,
            decision=planning.decision,
            change_set=planning.change_set,
            release_plan=planning.release_plan,
            version_resolution=planning.version_resolution,
        )
        return build_release_bundle(
            decision=planning.decision,
            change_set=planning.change_set,
            release_plan=planning.release_plan,
            version_resolution=planning.version_resolution,
            release_snapshot=snapshot,
        )

    def approve(
        self,
        bundle: ReleaseBundle,
        *,
        actor_reference: str,
        recorded_at: datetime,
        comment: str | None = None,
    ) -> ApprovalRecord:
        """Create explicit approval evidence for custom/manual REVIEW workflows."""
        if bundle.decision.decision is not DecisionResult.REVIEW:
            raise ValidationError(
                "Explicit release approval is only required for REVIEW releases"
            )
        return build_approval_record(
            decision_id=bundle.decision.decision_id,
            change_set_id=bundle.change_set.change_set_id,
            release_plan_id=bundle.release_plan.release_plan_id,
            version_resolution_id=bundle.version_resolution.version_resolution_id,
            operation=GovernanceOperation.PUBLISH,
            action=ReviewEvidenceAction.APPROVE,
            actor_reference=actor_reference,
            recorded_at=recorded_at,
            scope_reference=bundle.release_snapshot.release_snapshot_id,
            comment=comment,
            evidence_references=(bundle.bundle_digest,),
        )


class ReleaseFinalizer:
    """Authorize one exact ReleaseBundle and construct its ContractRelease fact."""

    def finalize(
        self,
        bundle: ReleaseBundle,
        *,
        approval: ApprovalRecord | None = None,
    ) -> ContractRelease:
        """Finalize domain state without persisting or materializing projections."""
        evidence = None
        if bundle.decision.decision is DecisionResult.REVIEW:
            if approval is None:
                raise ContractOpsAuthorizationError(
                    "Formal release requires approval for REVIEW"
                )
            if approval.scope_reference != bundle.release_snapshot.release_snapshot_id:
                raise ValidationError(
                    "ApprovalRecord is not scoped to the exact ReleaseSnapshot"
                )
            if bundle.bundle_digest not in approval.evidence_references:
                raise ValidationError(
                    "ApprovalRecord does not reference the exact ReleaseBundle digest"
                )
            evidence = project_review_authorization_evidence(approval)
        elif approval is not None:
            raise ValidationError("ALLOW release does not consume an ApprovalRecord")

        authorization = authorize_contract_operation(
            bundle.decision,
            bundle.change_set,
            bundle.release_plan,
            bundle.version_resolution,
            GovernanceOperation.PUBLISH,
            evidence=evidence,
        )
        if not authorization.allowed:
            raise ContractOpsAuthorizationError(
                "Formal release is not authorized: "
                f"{authorization.reason.value}"
            )
        return build_contract_release(bundle)
