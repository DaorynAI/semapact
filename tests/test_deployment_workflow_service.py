from __future__ import annotations

from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.application.services.deployment_workflow import DeploymentWorkflowService
from semapact.deployment import (
    DeploymentAdapter,
    DeploymentAssessment,
    DeploymentTarget,
    NativeOperation,
    NativeOperationKind,
)
from semapact.deployment.models import compute_deployment_assessment_id
from semapact.observation import (
    ObservedPlatformState,
    with_observed_state_fingerprint,
)
from semapact.reconciliation import ReconciliationResult


class _AssessmentAdapter(DeploymentAdapter):
    key = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def assess(self, contract, *, candidate_revision_ref, target):
        self.calls += 1
        observation = with_observed_state_fingerprint(
            ObservedPlatformState(
                platform="fake",
                source_identifier=target.source_reference,
                assets=(),
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
        assessment_id = compute_deployment_assessment_id(
            contract_id=str(contract.id),
            candidate_revision_ref=candidate_revision_ref,
            candidate_version=str(contract.version),
            target=target,
            source_identifier=observation.source_identifier,
            observation_fingerprint=observation.fingerprint,
            operations=operations,
        )
        return DeploymentAssessment(
            deployment_assessment_id=assessment_id,
            contract_id=str(contract.id),
            candidate_revision_ref=candidate_revision_ref,
            candidate_version=str(contract.version),
            target=target,
            source_identifier=observation.source_identifier,
            observation_fingerprint=observation.fingerprint,
            operations=operations,
        )

    def validate(self, plan):
        raise AssertionError("assessment must not create or validate a DeploymentPlan")

    def preview(self, plan):
        raise AssertionError("assessment must not create a DeploymentPreview")

    def execute(self, plan, preview, authorization):
        raise AssertionError("assessment must not execute")

    def verify(self, plan) -> ReconciliationResult:
        raise AssertionError("assessment must not verify a deployment")


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


def test_workflow_assessment_composes_release_planning_and_runtime_assessment() -> None:
    adapter = _AssessmentAdapter()
    target = DeploymentTarget(
        platform="fake",
        runtime_target="main.sales",
        source_reference="runtime:test",
    )

    result = DeploymentWorkflowService().assess(
        _contract(name="Orders old"),
        _contract(name="Orders new"),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=target,
        adapter=adapter,
    )

    assert adapter.calls == 1
    assert result.release.change_set.base_revision_ref == "git:base"
    assert result.release.release_plan.release_revision_ref == "git:candidate"
    assert result.deployment.candidate_revision_ref == "git:candidate"
    assert result.deployment.contract_id == result.release.release_plan.contract_id
    assert result.deployment.operations[0].kind is NativeOperationKind.CREATE
    assert not hasattr(result.deployment, "applied_release_id")
    assert not hasattr(result.deployment, "deployment_plan_id")
