from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.change_context import ChangeContext
from semapact.contractops import (
    ReviewAuthorizationEvidence,
    ReviewEvidenceAction,
    VersionAuthority,
    VersionAuthorityConfig,
    apply_contract_release,
    authorize_contract_operation,
    build_change_set_from_decision,
    build_release_plan,
    resolve_release_version,
)
from semapact.deployment import (
    DeploymentTarget,
    authorize_deployment,
    build_deployment_plan,
    verify_deployment_convergence,
)
from semapact.exceptions import (
    ContractOpsAuthorizationError,
    GovernanceBlockedError,
    ReleaseValidationError,
    ValidationError,
)
from semapact.governance import DecisionResult, evaluate_governance_decision
from semapact.governance.gate import GovernanceOperation
from semapact.observation.fingerprint import with_observed_state_fingerprint
from semapact.observation.models import (
    ObservedAsset,
    ObservedAssetIdentity,
    ObservedPlatformState,
    ObservedProperty,
    ObservedPropertyIdentity,
)
from semapact.observation.providers import RuntimeAssetBinding
from semapact.platforms.databricks.deployment import DatabricksDeploymentAdapter
from semapact.reconciliation import RuntimeDriftStatus, classify_reconciliation_status


CONTEXT = ChangeContext(effective_date=date(2026, 9, 11))
CAPTURED_AT = datetime(2026, 9, 11, 6, 0, tzinfo=timezone.utc)


def _contract(
    *,
    contract_id: str = "orders-product",
    contract_name: str = "orders",
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
        name=contract_name,
        version="1.0.0",
        status="active",
        schema=[SchemaObject(name="orders", properties=properties)],
    )


def _release_artifacts(candidate: OpenDataContractStandard):
    base = _contract(contract_name="orders-old")
    decision = evaluate_governance_decision(base, candidate, context=CONTEXT)
    change_set = build_change_set_from_decision(
        decision,
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        source="golden-test",
        actor_reference="service:ci",
    )
    release_plan = build_release_plan(change_set, decision)
    version_resolution = resolve_release_version(
        release_plan,
        current_version="1.0.0",
        config=VersionAuthorityConfig(),
    )
    return decision, change_set, release_plan, version_resolution


def _review_evidence(
    decision,
    change_set,
    release_plan,
    version_resolution,
    *,
    operation: GovernanceOperation,
    scope_reference: str | None = None,
) -> ReviewAuthorizationEvidence:
    return ReviewAuthorizationEvidence(
        evidence_reference=f"approval:{operation.value.lower()}",
        decision_id=decision.decision_id,
        change_set_id=change_set.change_set_id,
        release_plan_id=release_plan.release_plan_id,
        version_resolution_id=version_resolution.version_resolution_id,
        operation=operation,
        action=ReviewEvidenceAction.APPROVE,
        scope_reference=scope_reference,
    )


def _apply_release(candidate: OpenDataContractStandard):
    decision, change_set, release_plan, version_resolution = _release_artifacts(candidate)
    evidence = None
    if decision.decision is DecisionResult.REVIEW:
        evidence = _review_evidence(
            decision,
            change_set,
            release_plan,
            version_resolution,
            operation=GovernanceOperation.APPLY,
        )
    authorization = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.APPLY,
        evidence=evidence,
    )
    release = apply_contract_release(
        candidate,
        candidate_revision_ref="git:candidate",
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        authorization=authorization,
    )
    return decision, change_set, release_plan, version_resolution, authorization, release


def _allow_chain():
    candidate = _contract(contract_name="orders-new")
    (
        decision,
        change_set,
        release_plan,
        version_resolution,
        apply_authorization,
        release,
    ) = _apply_release(candidate)
    deployment_plan = build_deployment_plan(
        release,
        DeploymentTarget(
            platform="databricks",
            runtime_target="main.silver",
            server_name="production",
        ),
    )
    deploy_authorization = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.DEPLOY,
    )
    deployment_authorization = authorize_deployment(
        deployment_plan,
        release,
        deploy_authorization,
    )
    return SimpleNamespace(
        candidate=candidate,
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        apply_authorization=apply_authorization,
        release=release,
        deployment_plan=deployment_plan,
        deploy_authorization=deploy_authorization,
        deployment_authorization=deployment_authorization,
    )


def _observed_state(
    *,
    present: bool,
    physical_type: str | None = "varchar(255)",
    nullable: bool | None = False,
) -> ObservedPlatformState:
    identity = ObservedAssetIdentity(
        platform="databricks",
        namespace=("main", "silver"),
        asset="orders",
    )
    assets = ()
    if present:
        assets = (
            ObservedAsset(
                identity=identity,
                asset_type="MANAGED",
                properties=(
                    ObservedProperty(
                        identity=ObservedPropertyIdentity(
                            asset=identity,
                            property="id",
                        ),
                        physical_type=physical_type,
                        nullable=nullable,
                    ),
                ),
            ),
        )
    return with_observed_state_fingerprint(
        ObservedPlatformState(
            platform="databricks",
            source_identifier="workspace:golden",
            assets=assets,
            captured_at=CAPTURED_AT,
            fingerprint=None,
        )
    )


class _RuntimeProvider:
    key = "databricks"

    def __init__(self, state: ObservedPlatformState) -> None:
        self.state = state
        self.observe_calls = 0

    def resolve_bindings(self, *, runtime_target, assets):
        assert runtime_target == "main.silver"
        return tuple(
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

    def observe(self, *, bindings):
        self.observe_calls += 1
        return self.state


class _Statements:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute_statement(self, *, statement, warehouse_id, wait_timeout):
        assert warehouse_id == "warehouse-golden"
        self.calls.append(statement)
        return SimpleNamespace(
            statement_id="statement-golden",
            status=SimpleNamespace(state="SUCCEEDED", error=None),
        )

    def get_statement(self, statement_id):
        raise AssertionError(f"unexpected statement polling: {statement_id}")


class _Client:
    def __init__(self) -> None:
        self.statement_execution = _Statements()


def _adapter(provider: _RuntimeProvider):
    client = _Client()
    adapter = DatabricksDeploymentAdapter(
        client=client,
        runtime_provider=provider,
        warehouse_id="warehouse-golden",
        poll_interval_seconds=0,
    )
    return adapter, client


def _allow_semantic_projection(chain) -> dict[str, object]:
    action = chain.deployment_plan.actions[0]
    return {
        "decision": chain.decision.decision.value,
        "requiredVersionBump": chain.decision.required_version_bump,
        "changeCount": len(chain.change_set.changes),
        "releasePreconditions": [
            item.value for item in chain.release_plan.preconditions
        ],
        "versionAuthority": chain.version_resolution.authority.value,
        "selectedVersion": chain.version_resolution.selected_version,
        "actualBump": chain.version_resolution.actual_bump,
        "apply": {
            "operation": chain.apply_authorization.operation.value,
            "allowed": chain.apply_authorization.allowed,
            "reason": chain.apply_authorization.reason.value,
        },
        "appliedContract": {
            "name": chain.release.to_contract().name,
            "version": chain.release.to_contract().version,
        },
        "deployment": {
            "operation": chain.deploy_authorization.operation.value,
            "allowed": chain.deploy_authorization.allowed,
            "target": chain.deployment_plan.target.model_dump(mode="json"),
            "actions": [
                {
                    "kind": action.kind.value,
                    "governedAsset": action.governed_asset,
                    "physicalName": action.physical_name,
                }
            ],
        },
    }


def test_allow_chain_has_stable_cross_boundary_golden_semantics() -> None:
    first = _allow_chain()
    second = _allow_chain()

    assert _allow_semantic_projection(first) == {
        "decision": "ALLOW",
        "requiredVersionBump": "none",
        "changeCount": 1,
        "releasePreconditions": [],
        "versionAuthority": "semapact",
        "selectedVersion": "1.0.1",
        "actualBump": "patch",
        "apply": {
            "operation": "APPLY",
            "allowed": True,
            "reason": "allowed_by_governance",
        },
        "appliedContract": {"name": "orders-new", "version": "1.0.1"},
        "deployment": {
            "operation": "DEPLOY",
            "allowed": True,
            "target": {
                "platform": "databricks",
                "runtime_target": "main.silver",
                "server_name": "production",
            },
            "actions": [
                {
                    "kind": "ENSURE_ASSET_STATE",
                    "governedAsset": "orders",
                    "physicalName": "orders",
                }
            ],
        },
    }

    assert first.decision.decision_id == second.decision.decision_id
    assert first.change_set.change_set_id == second.change_set.change_set_id
    assert first.release_plan.release_plan_id == second.release_plan.release_plan_id
    assert (
        first.version_resolution.version_resolution_id
        == second.version_resolution.version_resolution_id
    )
    assert first.apply_authorization.authorization_id == second.apply_authorization.authorization_id
    assert first.release.applied_release_id == second.release.applied_release_id
    assert (
        first.deployment_plan.deployment_plan_id
        == second.deployment_plan.deployment_plan_id
    )
    assert (
        first.deployment_authorization.deployment_authorization_id
        == second.deployment_authorization.deployment_authorization_id
    )
    assert first.candidate.version == "1.0.0"


def test_review_requires_exact_apply_and_deployment_authorization() -> None:
    candidate = _contract(contract_name="orders-old", include_created_at=True)
    decision, change_set, release_plan, version_resolution = _release_artifacts(candidate)

    assert decision.decision is DecisionResult.REVIEW

    denied_apply = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.APPLY,
    )
    assert denied_apply.allowed is False
    with pytest.raises(ContractOpsAuthorizationError):
        apply_contract_release(
            candidate,
            candidate_revision_ref="git:candidate",
            decision=decision,
            change_set=change_set,
            release_plan=release_plan,
            version_resolution=version_resolution,
            authorization=denied_apply,
        )

    apply_evidence = _review_evidence(
        decision,
        change_set,
        release_plan,
        version_resolution,
        operation=GovernanceOperation.APPLY,
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
        candidate_revision_ref="git:candidate",
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        authorization=apply_authorization,
    )
    plan = build_deployment_plan(
        release,
        DeploymentTarget(platform="databricks", runtime_target="main.silver"),
    )

    unscoped_deploy_evidence = _review_evidence(
        decision,
        change_set,
        release_plan,
        version_resolution,
        operation=GovernanceOperation.DEPLOY,
    )
    unscoped_deploy = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.DEPLOY,
        evidence=unscoped_deploy_evidence,
    )
    with pytest.raises(ReleaseValidationError, match="scoped"):
        authorize_deployment(plan, release, unscoped_deploy)

    scoped_deploy_evidence = _review_evidence(
        decision,
        change_set,
        release_plan,
        version_resolution,
        operation=GovernanceOperation.DEPLOY,
        scope_reference=plan.deployment_plan_id,
    )
    scoped_deploy = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.DEPLOY,
        evidence=scoped_deploy_evidence,
    )
    deployment_authorization = authorize_deployment(plan, release, scoped_deploy)

    assert decision.decision is DecisionResult.REVIEW
    assert apply_authorization.allowed is True
    assert scoped_deploy.allowed is True
    assert deployment_authorization.allowed is True


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
    candidate = _contract(contract_name="orders-old", include_created_at=True)
    decision, _, release_plan, _ = _release_artifacts(candidate)

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
    assert semapact_resolution.authority_reference is None
    assert git_resolution.authority_reference == "v1.2.0"


def test_publish_authorization_cannot_authorize_runtime_deployment() -> None:
    chain = _allow_chain()
    publish_authorization = authorize_contract_operation(
        chain.decision,
        chain.change_set,
        chain.release_plan,
        chain.version_resolution,
        GovernanceOperation.PUBLISH,
    )

    with pytest.raises(ReleaseValidationError, match="DEPLOY authorization"):
        authorize_deployment(
            chain.deployment_plan,
            chain.release,
            publish_authorization,
        )


def test_execute_success_is_separate_from_runtime_convergence() -> None:
    chain = _allow_chain()
    missing_state = _observed_state(present=False)
    provider = _RuntimeProvider(missing_state)
    adapter, client = _adapter(provider)

    first_preview = adapter.preview(chain.deployment_plan, missing_state)
    second_preview = adapter.preview(chain.deployment_plan, missing_state)
    assert first_preview == second_preview
    assert client.statement_execution.calls == []

    adapter.execute(
        chain.deployment_plan,
        first_preview,
        chain.deployment_authorization,
    )
    assert len(client.statement_execution.calls) == 1

    statement_count = len(client.statement_execution.calls)
    drift_result = verify_deployment_convergence(chain.deployment_plan, provider)
    assert classify_reconciliation_status(drift_result) is RuntimeDriftStatus.DRIFT
    assert len(client.statement_execution.calls) == statement_count

    provider.state = _observed_state(present=True)
    in_sync_result = verify_deployment_convergence(chain.deployment_plan, provider)
    assert classify_reconciliation_status(in_sync_result) is RuntimeDriftStatus.IN_SYNC
    assert len(client.statement_execution.calls) == statement_count

    provider.state = _observed_state(
        present=True,
        physical_type=None,
        nullable=None,
    )
    indeterminate_result = verify_deployment_convergence(chain.deployment_plan, provider)
    assert (
        classify_reconciliation_status(indeterminate_result)
        is RuntimeDriftStatus.INDETERMINATE
    )
    assert len(client.statement_execution.calls) == statement_count


def test_stale_preview_fails_before_native_mutation() -> None:
    chain = _allow_chain()
    missing_state = _observed_state(present=False)
    provider = _RuntimeProvider(missing_state)
    adapter, client = _adapter(provider)
    preview = adapter.preview(chain.deployment_plan, missing_state)

    provider.state = _observed_state(present=True)
    with pytest.raises(ValidationError, match="no longer equals|Runtime state changed"):
        adapter.execute(
            chain.deployment_plan,
            preview,
            chain.deployment_authorization,
        )

    assert client.statement_execution.calls == []
