from __future__ import annotations

from datetime import datetime, timezone

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)
from pydantic import ValidationError as PydanticValidationError

from semapact.application.services.deployment_workflow import DeploymentWorkflowService
from semapact.application.services.release_workflow import ReleaseFinalizer, ReleaseWorkflowService
from semapact.deployment import (
    DeploymentAdapter,
    DeploymentPreview,
    DeploymentTarget,
    NativeOperation,
    NativeOperationKind,
)
from semapact.deployment.models import compute_deployment_preview_id
from semapact.governance import DecisionResult
from semapact.observation import ObservedPlatformState, with_observed_state_fingerprint
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

    def apply(self, plan, preview) -> None:
        raise AssertionError("CI bundle construction must not apply")

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
        self.metadata_calls = []

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

    def apply(self, plan, preview) -> None:
        self.execute_calls += 1
        self.executed_preview = preview

    def execute(self, plan, preview, authorization) -> None:
        assert authorization.allowed is True
        assert authorization.source_snapshot_id == plan.source_snapshot_id
        self.apply(plan, preview)

    def project_release_metadata(self, plan, metadata) -> None:
        self.metadata_calls.append((plan, metadata))

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
    def apply(self, plan, preview) -> None:
        raise RuntimeError("provider mutation failed")


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


def _target(name: str = "sales") -> DeploymentTarget:
    return DeploymentTarget(
        platform="fake",
        runtime_target=f"main.{name}",
        source_reference=f"runtime:{name}",
    )


def _finalized_release():
    workflow = ReleaseWorkflowService()
    bundle = workflow.assess(
        _contract(name="Orders"),
        _contract(name="Orders", include_created_at=True),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
    )
    approval = workflow.approve(
        bundle,
        actor_reference="human:reviewer",
        recorded_at=datetime(2026, 9, 20, 2, tzinfo=timezone.utc),
    )
    return ReleaseFinalizer().finalize(
        bundle,
        approval=approval,
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

    assert bundle.is_release is False
    assert bundle.contract_release is None
    assert bundle.decision is not None
    assert bundle.change_set is not None
    assert bundle.deployment_source.source_kind == "candidate"
    assert bundle.deployment_source.contract_version == "1.2.3"
    assert bundle.deployment_plan.plan_version == "5"


def test_finalized_release_assessment_binds_exact_release_record(tmp_path) -> None:
    release = _finalized_release()
    bundle = DeploymentWorkflowService().assess_release(
        release,
        target=_target(),
        adapter=_PreviewAdapter(),
    )

    assert bundle.is_release is True
    assert bundle.decision is None
    assert bundle.change_set is None
    assert bundle.contract_release == release
    assert bundle.deployment_source.release_id == release.contract_release_id
    assert bundle.deployment_source.contract_version == release.contract_version
    assert bundle.deployment_plan.release_id is None


def test_same_candidate_inputs_produce_same_bundle_digest() -> None:
    service = DeploymentWorkflowService()
    kwargs = dict(
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=_target(),
    )
    first = service.assess(
        _contract(name="Orders old"),
        _contract(name="Orders new"),
        adapter=_PreviewAdapter(),
        **kwargs,
    )
    second = service.assess(
        _contract(name="Orders old"),
        _contract(name="Orders new"),
        adapter=_PreviewAdapter(),
        **kwargs,
    )
    assert first == second
    assert first.bundle_digest == second.bundle_digest


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
        type(bundle).model_validate(payload)


def test_candidate_review_deployment_needs_no_release_approval() -> None:
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
    assert bundle.decision is not None
    assert bundle.decision.decision is DecisionResult.REVIEW

    result = service.deploy(bundle, adapter=_ExecutionAdapter())

    assert result.contract_release_id is None
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
    assert event.contract_release_id is None
    assert not hasattr(event, "deployment_authorization_id")
    assert event.reconciliation_status is None


def test_one_finalized_release_fans_out_to_multiple_targets(tmp_path) -> None:
    release = _finalized_release()
    service = DeploymentWorkflowService()

    dev = service.assess_release(
        release,
        target=_target("dev"),
        adapter=_PreviewAdapter(),
    )
    prod = service.assess_release(
        release,
        target=_target("prod"),
        adapter=_PreviewAdapter(),
    )

    assert dev.contract_release == prod.contract_release == release
    assert dev.bundle_digest != prod.bundle_digest
    assert dev.deployment_plan.deployment_plan_id != prod.deployment_plan.deployment_plan_id
    assert dev.deployment_source.release_id == prod.deployment_source.release_id


def test_release_deployment_projects_finalized_version_after_in_sync(tmp_path) -> None:
    release = _finalized_release()
    bundle = DeploymentWorkflowService().assess_release(
        release,
        target=_target(),
        adapter=_PreviewAdapter(),
    )
    adapter = _ExecutionAdapter()
    result = DeploymentWorkflowService().deploy(
        bundle,
        adapter=adapter,
    )

    assert result.status is RuntimeDriftStatus.IN_SYNC
    assert result.contract_release_id == release.contract_release_id
    assert len(adapter.metadata_calls) == 1
    plan, metadata = adapter.metadata_calls[0]
    assert metadata.contract_version == release.contract_version
    assert metadata.contract_release_id == release.contract_release_id
    assert plan.release_id is None
