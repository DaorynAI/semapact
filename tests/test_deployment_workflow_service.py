from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError as PydanticValidationError

from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.approval import build_approval_record
from semapact.application.models.deployment_workflow import DeploymentBundle
from semapact.application.services.deployment_approval import DeploymentApprovalResolver
from semapact.application.services.deployment_workflow import DeploymentWorkflowService
from semapact.deployment import (
    DeploymentAdapter,
    DeploymentPreview,
    DeploymentTarget,
    NativeOperation,
    NativeOperationKind,
)
from semapact.contractops import ReviewEvidenceAction
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
        self.execute_calls += 1
        self.executed_preview = preview

    def verify(self, plan) -> ReconciliationResult:
        self.verify_calls += 1
        return ReconciliationResult(
            contract_id=plan.contract_id,
            contract_version=plan.selected_version,
            observation_source_identifier=plan.target.source_reference,
            observation_fingerprint="obs-v2:sha256:verified",
        )


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


def test_workflow_assessment_builds_content_addressed_ci_bundle() -> None:
    adapter = _PreviewAdapter()
    target = DeploymentTarget(
        platform="fake",
        runtime_target="main.sales",
        source_reference="runtime:test",
    )

    bundle = DeploymentWorkflowService().assess(
        _contract(name="Orders old"),
        _contract(name="Orders new"),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=target,
        adapter=adapter,
    )

    assert adapter.preview_calls == 1
    assert bundle.change_set.base_revision_ref == "git:base"
    assert bundle.release_plan.release_revision_ref == "git:candidate"
    assert bundle.release_snapshot.release_revision_ref == "git:candidate"
    assert (
        bundle.deployment_plan.release_id
        == bundle.release_snapshot.release_snapshot_id
    )
    assert bundle.deployment_plan.plan_version == "3"
    assert bundle.review_preview.deployment_plan_id == bundle.deployment_plan.deployment_plan_id
    assert bundle.review_preview.operations[0].kind is NativeOperationKind.CREATE
    assert bundle.bundle_digest.startswith("sha256:")
    assert not hasattr(bundle, "authorization")
    assert not hasattr(bundle.release_snapshot, "authorization_id")


def test_same_inputs_produce_same_bundle_digest() -> None:
    target = DeploymentTarget(
        platform="fake",
        runtime_target="main.sales",
        source_reference="runtime:test",
    )
    first = DeploymentWorkflowService().assess(
        _contract(name="Orders old"),
        _contract(name="Orders new"),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=target,
        adapter=_PreviewAdapter(),
    )
    second = DeploymentWorkflowService().assess(
        _contract(name="Orders old"),
        _contract(name="Orders new"),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=target,
        adapter=_PreviewAdapter(),
    )

    assert first.bundle_digest == second.bundle_digest
    assert first == second


def test_bundle_rehydration_fails_closed_when_digest_is_tampered() -> None:
    target = DeploymentTarget(
        platform="fake",
        runtime_target="main.sales",
        source_reference="runtime:test",
    )
    bundle = DeploymentWorkflowService().assess(
        _contract(name="Orders old"),
        _contract(name="Orders new"),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=target,
        adapter=_PreviewAdapter(),
    )
    payload = bundle.model_dump(mode="json")
    payload["bundle_digest"] = "sha256:" + ("0" * 64)

    with pytest.raises(PydanticValidationError, match="digest does not match"):
        DeploymentBundle.model_validate(payload)


def test_cd_uses_fresh_preview_not_ci_review_preview() -> None:
    target = DeploymentTarget(
        platform="fake",
        runtime_target="main.sales",
        source_reference="runtime:test",
    )
    service = DeploymentWorkflowService()
    bundle = service.assess(
        _contract(name="Orders old"),
        _contract(name="Orders new"),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=target,
        adapter=_PreviewAdapter(),
    )
    assert bundle.decision.decision is DecisionResult.ALLOW
    assert bundle.review_preview.operations[0].kind is NativeOperationKind.CREATE

    adapter = _ExecutionAdapter()
    result = service.deploy(bundle, adapter=adapter)

    assert adapter.preview_calls == 1
    assert adapter.execute_calls == 1
    assert adapter.verify_calls == 1
    assert adapter.executed_preview is result.fresh_preview
    assert result.fresh_preview.operations[0].kind is NativeOperationKind.NO_OP
    assert result.review_preview_changed is True
    assert result.status is RuntimeDriftStatus.IN_SYNC


def test_workflow_approval_is_derived_from_exact_review_bundle() -> None:
    target = DeploymentTarget(
        platform="fake",
        runtime_target="main.sales",
        source_reference="runtime:test",
    )
    service = DeploymentWorkflowService()
    bundle = service.assess(
        _contract(name="Orders"),
        _contract(name="Orders", include_created_at=True),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=target,
        adapter=_PreviewAdapter(),
    )

    approval = service.approve(
        bundle,
        actor_reference="human:reviewer",
        recorded_at=datetime(2026, 9, 20, 2, tzinfo=timezone.utc),
        comment="Approved for production",
    )

    assert approval.operation is GovernanceOperation.DEPLOY
    assert approval.action is ReviewEvidenceAction.APPROVE
    assert approval.scope_reference == bundle.deployment_plan.deployment_plan_id
    assert approval.evidence_references == (bundle.bundle_digest,)
    assert approval.decision_id == bundle.decision.decision_id


def test_review_deployment_requires_approval_bound_to_plan_and_bundle_digest() -> None:
    target = DeploymentTarget(
        platform="fake",
        runtime_target="main.sales",
        source_reference="runtime:test",
    )
    service = DeploymentWorkflowService()
    bundle = service.assess(
        _contract(name="Orders"),
        _contract(name="Orders", include_created_at=True),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=target,
        adapter=_PreviewAdapter(),
    )
    assert bundle.decision.decision is DecisionResult.REVIEW

    with pytest.raises(ContractOpsAuthorizationError, match="requires approval"):
        service.deploy(bundle, adapter=_ExecutionAdapter())

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
        evidence_references=(bundle.bundle_digest,),
    )

    result = service.deploy(
        bundle,
        adapter=_ExecutionAdapter(),
        approval=approval,
    )
    assert result.status is RuntimeDriftStatus.IN_SYNC


def test_review_deployment_rejects_approval_for_different_bundle_digest() -> None:
    target = DeploymentTarget(
        platform="fake",
        runtime_target="main.sales",
        source_reference="runtime:test",
    )
    service = DeploymentWorkflowService()
    bundle = service.assess(
        _contract(name="Orders"),
        _contract(name="Orders", include_created_at=True),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=target,
        adapter=_PreviewAdapter(),
    )
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
        )


def test_deployment_approval_resolver_finds_exact_git_history_record(tmp_path) -> None:
    target = DeploymentTarget(
        platform="fake",
        runtime_target="main.sales",
        source_reference="runtime:test",
    )
    service = DeploymentWorkflowService()
    bundle = service.assess(
        _contract(name="Orders"),
        _contract(name="Orders", include_created_at=True),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=target,
        adapter=_PreviewAdapter(),
    )
    approval = service.approve(
        bundle,
        actor_reference="github:user:reviewer",
        recorded_at=datetime(2026, 9, 20, 2, tzinfo=timezone.utc),
    )
    repository = GitWorkingTreeHistoryRepository(tmp_path)
    repository.put_approval_record(approval)

    resolved = DeploymentApprovalResolver(repository).resolve(bundle)

    assert resolved == approval


def test_deployment_approval_resolver_ignores_non_exact_records(tmp_path) -> None:
    target = DeploymentTarget(
        platform="fake",
        runtime_target="main.sales",
        source_reference="runtime:test",
    )
    service = DeploymentWorkflowService()
    bundle = service.assess(
        _contract(name="Orders"),
        _contract(name="Orders", include_created_at=True),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=target,
        adapter=_PreviewAdapter(),
    )
    repository = GitWorkingTreeHistoryRepository(tmp_path)
    wrong_digest = build_approval_record(
        decision_id=bundle.decision.decision_id,
        change_set_id=bundle.change_set.change_set_id,
        release_plan_id=bundle.release_plan.release_plan_id,
        version_resolution_id=bundle.version_resolution.version_resolution_id,
        operation=GovernanceOperation.DEPLOY,
        action=ReviewEvidenceAction.APPROVE,
        actor_reference="github:user:reviewer",
        recorded_at=datetime(2026, 9, 20, 2, tzinfo=timezone.utc),
        scope_reference=bundle.deployment_plan.deployment_plan_id,
        evidence_references=("sha256:" + ("0" * 64),),
    )
    repository.put_approval_record(wrong_digest)

    assert DeploymentApprovalResolver(repository).resolve(bundle) is None


def test_deployment_approval_resolver_fails_closed_on_conflicting_exact_history(
    tmp_path,
) -> None:
    target = DeploymentTarget(
        platform="fake",
        runtime_target="main.sales",
        source_reference="runtime:test",
    )
    service = DeploymentWorkflowService()
    bundle = service.assess(
        _contract(name="Orders"),
        _contract(name="Orders", include_created_at=True),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=target,
        adapter=_PreviewAdapter(),
    )
    repository = GitWorkingTreeHistoryRepository(tmp_path)

    approved = service.approve(
        bundle,
        actor_reference="github:user:alice",
        recorded_at=datetime(2026, 9, 20, 2, tzinfo=timezone.utc),
    )
    request_changes = build_approval_record(
        decision_id=bundle.decision.decision_id,
        change_set_id=bundle.change_set.change_set_id,
        release_plan_id=bundle.release_plan.release_plan_id,
        version_resolution_id=bundle.version_resolution.version_resolution_id,
        operation=GovernanceOperation.DEPLOY,
        action=ReviewEvidenceAction.REQUEST_CHANGES,
        actor_reference="github:user:bob",
        recorded_at=datetime(2026, 9, 20, 2, 1, tzinfo=timezone.utc),
        scope_reference=bundle.deployment_plan.deployment_plan_id,
        evidence_references=(bundle.bundle_digest,),
    )
    repository.put_approval_record(approved)
    repository.put_approval_record(request_changes)

    assert DeploymentApprovalResolver(repository).resolve(bundle) is None
