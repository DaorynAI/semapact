#!/usr/bin/env python3
"""Live regression test runner for SemaPact Databricks table deployment.

Treats the entire Unity Catalog schema (manufacturing_demo.gold) as a Data Product:
1. Pre-flight readiness diagnostics (Doctor probe)
2. Discovery of all assets in the Data Product schema
3. Ingestion of all existing Data Product tables into one unified ODCS contract
4. Introduction of a brand-new table into the Data Product contract
5. Differential deployment assessment:
   - All existing Data Product tables plan as NO_OP (untouched)
   - New table plans and executes as CREATE TABLE ... USING DELTA
6. Schema evolution on the new table within the Data Product (ALTER TABLE ADD COLUMNS)
7. Formal release deployment & Unity Catalog table tag projection
8. Idempotent re-deployment convergence across the entire Data Product
9. Out-of-band drift detection & runtime reconciliation across the Data Product
10. Safe resource cleanup (drops only the new test table, preserving Data Product baseline)
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
import sys
import time

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
from semapact.governance import DecisionResult
from semapact.importers.unity_importer import import_unity_contract
from semapact.platforms.databricks import create_databricks_workspace_client
from semapact.platforms.databricks.deployment import (
    DatabricksDeploymentExecutionConfig,
    DatabricksStatementExecutor,
)
from semapact.platforms.databricks.readiness import DatabricksReadinessProbe
from semapact.platforms.databricks.runtime import DatabricksRuntimeProvider
from semapact.platforms.runtime_registry import create_deployment_adapter
from semapact.reconciliation import (
    RuntimeDriftStatus,
    classify_reconciliation_status,
    reconcile_governed_contract,
    runtime_asset_specs_from_contract,
)


def _log(step: str, msg: str) -> None:
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] [{step}] {msg}")


def _build_new_table_object(*, table_name: str, include_evolution: bool) -> SchemaObject:
    """Build ODCS schema object for a brand-new table introduced to the Data Product."""
    props = [
        SchemaProperty(
            name="action_id",
            physicalName="action_id",
            logicalType="integer",
            physicalType="BIGINT",
            required=True,
            description="Unique identifier for the risk mitigation action",
        ),
        SchemaProperty(
            name="action_type",
            physicalName="action_type",
            logicalType="string",
            physicalType="STRING",
            required=True,
            description="Action category: INSPECTION, REPAIR, or REPLACEMENT",
        ),
        SchemaProperty(
            name="estimated_cost",
            physicalName="estimated_cost",
            logicalType="number",
            physicalType="DOUBLE",
            required=False,
            description="Estimated cost of the mitigation action",
        ),
    ]
    if include_evolution:
        props.append(
            SchemaProperty(
                name="resolution_notes",
                physicalName="resolution_notes",
                logicalType="string",
                physicalType="STRING",
                required=False,
                description="Optional resolution details added in schema evolution",
            )
        )
    return SchemaObject(
        name=table_name,
        physicalName=table_name,
        physicalType="table",
        properties=props,
        description="Governed mitigation actions table paired with business risk assets",
    )


def main() -> int:
    catalog = os.environ.get("SEMAPACT_LIVE_DATABRICKS_CATALOG", "manufacturing_demo").strip()
    schema_name = os.environ.get("SEMAPACT_LIVE_DATABRICKS_PROD_SCHEMA", "gold").strip()
    warehouse_id = os.environ.get(
        "SEMAPACT_LIVE_DATABRICKS_WAREHOUSE_ID", "dae52f9b349fc77f"
    ).strip()

    run_ts = int(time.time())
    run_id = f"reg_{run_ts}"
    new_table_name = f"semapact_action_{run_id}"
    new_fqn = f"{catalog}.{schema_name}.{new_table_name}"

    _log("INIT", "=" * 70)
    _log("INIT", "SemaPact Live Databricks Regression Suite (Whole Schema as Data Product)")
    _log("INIT", f"Target Catalog:      {catalog}")
    _log("INIT", f"Data Product Schema: {schema_name}")
    _log("INIT", f"New Test Table:      {new_fqn} (managed lifecycle)")
    _log("INIT", f"SQL Warehouse:       {warehouse_id}")
    _log("INIT", "=" * 70)

    # 1. Authenticate client
    client = create_databricks_workspace_client()
    host = str(getattr(client.config, "host", "") or "").strip()
    user = client.current_user.me().user_name
    _log("AUTH", f"Connected to {host} as {user}")

    adapter = create_deployment_adapter(
        "databricks",
        execution_config=DatabricksDeploymentExecutionConfig(
            warehouse_id=warehouse_id
        ),
    )
    deployment_service = DeploymentWorkflowService()
    target = DeploymentTarget(
        platform="databricks",
        runtime_target=f"{catalog}.{schema_name}",
        source_reference=host,
    )

    def _delete_new_table() -> None:
        try:
            if bool(getattr(client.tables.exists(full_name=new_fqn), "table_exists", False)):
                client.tables.delete(full_name=new_fqn)
                _log("CLEANUP", f"Deleted test table {new_fqn}")
        except Exception as exc:
            _log("CLEANUP", f"Note during cleanup of {new_fqn}: {exc}")

    try:
        # Ensure new table doesn't pre-exist
        _delete_new_table()

        # ---------------------------------------------------------------------
        # Step 1: Pre-flight Readiness Diagnostics
        # ---------------------------------------------------------------------
        _log("STEP 1", "Running DatabricksReadinessProbe (Doctor check)...")
        probe = DatabricksReadinessProbe(
            runtime_target=f"{catalog}.{schema_name}",
            warehouse_id=warehouse_id,
        )
        checks = probe.run()
        for check in checks:
            status_symbol = "✓" if check.status.value == "PASS" else "✗"
            _log("STEP 1", f"  [{status_symbol}] {check.check_id}: {check.summary}")
            if check.status.value != "PASS":
                _log("ERROR", f"Readiness check failed: {check.remediation}")
                return 1
        _log("STEP 1", "Readiness diagnostics passed successfully.")

        # ---------------------------------------------------------------------
        # Step 2: Discover and Ingest Entire Data Product Schema from Unity Catalog
        # ---------------------------------------------------------------------
        _log("STEP 2", f"Ingesting complete Data Product schema {catalog}.{schema_name} via import_unity_contract...")
        data_product_contract_base = import_unity_contract(
            table_fqn=f"{catalog}.{schema_name}",
            client=client,
        )
        data_product_contract_base.id = f"manufacturing-gold-product-{run_id}"
        data_product_contract_base.name = f"Manufacturing Gold Data Product {run_id}"
        data_product_contract_base.version = "1.0.0"
        data_product_contract_base.status = "active"
        existing_table_names = [m.name for m in (data_product_contract_base.schema_ or [])]
        _log("STEP 2", f"Successfully ingested Data Product with {len(existing_table_names)} tables: {existing_table_names}")

        # ---------------------------------------------------------------------
        # Step 3: Add a Brand-New Governed Table into the Data Product
        # ---------------------------------------------------------------------
        _log("STEP 3", f"Adding new governed table '{new_table_name}' to Data Product contract...")
        new_table_base_schema = _build_new_table_object(
            table_name=new_table_name,
            include_evolution=False,
        )
        assert data_product_contract_base.schema_ is not None
        data_product_contract_base.schema_.append(new_table_base_schema)

        # ---------------------------------------------------------------------
        # Step 4: Candidate Assess & Deploy (Differential Convergence across whole Data Product)
        # ---------------------------------------------------------------------
        total_tables = len(data_product_contract_base.schema_)
        _log("STEP 4", f"Assessing complete Data Product ({total_tables} tables) against Unity Catalog...")
        bundle_candidate = deployment_service.assess(
            data_product_contract_base,
            data_product_contract_base,
            base_revision_ref=f"live:base:{run_id}",
            candidate_revision_ref=f"live:base:{run_id}",
            target=target,
            adapter=adapter,
        )

        planned_ops = {op.governed_asset: op for op in bundle_candidate.review_preview.operations}
        _log("STEP 4", f"Planned operations across all {len(planned_ops)} tables in Data Product:")
        for asset_name, op in sorted(planned_ops.items()):
            _log("STEP 4", f"  - {asset_name}: {op.kind.value}")

        # Crucial verification: all existing tables in the Data Product are NO_OP!
        for name in existing_table_names:
            assert planned_ops[name].kind is NativeOperationKind.NO_OP, \
                f"Expected existing Data Product table {name} to be NO_OP, got {planned_ops[name].kind}"
        # Crucial verification: newly introduced table is CREATE!
        assert planned_ops[new_table_name].kind is NativeOperationKind.CREATE, \
            f"Expected new table {new_table_name} to be CREATE, got {planned_ops[new_table_name].kind}"

        _log("STEP 4", f"Deploying Data Product (creating {new_fqn} on Databricks)...")
        result_candidate = deployment_service.deploy(bundle_candidate, adapter=adapter)
        _log("STEP 4", f"Data Product deploy result: {result_candidate.status.value}")
        assert result_candidate.status is RuntimeDriftStatus.IN_SYNC

        # Verify new table now exists in Unity Catalog
        new_table_info = client.tables.get(new_fqn)
        new_cols = [col.name for col in (new_table_info.columns or [])]
        _log("STEP 4", f"Verified columns in new Unity Catalog table: {new_cols}")
        assert "action_id" in new_cols and "action_type" in new_cols and "estimated_cost" in new_cols

        # ---------------------------------------------------------------------
        # Step 5: Schema Evolution on New Table within the Data Product
        # ---------------------------------------------------------------------
        _log("STEP 5", f"Evolving schema on {new_table_name} (adding 'resolution_notes')...")
        new_table_evolved_schema = _build_new_table_object(
            table_name=new_table_name,
            include_evolution=True,
        )
        evolved_schemas = [
            m for m in data_product_contract_base.schema_
            if m.name != new_table_name
        ] + [new_table_evolved_schema]

        data_product_contract_evolved = OpenDataContractStandard(
            apiVersion=data_product_contract_base.apiVersion,
            kind="DataContract",
            id=data_product_contract_base.id,
            name=data_product_contract_base.name,
            version=data_product_contract_base.version,
            status="active",
            schema=evolved_schemas,
        )

        bundle_evolve = deployment_service.assess(
            data_product_contract_base,
            data_product_contract_evolved,
            base_revision_ref=f"live:base:{run_id}",
            candidate_revision_ref=f"live:candidate:{run_id}",
            target=target,
            adapter=adapter,
        )
        evolve_ops = {op.governed_asset: op for op in bundle_evolve.review_preview.operations}
        for name in existing_table_names:
            assert evolve_ops[name].kind is NativeOperationKind.NO_OP
        assert evolve_ops[new_table_name].kind is NativeOperationKind.ALTER

        result_evolve = deployment_service.deploy(bundle_evolve, adapter=adapter)
        _log("STEP 5", f"Evolution deploy result: {result_evolve.status.value}")
        assert result_evolve.status is RuntimeDriftStatus.IN_SYNC

        evolved_table_info = client.tables.get(new_fqn)
        evolved_cols = [col.name for col in (evolved_table_info.columns or [])]
        _log("STEP 5", f"Updated columns in Unity Catalog: {evolved_cols}")
        assert "resolution_notes" in evolved_cols

        # ---------------------------------------------------------------------
        # Step 6: Formal Release Workflow & Provenance Tag Projection
        # ---------------------------------------------------------------------
        _log("STEP 6", "Finalizing formal release for the whole Data Product...")
        release_workflow = ReleaseWorkflowService()
        release_bundle = release_workflow.assess(
            data_product_contract_base,
            data_product_contract_evolved,
            base_revision_ref=f"live:base:{run_id}",
            candidate_revision_ref=f"live:candidate:{run_id}",
        )
        approval = None
        if release_bundle.decision.decision is DecisionResult.REVIEW:
            _log("STEP 6", "Recording formal release approval...")
            approval = release_workflow.approve(
                release_bundle,
                actor_reference="live-reg:lead-architect",
                recorded_at=datetime.now(timezone.utc),
                comment="Approved live regression release for manufacturing gold data product",
            )
        release = ReleaseFinalizer().finalize(release_bundle, approval=approval)
        _log("STEP 6", f"Finalized ContractRelease: {release.contract_release_id} (version {release.contract_version})")

        prod_bundle = deployment_service.assess_release(
            release,
            target=target,
            adapter=adapter,
        )
        result_prod = deployment_service.deploy(prod_bundle, adapter=adapter)
        _log("STEP 6", f"Formal release deploy result: {result_prod.status.value}")
        assert result_prod.status is RuntimeDriftStatus.IN_SYNC

        # Verify table tags on the new table
        executor = DatabricksStatementExecutor(
            client=client,
            warehouse_id=warehouse_id,
            poll_interval_seconds=1,
        )
        tag_rows = executor.query_rows(
            "SELECT tag_name, tag_value "
            f"FROM `{catalog}`.information_schema.table_tags "
            f"WHERE schema_name = '{schema_name.casefold()}' "
            f"AND table_name = '{new_table_name.casefold()}'"
        )
        tags_dict = {str(k): str(v) for k, v in tag_rows}
        _log("STEP 6", f"Verified Unity Catalog table tags on {new_table_name}:")
        for k, v in tags_dict.items():
            _log("STEP 6", f"  - {k} = {v}")
        assert tags_dict.get("semapact_contract_id") == release.contract_id
        assert tags_dict.get("semapact_contract_version") == release.contract_version
        assert tags_dict.get("semapact_release_id") == release.contract_release_id
        assert tags_dict.get("semapact_source_revision") == release.source_revision_ref

        # ---------------------------------------------------------------------
        # Step 7: Idempotency Verification across Data Product
        # ---------------------------------------------------------------------
        _log("STEP 7", "Verifying deployment idempotency (re-deploying prod bundle)...")
        repeat_result = deployment_service.deploy(prod_bundle, adapter=adapter)
        _log("STEP 7", f"Re-deploy result: {repeat_result.status.value}")
        assert repeat_result.status is RuntimeDriftStatus.IN_SYNC
        for op in repeat_result.fresh_preview.operations:
            assert op.kind is NativeOperationKind.NO_OP, f"Expected NO_OP, got {op.kind}"
        _log("STEP 7", f"All {len(repeat_result.fresh_preview.operations)} operations converged to NO_OP as expected.")

        # ---------------------------------------------------------------------
        # Step 8: Out-of-Band Drift Detection & Reconciliation across Data Product
        # ---------------------------------------------------------------------
        _log("STEP 8", f"Simulating out-of-band physical drift on {new_fqn}...")
        executor._run_statement(
            f"ALTER TABLE `{catalog}`.`{schema_name}`.`{new_table_name}` "
            "ADD COLUMNS (`rogue_telemetry_id` STRING COMMENT 'untracked drift column')"
        )

        _log("STEP 8", "Running runtime reconciliation across Data Product...")
        runtime_provider = DatabricksRuntimeProvider(
            client=client,
            source_identifier=host,
        )
        bindings = runtime_provider.resolve_bindings(
            runtime_target=f"{catalog}.{schema_name}",
            assets=runtime_asset_specs_from_contract(data_product_contract_evolved),
        )
        observation = runtime_provider.observe(bindings=bindings)
        reconcile_res = reconcile_governed_contract(
            data_product_contract_evolved,
            observation,
            asset_bindings=bindings,
        )
        drift_status = classify_reconciliation_status(reconcile_res)
        _log("STEP 8", f"Reconciliation classification: {drift_status.value}")
        assert drift_status is RuntimeDriftStatus.DRIFT, "Expected DRIFT classification"
        _log("STEP 8", "Drift detection successfully identified out-of-band column change across Data Product.")

        _log("SUMMARY", "=" * 70)
        _log("SUMMARY", "ALL LIVE REGRESSION TESTS PASSED FOR COMPLETE DATA PRODUCT!")
        _log("SUMMARY", "=" * 70)
        return 0

    finally:
        _log("CLEANUP", f"Cleaning up temporary test table {new_fqn} (leaving Data Product tables intact)...")
        _delete_new_table()


if __name__ == "__main__":
    sys.exit(main())
