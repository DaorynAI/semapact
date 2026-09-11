from __future__ import annotations

from datetime import datetime, timezone

import pytest
from open_data_contract_standard.model import SchemaObject, SchemaProperty

from semapact.deployment import (
    DeploymentAction,
    DeploymentActionKind,
    DeploymentAuthorization,
    DeploymentPlan,
    DeploymentPreview,
    DeploymentTarget,
    NativeOperation,
    NativeOperationKind,
)
from semapact.deployment.models import (
    compute_deployment_authorization_id,
    compute_deployment_plan_id,
    compute_deployment_preview_id,
)
from semapact.exceptions import ValidationError
from semapact.observation import (
    ObservedAsset,
    ObservedAssetIdentity,
    ObservedPlatformState,
    ObservedProperty,
    ObservedPropertyIdentity,
    RuntimeAssetBinding,
    with_observed_state_fingerprint,
)
from semapact.reconciliation import RuntimeDriftStatus, classify_reconciliation_status
from semapact.services.deployment_service import DeploymentService

CAPTURED_AT = datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc)
SOURCE_REFERENCE = "https://adb.example"


class FakeRuntimeProvider:
    key = "databricks"

    def __init__(self, observation: ObservedPlatformState) -> None:
        self.observation = observation
        self.resolve_calls = 0
        self.observe_calls = 0
        self.bindings: tuple[RuntimeAssetBinding, ...] = ()

    def resolve_bindings(self, *, runtime_target: str, assets):
        assert runtime_target == "main.silver"
        self.resolve_calls += 1
        self.bindings = tuple(
            RuntimeAssetBinding(
                governed_asset=asset.governed_asset,
                observed_asset=ObservedAssetIdentity(
                    platform="databricks",
                    namespace=("main", "silver"),
                    asset=asset.physical_name,
                ),
            )
            for asset in assets
        )
        return self.bindings

    def observe(self, *, bindings):
        assert tuple(bindings) == self.bindings
        self.observe_calls += 1
        return self.observation


class FakeDeploymentAdapter:
    key = "databricks"

    def __init__(self, preview: DeploymentPreview) -> None:
        self.preview_result = preview
        self.preview_calls = 0
        self.execute_calls = 0
        self.executed = None

    def validate(self, plan: DeploymentPlan) -> None:
        pass

    def preview(self, plan: DeploymentPlan, observed_state: ObservedPlatformState):
        self.preview_calls += 1
        assert observed_state.fingerprint == self.preview_result.observation_fingerprint
        return self.preview_result

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


def _observation(*, source: str = SOURCE_REFERENCE) -> ObservedPlatformState:
    asset_identity = ObservedAssetIdentity(
        platform="databricks",
        namespace=("main", "silver"),
        asset="orders_v2",
    )
    return with_observed_state_fingerprint(
        ObservedPlatformState(
            platform="databricks",
            source_identifier=source,
            captured_at=CAPTURED_AT,
            assets=(
                ObservedAsset(
                    identity=asset_identity,
                    asset_type="MANAGED",
                    properties=(
                        ObservedProperty(
                            identity=ObservedPropertyIdentity(
                                asset=asset_identity,
                                property="order_pk",
                            ),
                            physical_type="BIGINT",
                            nullable=False,
                        ),
                    ),
                ),
            ),
            fingerprint=None,
        )
    )


def _preview(plan: DeploymentPlan, observation: ObservedPlatformState) -> DeploymentPreview:
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


def test_preview_orchestrates_observation_without_execution() -> None:
    plan = _plan()
    observation = _observation()
    provider = FakeRuntimeProvider(observation)
    adapter = FakeDeploymentAdapter(_preview(plan, observation))

    result = DeploymentService().preview(
        plan,
        runtime_provider=provider,
        adapter=adapter,
    )

    assert result == adapter.preview_result
    assert provider.resolve_calls == 1
    assert provider.observe_calls == 1
    assert adapter.preview_calls == 1
    assert adapter.execute_calls == 0


def test_preview_rejects_runtime_source_mismatch() -> None:
    plan = _plan()
    observation = _observation(source="https://other-workspace.example")
    provider = FakeRuntimeProvider(observation)
    adapter = FakeDeploymentAdapter(_preview(plan, observation))

    with pytest.raises(ValidationError, match="source reference"):
        DeploymentService().preview(
            plan,
            runtime_provider=provider,
            adapter=adapter,
        )

    assert provider.observe_calls == 1
    assert adapter.preview_calls == 0


def test_execute_delegates_exact_canonical_artifacts() -> None:
    plan = _plan()
    observation = _observation()
    preview = _preview(plan, observation)
    authorization = _authorization(plan)
    adapter = FakeDeploymentAdapter(preview)

    DeploymentService().execute(
        plan,
        preview,
        authorization,
        adapter=adapter,
    )

    assert adapter.execute_calls == 1
    assert adapter.executed == (plan, preview, authorization)


def test_verify_reuses_existing_m1_reconciliation() -> None:
    plan = _plan()
    provider = FakeRuntimeProvider(_observation())

    result = DeploymentService().verify(plan, runtime_provider=provider)

    assert classify_reconciliation_status(result) is RuntimeDriftStatus.IN_SYNC
    assert result.contract_id == plan.contract_id
    assert result.contract_version == plan.selected_version


def test_preview_provider_mismatch_fails_before_observation() -> None:
    plan = _plan()
    observation = _observation()
    provider = FakeRuntimeProvider(observation)
    provider.key = "snowflake"
    adapter = FakeDeploymentAdapter(_preview(plan, observation))

    with pytest.raises(ValidationError, match="Runtime provider does not match"):
        DeploymentService().preview(
            plan,
            runtime_provider=provider,
            adapter=adapter,
        )

    assert provider.resolve_calls == 0
    assert provider.observe_calls == 0
    assert adapter.preview_calls == 0
