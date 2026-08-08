from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import pandas as pd

from datacontract.data_contract import DataContract
from open_data_contract_standard.model import OpenDataContractStandard
from semapact.core.validator import ValidationIssue, ValidationReport
from semapact.devops.audit import AuditMetadata
from semapact.lifecycle.merge_engine import MergeConflict, MergeResult
from semapact.lifecycle.policy import BreakingChange, PolicyEvaluation
from semapact.orchestrator.pipeline import ContractPipeline
from deltalake import write_deltalake


def test_pipeline_import_schema_supports_delta_and_sql(monkeypatch):
    def fake_import(format: str, source: str | None = None, **_kwargs):  # noqa: ANN001
        return OpenDataContractStandard.model_validate(
            {
                "apiVersion": "v3.1.0",
                "kind": "DataContract",
                "id": "from-importer",
                "name": source or "unknown",
                "version": "1.0.0",
                "status": "draft",
                "schema": [
                    {
                        "name": "t1",
                        "properties": [{"name": "id", "logicalType": "string"}],
                    }
                ],
            }
        )

    monkeypatch.setattr(DataContract, "import_from_source", staticmethod(fake_import))

    pipeline = ContractPipeline()

    delta_contract = pipeline.import_schema("delta", "delta://orders")
    sql_contract = pipeline.import_schema("sql", "orders_folder")

    assert delta_contract.id == "from-importer"
    assert sql_contract.id == "from-importer"


def test_pipeline_import_schema_requires_uc_credentials():
    pipeline = ContractPipeline()

    with pytest.raises(Exception, match="databricks.workspace_url and databricks.token"):
        pipeline.import_schema("uc", "main.silver.orders")


def test_pipeline_import_schema_supports_uc_when_credentials_are_given(monkeypatch):
    captured: dict[str, object] = {}

    def fake_import(format: str, source: str | None = None, **_kwargs):  # noqa: ANN001
        return OpenDataContractStandard.model_validate(
            {
                "apiVersion": "v3.1.0",
                "kind": "DataContract",
                "id": "uc-id",
                "name": "orders",
                "version": "1.0.0",
                "status": "draft",
                "schema": [
                    {
                        "name": "t1",
                        "properties": [{"name": "id", "logicalType": "string"}],
                    }
                ],
            }
        )

    def fake_enrich(contract, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return contract

    monkeypatch.setattr(
        "semapact.importers.unity_importer.DataContract.import_from_source",
        staticmethod(fake_import),
    )
    monkeypatch.setattr(
        "semapact.importers.unity_importer.enrich_unity_contract_relationships",
        fake_enrich,
    )
    pipeline = ContractPipeline()

    contract = pipeline.import_schema(
        "uc",
        "main.silver.orders",
        uc_workspace_url="https://adb.example",
        uc_token="token",
    )

    assert contract.id == "uc-id"
    assert captured["table_fqn"] == "main.silver.orders"
    assert captured["workspace_url"] == "https://adb.example"
    assert captured["token"] == "token"


def test_pipeline_import_schema_rejects_unknown_source_type():
    pipeline = ContractPipeline()

    with pytest.raises(Exception, match="Unsupported source_type"):
        pipeline.import_schema("unknown", "src")  # type: ignore[arg-type]


def test_pipeline_prepare_ci_cd_artifacts_writes_manifest_and_outputs(
    monkeypatch, tmp_path, sample_odcs_model
):
    pipeline = ContractPipeline()
    merged_contract = sample_odcs_model
    merge_result = MergeResult(
        contract=merged_contract, conflicts=[MergeConflict("p", "r", 1, 2)]
    )
    validation = ValidationReport(valid=True, issues=[])
    policy = PolicyEvaluation(valid=True, breaking_changes=[])
    audit = AuditMetadata(
        last_merge_ts="2026-02-24T00:00:00+00:00",
        last_merge_actor="tester",
        last_merge_source="sql",
    )
    fake_suite_path = tmp_path / "suite.json"
    fake_suite_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "semapact.orchestrator.pipeline.GreatExpectationsExporter.export_to_path",
        lambda self, *args, **kwargs: fake_suite_path,
    )

    artifacts = pipeline.prepare_ci_cd_artifacts(
        merged_contract,
        merge_result,
        validation,
        policy,
        merged_contract_output_path=str(tmp_path / "merged.yaml"),
        ge_suite_output_path=str(tmp_path / "suite.json"),
        ci_manifest_output_path=str(tmp_path / "manifest.json"),
        audit_metadata=audit,
    )

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert artifacts.merged_contract_path.exists()
    assert artifacts.ge_suite_path.exists()
    assert artifacts.ci_manifest_path.exists()
    assert manifest["valid"] is True
    assert manifest["policyValid"] is True
    assert manifest["idViolation"] is False
    assert manifest["versionViolation"] is False
    assert manifest["audit"]["last_merge_actor"] == "tester"


def test_pipeline_run_raises_on_failed_contract_validation(
    monkeypatch, sample_odcs_model
):
    pipeline = ContractPipeline()

    monkeypatch.setattr(
        ContractPipeline,
        "import_schema",
        lambda self, *args, **kwargs: sample_odcs_model,
    )
    monkeypatch.setattr(
        type(pipeline.loader), "load", lambda self, _: sample_odcs_model
    )
    monkeypatch.setattr(
        ContractPipeline,
        "merge_contract_updates",
        lambda self, *args, **kwargs: MergeResult(
            contract=sample_odcs_model, conflicts=[]
        ),
    )
    monkeypatch.setattr(
        ContractPipeline,
        "validate_contract",
        lambda self, _: ValidationReport(
            valid=False, issues=[ValidationIssue(path="schema", message="bad")]
        ),
    )

    with pytest.raises(Exception, match="Merged contract validation failed"):
        pipeline.run(
            source_type="sql",
            source="sql_folder",
            business_contract_path="examples/sample_odcs.yaml",
            merged_contract_output_path="/tmp/merged.yaml",
            ge_suite_output_path="/tmp/suite.json",
            ci_manifest_output_path="/tmp/manifest.json",
        )


def test_pipeline_run_raises_on_failed_lifecycle_policy(monkeypatch, sample_odcs_model):
    pipeline = ContractPipeline()

    monkeypatch.setattr(
        ContractPipeline,
        "import_schema",
        lambda self, *args, **kwargs: sample_odcs_model,
    )
    monkeypatch.setattr(
        type(pipeline.loader), "load", lambda self, _: sample_odcs_model
    )
    monkeypatch.setattr(
        ContractPipeline,
        "merge_contract_updates",
        lambda self, *args, **kwargs: MergeResult(
            contract=sample_odcs_model, conflicts=[]
        ),
    )
    monkeypatch.setattr(
        ContractPipeline,
        "validate_contract",
        lambda self, _: ValidationReport(valid=True, issues=[]),
    )
    monkeypatch.setattr(
        ContractPipeline,
        "evaluate_policy",
        lambda self, *args, **kwargs: SimpleNamespace(
            valid=False,
            version_violation=True,
            breaking_changes=[BreakingChange(path="schema[tbl]", message="removed")],
        ),
    )

    with pytest.raises(Exception, match="Policy Violation"):
        pipeline.run(
            source_type="sql",
            source="sql_folder",
            business_contract_path="examples/sample_odcs.yaml",
            merged_contract_output_path="/tmp/merged.yaml",
            ge_suite_output_path="/tmp/suite.json",
            ci_manifest_output_path="/tmp/manifest.json",
        )


def test_pipeline_run_does_not_block_non_version_policy_findings(
    monkeypatch, sample_odcs_model, tmp_path
):
    pipeline = ContractPipeline()
    from semapact.orchestrator.pipeline import PipelineArtifacts

    expected_artifacts = PipelineArtifacts(
        merged_contract_path=tmp_path / "merged.yaml",
        ge_suite_path=tmp_path / "suite.json",
        ci_manifest_path=tmp_path / "manifest.json",
    )

    monkeypatch.setattr(
        ContractPipeline,
        "import_schema",
        lambda self, *args, **kwargs: sample_odcs_model,
    )
    monkeypatch.setattr(
        type(pipeline.loader), "load", lambda self, _: sample_odcs_model
    )
    monkeypatch.setattr(
        ContractPipeline,
        "merge_contract_updates",
        lambda self, *args, **kwargs: MergeResult(
            contract=sample_odcs_model, conflicts=[]
        ),
    )
    monkeypatch.setattr(
        ContractPipeline,
        "validate_contract",
        lambda self, _: ValidationReport(valid=True, issues=[]),
    )
    monkeypatch.setattr(
        ContractPipeline,
        "evaluate_policy",
        lambda self, *args, **kwargs: PolicyEvaluation(
            valid=False,
            breaking_changes=[BreakingChange(path="schema[tbl]", message="removed")],
        ),
    )
    monkeypatch.setattr(
        ContractPipeline,
        "prepare_ci_cd_artifacts",
        lambda self, *args, **kwargs: expected_artifacts,
    )

    artifacts = pipeline.run(
        source_type="sql",
        source="sql_folder",
        business_contract_path="examples/sample_odcs.yaml",
        merged_contract_output_path=str(tmp_path / "merged2.yaml"),
        ge_suite_output_path=str(tmp_path / "suite2.json"),
        ci_manifest_output_path=str(tmp_path / "manifest2.json"),
    )

    assert artifacts == expected_artifacts


def test_pipeline_run_blocks_retired_contract(monkeypatch, sample_odcs_model):
    pipeline = ContractPipeline()
    retired_contract = sample_odcs_model.model_copy(deep=True)
    retired_contract.status = "retired"

    monkeypatch.setattr(
        ContractPipeline,
        "import_schema",
        lambda self, *args, **kwargs: sample_odcs_model,
    )
    monkeypatch.setattr(type(pipeline.loader), "load", lambda self, _: retired_contract)

    with pytest.raises(Exception, match="Cannot run pipeline on retired contract"):
        pipeline.run(
            source_type="sql",
            source="sql_folder",
            business_contract_path="examples/sample_odcs.yaml",
            merged_contract_output_path="/tmp/merged.yaml",
            ge_suite_output_path="/tmp/suite.json",
            ci_manifest_output_path="/tmp/manifest.json",
        )


def test_pipeline_run_blocks_when_merge_returns_none_contract(
    monkeypatch, sample_odcs_model
):
    pipeline = ContractPipeline()

    monkeypatch.setattr(
        ContractPipeline,
        "import_schema",
        lambda self, *args, **kwargs: sample_odcs_model,
    )
    monkeypatch.setattr(
        type(pipeline.loader), "load", lambda self, _: sample_odcs_model
    )
    monkeypatch.setattr(
        ContractPipeline,
        "merge_contract_updates",
        lambda self, *args, **kwargs: SimpleNamespace(contract=None, conflicts=[]),
    )

    with pytest.raises(Exception, match="Merge did not produce a contract"):
        pipeline.run(
            source_type="sql",
            source="sql_folder",
            business_contract_path="examples/sample_odcs.yaml",
            merged_contract_output_path="/tmp/merged.yaml",
            ge_suite_output_path="/tmp/suite.json",
            ci_manifest_output_path="/tmp/manifest.json",
        )


def test_pipeline_run_blocks_on_conflicts_when_fail_on_conflict(
    monkeypatch, sample_odcs_model
):
    pipeline = ContractPipeline()
    conflict = MergeConflict(
        schema_id="orders", property_name="id", message="type mismatch"
    )

    monkeypatch.setattr(
        ContractPipeline,
        "import_schema",
        lambda self, *args, **kwargs: sample_odcs_model,
    )
    monkeypatch.setattr(
        type(pipeline.loader), "load", lambda self, _: sample_odcs_model
    )
    monkeypatch.setattr(
        ContractPipeline,
        "merge_contract_updates",
        lambda self, *args, **kwargs: MergeResult(
            contract=sample_odcs_model, conflicts=[conflict]
        ),
    )

    with pytest.raises(
        Exception, match="Merge conflicts detected: orders.id: type mismatch"
    ):
        pipeline.run(
            source_type="sql",
            source="sql_folder",
            business_contract_path="examples/sample_odcs.yaml",
            merged_contract_output_path="/tmp/merged.yaml",
            ge_suite_output_path="/tmp/suite.json",
            ci_manifest_output_path="/tmp/manifest.json",
            fail_on_conflict=True,
        )


def test_pipeline_run_returns_artifacts_on_success(
    monkeypatch, sample_odcs_model, tmp_path
):
    pipeline = ContractPipeline()
    from semapact.orchestrator.pipeline import PipelineArtifacts

    expected_artifacts = PipelineArtifacts(
        merged_contract_path=tmp_path / "merged.yaml",
        ge_suite_path=tmp_path / "suite.json",
        ci_manifest_path=tmp_path / "manifest.json",
    )

    monkeypatch.setattr(
        ContractPipeline,
        "import_schema",
        lambda self, *args, **kwargs: sample_odcs_model,
    )
    monkeypatch.setattr(
        type(pipeline.loader), "load", lambda self, _: sample_odcs_model
    )
    monkeypatch.setattr(
        ContractPipeline,
        "merge_contract_updates",
        lambda self, *args, **kwargs: MergeResult(
            contract=sample_odcs_model, conflicts=[]
        ),
    )
    monkeypatch.setattr(
        ContractPipeline,
        "validate_contract",
        lambda self, _: ValidationReport(valid=True, issues=[]),
    )
    monkeypatch.setattr(
        ContractPipeline,
        "evaluate_policy",
        lambda self, *args, **kwargs: PolicyEvaluation(valid=True, breaking_changes=[]),
    )
    monkeypatch.setattr(
        ContractPipeline,
        "prepare_ci_cd_artifacts",
        lambda self, *args, **kwargs: expected_artifacts,
    )

    artifacts = pipeline.run(
        source_type="sql",
        source="sql_folder",
        business_contract_path="examples/sample_odcs.yaml",
        merged_contract_output_path=str(tmp_path / "merged2.yaml"),
        ge_suite_output_path=str(tmp_path / "suite2.json"),
        ci_manifest_output_path=str(tmp_path / "manifest2.json"),
    )

    assert artifacts == expected_artifacts


def test_pipeline_run_executes_real_merge_validation_and_policy_with_minimal_mocking(
    monkeypatch,
    sample_spark_ddl_contract_model,
    sample_unity_contract_dict,
    tmp_path,
):
    business_contract_path = tmp_path / "business.yaml"
    business_payload = sample_unity_contract_dict
    business_contract_path.write_text(
        OpenDataContractStandard.model_validate(business_payload).to_yaml(),
        encoding="utf-8",
    )

    imported_contract = sample_spark_ddl_contract_model.model_copy(deep=True)
    imported_contract.schema_[0].physicalName = "orders"

    monkeypatch.setattr(
        DataContract,
        "import_from_source",
        staticmethod(lambda format, source=None, **kwargs: imported_contract),
    )

    def fake_export_to_path(
        self, contract, output_path, *, schema_name="all", suite_name=None
    ):  # noqa: ANN001
        path = tmp_path / "suite.json"
        path.write_text('{"expectations": []}', encoding="utf-8")
        return path

    monkeypatch.setattr(
        "semapact.orchestrator.pipeline.GreatExpectationsExporter.export_to_path",
        fake_export_to_path,
    )

    artifacts = ContractPipeline().run(
        source_type="sql",
        source="sql_folder",
        business_contract_path=str(business_contract_path),
        merged_contract_output_path=str(tmp_path / "merged.yaml"),
        ge_suite_output_path=str(tmp_path / "suite.json"),
        ci_manifest_output_path=str(tmp_path / "manifest.json"),
    )

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    merged_contract = OpenDataContractStandard.from_file(
        str(artifacts.merged_contract_path)
    )
    merged_schema = merged_contract.schema_[0]
    merged_id = next(
        prop for prop in (merged_schema.properties or []) if prop.name == "id"
    )

    assert artifacts.merged_contract_path.exists()
    assert artifacts.ge_suite_path.exists()
    assert artifacts.ci_manifest_path.exists()
    assert manifest["valid"] is True
    assert manifest["policyValid"] is True
    assert merged_contract.id == "orders"
    assert merged_schema.description == "Orders external table"
    assert merged_id.description == "Order id"
    assert str(merged_id.physicalType).lower() == "bigint"


def test_pipeline_run_executes_real_sql_folder_workflow(
    monkeypatch,
    spark_ddl_orders_product_dir,
    sample_unity_contract_path,
    tmp_path,
):
    def fake_export_to_path(
        self, contract, output_path, *, schema_name="all", suite_name=None
    ):  # noqa: ANN001
        path = tmp_path / "suite.json"
        path.write_text('{"expectations": []}', encoding="utf-8")
        return path

    monkeypatch.setattr(
        "semapact.orchestrator.pipeline.GreatExpectationsExporter.export_to_path",
        fake_export_to_path,
    )

    artifacts = ContractPipeline().run(
        source_type="sql-folder",
        source=str(spark_ddl_orders_product_dir),
        business_contract_path=str(sample_unity_contract_path),
        merged_contract_output_path=str(tmp_path / "merged.yaml"),
        ge_suite_output_path=str(tmp_path / "suite.json"),
        ci_manifest_output_path=str(tmp_path / "manifest.json"),
    )

    merged_contract = OpenDataContractStandard.from_file(
        str(artifacts.merged_contract_path)
    )
    merged_schema = merged_contract.schema_[0]
    merged_props = {prop.name: prop for prop in (merged_schema.properties or [])}
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert artifacts.merged_contract_path.exists()
    assert manifest["valid"] is True
    assert manifest["policyValid"] is True
    assert merged_contract.id == "orders"
    assert merged_schema.name == "orders"
    assert "processed_at" in merged_props
    assert str(merged_props["processed_at"].physicalType).lower() == "timestamp"


def test_pipeline_run_executes_real_delta_workflow(
    monkeypatch,
    sample_unity_contract_path,
    tmp_path,
):
    table_path = tmp_path / "orders"
    data = pd.DataFrame(
        {
            "id": pd.Series([1, 2], dtype="int64"),
            "amount": pd.Series([10.5, 22.75], dtype="float64"),
            "processed_at": pd.to_datetime(
                ["2026-04-03T10:00:00Z", "2026-04-03T10:01:00Z"], utc=True
            ),
        }
    )
    write_deltalake(str(table_path), data, mode="overwrite")

    def fake_export_to_path(
        self, contract, output_path, *, schema_name="all", suite_name=None
    ):  # noqa: ANN001
        path = tmp_path / "suite.json"
        path.write_text('{"expectations": []}', encoding="utf-8")
        return path

    monkeypatch.setattr(
        "semapact.orchestrator.pipeline.GreatExpectationsExporter.export_to_path",
        fake_export_to_path,
    )

    artifacts = ContractPipeline().run(
        source_type="delta",
        source=str(table_path),
        business_contract_path=str(sample_unity_contract_path),
        merged_contract_output_path=str(tmp_path / "merged.yaml"),
        ge_suite_output_path=str(tmp_path / "suite.json"),
        ci_manifest_output_path=str(tmp_path / "manifest.json"),
    )

    merged_contract = OpenDataContractStandard.from_file(
        str(artifacts.merged_contract_path)
    )
    merged_schema = merged_contract.schema_[0]
    merged_props = {prop.name: prop for prop in (merged_schema.properties or [])}
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert artifacts.merged_contract_path.exists()
    assert manifest["valid"] is True
    assert manifest["policyValid"] is True
    assert merged_contract.version == "1.0.0"
    assert "processed_at" in merged_props
    assert merged_props["id"].logicalType == "integer"


def test_pipeline_run_executes_real_unity_workflow(
    monkeypatch,
    sample_unity_contract_path,
    sample_unity_contract_model,
    tmp_path,
):
    captured: dict[str, object] = {}

    imported_contract = sample_unity_contract_model.model_copy(deep=True)
    assert imported_contract.schema_ is not None
    assert imported_contract.schema_[0].properties is not None
    imported_contract.schema_[0].description = "Imported Unity orders table"
    imported_contract.schema_[0].properties.append(
        imported_contract.schema_[0]
        .properties[0]
        .model_copy(
            update={
                "id": "processed_at",
                "name": "processed_at",
                "physicalName": "processed_at",
                "logicalType": "timestamp",
                "physicalType": "TIMESTAMP",
                "required": False,
                "description": "Processing timestamp",
                "businessName": None,
            }
        )
    )

    def fake_import_from_source(format, source=None, **kwargs):  # noqa: ANN001
        assert format == "unity"
        assert kwargs["unity_table_full_name"] == ["main.silver.orders"]
        return imported_contract

    def fake_export_to_path(
        self, contract, output_path, *, schema_name="all", suite_name=None
    ):  # noqa: ANN001
        path = tmp_path / "suite.json"
        path.write_text('{"expectations": []}', encoding="utf-8")
        return path

    def fake_enrich(contract, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return contract

    monkeypatch.setattr(
        "semapact.importers.unity_importer.DataContract.import_from_source",
        staticmethod(fake_import_from_source),
    )
    monkeypatch.setattr(
        "semapact.orchestrator.pipeline.GreatExpectationsExporter.export_to_path",
        fake_export_to_path,
    )
    monkeypatch.setattr(
        "semapact.importers.unity_importer.enrich_unity_contract_relationships",
        fake_enrich,
    )

    artifacts = ContractPipeline().run(
        source_type="uc",
        source="main.silver.orders",
        business_contract_path=str(sample_unity_contract_path),
        merged_contract_output_path=str(tmp_path / "merged.yaml"),
        ge_suite_output_path=str(tmp_path / "suite.json"),
        ci_manifest_output_path=str(tmp_path / "manifest.json"),
        uc_workspace_url="https://adb.example",
        uc_token="token",
    )

    merged_contract = OpenDataContractStandard.from_file(
        str(artifacts.merged_contract_path)
    )
    merged_schema = merged_contract.schema_[0]
    merged_props = {prop.name: prop for prop in (merged_schema.properties or [])}
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert artifacts.merged_contract_path.exists()
    assert manifest["valid"] is True
    assert manifest["policyValid"] is True
    assert merged_schema.description == "Imported Unity orders table"
    assert "processed_at" in merged_props
    assert captured["table_fqn"] == "main.silver.orders"
    assert captured["workspace_url"] == "https://adb.example"
    assert captured["token"] == "token"


def test_pipeline_run_blocks_root_version_change_outside_release_flow(
    monkeypatch, sample_odcs_model
):
    pipeline = ContractPipeline()
    changed_version_contract = sample_odcs_model.model_copy(deep=True)
    changed_version_contract.version = "9.9.9"

    monkeypatch.setattr(
        ContractPipeline,
        "import_schema",
        lambda self, *args, **kwargs: sample_odcs_model,
    )
    monkeypatch.setattr(
        type(pipeline.loader), "load", lambda self, _: sample_odcs_model
    )
    monkeypatch.setattr(
        ContractPipeline,
        "merge_contract_updates",
        lambda self, *args, **kwargs: MergeResult(
            contract=changed_version_contract, conflicts=[]
        ),
    )
    monkeypatch.setattr(
        ContractPipeline,
        "validate_contract",
        lambda self, _: ValidationReport(valid=True, issues=[]),
    )

    with pytest.raises(Exception, match="Policy Violation"):
        pipeline.run(
            source_type="sql",
            source="sql_folder",
            business_contract_path="examples/sample_odcs.yaml",
            merged_contract_output_path="/tmp/merged.yaml",
            ge_suite_output_path="/tmp/suite.json",
            ci_manifest_output_path="/tmp/manifest.json",
        )


def test_pipeline_run_blocks_root_id_change_after_contract_creation(
    monkeypatch, sample_odcs_model
):
    pipeline = ContractPipeline()
    changed_id_contract = sample_odcs_model.model_copy(deep=True)
    changed_id_contract.id = "another-guid"

    monkeypatch.setattr(
        ContractPipeline,
        "import_schema",
        lambda self, *args, **kwargs: sample_odcs_model,
    )
    monkeypatch.setattr(
        type(pipeline.loader), "load", lambda self, _: sample_odcs_model
    )
    monkeypatch.setattr(
        ContractPipeline,
        "merge_contract_updates",
        lambda self, *args, **kwargs: MergeResult(
            contract=changed_id_contract, conflicts=[]
        ),
    )
    monkeypatch.setattr(
        ContractPipeline,
        "validate_contract",
        lambda self, _: ValidationReport(valid=True, issues=[]),
    )

    with pytest.raises(Exception, match="Policy Violation"):
        pipeline.run(
            source_type="sql",
            source="sql_folder",
            business_contract_path="examples/sample_odcs.yaml",
            merged_contract_output_path="/tmp/merged.yaml",
            ge_suite_output_path="/tmp/suite.json",
            ci_manifest_output_path="/tmp/manifest.json",
        )
