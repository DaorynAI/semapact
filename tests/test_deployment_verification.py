from __future__ import annotations

from datetime import datetime, timezone

import pytest
from open_data_contract_standard.model import SchemaObject, SchemaProperty

from semapact.deployment import (
    DeploymentAction,
    DeploymentActionKind,
    DeploymentPlan,
    DeploymentTarget,
    verify_deployment_convergence,
)
from semapact.deployment.models import compute_deployment_plan_id
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

CAPTURED_AT = datetime(2026, 9, 10, 7, 0, tzinfo=timezone.utc)


class FakeRuntimeProvider:
    key = "databricks"

    def __init__(self, observation: ObservedPlatformState) -> None:
        self.observation = observation
        self.bindings: tuple[RuntimeAssetBinding, ...] = ()

    def resolve_bindings(self, *, runtime_target: str, assets):
        assert runtime_target == "main.silver"
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
        return self.observation


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
    target = DeploymentTarget(platform="databricks", runtime_target="main.silver")
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


def _observation(
    *,
    physical_type: str | None = "BIGINT",
    nullable: bool | None = False,
) -> ObservedPlatformState:
    asset_identity = ObservedAssetIdentity(
        platform="databricks",
        namespace=("main", "silver"),
        asset="orders_v2",
    )
    state = ObservedPlatformState(
        platform="databricks",
        source_identifier="https://adb.example",
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
                        physical_type=physical_type,
                        nullable=nullable,
                    ),
                ),
            ),
        ),
        fingerprint=None,
    )
    return with_observed_state_fingerprint(state)


def test_exact_plan_state_is_verified_in_sync_through_physical_bindings() -> None:
    result = verify_deployment_convergence(_plan(), FakeRuntimeProvider(_observation()))

    assert result.contract_id == "orders-contract"
    assert result.contract_version == "1.2.3"
    assert result.differences == ()
    assert result.unverified_paths == ()
    assert classify_reconciliation_status(result) is RuntimeDriftStatus.IN_SYNC


def test_runtime_difference_is_reported_as_drift() -> None:
    result = verify_deployment_convergence(
        _plan(),
        FakeRuntimeProvider(_observation(physical_type="STRING")),
    )

    assert len(result.differences) == 1
    assert result.differences[0].property_identity == "order_id"
    assert classify_reconciliation_status(result) is RuntimeDriftStatus.DRIFT


def test_missing_runtime_evidence_is_indeterminate() -> None:
    result = verify_deployment_convergence(
        _plan(),
        FakeRuntimeProvider(_observation(physical_type=None)),
    )

    assert result.differences == ()
    assert result.unverified_paths == ("schema[orders].properties[order_id].physicalType",)
    assert classify_reconciliation_status(result) is RuntimeDriftStatus.INDETERMINATE


def test_verification_uses_exact_deployment_plan_version() -> None:
    result = verify_deployment_convergence(_plan(), FakeRuntimeProvider(_observation()))

    assert result.contract_version == "1.2.3"


def test_provider_platform_mismatch_fails_closed() -> None:
    provider = FakeRuntimeProvider(_observation())
    provider.key = "snowflake"

    with pytest.raises(ValidationError, match="does not match DeploymentPlan platform"):
        verify_deployment_convergence(_plan(), provider)


def test_tampered_deployment_plan_identity_fails_closed() -> None:
    plan = _plan().model_copy(update={"selected_version": "9.9.9"})

    with pytest.raises(ValueError, match="deterministic identity"):
        verify_deployment_convergence(plan, FakeRuntimeProvider(_observation()))
