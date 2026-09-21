from __future__ import annotations

import json

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)
from pydantic import ValidationError as PydanticValidationError

from semapact.contractops import ContractRelease
from semapact.contractops.integrity import compute_contract_release_id
from semapact.deployment import (
    DeploymentAction,
    DeploymentActionKind,
    DeploymentPlan,
    DeploymentTarget,
    build_candidate_deployment_source,
    build_contract_release_deployment_source,
    build_deployment_plan_from_source,
)
from semapact.odcs.serialization import canonical_contract_json


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


def _contract(
    *,
    schemas: list[SchemaObject] | None = None,
    version: str = "1.2.0",
) -> OpenDataContractStandard:
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders-product",
        name="Orders",
        version=version,
        status="active",
        schema=schemas or [_schema("orders")],
    )


def _release(
    *,
    schemas: list[SchemaObject] | None = None,
) -> ContractRelease:
    contract = _contract(schemas=schemas)
    released_contract_json = canonical_contract_json(contract)
    fields = {
        "contract_id": "orders-product",
        "contract_version": "1.2.0",
        "decision_id": "decision:test",
        "change_set_id": "change-set:test",
        "release_plan_id": "release-plan:test",
        "version_resolution_id": "version-resolution:test",
        "release_snapshot_id": "release-snapshot:test",
        "source_revision_ref": "rev:released",
        "released_contract_json": released_contract_json,
    }
    return ContractRelease(
        contract_release_id=compute_contract_release_id(**fields),
        **fields,
    )


def _target() -> DeploymentTarget:
    return DeploymentTarget(
        platform="Databricks",
        runtime_target="main.analytics",
        source_reference="https://workspace.example",
        server_name="production",
    )


def test_candidate_source_produces_canonical_v1_plan() -> None:
    source = build_candidate_deployment_source(
        _contract(),
        revision_ref="rev:candidate",
    )

    plan = build_deployment_plan_from_source(source, _target())

    assert plan.plan_version == "1"
    assert plan.source_snapshot_id == source.source_snapshot_id
    assert plan.contract_id == source.contract_id
    assert plan.contract_version == source.contract_version
    assert not hasattr(plan, "release_id")
    assert not hasattr(plan, "release_plan_id")


def test_finalized_release_source_produces_canonical_v1_plan() -> None:
    release = _release()
    source = build_contract_release_deployment_source(release)

    plan = build_deployment_plan_from_source(source, _target())

    assert plan.plan_version == "1"
    assert source.release_id == release.contract_release_id
    assert plan.source_snapshot_id == source.source_snapshot_id
    assert plan.contract_version == release.contract_version


def test_same_exact_source_and_target_produce_same_plan() -> None:
    source = build_contract_release_deployment_source(
        _release(schemas=[_schema("zeta"), _schema("alpha")])
    )

    first = build_deployment_plan_from_source(source, _target())
    second = build_deployment_plan_from_source(source, _target())

    assert first == second
    assert first.deployment_plan_id == second.deployment_plan_id
    assert [action.governed_asset for action in first.actions] == ["alpha", "zeta"]


def test_actions_are_provider_neutral_ensure_state_intents() -> None:
    source = build_candidate_deployment_source(
        _contract(schemas=[_schema("orders"), _schema("customers")]),
        revision_ref="rev:candidate",
    )
    plan = build_deployment_plan_from_source(source, _target())

    assert plan.actions
    assert all(
        action.kind is DeploymentActionKind.ENSURE_ASSET_STATE
        for action in plan.actions
    )


def test_physical_name_is_binding_hint_not_governed_identity() -> None:
    source = build_candidate_deployment_source(
        _contract(schemas=[_schema("Orders", physical_name="prod_orders_v2")]),
        revision_ref="rev:candidate",
    )
    plan = build_deployment_plan_from_source(source, _target())

    action = plan.actions[0]
    assert action.governed_asset == "orders"
    assert action.physical_name == "prod_orders_v2"


def test_missing_physical_name_falls_back_to_governed_schema_name() -> None:
    source = build_candidate_deployment_source(
        _contract(schemas=[_schema("Orders")]),
        revision_ref="rev:candidate",
    )
    plan = build_deployment_plan_from_source(source, _target())

    assert plan.actions[0].physical_name == "Orders"


def test_target_changes_plan_identity() -> None:
    source = build_contract_release_deployment_source(_release())

    production = build_deployment_plan_from_source(source, _target())
    staging = build_deployment_plan_from_source(
        source,
        DeploymentTarget(
            platform="databricks",
            runtime_target="main.staging",
            source_reference="https://staging-workspace.example",
            server_name="staging",
        ),
    )

    assert production.deployment_plan_id != staging.deployment_plan_id


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


def test_canonical_deployment_plan_rejects_release_provenance_fields() -> None:
    source = build_contract_release_deployment_source(_release())
    plan = build_deployment_plan_from_source(source, _target())
    payload = plan.model_dump(mode="json")
    payload["release_id"] = "unexpected"

    with pytest.raises(PydanticValidationError):
        DeploymentPlan.model_validate(payload)
