from __future__ import annotations

import json
import uuid
from datetime import date

from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.application.services.release_workflow import (
    ReleaseFinalizer,
    ReleaseWorkflowService,
)
from semapact.change_context import ChangeContext
from semapact.contractops import (
    VersionAuthority,
    VersionAuthorityConfig,
    build_change_set_from_decision,
    build_release_plan,
    resolve_release_version,
)
from semapact.deployment import (
    DeploymentTarget,
    build_contract_release_deployment_source,
    build_deployment_plan_from_source,
)
from semapact.governance import evaluate_governance_decision
from semapact.runtime import RuntimeAssetSpec, runtime_asset_specs_from_contract
from semapact.utils.deterministic import canonical_compact_json, deterministic_uuid5
from semapact.versioning import normalize_semver


CONTEXT = ChangeContext(effective_date=date(2026, 9, 10))


def _contract(
    *,
    name: str = "Orders",
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
        version="1.0.0",
        status="active",
        schema=[SchemaObject(name="orders", properties=properties)],
    )


def _finalized_allow_release():
    workflow = ReleaseWorkflowService()
    bundle = workflow.assess(
        _contract(name="Orders old"),
        _contract(name="Orders new"),
        effective_date="2026-09-10",
        base_revision_ref="rev:base",
        candidate_revision_ref="rev:candidate",
    )
    return ReleaseFinalizer().finalize(bundle)


def test_deterministic_helper_uses_canonical_compact_uuid_formula() -> None:
    namespace = uuid.UUID("3ea0f6d8-28ca-4bb4-94f5-ea1f0f48cb84")
    payload = {"z": "é", "a": [2, 1], "nested": {"b": True}}
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

    assert canonical_compact_json(payload) == encoded
    assert deterministic_uuid5(namespace, payload) == str(uuid.uuid5(namespace, encoded))


def test_runtime_asset_projection_has_one_canonical_owner() -> None:
    specs = runtime_asset_specs_from_contract(_contract())

    assert specs == (
        RuntimeAssetSpec(governed_asset="orders", physical_name="orders"),
    )


def test_finalized_release_projects_to_target_specific_canonical_plan() -> None:
    release = _finalized_allow_release()
    source = build_contract_release_deployment_source(release)
    production = build_deployment_plan_from_source(
        source,
        DeploymentTarget(
            platform="databricks",
            runtime_target="main.production",
            source_reference="https://production-workspace.example",
        ),
    )
    staging = build_deployment_plan_from_source(
        source,
        DeploymentTarget(
            platform="databricks",
            runtime_target="main.staging",
            source_reference="https://staging-workspace.example",
        ),
    )

    assert production.source_snapshot_id == source.source_snapshot_id
    assert staging.source_snapshot_id == source.source_snapshot_id
    assert production.deployment_plan_id != staging.deployment_plan_id


def test_same_runtime_namespace_on_another_source_has_distinct_plan_identity() -> None:
    release = _finalized_allow_release()
    source = build_contract_release_deployment_source(release)
    workspace_a = build_deployment_plan_from_source(
        source,
        DeploymentTarget(
            platform="databricks",
            runtime_target="main.production",
            source_reference="https://workspace-a.example",
        ),
    )
    workspace_b = build_deployment_plan_from_source(
        source,
        DeploymentTarget(
            platform="databricks",
            runtime_target="main.production",
            source_reference="https://workspace-b.example",
        ),
    )

    assert workspace_a.deployment_plan_id != workspace_b.deployment_plan_id


def test_version_authorities_preserve_required_bump() -> None:
    base = _contract()
    candidate = _contract(include_created_at=True)
    decision = evaluate_governance_decision(base, candidate, context=CONTEXT)
    change_set = build_change_set_from_decision(
        decision,
        base_revision_ref="rev:base",
        candidate_revision_ref="rev:candidate",
    )
    release_plan = build_release_plan(change_set, decision)

    semapact_resolution = resolve_release_version(
        release_plan,
        current_version="1.0.0",
        config=VersionAuthorityConfig(authority=VersionAuthority.SEMAPACT),
    )
    git_resolution = resolve_release_version(
        release_plan,
        current_version="1.0.0",
        config=VersionAuthorityConfig(
            authority=VersionAuthority.GIT,
            tag_pattern="v{version}",
        ),
        authority_reference="v1.2.0",
    )

    assert decision.required_version_bump == "minor"
    assert semapact_resolution.required_version_bump == "minor"
    assert git_resolution.required_version_bump == "minor"
    assert semapact_resolution.selected_version == "1.1.0"
    assert git_resolution.selected_version == "1.2.0"
    assert normalize_semver("v1.2.3") == "1.2.3"
