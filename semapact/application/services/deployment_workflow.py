"""Canonical contract-first deployment workflow orchestration."""

from __future__ import annotations

from datetime import date, datetime, timezone

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.application.models.deployment_workflow import (
    DeploymentBundle,
    DeploymentExecutionResult,
    build_deployment_bundle,
)
from semapact.application.services.contract_release_history import (
    ContractReleaseHistoryService,
)
from semapact.application.services.deployment import DeploymentService
from semapact.application.services.governance import GovernanceService
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
    RuntimeReleaseMetadata,
    RuntimeReleaseMetadataProjector,
    authorize_candidate_deployment,
    authorize_deployment,
    build_candidate_deployment_source,
    build_release_deployment_source,
)
from semapact.exceptions import ContractOpsAuthorizationError, ValidationError
from semapact.governance import DecisionResult, GovernanceOperation
from semapact.history import (
    OperationalHistorySink,
    build_operational_deployment_event,
)
from semapact.reconciliation import RuntimeDriftStatus, classify_reconciliation_status


class DeploymentWorkflowService:
    """Compose release planning and runtime assessment without inventing authority."""

    def __init__(
        self,
        *,
        release_planning_service: ReleasePlanningService | None = None,
        governance_service: GovernanceService | None = None,
        deployment_service: DeploymentService | None = None,
    ) -> None:
        self._release_planning = release_planning_service or ReleasePlanningService()
        self._governance = governance_service or GovernanceService()
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
        release: bool = False,
        authority_reference: str | None = None,
    ) -> DeploymentBundle:
        """Build an immutable candidate or formal-release CI handoff bundle."""
        if release:
            planned = self._release_planning.plan(
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
                decision=planned.decision,
                change_set=planned.change_set,
                release_plan=planned.release_plan,
                version_resolution=planned.version_resolution,
            )
            source = build_release_deployment_source(snapshot)
            decision = planned.decision
            change_set = planned.change_set
            release_plan = planned.release_plan
            version_resolution = planned.version_resolution
        else:
            proposal = self._governance.evaluate_proposal(
                base_contract,
                candidate_contract,
                effective_date=effective_date,
                base_revision_ref=base_revision_ref,
                candidate_revision_ref=candidate_revision_ref,
            )
            source = build_candidate_deployment_source(
                candidate_contract,
                revision_ref=candidate_revision_ref,
            )
            decision = proposal.decision
            change_set = proposal.change_set
            release_plan = None
            version_resolution = None
            snapshot = None

        plan = self._deployment.plan(source, target)
        preview = self._deployment.preview(plan, adapter=adapter)
        return build_deployment_bundle(
            release=release,
            decision=decision,
            change_set=change_set,
            deployment_source=source,
            deployment_plan=plan,
            review_preview=preview,
            release_plan=release_plan,
            version_resolution=version_resolution,
            release_snapshot=snapshot,
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
        if not bundle.release:
            raise ValidationError(
                "Non-release deployment does not create approval records"
            )
        if bundle.decision.decision is not DecisionResult.REVIEW:
            raise ValidationError(
                "Explicit deployment approval is only required for REVIEW releases"
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
        release_history: ContractReleaseHistoryService | None = None,
        operational_history: OperationalHistorySink | None = None,
        metadata_projector: RuntimeReleaseMetadataProjector | None = None,
    ) -> DeploymentExecutionResult:
        """Consume one exact bundle, authorize, deploy, verify, and persist configured facts."""
        if not isinstance(bundle, DeploymentBundle):
            raise TypeError(
                f"bundle must be DeploymentBundle, got {type(bundle).__name__}"
            )

        release_record = None
        deployment_authorization = None

        contract_authorization = None
        if bundle.release:
            if (
                bundle.release_plan is None
                or bundle.version_resolution is None
                or bundle.release_snapshot is None
            ):
                raise ValidationError(
                    "Release deployment bundle is missing release artifacts"
                )
            evidence = None
            if bundle.decision.decision is DecisionResult.REVIEW:
                if approval is None:
                    raise ContractOpsAuthorizationError(
                        "Release deployment requires approval for REVIEW"
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
        else:
            if approval is not None:
                raise ValidationError(
                    "Non-release deployment must not consume an ApprovalRecord"
                )
            deployment_authorization = authorize_candidate_deployment(
                bundle.deployment_plan,
                bundle.deployment_source,
                bundle.decision,
            )
            if not deployment_authorization.allowed:
                raise ContractOpsAuthorizationError(
                    "Candidate deployment is blocked by governance"
                )

        if bundle.release:
            if release_history is None:
                raise ValidationError(
                    "Formal release deployment requires a release history repository"
                )
            release_record = release_history.record_release(
                bundle,
                approval=approval,
            )

        # CI-time review preview is evidence only. CD always derives a fresh preview.
        started_at = datetime.now(timezone.utc)
        fresh_preview = None
        reconciliation = None
        status = None
        try:
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

            if (
                bundle.release
                and status is RuntimeDriftStatus.IN_SYNC
                and release_record is not None
                and metadata_projector is not None
            ):
                metadata_projector.project_release_metadata(
                    bundle.deployment_plan,
                    RuntimeReleaseMetadata(
                        contract_id=release_record.contract_id,
                        contract_version=release_record.contract_version,
                        contract_release_id=release_record.contract_release_id,
                        revision_ref=release_record.revision_ref,
                    ),
                )
        except Exception as exc:
            if operational_history is not None:
                operational_history.record_deployment(
                    build_operational_deployment_event(
                        bundle_digest=bundle.bundle_digest,
                        release=bundle.release,
                        release_record_id=(
                            release_record.contract_release_id
                            if release_record is not None
                            else None
                        ),
                        contract_id=bundle.deployment_plan.contract_id,
                        contract_version=bundle.deployment_plan.contract_version,
                        revision_ref=bundle.deployment_plan.revision_ref,
                        deployment_plan_id=bundle.deployment_plan.deployment_plan_id,
                        deployment_preview_id=(
                            fresh_preview.deployment_preview_id
                            if fresh_preview is not None
                            else None
                        ),
                        deployment_authorization_id=(
                            deployment_authorization.deployment_authorization_id
                        ),
                        platform=bundle.deployment_plan.target.platform,
                        runtime_target=bundle.deployment_plan.target.runtime_target,
                        source_reference=bundle.deployment_plan.target.source_reference,
                        status="FAILED",
                        reconciliation_status=status,
                        started_at=started_at,
                        completed_at=datetime.now(timezone.utc),
                        error_message=str(exc) or type(exc).__name__,
                    )
                )
            raise

        assert fresh_preview is not None
        assert reconciliation is not None
        assert status is not None
        result = DeploymentExecutionResult(
            bundle_digest=bundle.bundle_digest,
            deployment_plan_id=bundle.deployment_plan.deployment_plan_id,
            authorization_id=deployment_authorization.deployment_authorization_id,
            release_record_id=(
                release_record.contract_release_id
                if release_record is not None
                else None
            ),
            fresh_preview=fresh_preview,
            reconciliation=reconciliation,
            status=status,
            review_preview_changed=fresh_preview != bundle.review_preview,
        )
        if operational_history is not None:
            operational_history.record_deployment(
                build_operational_deployment_event(
                    bundle_digest=bundle.bundle_digest,
                    release=bundle.release,
                    release_record_id=result.release_record_id,
                    contract_id=bundle.deployment_plan.contract_id,
                    contract_version=bundle.deployment_plan.contract_version,
                    revision_ref=bundle.deployment_plan.revision_ref,
                    deployment_plan_id=bundle.deployment_plan.deployment_plan_id,
                    deployment_preview_id=fresh_preview.deployment_preview_id,
                    deployment_authorization_id=(
                        deployment_authorization.deployment_authorization_id
                    ),
                    platform=bundle.deployment_plan.target.platform,
                    runtime_target=bundle.deployment_plan.target.runtime_target,
                    source_reference=bundle.deployment_plan.target.source_reference,
                    status="SUCCEEDED",
                    reconciliation_status=status,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    error_message=None,
                )
            )
        return result

