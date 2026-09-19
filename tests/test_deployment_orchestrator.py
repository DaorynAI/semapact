from __future__ import annotations

from datetime import datetime, timezone

import pytest

from open_data_contract_standard.model import SchemaObject, SchemaProperty

from semapact.deployment.compilers import TransitionCompiler
from semapact.deployment.models import (
    DeploymentAction,
    DeploymentActionKind,
    DeploymentAuthorization,
    DeploymentPlan,
    DeploymentTarget,
    NativeOperation,
    NativeOperationKind,
    compute_deployment_authorization_id,
    compute_deployment_plan_id,
)
from semapact.deployment.orchestrator import DeploymentOrchestrator
from semapact.deployment.providers import DeploymentPlatform, NativeOperationExecutor
from semapact.deployment.schema_transitions import (
    SchemaTransition,
    SchemaTransitionKind,
)
from semapact.observation.fingerprint import with_observed_state_fingerprint
from semapact.observation.models import (
    ObservedAsset,
    ObservedAssetIdentity,
    ObservedPlatformState,
)
from semapact.observation.providers import RuntimeAssetBinding
from semapact.reconciliation import RuntimeDriftStatus, classify_reconciliation_status
from semapact.schema import PassThroughSchemaMapper, SchemaAssetState


class _RuntimeProvider:
    key = "fake"

    def __init__(self, state: ObservedPlatformState) -> None:
        self.state = state
        self.observe_calls = 0

    def resolve_bindings(self, *, runtime_target, assets):
        assert runtime_target == "main"
        assert tuple(asset.physical_name for asset in assets) == ("orders",)
        return (
            RuntimeAssetBinding(
                governed_asset="orders",
                observed_asset=ObservedAssetIdentity(
                    platform="fake",
                    namespace=("main",),
                    asset="orders",
                ),
            ),
        )

    def observe(self, *, bindings):
        assert len(tuple(bindings)) == 1
        self.observe_calls += 1
        return self.state


class _Compiler(TransitionCompiler):
    key = "fake"

    def compile(
        self,
        *,
        runtime_target: str,
        transition: SchemaTransition,
    ) -> NativeOperation:
        assert runtime_target == "main"
        if transition.kind is SchemaTransitionKind.NO_OP:
            return NativeOperation(
                kind=NativeOperationKind.NO_OP,
                governed_asset=transition.governed_asset,
            )
        return NativeOperation(
            kind=(
                NativeOperationKind.CREATE
                if transition.kind is SchemaTransitionKind.CREATE_ASSET
                else NativeOperationKind.ALTER
            ),
            governed_asset=transition.governed_asset,
            statement=f"{transition.kind.value} {transition.physical_name}",
        )


class _Platform(DeploymentPlatform):
    key = "fake"

    def __init__(self, runtime_provider: _RuntimeProvider) -> None:
        self.runtime_provider = runtime_provider
        self.schema_mapper = PassThroughSchemaMapper()
        self.transition_compiler = _Compiler()

    def validate_target(self, target: DeploymentTarget) -> None:
        assert target.runtime_target == "main"

    def validate_desired_asset(
        self,
        *,
        target: DeploymentTarget,
        physical_name: str,
        desired: SchemaObject,
        mapped: SchemaAssetState,
    ) -> None:
        assert target.platform == "fake"
        assert physical_name == "orders"
        assert desired.name == "orders"
        assert mapped.identity == "orders"

    def validate_observed_asset(
        self,
        *,
        target: DeploymentTarget,
        physical_name: str,
        observed: ObservedAsset,
    ) -> None:
        raise AssertionError("missing asset scenario should not validate an observed asset")


class _Executor(NativeOperationExecutor):
    key = "fake"

    def __init__(self) -> None:
        self.operations: list[NativeOperation] = []

    def execute(self, operation: NativeOperation) -> None:
        self.operations.append(operation)


def _plan() -> DeploymentPlan:
    schema = SchemaObject(
        name="orders",
        physicalName="orders",
        physicalType="table",
        properties=[
            SchemaProperty(
                name="id",
                logicalType="integer",
                physicalType="BIGINT",
                required=False,
            )
        ],
    )
    action = DeploymentAction(
        kind=DeploymentActionKind.ENSURE_ASSET_STATE,
        governed_asset="orders",
        physical_name="orders",
        desired_state_json=schema.model_dump_json(by_alias=True),
    )
    target = DeploymentTarget(
        platform="fake",
        runtime_target="main",
        source_reference="source-1",
    )
    kwargs = dict(
        applied_release_id="release-1",
        contract_id="contract-1",
        release_plan_id="release-plan-1",
        released_revision_ref="revision-1",
        selected_version="1.0.0",
        target=target,
        actions=(action,),
    )
    return DeploymentPlan(
        deployment_plan_id=compute_deployment_plan_id(**kwargs),
        **kwargs,
    )


def _observation() -> ObservedPlatformState:
    return with_observed_state_fingerprint(
        ObservedPlatformState(
            platform="fake",
            source_identifier="source-1",
            assets=(),
            captured_at=datetime(2026, 9, 19, tzinfo=timezone.utc),
        )
    )


def test_generic_orchestrator_owns_observe_preview_freshness_and_execute() -> None:
    plan = _plan()
    runtime_provider = _RuntimeProvider(_observation())
    executor = _Executor()
    orchestrator = DeploymentOrchestrator(
        platform=_Platform(runtime_provider),
        executor=executor,
    )

    preview = orchestrator.preview(plan)

    assert runtime_provider.observe_calls == 1
    assert len(preview.operations) == 1
    assert preview.operations[0].kind is NativeOperationKind.CREATE
    assert preview.operations[0].statement == "CREATE_ASSET orders"

    authorization_id = compute_deployment_authorization_id(
        contract_ops_authorization_id="contract-auth-1",
        deployment_plan_id=plan.deployment_plan_id,
        applied_release_id=plan.applied_release_id,
        allowed=True,
    )
    authorization = DeploymentAuthorization(
        deployment_authorization_id=authorization_id,
        contract_ops_authorization_id="contract-auth-1",
        deployment_plan_id=plan.deployment_plan_id,
        applied_release_id=plan.applied_release_id,
        allowed=True,
    )

    orchestrator.execute(plan, preview, authorization)

    assert runtime_provider.observe_calls == 2
    assert executor.operations == [preview.operations[0]]


def test_generic_orchestrator_owns_verification_entrypoint() -> None:
    plan = _plan()
    runtime_provider = _RuntimeProvider(_observation())
    orchestrator = DeploymentOrchestrator(
        platform=_Platform(runtime_provider),
        executor=_Executor(),
    )

    result = orchestrator.verify(plan)

    assert runtime_provider.observe_calls == 1
    assert classify_reconciliation_status(result) is RuntimeDriftStatus.DRIFT
    assert result.differences[0].asset_identity == "orders"


def test_generic_orchestrator_rejects_component_key_mismatch() -> None:
    runtime_provider = _RuntimeProvider(_observation())
    executor = _Executor()
    executor.key = "other"

    with pytest.raises(ValueError, match="executor keys must match"):
        DeploymentOrchestrator(
            platform=_Platform(runtime_provider),
            executor=executor,
        )
