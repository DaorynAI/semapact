from __future__ import annotations

from datetime import datetime, timezone

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)
from pydantic import ValidationError as PydanticValidationError

from semapact.approval import build_approval_record
from semapact.application.models.deployment_workflow import DeploymentBundle
from semapact.application.services.contract_release_history import (
    ContractReleaseHistoryService,
)
from semapact.application.services.deployment_approval import DeploymentApprovalResolver
from semapact.application.services.deployment_workflow import DeploymentWorkflowService
from semapact.contractops import ReviewEvidenceAction
from semapact.deployment import (
    DeploymentAdapter,
    DeploymentPreview,
    DeploymentTarget,
    NativeOperation,
    NativeOperationKind,
)
from semapact.deployment.models import compute_deployment_preview_id
from semapact.exceptions import ContractOpsAuthorizationError, ValidationError
from semapact.governance import DecisionResult, GovernanceOperation
from semapact.observation import ObservedPlatformState, with_observed_state_fingerprint
from semapact.platforms.git import GitWorkingTreeHistoryRepository
from semapact.reconciliation import ReconciliationResult, RuntimeDriftStatus


class _PreviewAdapter(DeploymentAdapter):
    key = "fake"

    def __init__(self) -> None:
        self.preview_calls = 0

    def validate(self, plan) -> None:
        pass

    def preview(self, plan) -> DeploymentPreview:
        self.preview_calls += 1
        observation = with_observed_state_fingerprint(
            ObservedPlatformState(
                platform="fake",
                source_identifier=plan.target.source_reference,
                assets=(),
                captured_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
            )
        )
        assert observation.fingerprint is not None
        operations = (
            NativeOperation(
                kind=NativeOperationKind.CREATE,
                governed_asset="orders",
                statement="CREATE orders",
            ),
        )
        return DeploymentPreview(
            deployment_preview_id=compute_deployment_preview_id(
                deployment_plan_id=plan.deployment_plan_id,
                platform="fake",
                runtime_target=plan.target.runtime_target,
                source_identifier=observation.source_identifier,
                observation_fingerprint=observation.fingerprint,
                operations=operations,
            ),
            deployment_plan_id=plan.deployment_plan_id,
            platform="fake",
            runtime_target=plan.target.runtime_target,
            source_identifier=observation.source_identifier,
            observation_fingerprint=observation.fingerprint,
            operations=operations,
        )

    def execute(self, plan, preview, authorization) -> None:
        raise AssertionError("CI bundle construction must not execute")

    def verify(self, plan) -> ReconciliationResult:
        raise AssertionError("CI bundle construction must not verify deployment")


class _ExecutionAdapter(DeploymentAdapter):
    key = "fake"

    def __init__(self) -> None:
        self.preview_calls = 0
        self.execute_calls = 0
        self.verify_calls = 0
        self.executed_preview = None

    def validate(self, plan) -> None:
        pass

    def preview(self, plan) -> DeploymentPreview:
        self.preview_calls += 1
        observation = with_observed_state_fingerprint(
            ObservedPlatformState(
                platform="fake",
                source_identifier=plan.target.source_reference,
                assets=(),
                captured_at=datetime(2026, 9, 20, 1, tzinfo=timezone.utc),
            )
        )
        assert observation.fingerprint is not None
        operations = (
            NativeOperation(
                kind=NativeOperationKind.NO_OP,
                governed_asset="orders",
            ),
        )
        return DeploymentPreview(
            deployment_preview_id=compute_deployment_preview_id(
                deployment_plan_id=plan.deployment_plan_id,
                platform="fake",
                runtime_target=plan.target.runtime_target,
                source_identifier=observation.source_identifier,
                observation_fingerprint=observation.fingerprint,
                operations=operations,
            ),
            deployment_plan_id=plan.deployment_plan_id,
            platform="fake",
            runtime_target=plan.target.runtime_target,
            source_identifier=observation.source_identifier,
            observation_fingerprint=observation.fingerprint,
            operations=operations,
        )

    def execute(self, plan, preview, authorization) -> None:
        assert authorization.allowed is True
        assert authorization.source_snapshot_id == plan.source_snapshot_id
        self.execute_calls += 1
        self.executed_preview = preview

    def verify(self, plan) -> ReconciliationResult:
        self.verify_calls += 1
        return ReconciliationResult(
            contract_id=plan.contract_id,
            contract_version=plan.contract_version,
            observation_source_identifier=plan.target.source_reference,
            observation_fingerprint="obs-v2:sha256:verified",
        )


class _OperationalSink:
    def __init__(self) -> None:
        self.events = []

    def record_deployment(self, event) -> None:
        self.events.append(event)


class _FailingExecutionAdapter(_ExecutionAdapter):
    def execute(self, plan, preview, authorization) -> None:
        raise RuntimeError("provider mutation failed")


class _MetadataProjector:
    def __init__(self) -> None:
        self.calls = []

    def project_release_metadata(self, plan, metadata) -> None:
        self.calls.append((plan, metadata))


def _contract(
    *,
    name: str,
    include_created_at: bool = False,
) -> OpenDataContractStandard:
    properties = [
        SchemaProperty(
            name="id",
            logicalType="string",
            physicalType="varchar(255)",
            required=True,
        )
    ]
    if include_created_at:
        properties.append(
            SchemaProperty(
                name="created_at",
                logicalType="timestamp",
                physicalType="timestamp",
                required=False,
            )
        )
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders-product",
        name=name,
        version="1.2.3",
        status="active",
        schema=[SchemaObject(name="orders", properties=properties)],
    )


def _target() -> DeploymentTarget:
    return DeploymentTarget(
        platform="fake",
        runtime_target="main.sales",
        source_reference="runtime:test",
    )


def _release_history(tmp_path) -> ContractReleaseHistoryService:
    return ContractReleaseHistoryService(
        GitWorkingTreeHistoryRepository(tmp_path)
    )


def _review_release_bundle() -> DeploymentBundle:
    return DeploymentWorkflowService().assess(
        _contract(name="Orders"),
        _contract(name="Orders", include_created_at=True),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=_target(),
        adapter=_PreviewAdapter(),
        release=True,
    )


def test_candidate_assessment_does_not_calculate_release_version() -> None:
    bundle = DeploymentWorkflowService().assess(
        _contract(name="Orders old"),
        _contract(name="Orders new"),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=_target(),
        adapter=_PreviewAdapter(),
    )

    assert bundle.release is False
    assert bundle.release_plan is None
    assert bundle.version_resolution is None
    assert bundle.release_snapshot is None
    assert bundle.deployment_source.release is False
    assert bundle.deployment_source.contract_version == "1.2.3"
    assert bundle.deployment_plan.release is False
    assert bundle.deployment_plan.contract_version == "1.2.3"
    assert bundle.deployment_plan.plan_version == "4"


def test_release_assessment_resolves_version_once_and_binds_source() -> None:
    bundle = _review_release_bundle()

    assert bundle.release is True
    assert bundle.release_plan is not None
    assert bundle.version_resolution is not None
    assert bundle.release_snapshot is not None
    assert bundle.deployment_source.release is True
    assert (
        bundle.deployment_source.release_id
        == bundle.release_snapshot.release_snapshot_id
    )
    assert (
        bundle.deployment_source.contract_version
        == bundle.version_resolution.selected_version
    )
    assert bundle.deployment_plan.release is True
    assert bundle.deployment_plan.plan_version == "4"


def test_same_inputs_produce_same_bundle_digest() -> None:
    first = DeploymentWorkflowService().assess(
        _contract(name="Orders old"),
        _contract(name="Orders new"),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=_target(),
        adapter=_PreviewAdapter(),
    )
    second = DeploymentWorkflowService().assess(
        _contract(name="Orders old"),
        _contract(name="Orders new"),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=_target(),
        adapter=_PreviewAdapter(),
    )
    assert first == second
    assert first.bundle_digest == second.bundle_digest


def test_release_mode_changes_bundle_identity() -> None:
    candidate = DeploymentWorkflowService().assess(
        _contract(name="Orders"),
        _contract(name="Orders", include_created_at=True),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=_target(),
        adapter=_PreviewAdapter(),
    )
    release = _review_release_bundle()

    assert candidate.bundle_digest != release.bundle_digest


def test_bundle_rehydration_fails_closed_when_digest_is_tampered() -> None:
    bundle = DeploymentWorkflowService().assess(
        _contract(name="Orders old"),
        _contract(name="Orders new"),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=_target(),
        adapter=_PreviewAdapter(),
    )
    payload = bundle.model_dump(mode="json")
    payload["bundle_digest"] = "sha256:" + ("0" * 64)

    with pytest.raises(PydanticValidationError, match="digest does not match"):
        DeploymentBundle.model_validate(payload)


def test_candidate_review_deployment_needs_no_approval_or_release_history() -> None:
    service = DeploymentWorkflowService()
    bundle = service.assess(
        _contract(name="Orders"),
        _contract(name="Orders", include_created_at=True),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=_target(),
        adapter=_PreviewAdapter(),
    )
    assert bundle.decision.decision is DecisionResult.REVIEW
    assert bundle.release is False

    result = service.deploy(bundle, adapter=_ExecutionAdapter())

    assert result.release_record_id is None
    assert result.status is RuntimeDriftStatus.IN_SYNC


def test_cd_uses_fresh_preview_not_ci_review_preview() -> None:
    service = DeploymentWorkflowService()
    bundle = service.assess(
        _contract(name="Orders old"),
        _contract(name="Orders new"),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=_target(),
        adapter=_PreviewAdapter(),
    )
    adapter = _ExecutionAdapter()

    result = service.deploy(bundle, adapter=adapter)

    assert adapter.preview_calls == 1
    assert adapter.execute_calls == 1
    assert adapter.verify_calls == 1
    assert adapter.executed_preview is result.fresh_preview
    assert result.fresh_preview.operations[0].kind is NativeOperationKind.NO_OP
    assert result.review_preview_changed is True


def test_configured_operational_history_records_failed_candidate_deployment() -> None:
    service = DeploymentWorkflowService()
    bundle = service.assess(
        _contract(name="Orders old"),
        _contract(name="Orders new"),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=_target(),
        adapter=_PreviewAdapter(),
    )
    sink = _OperationalSink()

    with pytest.raises(RuntimeError, match="provider mutation failed"):
        service.deploy(
            bundle,
            adapter=_FailingExecutionAdapter(),
            operational_history=sink,
        )

    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.status == "FAILED"
    assert event.release is False
    assert event.release_record_id is None
    assert event.deployment_preview_id is not None
    assert event.reconciliation_status is None


def test_non_release_bundle_rejects_manual_approval() -> None:
    service = DeploymentWorkflowService()
    bundle = service.assess(
        _contract(name="Orders"),
        _contract(name="Orders", include_created_at=True),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=_target(),
        adapter=_PreviewAdapter(),
    )

    with pytest.raises(ValidationError, match="Non-release"):
        service.approve(
            bundle,
            actor_reference="human:reviewer",
            recorded_at=datetime(2026, 9, 20, 2, tzinfo=timezone.utc),
        )


def test_release_approval_is_derived_from_exact_bundle() -> None:
    service = DeploymentWorkflowService()
    bundle = _review_release_bundle()

    approval = service.approve(
        bundle,
        actor_reference="human:reviewer",
        recorded_at=datetime(2026, 9, 20, 2, tzinfo=timezone.utc),
    )

    assert approval.operation is GovernanceOperation.DEPLOY
    assert approval.action is ReviewEvidenceAction.APPROVE
    assert approval.scope_reference == bundle.deployment_plan.deployment_plan_id
    assert approval.evidence_references == (bundle.bundle_digest,)


def test_review_release_requires_approval_and_records_formal_release(tmp_path) -> None:
    service = DeploymentWorkflowService()
    bundle = _review_release_bundle()

    with pytest.raises(ContractOpsAuthorizationError, match="requires approval"):
        service.deploy(
            bundle,
            adapter=_ExecutionAdapter(),
            release_history=_release_history(tmp_path),
        )

    approval = service.approve(
        bundle,
        actor_reference="human:reviewer",
        recorded_at=datetime(2026, 9, 20, 2, tzinfo=timezone.utc),
    )
    result = service.deploy(
        bundle,
        adapter=_ExecutionAdapter(),
        approval=approval,
        release_history=_release_history(tmp_path),
    )

    assert result.release_record_id is not None
    repository = GitWorkingTreeHistoryRepository(tmp_path)
    record = repository.get_contract_release(result.release_record_id)
    assert record.contract_version == bundle.version_resolution.selected_version
    assert record.release_snapshot_id == bundle.release_snapshot.release_snapshot_id
    assert record.revision_ref == bundle.release_snapshot.release_revision_ref


def test_contract_release_identity_is_target_neutral(tmp_path) -> None:
    service = DeploymentWorkflowService()
    base = _contract(name="Orders")
    candidate = _contract(name="Orders", include_created_at=True)

    dev = service.assess(
        base,
        candidate,
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=DeploymentTarget(
            platform="fake",
            runtime_target="main.dev",
            source_reference="runtime:dev",
        ),
        adapter=_PreviewAdapter(),
        release=True,
    )
    prod = service.assess(
        base,
        candidate,
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=DeploymentTarget(
            platform="fake",
            runtime_target="main.prod",
            source_reference="runtime:prod",
        ),
        adapter=_PreviewAdapter(),
        release=True,
    )
    assert dev.bundle_digest != prod.bundle_digest
    assert dev.deployment_plan.deployment_plan_id != prod.deployment_plan.deployment_plan_id

    history = _release_history(tmp_path)
    dev_approval = service.approve(
        dev,
        actor_reference="human:reviewer",
        recorded_at=datetime(2026, 9, 20, 2, tzinfo=timezone.utc),
    )
    prod_approval = service.approve(
        prod,
        actor_reference="human:reviewer",
        recorded_at=datetime(2026, 9, 20, 2, 1, tzinfo=timezone.utc),
    )

    first = history.record_release(dev, approval=dev_approval)
    second = history.record_release(prod, approval=prod_approval)

    assert first == second
    assert first.contract_release_id == second.contract_release_id


def test_release_projects_metadata_only_after_in_sync(tmp_path) -> None:
    service = DeploymentWorkflowService()
    bundle = _review_release_bundle()
    approval = service.approve(
        bundle,
        actor_reference="human:reviewer",
        recorded_at=datetime(2026, 9, 20, 2, tzinfo=timezone.utc),
    )
    projector = _MetadataProjector()

    result = service.deploy(
        bundle,
        adapter=_ExecutionAdapter(),
        approval=approval,
        release_history=_release_history(tmp_path),
        metadata_projector=projector,
    )

    assert result.status is RuntimeDriftStatus.IN_SYNC
    assert len(projector.calls) == 1
    plan, metadata = projector.calls[0]
    assert metadata.contract_version == plan.contract_version
    assert metadata.contract_release_id == result.release_record_id


def test_review_release_rejects_approval_for_different_bundle_digest(tmp_path) -> None:
    service = DeploymentWorkflowService()
    bundle = _review_release_bundle()
    assert bundle.release_plan is not None
    assert bundle.version_resolution is not None
    approval = build_approval_record(
        decision_id=bundle.decision.decision_id,
        change_set_id=bundle.change_set.change_set_id,
        release_plan_id=bundle.release_plan.release_plan_id,
        version_resolution_id=bundle.version_resolution.version_resolution_id,
        operation=GovernanceOperation.DEPLOY,
        action=ReviewEvidenceAction.APPROVE,
        actor_reference="human:reviewer",
        recorded_at=datetime(2026, 9, 20, 2, tzinfo=timezone.utc),
        scope_reference=bundle.deployment_plan.deployment_plan_id,
        evidence_references=("sha256:" + ("0" * 64),),
    )

    with pytest.raises(ValidationError, match="exact DeploymentBundle digest"):
        service.deploy(
            bundle,
            adapter=_ExecutionAdapter(),
            approval=approval,
            release_history=_release_history(tmp_path),
        )


def test_deployment_approval_resolver_finds_exact_release_record(tmp_path) -> None:
    service = DeploymentWorkflowService()
    bundle = _review_release_bundle()
    approval = service.approve(
        bundle,
        actor_reference="github:user:reviewer",
        recorded_at=datetime(2026, 9, 20, 2, tzinfo=timezone.utc),
    )
    repository = GitWorkingTreeHistoryRepository(tmp_path)
    repository.put_approval_record(approval)

    assert DeploymentApprovalResolver(repository).resolve(bundle) == approval


def test_deployment_approval_resolver_ignores_candidate_bundle(tmp_path) -> None:
    bundle = DeploymentWorkflowService().assess(
        _contract(name="Orders"),
        _contract(name="Orders", include_created_at=True),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=_target(),
        adapter=_PreviewAdapter(),
    )

    assert (
        DeploymentApprovalResolver(
            GitWorkingTreeHistoryRepository(tmp_path)
        ).resolve(bundle)
        is None
    )
