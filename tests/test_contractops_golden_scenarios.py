from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
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
from semapact.exceptions import ContractOpsAuthorizationError, GovernanceBlockedError
from semapact.governance import DecisionResult, evaluate_governance_decision


CONTEXT = ChangeContext(effective_date=date(2026, 9, 11))


def _contract(
    *,
    contract_id: str = "orders-product",
    name: str = "orders",
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
        id=contract_id,
        name=name,
        version="1.0.0",
        status="active",
        schema=[
            SchemaObject(
                name="orders",
                physicalName="orders",
                properties=properties,
            )
        ],
    )


def _allow_chain():
    workflow = ReleaseWorkflowService()
    bundle = workflow.assess(
        _contract(name="orders-old"),
        _contract(name="orders-new"),
        effective_date="2026-09-11",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
    )
    release = ReleaseFinalizer().finalize(bundle)
    source = build_contract_release_deployment_source(release)
    plan = build_deployment_plan_from_source(
        source,
        DeploymentTarget(
            platform="databricks",
            runtime_target="main.silver",
            source_reference="workspace:golden",
            server_name="production",
        ),
    )
    return bundle, release, source, plan


def test_allow_chain_has_stable_cross_boundary_semantics() -> None:
    first = _allow_chain()
    second = _allow_chain()

    first_bundle, first_release, first_source, first_plan = first
    second_bundle, second_release, second_source, second_plan = second

    assert first_bundle.decision.decision is DecisionResult.ALLOW
    assert first_bundle.version_resolution.selected_version == "1.0.1"
    assert first_release.contract_version == "1.0.1"
    assert first_release.to_contract().name == "orders-new"
    assert first_source.release_id == first_release.contract_release_id
    assert first_plan.contract_version == first_release.contract_version

    assert first_bundle.bundle_digest == second_bundle.bundle_digest
    assert first_release.contract_release_id == second_release.contract_release_id
    assert first_source.source_snapshot_id == second_source.source_snapshot_id
    assert first_plan.deployment_plan_id == second_plan.deployment_plan_id


def test_review_release_requires_exact_publish_approval() -> None:
    workflow = ReleaseWorkflowService()
    bundle = workflow.assess(
        _contract(name="orders", include_created_at=False),
        _contract(name="orders", include_created_at=True),
        effective_date="2026-09-11",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
    )
    assert bundle.decision.decision is DecisionResult.REVIEW

    with pytest.raises(ContractOpsAuthorizationError, match="requires approval"):
        ReleaseFinalizer().finalize(bundle)

    approval = workflow.approve(
        bundle,
        actor_reference="human:reviewer",
        recorded_at=datetime(2026, 9, 11, 8, tzinfo=timezone.utc),
    )
    release = ReleaseFinalizer().finalize(bundle, approval=approval)

    assert release.contract_version == bundle.version_resolution.selected_version
    assert release.release_snapshot_id == bundle.release_snapshot.release_snapshot_id


def test_block_cannot_enter_release_chain() -> None:
    base = _contract()
    candidate = _contract(contract_id="other-product")
    decision = evaluate_governance_decision(base, candidate, context=CONTEXT)
    change_set = build_change_set_from_decision(
        decision,
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
    )

    assert decision.decision is DecisionResult.BLOCK
    with pytest.raises(GovernanceBlockedError):
        build_release_plan(change_set, decision)


def test_version_authorities_preserve_same_required_bump() -> None:
    base = _contract()
    candidate = _contract(include_created_at=True)
    decision = evaluate_governance_decision(base, candidate, context=CONTEXT)
    change_set = build_change_set_from_decision(
        decision,
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
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
