"""Canonical target-specific deployment workflow orchestration."""

from __future__ import annotations

from datetime import date, datetime, timezone

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.application.models.deployment_workflow import (
    DeploymentBundle,
    DeploymentExecutionResult,
    build_deployment_bundle,
)
from semapact.application.services.deployment import DeploymentService
from semapact.application.services.governance import GovernanceService
from semapact.deployment import (
    DeploymentAdapter,
    DeploymentTarget,
    RuntimeReleaseMetadata,
    RuntimeReleaseMetadataProjector,
    authorize_candidate_deployment,
    authorize_contract_release_deployment,
    build_candidate_deployment_source,
    build_contract_release_deployment_source,
)
from semapact.exceptions import ContractOpsAuthorizationError
from semapact.contractops import ContractRelease
from semapact.history import (
    OperationalHistorySink,
    build_operational_deployment_event,
)
from semapact.reconciliation import RuntimeDriftStatus, classify_reconciliation_status


class DeploymentWorkflowService:
    """Assess candidate/finalized-release desired state and converge one runtime target."""

    def __init__(
        self,
        *,
        governance_service: GovernanceService | None = None,
        deployment_service: DeploymentService | None = None,
    ) -> None:
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
    ) -> DeploymentBundle:
        """Build an immutable non-release candidate deployment bundle."""
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
        plan = self._deployment.plan(source, target)
        preview = self._deployment.preview(plan, adapter=adapter)
        return build_deployment_bundle(
            release=False,
            decision=proposal.decision,
            change_set=proposal.change_set,
            deployment_source=source,
            deployment_plan=plan,
            review_preview=preview,
        )

    def assess_release(
        self,
        release: ContractRelease,
        *,
        target: DeploymentTarget,
        adapter: DeploymentAdapter,
    ) -> DeploymentBundle:
        """Build one target-specific bundle from an already-finalized release."""
        source = build_contract_release_deployment_source(release)
        plan = self._deployment.plan(source, target)
        preview = self._deployment.preview(plan, adapter=adapter)
        return build_deployment_bundle(
            release=True,
            contract_release=release,
            deployment_source=source,
            deployment_plan=plan,
            review_preview=preview,
        )

    def deploy(
        self,
        bundle: DeploymentBundle,
        *,
        adapter: DeploymentAdapter,
        operational_history: OperationalHistorySink | None = None,
        metadata_projector: RuntimeReleaseMetadataProjector | None = None,
    ) -> DeploymentExecutionResult:
        """Consume one exact target bundle, deploy from fresh runtime evidence, and verify."""
        if not isinstance(bundle, DeploymentBundle):
            raise TypeError(
                f"bundle must be DeploymentBundle, got {type(bundle).__name__}"
            )

        if bundle.release:
            assert bundle.contract_release is not None
            deployment_authorization = authorize_contract_release_deployment(
                bundle.deployment_plan,
                bundle.deployment_source,
                bundle.contract_release,
            )
            release_record = bundle.contract_release
        else:
            assert bundle.decision is not None
            deployment_authorization = authorize_candidate_deployment(
                bundle.deployment_plan,
                bundle.deployment_source,
                bundle.decision,
            )
            if not deployment_authorization.allowed:
                raise ContractOpsAuthorizationError(
                    "Candidate deployment is blocked by governance"
                )
            release_record = None

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
                release_record is not None
                and status is RuntimeDriftStatus.IN_SYNC
                and metadata_projector is not None
            ):
                metadata_projector.project_release_metadata(
                    bundle.deployment_plan,
                    RuntimeReleaseMetadata(
                        contract_id=release_record.contract_id,
                        contract_version=release_record.contract_version,
                        contract_release_id=release_record.contract_release_id,
                        source_revision_ref=release_record.source_revision_ref,
                    ),
                )
        except Exception as exc:
            if operational_history is not None:
                operational_history.record_deployment(
                    build_operational_deployment_event(
                        bundle_digest=bundle.bundle_digest,
                        release=bundle.release,
                        contract_release_id=(
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
            contract_release_id=(
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
                    contract_release_id=result.contract_release_id,
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
