from __future__ import annotations

from datetime import datetime, timezone

from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.application.services.deployment_workflow import DeploymentWorkflowService
from semapact.deployment import (
    DeploymentAdapter,
    DeploymentPreview,
    DeploymentTarget,
    NativeOperation,
    NativeOperationKind,
)
from semapact.deployment.models import compute_deployment_preview_id
from semapact.observation import ObservedPlatformState, with_observed_state_fingerprint
from semapact.reconciliation import ReconciliationResult


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


def _contract(*, name: str) -> OpenDataContractStandard:
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders-product",
        name=name,
        version="1.2.3",
        status="active",
        schema=[
            SchemaObject(
                name="orders",
                properties=[
                    SchemaProperty(
                        name="id",
                        logicalType="string",
                        physicalType="varchar(255)",
                        required=True,
                    )
                ],
            )
        ],
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
