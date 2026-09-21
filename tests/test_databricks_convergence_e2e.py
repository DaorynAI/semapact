from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.application.services.deployment import DeploymentService
from semapact.application.services.deployment_workflow import DeploymentWorkflowService
from semapact.change_context import ChangeContext
from semapact.contractops import (
    apply_contract_release,
    authorize_contract_operation,
    build_change_set_from_decision,
    build_release_plan,
    resolve_release_version,
    VersionAuthorityConfig,
)
from semapact.deployment import (
    DeploymentPlan,
    DeploymentPreview,
    DeploymentTarget,
)
from semapact.deployment.compatibility import (
    authorize_legacy_deployment,
    build_legacy_deployment_plan,
)
from semapact.deployment.models import (
    NativeOperationKind,
    compute_deployment_authorization_id,
)
from semapact.exceptions import ContractOpsAuthorizationError, ValidationError
from semapact.governance import DecisionResult, evaluate_governance_decision
from semapact.governance.gate import GovernanceOperation
from semapact.interfaces.commands import deployment_cmd
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


_CONTEXT = ChangeContext(effective_date=date(2026, 9, 19))
_SOURCE = "workspace:golden"
_RUNTIME_TARGET = "main.silver"
_CAPTURED_AT = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)


def _property(
    name: str,
    physical_type: str,
    *,
    required: bool = False,
) -> SchemaProperty:
    logical_type = "integer" if physical_type.casefold() == "integer" else "string"
    return SchemaProperty(
        name=name,
        physicalName=name,
        logicalType=logical_type,
        physicalType=physical_type,
        required=required,
    )


def _contract(
    *properties: SchemaProperty,
    name: str,
) -> OpenDataContractStandard:
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders-product",
        name=name,
        version="1.0.0",
        status="active",
        schema=[
            SchemaObject(
                name="orders",
                physicalName="orders",
                physicalType="table",
                properties=list(properties),
            )
        ],
    )


def _release_context(*properties: SchemaProperty):
    base = _contract(*properties, name="orders-old")
    candidate = _contract(*properties, name="orders-new")
    decision = evaluate_governance_decision(base, candidate, context=_CONTEXT)
    assert decision.decision is DecisionResult.ALLOW

    change_set = build_change_set_from_decision(
        decision,
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        source="databricks-convergence-golden",
        actor_reference="service:ci",
    )
    release_plan = build_release_plan(change_set, decision)
    version_resolution = resolve_release_version(
        release_plan,
        current_version="1.0.0",
        config=VersionAuthorityConfig(),
    )
    apply_authorization = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.APPLY,
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
    deploy_authorization = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.DEPLOY,
    )
    return SimpleNamespace(
        release=release,
        deploy_authorization=deploy_authorization,
    )


def _target(*, source_reference: str = _SOURCE) -> DeploymentTarget:
    return DeploymentTarget(
        platform="databricks",
        runtime_target=_RUNTIME_TARGET,
        source_reference=source_reference,
        server_name="production",
    )


class _StatefulWorkspace:
    def __init__(
        self,
        *,
        present: bool,
        columns: tuple[tuple[str, str, bool], ...] = (),
        asset_type: str = "MANAGED",
        source_identifier: str = _SOURCE,
    ) -> None:
        self.present = present
        self.columns = list(columns)
        self.asset_type = asset_type
        self.source_identifier = source_identifier
        self.capture_count = 0
        self.statements: list[str] = []

    def observe(self) -> ObservedPlatformState:
        identity = ObservedAssetIdentity(
            platform="databricks",
            namespace=("main", "silver"),
            asset="orders",
        )
        assets = ()
        if self.present:
            assets = (
                ObservedAsset(
                    identity=identity,
                    asset_type=self.asset_type,
                    properties=tuple(
                        ObservedProperty(
                            identity=ObservedPropertyIdentity(
                                asset=identity,
                                property=name,
                            ),
                            physical_type=physical_type,
                            nullable=nullable,
                        )
                        for name, physical_type, nullable in self.columns
                    ),
                ),
            )

        captured_at = _CAPTURED_AT + timedelta(seconds=self.capture_count)
        self.capture_count += 1
        return with_observed_state_fingerprint(
            ObservedPlatformState(
                platform="databricks",
                source_identifier=self.source_identifier,
                assets=assets,
                captured_at=captured_at,
            )
        )

    def apply(self, statement: str) -> None:
        self.statements.append(statement)

        create_match = re.fullmatch(
            r"CREATE TABLE `main`.`silver`.`orders` "
            r"\((?P<columns>.*)\) USING DELTA",
            statement,
        )
        if create_match is not None:
            self.present = True
            self.asset_type = "MANAGED"
            self.columns = list(_parse_columns(create_match.group("columns")))
            return

        alter_match = re.fullmatch(
            r"ALTER TABLE `main`.`silver`.`orders` "
            r"ADD COLUMNS \((?P<columns>.*)\)",
            statement,
        )
        if alter_match is not None:
            if not self.present:
                raise AssertionError("ALTER cannot mutate a missing mock asset")
            self.columns.extend(_parse_columns(alter_match.group("columns")))
            return

        raise AssertionError(f"unexpected Databricks statement: {statement}")


def _parse_columns(value: str) -> tuple[tuple[str, str, bool], ...]:
    # Golden scenarios intentionally use scalar types so a simple harness parser
    # can model the runtime side effect without becoming another SQL compiler.
    parsed: list[tuple[str, str, bool]] = []
    for raw in value.split(","):
        item = raw.strip()
        match = re.fullmatch(
            r"`(?P<name>[^`]+)`\s+(?P<type>.+?)(?P<not_null>\s+NOT NULL)?",
            item,
        )
        if match is None:
            raise AssertionError(f"unexpected mock column definition: {item}")
        physical_type = match.group("type").strip()
        parsed.append(
            (
                match.group("name"),
                physical_type,
                match.group("not_null") is None,
            )
        )
    return tuple(parsed)


class _StatefulRuntimeProvider:
    key = "databricks"

    def __init__(self, workspace: _StatefulWorkspace) -> None:
        self.workspace = workspace

    def resolve_bindings(self, *, runtime_target, assets):
        assert runtime_target == _RUNTIME_TARGET
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
        assert tuple(bindings)
        return self.workspace.observe()


class _StatefulStatements:
    def __init__(self, workspace: _StatefulWorkspace) -> None:
        self.workspace = workspace

    def execute_statement(self, *, statement, warehouse_id, wait_timeout):
        assert warehouse_id == "warehouse-golden"
        assert wait_timeout == "10s"
        self.workspace.apply(statement)
        return SimpleNamespace(
            statement_id="statement-golden",
            status=SimpleNamespace(state="SUCCEEDED", error=None),
        )

    def get_statement(self, statement_id):
        raise AssertionError(f"unexpected statement polling: {statement_id}")


class _Client:
    def __init__(self, workspace: _StatefulWorkspace) -> None:
        self.statement_execution = _StatefulStatements(workspace)


def _adapter(workspace: _StatefulWorkspace) -> DatabricksDeploymentAdapter:
    return DatabricksDeploymentAdapter(
        client=_Client(workspace),
        runtime_provider=_StatefulRuntimeProvider(workspace),
        warehouse_id="warehouse-golden",
        poll_interval_seconds=0,
    )


def _workflow(
    workspace: _StatefulWorkspace,
    *properties: SchemaProperty,
):
    release_context = _release_context(*properties)
    service = DeploymentService()
    plan = build_legacy_deployment_plan(release_context.release, _target())
    authorization = authorize_legacy_deployment(
        plan,
        release_context.release,
        release_context.deploy_authorization,
    )
    return SimpleNamespace(
        service=service,
        plan=plan,
        authorization=authorization,
        adapter=_adapter(workspace),
        release_context=release_context,
    )


def _assert_in_sync(workflow) -> None:
    result = workflow.service.verify(
        workflow.plan,
        adapter=workflow.adapter,
    )
    assert classify_reconciliation_status(result) is RuntimeDriftStatus.IN_SYNC
    assert result.differences == ()
    assert result.unverified_paths == ()


def test_bundle_ci_to_cd_create_and_fresh_verify_converge() -> None:
    workspace = _StatefulWorkspace(present=False)
    adapter = _adapter(workspace)
    base = _contract(
        _property("id", "integer", required=True),
        name="orders-old",
    )
    candidate = _contract(
        _property("id", "integer", required=True),
        name="orders-new",
    )
    service = DeploymentWorkflowService()

    bundle = service.assess(
        base,
        candidate,
        effective_date=_CONTEXT.effective_date,
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=_target(),
        adapter=adapter,
    )
    assert bundle.review_preview.operations[0].kind is NativeOperationKind.CREATE

    result = service.deploy(bundle, adapter=adapter)

    assert result.status is RuntimeDriftStatus.IN_SYNC
    assert result.fresh_preview.operations[0].kind is NativeOperationKind.CREATE
    assert workspace.statements == [
        "CREATE TABLE `main`.`silver`.`orders` "
        "(`id` INT NOT NULL) USING DELTA"
    ]


def test_bundle_cd_replans_against_runtime_changed_after_ci() -> None:
    workspace = _StatefulWorkspace(present=False)
    adapter = _adapter(workspace)
    base = _contract(
        _property("id", "integer", required=True),
        name="orders-old",
    )
    candidate = _contract(
        _property("id", "integer", required=True),
        name="orders-new",
    )
    service = DeploymentWorkflowService()

    bundle = service.assess(
        base,
        candidate,
        effective_date=_CONTEXT.effective_date,
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        target=_target(),
        adapter=adapter,
    )
    assert bundle.review_preview.operations[0].kind is NativeOperationKind.CREATE

    # Another actor converges the table after CI but before CD.
    workspace.present = True
    workspace.columns = [("id", "INT", False)]

    result = service.deploy(bundle, adapter=adapter)

    assert result.status is RuntimeDriftStatus.IN_SYNC
    assert result.review_preview_changed is True
    assert result.fresh_preview.operations[0].kind is NativeOperationKind.NO_OP
    assert workspace.statements == []


def test_missing_table_create_execute_and_fresh_verify_converge() -> None:
    workspace = _StatefulWorkspace(present=False)
    workflow = _workflow(
        workspace,
        _property("id", "integer", required=True),
    )

    preview = workflow.service.preview(
        workflow.plan,
        adapter=workflow.adapter,
    )
    assert preview.operations[0].kind is NativeOperationKind.CREATE

    workflow.service.execute(
        workflow.plan,
        preview,
        workflow.authorization,
        adapter=workflow.adapter,
    )

    assert workspace.columns == [("id", "INT", False)]
    assert workspace.statements == [
        "CREATE TABLE `main`.`silver`.`orders` "
        "(`id` INT NOT NULL) USING DELTA"
    ]
    _assert_in_sync(workflow)


def test_missing_nullable_column_alter_execute_and_fresh_verify_converge() -> None:
    workspace = _StatefulWorkspace(
        present=True,
        columns=(("id", "INT", False),),
    )
    workflow = _workflow(
        workspace,
        _property("id", "integer", required=True),
        _property("note", "STRING"),
    )

    preview = workflow.service.preview(
        workflow.plan,
        adapter=workflow.adapter,
    )
    assert preview.operations[0].kind is NativeOperationKind.ALTER

    workflow.service.execute(
        workflow.plan,
        preview,
        workflow.authorization,
        adapter=workflow.adapter,
    )

    assert workspace.columns == [
        ("id", "INT", False),
        ("note", "STRING", True),
    ]
    assert workspace.statements == [
        "ALTER TABLE `main`.`silver`.`orders` "
        "ADD COLUMNS (`note` STRING)"
    ]
    _assert_in_sync(workflow)


def test_compliant_table_no_op_execute_and_verify_converge() -> None:
    workspace = _StatefulWorkspace(
        present=True,
        columns=(("id", "INT", False),),
    )
    workflow = _workflow(
        workspace,
        _property("id", "integer", required=True),
    )

    preview = workflow.service.preview(
        workflow.plan,
        adapter=workflow.adapter,
    )
    assert preview.operations[0].kind is NativeOperationKind.NO_OP

    workflow.service.execute(
        workflow.plan,
        preview,
        workflow.authorization,
        adapter=workflow.adapter,
    )

    assert workspace.statements == []
    _assert_in_sync(workflow)


def test_stale_runtime_between_preview_and_execute_fails_closed() -> None:
    workspace = _StatefulWorkspace(present=False)
    workflow = _workflow(
        workspace,
        _property("id", "integer", required=True),
    )
    preview = workflow.service.preview(
        workflow.plan,
        adapter=workflow.adapter,
    )

    workspace.present = True
    workspace.columns = [("id", "INT", False)]

    with pytest.raises(ValidationError, match="Runtime state changed"):
        workflow.service.execute(
            workflow.plan,
            preview,
            workflow.authorization,
            adapter=workflow.adapter,
        )

    assert workspace.statements == []


def test_external_asset_requiring_mutation_fails_closed() -> None:
    workspace = _StatefulWorkspace(
        present=True,
        columns=(("id", "INT", False),),
        asset_type="EXTERNAL",
    )
    workflow = _workflow(
        workspace,
        _property("id", "integer", required=True),
        _property("note", "STRING"),
    )

    with pytest.raises(ValidationError, match="MANAGED"):
        workflow.service.preview(
            workflow.plan,
            adapter=workflow.adapter,
        )

    assert workspace.statements == []


def test_wrong_workspace_source_fails_preview_and_execute_closed() -> None:
    wrong_workspace = _StatefulWorkspace(
        present=False,
        source_identifier="workspace:other",
    )
    wrong_workflow = _workflow(
        wrong_workspace,
        _property("id", "integer", required=True),
    )

    with pytest.raises(ValidationError, match="source reference"):
        wrong_workflow.service.preview(
            wrong_workflow.plan,
            adapter=wrong_workflow.adapter,
        )

    workspace = _StatefulWorkspace(present=False)
    workflow = _workflow(
        workspace,
        _property("id", "integer", required=True),
    )
    preview = workflow.service.preview(
        workflow.plan,
        adapter=workflow.adapter,
    )
    workspace.source_identifier = "workspace:other"

    with pytest.raises(ValidationError, match="Runtime source changed"):
        workflow.service.execute(
            workflow.plan,
            preview,
            workflow.authorization,
            adapter=workflow.adapter,
        )

    assert workspace.statements == []


def test_denied_deployment_authorization_fails_before_native_mutation() -> None:
    workspace = _StatefulWorkspace(present=False)
    workflow = _workflow(
        workspace,
        _property("id", "integer", required=True),
    )
    preview = workflow.service.preview(
        workflow.plan,
        adapter=workflow.adapter,
    )
    denied = workflow.authorization.model_copy(
        update={
            "allowed": False,
            "deployment_authorization_id": compute_deployment_authorization_id(
                contract_ops_authorization_id=(
                    workflow.authorization.contract_ops_authorization_id
                ),
                deployment_plan_id=workflow.plan.deployment_plan_id,
                source_snapshot_id=workflow.plan.source_snapshot_id,
                allowed=False,
            ),
        }
    )

    with pytest.raises(ContractOpsAuthorizationError, match="not allowed"):
        workflow.service.execute(
            workflow.plan,
            preview,
            denied,
            adapter=workflow.adapter,
        )

    assert workspace.statements == []


def test_databricks_integer_target_alias_does_not_create_false_drift() -> None:
    workspace = _StatefulWorkspace(
        present=True,
        columns=(("id", "INT", False),),
    )
    workflow = _workflow(
        workspace,
        _property("id", "integer", required=True),
    )

    preview = workflow.service.preview(
        workflow.plan,
        adapter=workflow.adapter,
    )
    assert preview.operations[0].kind is NativeOperationKind.NO_OP

    _assert_in_sync(workflow)
