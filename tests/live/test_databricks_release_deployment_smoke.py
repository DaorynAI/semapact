from __future__ import annotations

from datetime import datetime, timezone
import os
import re

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.application.services.deployment_workflow import DeploymentWorkflowService
from semapact.application.services.release_workflow import (
    ReleaseFinalizer,
    ReleaseWorkflowService,
)
from semapact.deployment import DeploymentTarget, NativeOperationKind
from semapact.exceptions import ValidationError
from semapact.governance import DecisionResult
from semapact.platforms.databricks import create_databricks_workspace_client
from semapact.platforms.databricks.deployment import (
    DatabricksDeploymentExecutionConfig,
    DatabricksStatementExecutor,
)
from semapact.platforms.databricks.runtime import DatabricksRuntimeProvider
from semapact.platforms.runtime_registry import create_deployment_adapter
from semapact.reconciliation import (
    RuntimeDriftStatus,
    classify_reconciliation_status,
    reconcile_governed_contract,
    runtime_asset_specs_from_contract,
)
from semapact.schema import validate_simple_sql_identifier


pytestmark = [
    pytest.mark.live_databricks,
    pytest.mark.skipif(
        os.environ.get("SEMAPACT_RUN_LIVE_DATABRICKS") != "1",
        reason="live Databricks smoke is opt-in",
    ),
]

_RESERVED_TAGS = (
    "semapact_contract_id",
    "semapact_contract_version",
    "semapact_release_id",
    "semapact_source_revision",
)
_CONFIRMATION = "I_UNDERSTAND_THIS_CREATES_TABLES"
_DEFAULT_CATALOG = "manufacturing_demo"
_DEFAULT_SCHEMA = "gold"
_DEFAULT_WAREHOUSE_ID = "dae52f9b349fc77f"


def _safe_identifier(name: str, label: str) -> str:
    try:
        validate_simple_sql_identifier(name, label)
    except ValidationError as exc:
        pytest.fail(str(exc))
    return name


def _safe_schema(name: str) -> str:
    return _safe_identifier(name, "schema")


def _safe_run_id(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]", "_", value.strip())
    if not normalized:
        pytest.fail("run ID must contain a valid identifier")
    return normalized[:48].casefold()


def _contract(
    *,
    table_name: str,
    include_note: bool,
) -> OpenDataContractStandard:
    properties = [
        SchemaProperty(
            name="id",
            physicalName="id",
            logicalType="integer",
            physicalType="BIGINT",
            required=True,
        )
    ]
    if include_note:
        properties.append(
            SchemaProperty(
                name="note",
                physicalName="note",
                logicalType="string",
                physicalType="STRING",
                required=False,
            )
        )
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id=f"semapact-live-smoke-{table_name}",
        name=f"SemaPact live smoke {table_name}",
        version="1.0.0",
        status="active",
        schema=[
            SchemaObject(
                name=table_name,
                physicalName=table_name,
                physicalType="table",
                properties=properties,
            )
        ],
    )


def _target(*, catalog: str, schema_name: str, source_reference: str) -> DeploymentTarget:
    return DeploymentTarget(
        platform="databricks",
        runtime_target=f"{catalog}.{schema_name}",
        source_reference=source_reference,
    )


def _adapter(*, warehouse_id: str):
    return create_deployment_adapter(
        "databricks",
        execution_config=DatabricksDeploymentExecutionConfig(
            warehouse_id=warehouse_id
        ),
    )


def _read_release_tags(
    *,
    client,
    warehouse_id: str,
    catalog: str,
    schema_name: str,
    table_name: str,
) -> dict[str, str]:
    executor = DatabricksStatementExecutor(
        client=client,
        warehouse_id=warehouse_id,
        poll_interval_seconds=1,
    )
    keys = ", ".join(f"'{key}'" for key in _RESERVED_TAGS)
    rows = executor.query_rows(
        "SELECT tag_name, tag_value "
        f"FROM `{catalog}`.information_schema.table_tags "
        f"WHERE schema_name = '{schema_name.casefold()}' "
        f"AND table_name = '{table_name.casefold()}' "
        f"AND tag_name IN ({keys})"
    )
    return {str(key): str(value) for key, value in rows}


def _delete_if_present(client, full_name: str) -> None:
    exists = client.tables.exists(full_name=full_name)
    if bool(getattr(exists, "table_exists", False)):
        client.tables.delete(full_name=full_name)


def test_live_candidate_release_and_redeployment_converge() -> None:
    if os.environ.get("SEMAPACT_LIVE_DATABRICKS_CONFIRM") != _CONFIRMATION:
        pytest.fail(
            "set SEMAPACT_LIVE_DATABRICKS_CONFIRM="
            f"{_CONFIRMATION} to run the live smoke"
        )

    catalog = _safe_identifier(
        os.environ.get("SEMAPACT_LIVE_DATABRICKS_CATALOG", _DEFAULT_CATALOG).strip(),
        "catalog",
    )
    uat_schema = _safe_schema(
        os.environ.get("SEMAPACT_LIVE_DATABRICKS_UAT_SCHEMA", _DEFAULT_SCHEMA).strip()
    )
    prod_schema = _safe_schema(
        os.environ.get("SEMAPACT_LIVE_DATABRICKS_PROD_SCHEMA", _DEFAULT_SCHEMA).strip()
    )
    warehouse_id = os.environ.get(
        "SEMAPACT_LIVE_DATABRICKS_WAREHOUSE_ID", _DEFAULT_WAREHOUSE_ID
    ).strip()
    raw_run_id = os.environ.get("SEMAPACT_LIVE_RUN_ID", "").strip() or f"reg_{int(datetime.now(timezone.utc).timestamp())}"
    run_id = _safe_run_id(raw_run_id)

    if uat_schema.casefold() == prod_schema.casefold():
        uat_table_name = f"semapact_uat_{run_id}"
        prod_table_name = f"semapact_prod_{run_id}"
    else:
        uat_table_name = f"semapact_smoke_{run_id}"
        prod_table_name = f"semapact_smoke_{run_id}"

    client = create_databricks_workspace_client()
    source_reference = str(getattr(client.config, "host", "") or "").strip()
    if not source_reference:
        pytest.fail("Databricks SDK did not resolve a workspace host")

    uat_full_name = f"{catalog}.{uat_schema}.{uat_table_name}"
    prod_full_name = f"{catalog}.{prod_schema}.{prod_table_name}"

    base_uat = _contract(table_name=uat_table_name, include_note=False)
    candidate_uat = _contract(table_name=uat_table_name, include_note=True)
    deployment = DeploymentWorkflowService()

    try:
        _delete_if_present(client, uat_full_name)
        _delete_if_present(client, prod_full_name)

        uat_target = _target(
            catalog=catalog,
            schema_name=uat_schema,
            source_reference=source_reference,
        )

        create_bundle = deployment.assess(
            base_uat,
            base_uat,
            base_revision_ref=f"live:base:{run_id}",
            candidate_revision_ref=f"live:base:{run_id}",
            target=uat_target,
            adapter=_adapter(warehouse_id=warehouse_id),
        )
        assert create_bundle.is_release is False
        assert create_bundle.review_preview.operations[0].kind is NativeOperationKind.CREATE

        create_result = deployment.deploy(
            create_bundle,
            adapter=_adapter(warehouse_id=warehouse_id),
        )
        assert create_result.status is RuntimeDriftStatus.IN_SYNC
        assert create_result.contract_release_id is None

        alter_bundle = deployment.assess(
            base_uat,
            candidate_uat,
            base_revision_ref=f"live:base:{run_id}",
            candidate_revision_ref=f"live:candidate:{run_id}",
            target=uat_target,
            adapter=_adapter(warehouse_id=warehouse_id),
        )
        assert alter_bundle.is_release is False
        assert alter_bundle.review_preview.operations[0].kind is NativeOperationKind.ALTER

        alter_result = deployment.deploy(
            alter_bundle,
            adapter=_adapter(warehouse_id=warehouse_id),
        )
        assert alter_result.status is RuntimeDriftStatus.IN_SYNC
        assert alter_result.contract_release_id is None
        assert _read_release_tags(
            client=client,
            warehouse_id=warehouse_id,
            catalog=catalog,
            schema_name=uat_schema,
            table_name=uat_table_name,
        ) == {}

        # Formal release workflow
        base_prod = _contract(table_name=prod_table_name, include_note=False)
        candidate_prod = _contract(table_name=prod_table_name, include_note=True)

        release_workflow = ReleaseWorkflowService()
        release_bundle = release_workflow.assess(
            base_prod,
            candidate_prod,
            base_revision_ref=f"live:base:{run_id}",
            candidate_revision_ref=f"live:candidate:{run_id}",
        )
        approval = None
        if release_bundle.decision.decision is DecisionResult.REVIEW:
            approval = release_workflow.approve(
                release_bundle,
                actor_reference="live-smoke:reviewer",
                recorded_at=datetime.now(timezone.utc),
                comment="Live Databricks smoke approval",
            )
        release = ReleaseFinalizer().finalize(
            release_bundle,
            approval=approval,
        )
        assert release.contract_version != base_prod.version

        prod_target = _target(
            catalog=catalog,
            schema_name=prod_schema,
            source_reference=source_reference,
        )
        prod_bundle = deployment.assess_release(
            release,
            target=prod_target,
            adapter=_adapter(warehouse_id=warehouse_id),
        )
        assert prod_bundle.review_preview.operations[0].kind is NativeOperationKind.CREATE

        prod_result = deployment.deploy(
            prod_bundle,
            adapter=_adapter(warehouse_id=warehouse_id),
        )
        assert prod_result.status is RuntimeDriftStatus.IN_SYNC
        assert prod_result.contract_release_id == release.contract_release_id

        expected_tags = {
            "semapact_contract_id": release.contract_id,
            "semapact_contract_version": release.contract_version,
            "semapact_release_id": release.contract_release_id,
            "semapact_source_revision": release.source_revision_ref,
        }
        assert _read_release_tags(
            client=client,
            warehouse_id=warehouse_id,
            catalog=catalog,
            schema_name=prod_schema,
            table_name=prod_table_name,
        ) == expected_tags

        repeat_result = deployment.deploy(
            prod_bundle,
            adapter=_adapter(warehouse_id=warehouse_id),
        )
        assert repeat_result.status is RuntimeDriftStatus.IN_SYNC
        assert all(
            operation.kind is NativeOperationKind.NO_OP
            for operation in repeat_result.fresh_preview.operations
        )
        assert _read_release_tags(
            client=client,
            warehouse_id=warehouse_id,
            catalog=catalog,
            schema_name=prod_schema,
            table_name=prod_table_name,
        ) == expected_tags
    finally:
        _delete_if_present(client, uat_full_name)
        _delete_if_present(client, prod_full_name)


def test_live_databricks_drift_reconciliation() -> None:
    if os.environ.get("SEMAPACT_LIVE_DATABRICKS_CONFIRM") != _CONFIRMATION:
        pytest.fail(
            "set SEMAPACT_LIVE_DATABRICKS_CONFIRM="
            f"{_CONFIRMATION} to run the live smoke"
        )

    catalog = _safe_identifier(
        os.environ.get("SEMAPACT_LIVE_DATABRICKS_CATALOG", _DEFAULT_CATALOG).strip(),
        "catalog",
    )
    schema_name = _safe_schema(
        os.environ.get("SEMAPACT_LIVE_DATABRICKS_PROD_SCHEMA", _DEFAULT_SCHEMA).strip()
    )
    warehouse_id = os.environ.get(
        "SEMAPACT_LIVE_DATABRICKS_WAREHOUSE_ID", _DEFAULT_WAREHOUSE_ID
    ).strip()
    raw_run_id = os.environ.get("SEMAPACT_LIVE_RUN_ID", "").strip() or f"drift_{int(datetime.now(timezone.utc).timestamp())}"
    run_id = _safe_run_id(raw_run_id)

    table_name = f"semapact_drift_{run_id}"
    client = create_databricks_workspace_client()
    source_reference = str(getattr(client.config, "host", "") or "").strip()
    if not source_reference:
        pytest.fail("Databricks SDK did not resolve a workspace host")

    full_name = f"{catalog}.{schema_name}.{table_name}"
    contract = _contract(table_name=table_name, include_note=False)
    deployment = DeploymentWorkflowService()
    target = _target(
        catalog=catalog,
        schema_name=schema_name,
        source_reference=source_reference,
    )

    try:
        _delete_if_present(client, full_name)

        bundle = deployment.assess(
            contract,
            contract,
            base_revision_ref=f"live:base:{run_id}",
            candidate_revision_ref=f"live:base:{run_id}",
            target=target,
            adapter=_adapter(warehouse_id=warehouse_id),
        )
        create_result = deployment.deploy(
            bundle,
            adapter=_adapter(warehouse_id=warehouse_id),
        )
        assert create_result.status is RuntimeDriftStatus.IN_SYNC

        # Introduce out-of-band drift
        executor = DatabricksStatementExecutor(
            client=client,
            warehouse_id=warehouse_id,
            poll_interval_seconds=1,
        )
        executor._run_statement(
            f"ALTER TABLE `{catalog}`.`{schema_name}`.`{table_name}` "
            "ADD COLUMNS (`rogue_col` STRING COMMENT 'out of band drift')"
        )

        # Observe runtime via DatabricksRuntimeProvider and reconcile
        runtime_provider = DatabricksRuntimeProvider(
            client=client,
            source_identifier=source_reference,
        )
        bindings = runtime_provider.resolve_bindings(
            runtime_target=f"{catalog}.{schema_name}",
            assets=runtime_asset_specs_from_contract(contract),
        )
        observation = runtime_provider.observe(bindings=bindings)
        reconciliation_result = reconcile_governed_contract(
            contract,
            observation,
            asset_bindings=bindings,
        )
        drift_status = classify_reconciliation_status(reconciliation_result)
        assert drift_status is RuntimeDriftStatus.DRIFT
    finally:
        _delete_if_present(client, full_name)
