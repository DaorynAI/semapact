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
from semapact.contractops import ContractRelease
from semapact.deployment import (
    DeploymentAdapter,
    DeploymentTarget,
    RuntimeReleaseMetadata,
    RuntimeReleaseMetadataProjector,
    build_candidate_deployment_source,
    build_contract_release_deployment_source,
    validate_candidate_deployment_context,
    validate_contract_release_deployment_context,
)
from semapact.history import (
    OperationalHistorySink,
    build_operational_deployment_event,
)
from semapact.reconciliation import RuntimeDriftStatus, classify_reconciliation_status


class DeploymentWorkflowService:
    """Assess desired state and converge one target after the external CD gate runs."""

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
        """Build an immutable candidate deployment bundle."""
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
    ) -> DeploymentExecutionResult:
        """Apply one exact bundle after the caller's execution boundary allows CD.

        SemaPact validates governance/release provenance, runtime freshness and
        deterministic operations. It does not turn ContractRelease into DEPLOY
        authorization; protected CI/CD environments control whether this operation
        may be invoked.
        """
        if not isinstance(bundle, DeploymentBundle):
            raise TypeError(
                f"bundle must be DeploymentBundle, got {type(bundle).__name__}"
            )

        release_record = None
        if bundle.is_release:
            assert bundle.contract_release is not None
            validate_contract_release_deployment_context(
                bundle.deployment_plan,
                bundle.deployment_source,
                bundle.contract_release,
            )
            release_record = bundle.contract_release
        else:
            assert bundle.decision is not None
            validate_candidate_deployment_context(
                bundle.deployment_plan,
                bundle.deployment_source,
                bundle.decision,
            )

        started_at = datetime.now(timezone.utc)
        fresh_preview = None
        reconciliation = None
        status = None
        try:
            fresh_preview = self._deployment.preview(
                bundle.deployment_plan,
                adapter=adapter,
            )
            self._deployment.apply(
                bundle.deployment_plan,
                fresh_preview,
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
                and isinstance(adapter, RuntimeReleaseMetadataProjector)
            ):
                adapter.project_release_metadata(
                    bundle.deployment_plan,
                    RuntimeReleaseMetadata(
                        contract_id=release_record.contract_id,
                        contract_version=release_record.contract_version,
                        contract_release_id=release_record.contract_release_id,
                        source_revision_ref=release_record.source_revision_ref,
                    ),
                )
        except Exception as exc:
            _record_operational_event(
                operational_history,
                bundle=bundle,
                contract_release=release_record,
                deployment_preview_id=(
                    fresh_preview.deployment_preview_id
                    if fresh_preview is not None
                    else None
                ),
                status="FAILED",
                reconciliation_status=status,
                started_at=started_at,
                error_message=str(exc) or type(exc).__name__,
            )
            raise

        assert fresh_preview is not None
        assert reconciliation is not None
        assert status is not None
        result = DeploymentExecutionResult(
            bundle_digest=bundle.bundle_digest,
            deployment_plan_id=bundle.deployment_plan.deployment_plan_id,
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
        _record_operational_event(
            operational_history,
            bundle=bundle,
            contract_release=release_record,
            deployment_preview_id=fresh_preview.deployment_preview_id,
            status="SUCCEEDED",
            reconciliation_status=status,
            started_at=started_at,
            error_message=None,
        )
        return result


def _record_operational_event(
    sink: OperationalHistorySink | None,
    *,
    bundle: DeploymentBundle,
    contract_release: ContractRelease | None,
    deployment_preview_id: str | None,
    status: str,
    reconciliation_status: RuntimeDriftStatus | None,
    started_at: datetime,
    error_message: str | None,
) -> None:
    """Persist optional deployment telemetry without influencing execution semantics."""
    if sink is None:
        return
    plan = bundle.deployment_plan
    sink.record_deployment(
        build_operational_deployment_event(
            bundle_digest=bundle.bundle_digest,
            contract_release_id=(
                contract_release.contract_release_id
                if contract_release is not None
                else None
            ),
            contract_id=plan.contract_id,
            contract_version=plan.contract_version,
            revision_ref=plan.revision_ref,
            deployment_plan_id=plan.deployment_plan_id,
            deployment_preview_id=deployment_preview_id,
            platform=plan.target.platform,
            runtime_target=plan.target.runtime_target,
            source_reference=plan.target.source_reference,
            status=status,
            reconciliation_status=reconciliation_status,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            error_message=error_message,
        )
    )
