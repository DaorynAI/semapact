"""Canonical contract-first deployment workflow orchestration."""

from __future__ import annotations

from datetime import date, datetime

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.application.models.deployment_workflow import (
    DeploymentBundle,
    DeploymentExecutionResult,
    build_deployment_bundle,
)
from semapact.application.services.deployment import DeploymentService
from semapact.application.services.release_planning import ReleasePlanningService
from semapact.approval import (
    ApprovalRecord,
    build_approval_record,
    project_review_authorization_evidence,
)
from semapact.contractops import (
    ReviewEvidenceAction,
    authorize_contract_operation,
    build_release_snapshot,
)
from semapact.deployment import (
    DeploymentAdapter,
    DeploymentTarget,
    authorize_deployment,
)
from semapact.exceptions import ContractOpsAuthorizationError, ValidationError
from semapact.governance import DecisionResult, GovernanceOperation
from semapact.reconciliation import classify_reconciliation_status


class DeploymentWorkflowService:
    """Compose release planning and runtime assessment without inventing authority."""

    def __init__(
        self,
        *,
        release_planning_service: ReleasePlanningService | None = None,
        deployment_service: DeploymentService | None = None,
    ) -> None:
        self._release_planning = release_planning_service or ReleasePlanningService()
        self._deployment = deployment_service or DeploymentService()

    def assess(
        self,
        base_contract: OpenDataContractStandard,
        candidate_contract: OpenDataContractStandard,
        *,
        effective_date: date | str,
        base_revision_ref: str,
        candidate_revision_ref: str,
        target: DeploymentTarget,
        adapter: DeploymentAdapter,
        authority_reference: str | None = None,
    ) -> DeploymentBundle:
        """Build the immutable CI handoff bundle without side-effect authorization."""
        release = self._release_planning.plan(
            base_contract,
            candidate_contract,
            effective_date=effective_date,
            base_revision_ref=base_revision_ref,
            candidate_revision_ref=candidate_revision_ref,
            authority_reference=authority_reference,
        )
        snapshot = build_release_snapshot(
            candidate_contract,
            candidate_revision_ref=candidate_revision_ref,
            decision=release.decision,
            change_set=release.change_set,
            release_plan=release.release_plan,
            version_resolution=release.version_resolution,
        )
        plan = self._deployment.plan(snapshot, target)
        preview = self._deployment.preview(plan, adapter=adapter)
        return build_deployment_bundle(
            decision=release.decision,
            change_set=release.change_set,
            release_plan=release.release_plan,
            version_resolution=release.version_resolution,
            release_snapshot=snapshot,
            deployment_plan=plan,
            review_preview=preview,
        )

    def approve(
        self,
        bundle: DeploymentBundle,
        *,
        actor_reference: str,
        recorded_at: datetime,
        comment: str | None = None,
    ) -> ApprovalRecord:
        """Record an explicit human DEPLOY approval for one exact bundle."""
        if bundle.decision.decision is not DecisionResult.REVIEW:
            raise ValidationError(
                "Explicit deployment approval is only required for REVIEW decisions"
            )
        return build_approval_record(
            decision_id=bundle.decision.decision_id,
            change_set_id=bundle.change_set.change_set_id,
            release_plan_id=bundle.release_plan.release_plan_id,
            version_resolution_id=bundle.version_resolution.version_resolution_id,
            operation=GovernanceOperation.DEPLOY,
            action=ReviewEvidenceAction.APPROVE,
            actor_reference=actor_reference,
            recorded_at=recorded_at,
            scope_reference=bundle.deployment_plan.deployment_plan_id,
            comment=comment,
            evidence_references=(bundle.bundle_digest,),
        )

    def deploy(
        self,
        bundle: DeploymentBundle,
        *,
        adapter: DeploymentAdapter,
        approval: ApprovalRecord | None = None,
    ) -> DeploymentExecutionResult:
        """Consume one exact bundle, authorize, fresh-preview, execute, and verify."""
        if not isinstance(bundle, DeploymentBundle):
            raise TypeError(
                f"bundle must be DeploymentBundle, got {type(bundle).__name__}"
            )

        evidence = None
        if bundle.decision.decision is DecisionResult.REVIEW:
            if approval is None:
                raise ContractOpsAuthorizationError(
                    "Deployment requires approval for a REVIEW governance decision"
                )
            if bundle.bundle_digest not in approval.evidence_references:
                raise ValidationError(
                    "ApprovalRecord does not reference the exact DeploymentBundle digest"
                )
            evidence = project_review_authorization_evidence(approval)

        contract_authorization = authorize_contract_operation(
            bundle.decision,
            bundle.change_set,
            bundle.release_plan,
            bundle.version_resolution,
            GovernanceOperation.DEPLOY,
            evidence=evidence,
        )
        if not contract_authorization.allowed:
            raise ContractOpsAuthorizationError(
                "Deployment is not authorized: "
                f"{contract_authorization.reason.value}"
            )

        deployment_authorization = authorize_deployment(
            bundle.deployment_plan,
            bundle.release_snapshot,
            contract_authorization,
        )

        # CI-time review preview is evidence only. CD always derives a fresh preview.
        fresh_preview = self._deployment.preview(
            bundle.deployment_plan,
            adapter=adapter,
        )
        self._deployment.execute(
            bundle.deployment_plan,
            fresh_preview,
            deployment_authorization,
            adapter=adapter,
        )
        reconciliation = self._deployment.verify(
            bundle.deployment_plan,
            adapter=adapter,
        )
        status = classify_reconciliation_status(reconciliation)

        return DeploymentExecutionResult(
            bundle_digest=bundle.bundle_digest,
            deployment_plan_id=bundle.deployment_plan.deployment_plan_id,
            authorization_id=contract_authorization.authorization_id,
            fresh_preview=fresh_preview,
            reconciliation=reconciliation,
            status=status,
            review_preview_changed=fresh_preview != bundle.review_preview,
        )

