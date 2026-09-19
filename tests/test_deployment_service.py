from __future__ import annotations

from datetime import datetime, timezone

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.deployment import (
    DeploymentAction,
    DeploymentAdapter,
    DeploymentActionKind,
    DeploymentAssessment,
    DeploymentAuthorization,
    DeploymentPlan,
    DeploymentPreview,
    DeploymentTarget,
    NativeOperation,
    NativeOperationKind,
)
from semapact.deployment.models import (
    compute_deployment_assessment_id,
    compute_deployment_authorization_id,
    compute_deployment_plan_id,
    compute_deployment_preview_id,
)
from semapact.exceptions import ValidationError
from semapact.observation import ObservedPlatformState, with_observed_state_fingerprint
from semapact.reconciliation import ReconciliationResult
from semapact.services.deployment_service import DeploymentService

CAPTURED_AT = datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc)
SOURCE_REFERENCE = "https://adb.example"


class FakeDeploymentAdapter(DeploymentAdapter):
    key = "databricks"

    def __init__(
        self,
        preview: DeploymentPreview,
        verification: ReconciliationResult,
        assessment: DeploymentAssessment | None = None,
    ) -> None:
        self.preview_result = preview
        self.verification_result = verification
        self.assessment_result = assessment
        self.assess_calls = 0
        self.preview_calls = 0
        self.verify_calls = 0
        self.execute_calls = 0
        self.executed = None

    def assess(self, contract, *, candidate_revision_ref, target):
        self.assess_calls += 1
        assert self.assessment_result is not None
        return self.assessment_result

    def validate(self, plan: DeploymentPlan) -> None:
        pass

    def preview(self, plan: DeploymentPlan) -> DeploymentPreview:
        self.preview_calls += 1
        return self.preview_result

    def verify(self, plan: DeploymentPlan) -> ReconciliationResult:
        self.verify_calls += 1
        return self.verification_result

    def execute(self, plan, preview, authorization) -> None:
        self.execute_calls += 1
        self.executed = (plan, preview, authorization)


def _plan() -> DeploymentPlan:
    schema = SchemaObject(
        name="orders",
        physicalName="orders_v2",
        properties=[
            SchemaProperty(
                name="order_id",
                physicalName="order_pk",
                type="integer",
                physicalType="BIGINT",
                required=True,
            )
        ],
    )
    action = DeploymentAction(
        kind=DeploymentActionKind.ENSURE_ASSET_STATE,
        governed_asset="orders",
        physical_name="orders_v2",
        desired_state_json=schema.model_dump_json(by_alias=True, exclude_none=True),
    )
    target = DeploymentTarget(
        platform="databricks",
        runtime_target="main.silver",
        source_reference=SOURCE_REFERENCE,
    )
    plan_id = compute_deployment_plan_id(
        applied_release_id="release-1",
        contract_id="orders-contract",
        release_plan_id="release-plan-1",
        released_revision_ref="abc123",
        selected_version="1.2.3",
        target=target,
        actions=(action,),
    )
    return DeploymentPlan(
        deployment_plan_id=plan_id,
        applied_release_id="release-1",
        contract_id="orders-contract",
        release_plan_id="release-plan-1",
        released_revision_ref="abc123",
        selected_version="1.2.3",
        target=target,
        actions=(action,),
    )


def _observation() -> ObservedPlatformState:
    return with_observed_state_fingerprint(
        ObservedPlatformState(
            platform="databricks",
            source_identifier=SOURCE_REFERENCE,
            captured_at=CAPTURED_AT,
            assets=(),
            fingerprint=None,
        )
    )


def _preview(plan: DeploymentPlan) -> DeploymentPreview:
    observation = _observation()
    operation = NativeOperation(
        kind=NativeOperationKind.NO_OP,
        governed_asset="orders",
    )
    assert observation.fingerprint is not None
    preview_id = compute_deployment_preview_id(
        deployment_plan_id=plan.deployment_plan_id,
        platform="databricks",
        runtime_target=plan.target.runtime_target,
        source_identifier=observation.source_identifier,
        observation_fingerprint=observation.fingerprint,
        operations=(operation,),
    )
    return DeploymentPreview(
        deployment_preview_id=preview_id,
        deployment_plan_id=plan.deployment_plan_id,
        platform="databricks",
        runtime_target=plan.target.runtime_target,
        source_identifier=observation.source_identifier,
        observation_fingerprint=observation.fingerprint,
        operations=(operation,),
    )


def _verification(plan: DeploymentPlan) -> ReconciliationResult:
    observation = _observation()
    assert observation.fingerprint is not None
    return ReconciliationResult(
        contract_id=plan.contract_id,
        contract_version=plan.selected_version,
        observation_source_identifier=observation.source_identifier,
        observation_fingerprint=observation.fingerprint,
    )


def _adapter(plan: DeploymentPlan) -> FakeDeploymentAdapter:
    return FakeDeploymentAdapter(
        _preview(plan),
        _verification(plan),
        _assessment(plan),
    )


def _candidate_contract() -> OpenDataContractStandard:
    return OpenDataContractStandard.model_construct(
        id="orders-contract",
        version="1.2.3",
        schema_=[],
        servers=[],
    )


def _assessment(plan: DeploymentPlan) -> DeploymentAssessment:
    observation = _observation()
    operation = NativeOperation(
        kind=NativeOperationKind.NO_OP,
        governed_asset="orders",
    )
    assert observation.fingerprint is not None
    assessment_id = compute_deployment_assessment_id(
        contract_id="orders-contract",
        candidate_revision_ref="candidate:abc",
        candidate_version="1.2.3",
        target=plan.target,
        source_identifier=observation.source_identifier,
        observation_fingerprint=observation.fingerprint,
        operations=(operation,),
    )
    return DeploymentAssessment(
        deployment_assessment_id=assessment_id,
        contract_id="orders-contract",
        candidate_revision_ref="candidate:abc",
        candidate_version="1.2.3",
        target=plan.target,
        source_identifier=observation.source_identifier,
        observation_fingerprint=observation.fingerprint,
        operations=(operation,),
    )


def _authorization(plan: DeploymentPlan) -> DeploymentAuthorization:
    authorization_id = compute_deployment_authorization_id(
        contract_ops_authorization_id="contractops-auth-1",
        deployment_plan_id=plan.deployment_plan_id,
        applied_release_id=plan.applied_release_id,
        allowed=True,
    )
    return DeploymentAuthorization(
        deployment_authorization_id=authorization_id,
        contract_ops_authorization_id="contractops-auth-1",
        deployment_plan_id=plan.deployment_plan_id,
        applied_release_id=plan.applied_release_id,
        allowed=True,
    )




def test_assess_delegates_candidate_to_unified_adapter_entrypoint() -> None:
    plan = _plan()
    adapter = _adapter(plan)

    result = DeploymentService().assess(
        _candidate_contract(),
        candidate_revision_ref="candidate:abc",
        target=plan.target,
        adapter=adapter,
    )

    assert result == adapter.assessment_result
    assert adapter.assess_calls == 1
    assert adapter.assess_calls == 0
    assert adapter.preview_calls == 0
    assert adapter.execute_calls == 0


def test_preview_delegates_to_unified_adapter_entrypoint() -> None:
    plan = _plan()
    adapter = _adapter(plan)

    result = DeploymentService().preview(plan, adapter=adapter)

    assert result == adapter.preview_result
    assert adapter.preview_calls == 1
    assert adapter.execute_calls == 0


def test_execute_delegates_exact_canonical_artifacts() -> None:
    plan = _plan()
    preview = _preview(plan)
    authorization = _authorization(plan)
    adapter = _adapter(plan)

    DeploymentService().execute(
        plan,
        preview,
        authorization,
        adapter=adapter,
    )

    assert adapter.execute_calls == 1
    assert adapter.executed == (plan, preview, authorization)


def test_verify_delegates_to_same_adapter_entrypoint() -> None:
    plan = _plan()
    adapter = _adapter(plan)

    result = DeploymentService().verify(plan, adapter=adapter)

    assert result == adapter.verification_result
    assert adapter.verify_calls == 1


@pytest.mark.parametrize("operation", ["assess", "preview", "verify", "execute"])
def test_service_rejects_adapter_platform_mismatch(operation: str) -> None:
    plan = _plan()
    adapter = _adapter(plan)
    adapter.key = "snowflake"

    with pytest.raises(ValidationError, match="Deployment adapter does not match"):
        if operation == "assess":
            DeploymentService().assess(
                _candidate_contract(),
                candidate_revision_ref="candidate:abc",
                target=plan.target,
                adapter=adapter,
            )
        elif operation == "preview":
            DeploymentService().preview(plan, adapter=adapter)
        elif operation == "verify":
            DeploymentService().verify(plan, adapter=adapter)
        else:
            DeploymentService().execute(
                plan,
                _preview(plan),
                _authorization(plan),
                adapter=adapter,
            )

    assert adapter.preview_calls == 0
    assert adapter.verify_calls == 0
    assert adapter.execute_calls == 0
