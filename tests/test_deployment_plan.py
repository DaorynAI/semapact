from __future__ import annotations

import json

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)
from pydantic import ValidationError as PydanticValidationError

from semapact.contractops import AppliedContractRelease
from semapact.deployment import (
    DeploymentAction,
    DeploymentActionKind,
    DeploymentTarget,
    build_deployment_plan,
)


def _schema(
    name: str,
    *,
    physical_name: str | None = None,
) -> SchemaObject:
    return SchemaObject(
        name=name,
        physicalName=physical_name,
        properties=[
            SchemaProperty(
                name="id",
                logicalType="string",
                physicalType="varchar(255)",
                required=True,
            )
        ],
    )


def _release(
    *,
    schemas: list[SchemaObject] | None = None,
    applied_release_id: str = "applied-release:test",
) -> AppliedContractRelease:
    contract = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders-product",
        name="Orders",
        version="1.2.0",
        status="active",
        schema=schemas or [_schema("orders")],
    )
    released_contract_json = json.dumps(
        contract.model_dump(mode="json", by_alias=True, exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return AppliedContractRelease(
        applied_release_id=applied_release_id,
        contract_id="orders-product",
        decision_id="decision:test",
        change_set_id="change-set:test",
        release_plan_id="release-plan:test",
        version_resolution_id="version-resolution:test",
        release_revision_ref="rev:released",
        selected_version="1.2.0",
        authorization_id="authorization:test",
        released_contract_json=released_contract_json,
    )


def _target() -> DeploymentTarget:
    return DeploymentTarget(
        platform="Databricks",
        runtime_target="main.analytics",
        server_name="production",
    )


def test_same_exact_release_and_target_produce_same_plan() -> None:
    release = _release(schemas=[_schema("zeta"), _schema("alpha")])

    first = build_deployment_plan(release, _target())
    second = build_deployment_plan(release, _target())

    assert first == second
    assert first.deployment_plan_id == second.deployment_plan_id
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert [action.governed_asset for action in first.actions] == ["alpha", "zeta"]


def test_plan_preserves_exact_applied_release_provenance() -> None:
    release = _release()

    plan = build_deployment_plan(release, _target())

    assert plan.applied_release_id == release.applied_release_id
    assert plan.contract_id == release.contract_id
    assert plan.release_plan_id == release.release_plan_id
    assert plan.released_revision_ref == release.release_revision_ref
    assert plan.selected_version == release.selected_version
    assert plan.plan_version == "1"


def test_actions_are_provider_neutral_ensure_state_intents() -> None:
    plan = build_deployment_plan(
        _release(schemas=[_schema("orders"), _schema("customers")]),
        _target(),
    )

    assert plan.actions
    assert all(
        action.kind is DeploymentActionKind.ENSURE_ASSET_STATE
        for action in plan.actions
    )
    assert {action.kind.value for action in plan.actions} == {"ENSURE_ASSET_STATE"}


def test_physical_name_is_binding_hint_not_governed_identity() -> None:
    plan = build_deployment_plan(
        _release(schemas=[_schema("Orders", physical_name="prod_orders_v2")]),
        _target(),
    )

    action = plan.actions[0]
    assert action.governed_asset == "orders"
    assert action.physical_name == "prod_orders_v2"

    desired = SchemaObject.model_validate_json(action.desired_state_json)
    assert desired.name == "Orders"
    assert desired.physicalName == "prod_orders_v2"


def test_missing_physical_name_falls_back_to_governed_schema_name() -> None:
    plan = build_deployment_plan(
        _release(schemas=[_schema("Orders")]),
        _target(),
    )

    action = plan.actions[0]
    assert action.governed_asset == "orders"
    assert action.physical_name == "Orders"


def test_target_is_explicit_and_changes_plan_identity() -> None:
    release = _release()

    production = build_deployment_plan(release, _target())
    staging = build_deployment_plan(
        release,
        DeploymentTarget(
            platform="databricks",
            runtime_target="main.staging",
            server_name="staging",
        ),
    )

    assert production.deployment_plan_id != staging.deployment_plan_id
    assert production.target.platform == "databricks"
    assert staging.target.runtime_target == "main.staging"


def test_schema_order_is_canonicalized_within_each_exact_release() -> None:
    first_release = _release(
        schemas=[_schema("zeta"), _schema("alpha")],
        applied_release_id="applied-release:first",
    )
    second_release = _release(
        schemas=[_schema("alpha"), _schema("zeta")],
        applied_release_id="applied-release:second",
    )

    first = build_deployment_plan(first_release, _target())
    second = build_deployment_plan(second_release, _target())

    assert [action.governed_asset for action in first.actions] == ["alpha", "zeta"]
    assert [action.governed_asset for action in second.actions] == ["alpha", "zeta"]
    # Exact release identity remains authoritative; #115 does not collapse two
    # distinct AppliedContractRelease artifacts into one plan identity.
    assert first.deployment_plan_id != second.deployment_plan_id


def test_desired_state_identity_mismatch_fails_closed() -> None:
    schema = _schema("orders")
    desired_state_json = json.dumps(
        schema.model_dump(mode="json", by_alias=True, exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
    )

    with pytest.raises(PydanticValidationError, match="governed_asset"):
        DeploymentAction(
            kind=DeploymentActionKind.ENSURE_ASSET_STATE,
            governed_asset="customers",
            physical_name="orders",
            desired_state_json=desired_state_json,
        )


def test_deployment_models_are_immutable() -> None:
    plan = build_deployment_plan(_release(), _target())

    with pytest.raises(PydanticValidationError):
        plan.selected_version = "9.9.9"  # type: ignore[misc]
