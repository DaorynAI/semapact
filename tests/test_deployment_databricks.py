from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from open_data_contract_standard.model import SchemaObject, SchemaProperty

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
    compute_deployment_preview_id,
)
from semapact.exceptions import ContractOpsAuthorizationError, ValidationError
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

CAPTURED_AT = datetime(2026, 9, 10, 5, 0, tzinfo=timezone.utc)
SOURCE_REFERENCE = "workspace-a"


def _property(name: str, physical_type: str, *, required: bool = False) -> SchemaProperty:
    return SchemaProperty(
        name=name,
        physicalName=name,
        logicalType="string",
        physicalType=physical_type,
        required=required,
    )


def _plan(*properties: SchemaProperty, source_reference: str = SOURCE_REFERENCE) -> DeploymentPlan:
    schema = SchemaObject(
        name="orders",
        physicalName="orders",
        physicalType="table",
        properties=list(properties),
    )
    action = DeploymentAction(
        kind=DeploymentActionKind.ENSURE_ASSET_STATE,
        governed_asset="orders",
        physical_name="orders",
        desired_state_json=json.dumps(
            schema.model_dump(mode="json", by_alias=True, exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    target = DeploymentTarget(
        platform="databricks",
        runtime_target="main.silver",
        source_reference=source_reference,
    )
    plan_id = compute_deployment_plan_id(
        applied_release_id="applied:test",
        contract_id="orders-product",
        release_plan_id="release-plan:test",
        released_revision_ref="rev:released",
        selected_version="1.2.0",
        target=target,
        actions=(action,),
    )
    return DeploymentPlan(
        deployment_plan_id=plan_id,
        applied_release_id="applied:test",
        contract_id="orders-product",
        release_plan_id="release-plan:test",
        released_revision_ref="rev:released",
        selected_version="1.2.0",
        target=target,
        actions=(action,),
    )


def _authorization(plan: DeploymentPlan, allowed: bool = True) -> DeploymentAuthorization:
    authorization_id = compute_deployment_authorization_id(
        contract_ops_authorization_id="contractops-auth:test",
        deployment_plan_id=plan.deployment_plan_id,
        applied_release_id=plan.applied_release_id,
        allowed=allowed,
    )
    return DeploymentAuthorization(
        deployment_authorization_id=authorization_id,
        contract_ops_authorization_id="contractops-auth:test",
        deployment_plan_id=plan.deployment_plan_id,
        applied_release_id=plan.applied_release_id,
        allowed=allowed,
    )


def _state(
    *columns: tuple[str, str, bool],
    asset_type: str = "MANAGED",
    source: str = SOURCE_REFERENCE,
    present: bool = True,
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
                asset_type=asset_type,
                properties=tuple(
                    ObservedProperty(
                        identity=ObservedPropertyIdentity(asset=identity, property=name),
                        physical_type=physical_type,
                        nullable=nullable,
                    )
                    for name, physical_type, nullable in columns
                ),
            ),
        )
    raw = ObservedPlatformState(
        platform="databricks",
        source_identifier=source,
        assets=assets,
        captured_at=CAPTURED_AT,
        fingerprint=None,
    )
    return with_observed_state_fingerprint(raw)


class _Provider:
    key = "databricks"

    def __init__(self, state: ObservedPlatformState) -> None:
        self.state = state

    def resolve_bindings(self, *, runtime_target, assets):
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
        return self.state


class _Statements:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute_statement(self, *, statement, warehouse_id, wait_timeout):
        self.calls.append(statement)
        return SimpleNamespace(
            statement_id="s-1",
            status=SimpleNamespace(state="SUCCEEDED", error=None),
        )

    def get_statement(self, statement_id):
        raise AssertionError(f"unexpected poll: {statement_id}")


class _Client:
    def __init__(self) -> None:
        self.statement_execution = _Statements()


def _adapter(state: ObservedPlatformState, *, warehouse_id: str | None = "warehouse-1"):
    client = _Client()
    provider = _Provider(state)
    adapter = DatabricksDeploymentAdapter(
        client=client,
        runtime_provider=provider,
        warehouse_id=warehouse_id,
        poll_interval_seconds=0,
    )
    return adapter, provider, client


def test_preview_create_alter_and_no_op() -> None:
    create_plan = _plan(_property("id", "BIGINT", required=True))
    missing = _state(present=False)
    adapter, _, _ = _adapter(missing)
    create_preview = adapter.preview(create_plan, missing)
    assert create_preview.operations[0].kind is NativeOperationKind.CREATE

    alter_plan = _plan(
        _property("id", "BIGINT", required=True),
        _property("note", "STRING"),
    )
    current = _state(("id", "bigint", False))
    adapter, _, _ = _adapter(current)
    alter_preview = adapter.preview(alter_plan, current)
    assert alter_preview.operations[0].kind is NativeOperationKind.ALTER
    assert "ADD COLUMNS (`note` STRING)" in alter_preview.operations[0].statement

    no_op = adapter.preview(create_plan, current)
    assert no_op.operations == (
        NativeOperation(kind=NativeOperationKind.NO_OP, governed_asset="orders"),
    )


def test_preview_never_drops_extra_runtime_columns() -> None:
    plan = _plan(_property("id", "BIGINT", required=True))
    current = _state(("id", "bigint", False), ("extra", "string", True))
    adapter, _, _ = _adapter(current)
    assert adapter.preview(plan, current).operations[0].kind is NativeOperationKind.NO_OP


@pytest.mark.parametrize(
    ("plan", "state", "message"),
    [
        (
            _plan(_property("id", "STRING", required=True)),
            _state(("id", "bigint", False)),
            "type mutation",
        ),
        (
            _plan(_property("id", "BIGINT", required=True)),
            _state(("id", "bigint", True)),
            "nullability mutation",
        ),
        (
            _plan(
                _property("id", "BIGINT", required=True),
                _property("new_required", "STRING", required=True),
            ),
            _state(("id", "bigint", False)),
            "safe default",
        ),
    ],
)
def test_unsafe_existing_mutations_fail_closed(plan, state, message) -> None:
    adapter, _, _ = _adapter(state)
    with pytest.raises(ValidationError, match=message):
        adapter.preview(plan, state)


def test_non_managed_asset_and_unsafe_type_fail_closed() -> None:
    plan = _plan(_property("id", "BIGINT", required=True))
    external = _state(("id", "bigint", False), asset_type="EXTERNAL")
    adapter, _, _ = _adapter(external)
    with pytest.raises(ValidationError, match="MANAGED"):
        adapter.preview(plan, external)

    malicious_type = "STRING);DROP"
    malicious = _plan(_property("id", malicious_type))
    with pytest.raises(ValidationError, match="physicalType"):
        adapter.validate(malicious)


def test_preview_rejects_cross_source_runtime_evidence() -> None:
    plan = _plan(_property("id", "BIGINT", required=True))
    other_workspace = _state(("id", "bigint", False), source="workspace-b")
    adapter, _, _ = _adapter(other_workspace)

    with pytest.raises(ValidationError, match="source reference"):
        adapter.preview(plan, other_workspace)


def test_execute_fails_closed_for_denied_stale_and_cross_source() -> None:
    plan = _plan(_property("id", "BIGINT", required=True))
    before = _state(("id", "bigint", False))
    adapter, provider, _ = _adapter(before)
    preview = adapter.preview(plan, before)

    with pytest.raises(ContractOpsAuthorizationError, match="not allowed"):
        adapter.execute(plan, preview, _authorization(plan, False))

    provider.state = _state(
        ("id", "bigint", False),
        ("other", "string", True),
    )
    with pytest.raises(ValidationError, match="Runtime state changed"):
        adapter.execute(plan, preview, _authorization(plan))

    provider.state = before.model_copy(update={"source_identifier": "workspace-b"})
    with pytest.raises(ValidationError, match="Runtime source changed"):
        adapter.execute(plan, preview, _authorization(plan))


def test_execute_rejects_tampered_plan_and_forged_native_command() -> None:
    plan = _plan(_property("id", "BIGINT", required=True))
    current = _state(("id", "bigint", False))
    adapter, _, client = _adapter(current)
    preview = adapter.preview(plan, current)

    tampered = plan.model_copy(update={"selected_version": "9.9.9"})
    with pytest.raises(ValueError, match="DeploymentPlan deterministic identity"):
        adapter.execute(tampered, preview, _authorization(plan))

    forged_operations = (
        NativeOperation(
            kind=NativeOperationKind.ALTER,
            governed_asset="orders",
            statement="DROP TABLE `main`.`silver`.`orders`",
        ),
    )
    forged_id = compute_deployment_preview_id(
        deployment_plan_id=preview.deployment_plan_id,
        platform=preview.platform,
        runtime_target=preview.runtime_target,
        source_identifier=preview.source_identifier,
        observation_fingerprint=preview.observation_fingerprint,
        operations=forged_operations,
    )
    forged = preview.model_copy(
        update={"deployment_preview_id": forged_id, "operations": forged_operations}
    )
    with pytest.raises(ValidationError, match="no longer equals"):
        adapter.execute(plan, forged, _authorization(plan))
    assert client.statement_execution.calls == []


def test_execute_runs_exact_preview_statement() -> None:
    plan = _plan(
        _property("id", "BIGINT", required=True),
        _property("note", "STRING"),
    )
    current = _state(("id", "bigint", False))
    adapter, _, client = _adapter(current)
    preview = adapter.preview(plan, current)

    adapter.execute(plan, preview, _authorization(plan))

    assert client.statement_execution.calls == [
        "ALTER TABLE `main`.`silver`.`orders` ADD COLUMNS (`note` STRING)"
    ]


def test_no_op_execute_does_not_require_warehouse() -> None:
    plan = _plan(_property("id", "BIGINT", required=True))
    current = _state(("id", "bigint", False))
    adapter, _, client = _adapter(current, warehouse_id=None)
    preview = adapter.preview(plan, current)

    assert preview.operations[0].kind is NativeOperationKind.NO_OP
    adapter.execute(plan, preview, _authorization(plan))
    assert client.statement_execution.calls == []


def test_mutation_execute_without_warehouse_fails_closed() -> None:
    plan = _plan(
        _property("id", "BIGINT", required=True),
        _property("note", "STRING"),
    )
    current = _state(("id", "bigint", False))
    adapter, _, client = _adapter(current, warehouse_id=None)
    preview = adapter.preview(plan, current)

    with pytest.raises(ValidationError, match="warehouse_id"):
        adapter.execute(plan, preview, _authorization(plan))
    assert client.statement_execution.calls == []


def test_runtime_source_participates_in_plan_identity() -> None:
    plan_a = _plan(_property("id", "BIGINT", required=True), source_reference="workspace-a")
    plan_b = _plan(_property("id", "BIGINT", required=True), source_reference="workspace-b")

    assert plan_a.deployment_plan_id != plan_b.deployment_plan_id
