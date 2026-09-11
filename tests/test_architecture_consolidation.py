from __future__ import annotations

import json
import uuid
from datetime import date

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.change_context import ChangeContext
from semapact.contractops import (
    AuthorizationReason,
    ReviewAuthorizationEvidence,
    ReviewEvidenceAction,
    VersionAuthorityConfig,
    apply_contract_release,
    authorize_contract_operation,
    build_change_set_from_decision,
    build_release_plan,
    resolve_release_version,
)
from semapact.core.release import (
    classify_contract_change as legacy_classify_contract_change,
    normalize_semver as legacy_normalize_semver,
)
from semapact.deployment import (
    DeploymentTarget,
    authorize_deployment,
    build_deployment_plan,
)
from semapact.exceptions import ReleaseValidationError
from semapact.governance import DecisionResult, evaluate_governance_decision
from semapact.governance.change_classification import classify_contract_change
from semapact.governance.gate import GovernanceOperation
from semapact.observation import RuntimeAssetSpec as ObservationRuntimeAssetSpec
from semapact.reconciliation.binding import (
    runtime_asset_specs_from_contract as legacy_runtime_asset_specs_from_contract,
)
from semapact.runtime import RuntimeAssetSpec, runtime_asset_specs_from_contract
from semapact.utils.deterministic import canonical_compact_json, deterministic_uuid5
from semapact.versioning import normalize_semver


CONTEXT = ChangeContext(effective_date=date(2026, 9, 10))


def _contract(*, include_created_at: bool = False) -> OpenDataContractStandard:
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
        name="Orders",
        version="1.0.0",
        status="active",
        schema=[SchemaObject(name="orders", properties=properties)],
    )


def _review_release_chain():
    base = _contract()
    candidate = _contract(include_created_at=True)
    decision = evaluate_governance_decision(base, candidate, context=CONTEXT)
    assert decision.decision is DecisionResult.REVIEW

    change_set = build_change_set_from_decision(
        decision,
        base_revision_ref="rev:base",
        candidate_revision_ref="rev:candidate",
    )
    release_plan = build_release_plan(change_set, decision)
    version_resolution = resolve_release_version(
        release_plan,
        current_version="1.0.0",
        config=VersionAuthorityConfig(),
    )
    apply_evidence = ReviewAuthorizationEvidence(
        evidence_reference="approval:apply",
        decision_id=decision.decision_id,
        change_set_id=change_set.change_set_id,
        release_plan_id=release_plan.release_plan_id,
        version_resolution_id=version_resolution.version_resolution_id,
        operation=GovernanceOperation.APPLY,
        action=ReviewEvidenceAction.APPROVE,
    )
    apply_authorization = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.APPLY,
        evidence=apply_evidence,
    )
    release = apply_contract_release(
        candidate,
        candidate_revision_ref="rev:candidate",
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        authorization=apply_authorization,
    )
    return decision, change_set, release_plan, version_resolution, release


def test_deterministic_helper_preserves_existing_compact_uuid_formula() -> None:
    namespace = uuid.UUID("3ea0f6d8-28ca-4bb4-94f5-ea1f0f48cb84")
    payload = {"z": "é", "a": [2, 1], "nested": {"b": True}}

    legacy_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    legacy_id = str(uuid.uuid5(namespace, legacy_json))

    assert canonical_compact_json(payload) == legacy_json
    assert deterministic_uuid5(namespace, payload) == legacy_id


def test_legacy_release_imports_delegate_to_canonical_owners() -> None:
    assert legacy_normalize_semver is normalize_semver
    assert legacy_classify_contract_change is classify_contract_change
    assert legacy_normalize_semver("v1.2.3") == "1.2.3"


def test_reconciliation_asset_projection_remains_compatible_but_neutral() -> None:
    assert legacy_runtime_asset_specs_from_contract is runtime_asset_specs_from_contract
    assert ObservationRuntimeAssetSpec is RuntimeAssetSpec

    specs = runtime_asset_specs_from_contract(_contract())
    assert specs == (RuntimeAssetSpec(governed_asset="orders", physical_name="orders"),)


def test_review_deploy_authorization_is_bound_to_exact_deployment_plan() -> None:
    decision, change_set, release_plan, version_resolution, release = _review_release_chain()
    production_plan = build_deployment_plan(
        release,
        DeploymentTarget(
            platform="databricks",
            runtime_target="main.production",
            source_reference="https://production-workspace.example",
        ),
    )

    evidence = ReviewAuthorizationEvidence(
        evidence_reference="approval:deploy-production",
        decision_id=decision.decision_id,
        change_set_id=change_set.change_set_id,
        release_plan_id=release_plan.release_plan_id,
        version_resolution_id=version_resolution.version_resolution_id,
        operation=GovernanceOperation.DEPLOY,
        action=ReviewEvidenceAction.APPROVE,
        scope_reference=production_plan.deployment_plan_id,
    )
    contractops_authorization = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.DEPLOY,
        evidence=evidence,
    )

    assert contractops_authorization.allowed is True
    assert contractops_authorization.reason is AuthorizationReason.ALLOWED_BY_REVIEW
    assert contractops_authorization.scope_reference == production_plan.deployment_plan_id

    deployment_authorization = authorize_deployment(
        production_plan,
        release,
        contractops_authorization,
    )
    assert deployment_authorization.allowed is True
    assert deployment_authorization.deployment_plan_id == production_plan.deployment_plan_id

    staging_plan = build_deployment_plan(
        release,
        DeploymentTarget(
            platform="databricks",
            runtime_target="main.staging",
            source_reference="https://staging-workspace.example",
        ),
    )
    with pytest.raises(ReleaseValidationError, match="not scoped to this DeploymentPlan"):
        authorize_deployment(staging_plan, release, contractops_authorization)


def test_same_runtime_namespace_on_another_source_requires_distinct_plan() -> None:
    _, _, _, _, release = _review_release_chain()
    workspace_a = build_deployment_plan(
        release,
        DeploymentTarget(
            platform="databricks",
            runtime_target="main.production",
            source_reference="https://workspace-a.example",
        ),
    )
    workspace_b = build_deployment_plan(
        release,
        DeploymentTarget(
            platform="databricks",
            runtime_target="main.production",
            source_reference="https://workspace-b.example",
        ),
    )

    assert workspace_a.deployment_plan_id != workspace_b.deployment_plan_id


def test_publish_authorization_cannot_be_reused_for_runtime_deploy() -> None:
    decision, change_set, release_plan, version_resolution, release = _review_release_chain()
    plan = build_deployment_plan(
        release,
        DeploymentTarget(
            platform="databricks",
            runtime_target="main.production",
            source_reference="https://production-workspace.example",
        ),
    )
    evidence = ReviewAuthorizationEvidence(
        evidence_reference="approval:publish",
        decision_id=decision.decision_id,
        change_set_id=change_set.change_set_id,
        release_plan_id=release_plan.release_plan_id,
        version_resolution_id=version_resolution.version_resolution_id,
        operation=GovernanceOperation.PUBLISH,
        action=ReviewEvidenceAction.APPROVE,
    )
    publish_authorization = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.PUBLISH,
        evidence=evidence,
    )

    with pytest.raises(ReleaseValidationError, match="DEPLOY authorization"):
        authorize_deployment(plan, release, publish_authorization)
