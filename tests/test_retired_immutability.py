from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from open_data_contract_standard.model import (
    CustomProperty,
    DataQuality,
    Description,
    OpenDataContractStandard,
    Relationship,
    SchemaObject,
    SchemaProperty,
)

from semapact.change_context import ChangeContext
from semapact.core.loader import ContractLoader
from semapact.devops.release_workflow import build_batch_release_manifest, create_release_pull_request
from semapact.exceptions import GovernanceBlockedError
from semapact.governance import (
    DecisionResult,
    GovernanceOperation,
    GovernanceReasonCode,
    evaluate_governance_decision,
    evaluate_governance_gate,
)
from semapact.interfaces.commands.export_cmd import run_export
from semapact.interfaces.commands.import_cmd import run_import
from semapact.interfaces.commands.lifecycle_cmd import (
    run_lifecycle_deprecate,
    run_lifecycle_promote,
)
from semapact.interfaces.commands.merge_cmd import run_merge
from semapact.interfaces.commands.release_cmd import (
    run_release_classify,
    run_release_prepare,
)
from semapact.orchestrator.pipeline import ContractPipeline
from semapact.services import GovernanceService
from semapact.utils.schema_utils import contract_to_dict
from semapact.utils.yaml_utils import dump_yaml

TEST_CONTEXT = ChangeContext(effective_date=date(2026, 8, 14))


def _make_retired_contract(**kwargs: object) -> OpenDataContractStandard:
    payload: dict[str, object] = {
        "apiVersion": "v3.1.0",
        "kind": "DataContract",
        "id": "urn:datacontract:orders",
        "name": "orders",
        "version": "1.0.0",
        "status": "retired",
        "description": {"usage": "Retired orders contract"},
        "tags": ["legacy", "orders"],
        "schema": [
            {
                "name": "orders",
                "physicalName": "tbl_orders",
                "description": "Orders table",
                "properties": [
                    {
                        "name": "order_id",
                        "physicalName": "order_id",
                        "logicalType": "string",
                        "physicalType": "VARCHAR(32)",
                        "required": True,
                        "description": "Primary order id",
                    },
                    {
                        "name": "amount",
                        "physicalName": "amount",
                        "logicalType": "number",
                        "physicalType": "DECIMAL(10,2)",
                        "required": False,
                        "description": "Total order amount",
                    },
                ],
            }
        ],
    }
    payload.update(kwargs)
    return OpenDataContractStandard.model_validate(payload)


def _make_active_contract(**kwargs: object) -> OpenDataContractStandard:
    c = _make_retired_contract(**kwargs)
    c.status = "active"
    return c


# ==============================================================================
# 1. Governance Kernel Matrix
# ==============================================================================


class TestRetiredKernelMatrix:
    """Validate kernel evaluation invariants for retired contracts."""

    def test_retired_unchanged_allows(self) -> None:
        """Unchanged retired base evaluated against identical candidate produces ALLOW."""
        base = _make_retired_contract()
        candidate = _make_retired_contract()

        decision = evaluate_governance_decision(base, candidate, context=TEST_CONTEXT)

        assert decision.decision == DecisionResult.ALLOW
        assert decision.policy.retired_violation is False
        assert not any(
            r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
            for r in decision.reasons
        )

    def test_retired_descriptive_metadata_change_blocks(self) -> None:
        """Modifying description or tags on a retired contract produces BLOCK."""
        base = _make_retired_contract()
        candidate = _make_retired_contract()
        candidate.description = Description(usage="Updated description on retired contract")
        candidate.tags = ["legacy", "orders", "updated"]

        decision = evaluate_governance_decision(base, candidate, context=TEST_CONTEXT)

        assert decision.decision == DecisionResult.BLOCK
        assert decision.policy.retired_violation is True
        assert any(
            r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
            for r in decision.reasons
        )

    def test_retired_via_custom_properties_effective_lifecycle_blocks(self) -> None:
        """Effective lifecycle from customProperties.lifecycleStatus=retired blocks candidate mutation."""
        base = _make_retired_contract()
        base.status = None
        base.customProperties = [
            CustomProperty(property="lifecycleStatus", value="retired")
        ]

        candidate = base.model_copy(deep=True)
        candidate.description = Description(usage="Mutated candidate description")

        decision = evaluate_governance_decision(base, candidate, context=TEST_CONTEXT)

        assert decision.decision == DecisionResult.BLOCK
        assert decision.policy.retired_violation is True
        assert any(
            r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
            for r in decision.reasons
        )

    def test_retired_schema_change_blocks(self) -> None:
        """Adding a new schema object to a retired contract produces BLOCK."""
        base = _make_retired_contract()
        candidate = _make_retired_contract()
        assert candidate.schema_ is not None
        candidate.schema_.append(
            SchemaObject(
                name="order_items",
                properties=[SchemaProperty(name="item_id", logicalType="string")],
            )
        )

        decision = evaluate_governance_decision(base, candidate, context=TEST_CONTEXT)

        assert decision.decision == DecisionResult.BLOCK
        assert decision.policy.retired_violation is True
        assert any(
            r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
            for r in decision.reasons
        )

    def test_retired_property_change_blocks(self) -> None:
        """Adding, removing, or modifying properties on a retired contract produces BLOCK."""
        base = _make_retired_contract()
        candidate = _make_retired_contract()
        assert candidate.schema_ is not None
        assert candidate.schema_[0].properties is not None
        candidate.schema_[0].properties.append(
            SchemaProperty(name="customer_id", logicalType="string", required=False)
        )

        decision = evaluate_governance_decision(base, candidate, context=TEST_CONTEXT)

        assert decision.decision == DecisionResult.BLOCK
        assert decision.policy.retired_violation is True
        assert any(
            r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
            for r in decision.reasons
        )

    def test_retired_quality_rule_change_blocks(self) -> None:
        """Adding or modifying quality rules on a retired contract produces BLOCK."""
        base = _make_retired_contract()
        candidate = _make_retired_contract()
        assert candidate.schema_ is not None
        candidate.schema_[0].quality = [
            DataQuality.model_validate(
                {
                    "name": "row_count_check",
                    "type": "rowCount",
                    "description": "Check row count",
                }
            )
        ]

        decision = evaluate_governance_decision(base, candidate, context=TEST_CONTEXT)

        assert decision.decision == DecisionResult.BLOCK
        assert decision.policy.retired_violation is True
        assert any(
            r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
            for r in decision.reasons
        )

    def test_retired_relationship_change_blocks(self) -> None:
        """Adding or modifying relationships on a retired contract produces BLOCK."""
        base = _make_retired_contract()
        candidate = _make_retired_contract()
        assert candidate.schema_ is not None
        candidate.schema_[0].relationships = [
            Relationship.model_validate(
                {
                    "type": "foreignKey",
                    "to": "customers.customer_id",
                }
            )
        ]

        decision = evaluate_governance_decision(base, candidate, context=TEST_CONTEXT)

        assert decision.decision == DecisionResult.BLOCK
        assert decision.policy.retired_violation is True
        assert any(
            r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
            for r in decision.reasons
        )

    def test_retired_custom_properties_change_blocks(self) -> None:
        """Adding or modifying customProperties on a retired contract produces BLOCK."""
        base = _make_retired_contract()
        candidate = _make_retired_contract()
        candidate.customProperties = [
            CustomProperty(property="costCenter", value="finance")
        ]

        decision = evaluate_governance_decision(base, candidate, context=TEST_CONTEXT)

        assert decision.decision == DecisionResult.BLOCK
        assert decision.policy.retired_violation is True
        assert any(
            r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
            for r in decision.reasons
        )

    def test_retired_reactivation_blocks(self) -> None:
        """Reactivating a retired contract to active, draft, or deprecated produces BLOCK."""
        base = _make_retired_contract()

        for target_status in ("active", "draft", "deprecated"):
            candidate = _make_retired_contract()
            candidate.status = target_status

            decision = evaluate_governance_decision(base, candidate, context=TEST_CONTEXT)

            assert decision.decision == DecisionResult.BLOCK
            assert decision.policy.retired_violation is True
            assert any(
                r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
                for r in decision.reasons
            )

    def test_retired_version_change_blocks(self) -> None:
        """Modifying version on a retired contract produces BLOCK with both reasons."""
        base = _make_retired_contract()
        candidate = _make_retired_contract()
        candidate.version = "2.0.0"

        decision = evaluate_governance_decision(base, candidate, context=TEST_CONTEXT)

        assert decision.decision == DecisionResult.BLOCK
        assert decision.policy.retired_violation is True
        assert decision.policy.version_violation is True
        reason_codes = {r.code for r in decision.reasons}
        assert GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED in reason_codes
        assert GovernanceReasonCode.CONTRACT_VERSION_MANUALLY_CHANGED in reason_codes

    def test_active_to_retired_transition_reviews_not_mutation(self) -> None:
        """Transitioning an active contract to retired produces REVIEW (not retired mutation)."""
        base = _make_active_contract()
        candidate = _make_retired_contract()

        decision = evaluate_governance_decision(base, candidate, context=TEST_CONTEXT)

        assert decision.decision == DecisionResult.REVIEW
        assert decision.policy.retired_violation is False
        assert any(
            r.code == GovernanceReasonCode.CONTRACT_RETIRED_TRANSITION
            for r in decision.reasons
        )
        assert not any(
            r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
            for r in decision.reasons
        )

    def test_draft_and_deprecated_to_retired_transition_reviews(self) -> None:
        """Transitioning draft or deprecated contract to retired produces REVIEW."""
        for start_status in ("draft", "deprecated"):
            base = _make_retired_contract()
            base.status = start_status
            candidate = _make_retired_contract()

            decision = evaluate_governance_decision(base, candidate, context=TEST_CONTEXT)

            assert decision.decision == DecisionResult.REVIEW
            assert decision.policy.retired_violation is False
            assert any(
                r.code == GovernanceReasonCode.CONTRACT_RETIRED_TRANSITION
                for r in decision.reasons
            )
            assert not any(
                r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
                for r in decision.reasons
            )

    def test_retired_invalid_mutated_candidate_blocks_cleanly(self) -> None:
        """Invalid candidate with mutated retired base blocks with no exception leakage."""
        base = _make_retired_contract()
        # Candidate with invalid status string and mutated field
        candidate = _make_retired_contract()
        candidate.status = "invalid_status_value"
        candidate.description = Description(usage="Mutated invalid contract")

        decision = evaluate_governance_decision(base, candidate, context=TEST_CONTEXT)

        assert decision.decision == DecisionResult.BLOCK
        assert decision.validation.valid is False
        assert decision.policy.retired_violation is True
        reason_codes = {r.code for r in decision.reasons}
        assert GovernanceReasonCode.VALIDATION_FAILED in reason_codes
        assert GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED in reason_codes


# ==============================================================================
# 2. Mutation Boundary Matrix
# ==============================================================================


class TestRetiredMutationBoundaries:
    """Verify that all mutation-capable entrypoints block retired mutations without side effects."""

    def test_merge_command_blocks_retired_mutation(self, tmp_path: Path) -> None:
        """run_merge blocks retired base mutation and writes no output file."""
        base_retired = _make_retired_contract()
        source_technical = OpenDataContractStandard(
            apiVersion="v3.1.0",
            kind="DataContract",
            id="urn:datacontract:orders",
            name="orders",
            version="1.0.0",
            status="active",
            schema=[
                SchemaObject(
                    name="orders",
                    properties=[
                        SchemaProperty(
                            name="new_col",
                            logicalType="string",
                            physicalType="VARCHAR(50)",
                        )
                    ],
                )
            ],
        )

        base_path = dump_yaml(contract_to_dict(base_retired), tmp_path / "base.yaml")
        src_path = dump_yaml(contract_to_dict(source_technical), tmp_path / "src.yaml")
        out_path = tmp_path / "merged_out.yaml"

        args = argparse.Namespace(
            base=str(src_path),
            business=str(base_path),
            output=str(out_path),
            runtime_context="auto",
            effective_date="2026-08-14",
        )

        with pytest.raises(GovernanceBlockedError) as exc_info:
            run_merge(args)

        assert exc_info.value.operation == GovernanceOperation.PROPOSE
        assert exc_info.value.decision is not None
        assert any(
            r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
            for r in exc_info.value.decision.reasons
        )
        assert not out_path.exists()

    def test_import_command_existing_blocks_retired_mutation(self, tmp_path: Path) -> None:
        """run_import with --existing blocks retired contract mutation and writes no output."""
        base_retired = _make_retired_contract()
        base_path = dump_yaml(contract_to_dict(base_retired), tmp_path / "existing.yaml")
        out_path = tmp_path / "import_out.yaml"

        imported_dummy = OpenDataContractStandard(
            apiVersion="v3.1.0",
            kind="DataContract",
            id="imported_id",
            name="orders",
            version="1.0.0",
            status="draft",
            schema=[
                SchemaObject(
                    name="orders",
                    properties=[SchemaProperty(name="extra", logicalType="string")],
                )
            ],
        )

        args = argparse.Namespace(
            format="sql",
            source="orders_ddl.sql",
            existing=str(base_path),
            output=str(out_path),
            runtime_context="auto",
            effective_date="2026-08-14",
        )

        with patch("datacontract.data_contract.DataContract.import_from_source", return_value=imported_dummy):
            with pytest.raises(GovernanceBlockedError) as exc_info:
                run_import(args)

        assert exc_info.value.operation == GovernanceOperation.PROPOSE
        assert exc_info.value.decision is not None
        assert any(
            r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
            for r in exc_info.value.decision.reasons
        )
        assert not out_path.exists()

    def test_lifecycle_promote_blocks_retired_contract(self, tmp_path: Path) -> None:
        """run_lifecycle_promote on retired contract blocks and preserves original file."""
        base_retired = _make_retired_contract()
        contract_path = dump_yaml(contract_to_dict(base_retired), tmp_path / "contract.yaml")
        original_content = contract_path.read_text(encoding="utf-8")

        args = argparse.Namespace(
            contract=str(contract_path),
            schema=None,
            property=None,
            output=None,
            runtime_context="auto",
            effective_date="2026-08-14",
        )

        with pytest.raises(GovernanceBlockedError) as exc_info:
            run_lifecycle_promote(args)

        assert exc_info.value.operation == GovernanceOperation.APPLY
        assert exc_info.value.decision is not None
        assert any(
            r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
            for r in exc_info.value.decision.reasons
        )
        assert contract_path.read_text(encoding="utf-8") == original_content

    def test_lifecycle_deprecate_property_blocks_retired_contract(self, tmp_path: Path) -> None:
        """run_lifecycle_deprecate on property of retired contract blocks without mutating file."""
        base_retired = _make_retired_contract()
        contract_path = dump_yaml(contract_to_dict(base_retired), tmp_path / "contract.yaml")
        original_content = contract_path.read_text(encoding="utf-8")

        args = argparse.Namespace(
            contract=str(contract_path),
            schema="orders",
            property="amount",
            output=None,
            runtime_context="auto",
            effective_date="2026-08-14",
        )

        with pytest.raises(GovernanceBlockedError) as exc_info:
            run_lifecycle_deprecate(args)

        assert exc_info.value.operation == GovernanceOperation.APPLY
        assert exc_info.value.decision is not None
        assert any(
            r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
            for r in exc_info.value.decision.reasons
        )
        assert contract_path.read_text(encoding="utf-8") == original_content

    def test_release_prepare_blocks_retired_contract(self, tmp_path: Path) -> None:
        """run_release_prepare blocks retired contract modification and writes no output."""
        base_retired = _make_retired_contract()
        candidate = _make_retired_contract()
        candidate.description = Description(usage="Candidate with metadata updates")

        base_path = dump_yaml(contract_to_dict(base_retired), tmp_path / "base.yaml")
        cand_path = dump_yaml(contract_to_dict(candidate), tmp_path / "cand.yaml")
        out_path = tmp_path / "promoted.yaml"

        args = argparse.Namespace(
            base=str(base_path),
            candidate=str(cand_path),
            output=str(out_path),
            release_tag="orders/v1.1.0",
            runtime_context="auto",
            effective_date="2026-08-14",
        )

        with pytest.raises(GovernanceBlockedError) as exc_info:
            run_release_prepare(args)

        assert exc_info.value.operation == GovernanceOperation.PROPOSE
        assert exc_info.value.decision is not None
        assert any(
            r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
            for r in exc_info.value.decision.reasons
        )
        assert not out_path.exists()

    def test_release_create_pr_blocks_retired_contract(self, tmp_path: Path) -> None:
        """create_release_pull_request blocks retired contract mutation before Git/file mutations."""
        base_retired = _make_retired_contract()
        candidate = _make_retired_contract()
        candidate.description = Description(usage="Modified retired contract")

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        contract_file = repo_dir / "contracts" / "orders.yaml"
        contract_file.parent.mkdir(parents=True)
        dump_yaml(contract_to_dict(base_retired), contract_file)

        mock_config = MagicMock()

        with pytest.raises(GovernanceBlockedError) as exc_info:
            create_release_pull_request(
                config=mock_config,
                repo_path=str(repo_dir),
                contract_repo_path="contracts/orders.yaml",
                base_contract=base_retired,
                candidate_contract=candidate,
                release_tag="orders/v1.1.0",
                source_branch="release/orders-v1.1.0",
                target_branch="main",
                context=TEST_CONTEXT,
            )

        assert exc_info.value.operation == GovernanceOperation.PROPOSE
        assert exc_info.value.decision is not None
        assert any(
            r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
            for r in exc_info.value.decision.reasons
        )
        # Verify no git push or PR creation was called
        mock_config.assert_not_called()

    def test_pipeline_ci_run_blocks_retired_contract(self, tmp_path: Path) -> None:
        """ContractPipeline.run on retired base writes audit manifest and blocks before writing artifacts."""
        base_retired = _make_retired_contract()
        imported_candidate = OpenDataContractStandard(
            apiVersion="v3.1.0",
            kind="DataContract",
            id="urn:datacontract:orders",
            name="orders",
            version="1.0.0",
            status="active",
            schema=[
                SchemaObject(
                    name="orders",
                    properties=[SchemaProperty(name="new_field", logicalType="string")],
                )
            ],
        )

        base_path = dump_yaml(contract_to_dict(base_retired), tmp_path / "governed_base.yaml")
        merged_out = tmp_path / "merged.yaml"
        suite_out = tmp_path / "suite.json"
        manifest_out = tmp_path / "ci_manifest.json"

        pipeline = ContractPipeline()

        with patch.object(ContractPipeline, "import_schema", return_value=imported_candidate):
            with pytest.raises(GovernanceBlockedError) as exc_info:
                pipeline.run(
                    source_type="sql",
                    source="dummy.sql",
                    business_contract_path=str(base_path),
                    merged_contract_output_path=str(merged_out),
                    ge_suite_output_path=str(suite_out),
                    ci_manifest_output_path=str(manifest_out),
                    change_context=TEST_CONTEXT,
                )

        assert exc_info.value.operation == GovernanceOperation.CI
        assert exc_info.value.decision is not None
        assert any(
            r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
            for r in exc_info.value.decision.reasons
        )

        # Manifest must be written for CI audit, but merged contract and GE suite must NOT be written
        assert manifest_out.exists()
        manifest_data = json.loads(manifest_out.read_text(encoding="utf-8"))
        assert manifest_data["governanceDecision"]["decision"] == "BLOCK"
        assert not merged_out.exists()
        assert not suite_out.exists()

    def test_batch_release_manifest_skips_retired_contract(self, tmp_path: Path) -> None:
        """build_batch_release_manifest skips retired mutated contracts via PROPOSE gate."""
        base_root = tmp_path / "base"
        cand_root = tmp_path / "cand"
        base_root.mkdir()
        cand_root.mkdir()

        base_retired = _make_retired_contract()
        cand_retired_mutated = _make_retired_contract()
        cand_retired_mutated.description = Description(usage="Mutated retired description")

        dump_yaml(contract_to_dict(base_retired), base_root / "orders.yaml")
        dump_yaml(contract_to_dict(cand_retired_mutated), cand_root / "orders.yaml")

        build = build_batch_release_manifest(
            base_root=base_root,
            candidate_root=cand_root,
            context=TEST_CONTEXT,
        )

        # The retired mutated contract must be skipped, not included in tasks
        assert len(build.tasks) == 0
        assert len(build.skipped) == 1
        assert build.skipped[0].contract_repo_path == "orders.yaml"


# ==============================================================================
# 3. Read-Only Matrix
# ==============================================================================


class TestRetiredReadOnlyMatrix:
    """Verify that read-only, inspection, and export operations remain fully allowed."""

    def test_load_retired_contract_allowed(self, tmp_path: Path) -> None:
        """ContractLoader successfully loads a retired contract."""
        base_retired = _make_retired_contract()
        path = dump_yaml(contract_to_dict(base_retired), tmp_path / "retired.yaml")

        loaded = ContractLoader().load(str(path))

        assert loaded.id == base_retired.id
        assert loaded.status == "retired"

    def test_analyze_unchanged_retired_allowed(self) -> None:
        """GovernanceService.evaluate on unchanged retired contract produces ALLOW and gate passes."""
        base_retired = _make_retired_contract()
        candidate = _make_retired_contract()

        decision = GovernanceService().evaluate(
            base_retired,
            candidate,
            effective_date=date(2026, 8, 14),
        )

        gate_res = evaluate_governance_gate(decision, GovernanceOperation.ANALYZE)
        assert gate_res.allowed is True
        assert gate_res.reason == "allowed"
        assert decision.decision == DecisionResult.ALLOW

    def test_analyze_mutated_retired_returns_block_decision_without_error(self, tmp_path: Path) -> None:
        """semapact release classify on mutated retired contract returns BLOCK decision without raising."""
        base_retired = _make_retired_contract()
        candidate = _make_retired_contract()
        candidate.description = Description(usage="Mutated retired contract")

        base_path = dump_yaml(contract_to_dict(base_retired), tmp_path / "base.yaml")
        cand_path = dump_yaml(contract_to_dict(candidate), tmp_path / "cand.yaml")

        args = argparse.Namespace(
            base=str(base_path),
            candidate=str(cand_path),
            runtime_context="auto",
            effective_date="2026-08-14",
        )

        result = run_release_classify(args)

        assert result["hasChanges"] is True
        assert result["governanceDecision"]["decision"] == "BLOCK"
        reason_codes = {r["code"] for r in result["governanceDecision"]["reasons"]}
        assert GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED.value in reason_codes

    def test_export_retired_contract_allowed(self, tmp_path: Path) -> None:
        """run_export succeeds for retired contracts without errors."""
        base_retired = _make_retired_contract()
        contract_path = dump_yaml(contract_to_dict(base_retired), tmp_path / "retired.yaml")
        out_sql = tmp_path / "export.sql"

        args = argparse.Namespace(
            location=str(contract_path),
            format="sql",
            output=str(out_sql),
            schema_name="all",
            server=None,
            sql_server_type="snowflake",
            export_args=None,
        )

        # Mock datacontract export
        with patch("datacontract.data_contract.DataContract.export", return_value="CREATE TABLE tbl_orders;"):
            res = run_export(args)

        assert "Exported" in res
        assert out_sql.exists()
        assert out_sql.read_text(encoding="utf-8") == "CREATE TABLE tbl_orders;"
