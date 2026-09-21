from __future__ import annotations

import json

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)
from pydantic import ValidationError as PydanticValidationError

from semapact.contractops import AppliedContractRelease, ReleaseSnapshot
from semapact.contractops.integrity import (
    compute_applied_release_id,
    compute_release_snapshot_id,
)
from semapact.deployment.compatibility import (
    build_legacy_deployment_plan,
    parse_deployment_plan_payload,
    serialize_deployment_plan_payload,
)
from semapact.deployment.models import (
    SEMAPACT_DEPLOYMENT_PLAN_NAMESPACE,
    DeploymentAction,
    DeploymentActionKind,
    DeploymentPlan,
    DeploymentTarget,
)
from semapact.utils.deterministic import deterministic_uuid5


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
    fields = {
        "contract_id": "orders-product",
        "decision_id": "decision:test",
        "change_set_id": "change-set:test",
        "release_plan_id": "release-plan:test",
        "version_resolution_id": "version-resolution:test",
        "release_revision_ref": "rev:released",
        "selected_version": "1.2.0",
        "authorization_id": "authorization:test",
        "released_contract_json": released_contract_json,
    }
    return AppliedContractRelease(
        applied_release_id=compute_applied_release_id(**fields),
        **fields,
    )


def _snapshot(
    *,
    schemas: list[SchemaObject] | None = None,
) -> ReleaseSnapshot:
    applied = _release(schemas=schemas)
    fields = {
        "contract_id": applied.contract_id,
        "decision_id": applied.decision_id,
        "change_set_id": applied.change_set_id,
        "release_plan_id": applied.release_plan_id,
        "version_resolution_id": applied.version_resolution_id,
        "release_revision_ref": applied.release_revision_ref,
        "selected_version": applied.selected_version,
        "released_contract_json": applied.released_contract_json,
    }
    return ReleaseSnapshot(
        release_snapshot_id=compute_release_snapshot_id(**fields),
        **fields,
    )


def _target() -> DeploymentTarget:
    return DeploymentTarget(
        platform="Databricks",
        runtime_target="main.analytics",
        source_reference="https://workspace.example",
        server_name="production",
    )


def test_legacy_release_snapshot_is_adapted_to_canonical_v5_plan() -> None:
    snapshot = _snapshot()

    plan = build_legacy_deployment_plan(snapshot, _target())

    assert plan.plan_version == "5"
    assert plan.source_snapshot_id == snapshot.release_snapshot_id
    assert plan.contract_id == snapshot.contract_id
    assert plan.contract_version == snapshot.selected_version
    payload = serialize_deployment_plan_payload(plan)
    assert payload["plan_version"] == "5"
    assert "release_id" not in payload
    assert "release_plan_id" not in payload
    assert "applied_release_id" not in payload
    assert "selected_version" not in payload


def test_same_exact_legacy_release_and_target_produce_same_canonical_plan() -> None:
    release = _release(schemas=[_schema("zeta"), _schema("alpha")])

    first = build_legacy_deployment_plan(release, _target())
    second = build_legacy_deployment_plan(release, _target())

    assert first == second
    assert first.deployment_plan_id == second.deployment_plan_id
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert [action.governed_asset for action in first.actions] == ["alpha", "zeta"]


def test_legacy_v2_wire_payload_upgrades_to_canonical_identity() -> None:
    release = _release()
    canonical = build_legacy_deployment_plan(release, _target())
    legacy_payload = {
        "applied_release_id": release.applied_release_id,
        "contract_id": release.contract_id,
        "release_plan_id": release.release_plan_id,
        "released_revision_ref": release.release_revision_ref,
        "selected_version": release.selected_version,
        "target": canonical.target.model_dump(mode="json"),
        "actions": [action.model_dump(mode="json") for action in canonical.actions],
        "plan_version": "2",
    }
    legacy_payload["deployment_plan_id"] = deterministic_uuid5(
        SEMAPACT_DEPLOYMENT_PLAN_NAMESPACE,
        {
            **legacy_payload,
            "target": canonical.target.model_dump(mode="json"),
            "actions": [action.model_dump(mode="json") for action in canonical.actions],
        },
    )

    upgraded = parse_deployment_plan_payload(legacy_payload)

    assert upgraded == canonical
    assert upgraded.plan_version == "5"
    assert upgraded.deployment_plan_id != legacy_payload["deployment_plan_id"]


def test_legacy_v2_wire_payload_tamper_fails_closed() -> None:
    release = _release()
    canonical = build_legacy_deployment_plan(release, _target())
    legacy_payload = {
        "deployment_plan_id": "legacy:stale",
        "applied_release_id": release.applied_release_id,
        "contract_id": release.contract_id,
        "release_plan_id": release.release_plan_id,
        "released_revision_ref": release.release_revision_ref,
        "selected_version": release.selected_version,
        "target": canonical.target.model_dump(mode="json"),
        "actions": [action.model_dump(mode="json") for action in canonical.actions],
        "plan_version": "2",
    }

    with pytest.raises(ValueError, match="Legacy DeploymentPlan deterministic identity"):
        parse_deployment_plan_payload(legacy_payload)


def test_actions_are_provider_neutral_ensure_state_intents() -> None:
    plan = build_legacy_deployment_plan(
        _release(schemas=[_schema("orders"), _schema("customers")]),
        _target(),
    )

    assert plan.actions
    assert all(
        action.kind is DeploymentActionKind.ENSURE_ASSET_STATE
        for action in plan.actions
    )


def test_physical_name_is_binding_hint_not_governed_identity() -> None:
    plan = build_legacy_deployment_plan(
        _release(schemas=[_schema("Orders", physical_name="prod_orders_v2")]),
        _target(),
    )

    action = plan.actions[0]
    assert action.governed_asset == "orders"
    assert action.physical_name == "prod_orders_v2"


def test_target_changes_canonical_plan_identity() -> None:
    release = _release()

    production = build_legacy_deployment_plan(release, _target())
    staging = build_legacy_deployment_plan(
        release,
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


def test_canonical_deployment_plan_rejects_legacy_fields() -> None:
    plan = build_legacy_deployment_plan(_release(), _target())
    payload = plan.model_dump(mode="json")
    payload["release_id"] = "legacy-release"

    with pytest.raises(PydanticValidationError):
        DeploymentPlan.model_validate(payload)
