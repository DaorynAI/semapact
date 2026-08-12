"""Integration tests verifying centralized fail-closed governance behavior across all execution paths."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock
import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.core.lifecycle_cli import apply_lifecycle
from semapact.devops.ci_cd import evaluate_ci_gate
from semapact.devops.release_workflow import (
    build_batch_release_manifest,
)
from semapact.exceptions import GovernanceBlockedError, GovernanceReviewRequiredError, MergeConflictError
from semapact.governance import (
    evaluate_governance_decision,
)
from semapact.interfaces.commands.merge_cmd import run_merge
from semapact.interfaces.commands.plan_cmd import run_plan
from semapact.interfaces.commands.release_cmd import run_release_classify, run_release_prepare
from semapact.orchestrator.pipeline import ContractPipeline
from semapact.utils.schema_utils import contract_to_dict
from semapact.utils.yaml_utils import dump_yaml


def _make_contract(
    contract_id: str = "my-contract",
    version: str = "1.0.0",
    status: str = "active",
    properties: list[SchemaProperty] | None = None,
) -> OpenDataContractStandard:
    if properties is None:
        properties = [
            SchemaProperty(
                name="id",
                logicalType="string",
                physicalType="varchar(255)",
                required=True,
            ),
            SchemaProperty(
                name="amount",
                logicalType="number",
                physicalType="decimal(10,2)",
                required=False,
            ),
        ]
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id=contract_id,
        name=contract_id,
        version=version,
        status=status,
        schema=[
            SchemaObject(
                name="orders",
                physicalName="orders",
                properties=properties,
            )
        ],
    )


def test_injected_block_decision_prevents_side_effects(tmp_path, monkeypatch):
    """Verify that a BLOCK decision (e.g. version mismatch policy violation) stops side-effects across all mutating entry points."""
    base = _make_contract(contract_id="contract-a", version="1.0.0", status="active")
    candidate = _make_contract(contract_id="contract-a", version="1.0.0", status="active")
    # Invalid data quality check causes ContractValidator failure -> BLOCK decision
    from open_data_contract_standard.model import DataQuality
    candidate.schema_[0].properties[0].quality = [DataQuality(type="invalid_quality_type_xyz")]

    base_path = dump_yaml(contract_to_dict(base), tmp_path / "base.yaml")
    candidate_path = dump_yaml(contract_to_dict(candidate), tmp_path / "candidate.yaml")

    # 1. merge command: raises GovernanceBlockedError and does NOT write output
    merge_args = SimpleNamespace(
        base=str(candidate_path),
        business=str(base_path),
        output=str(tmp_path / "merge_out.yaml"),
        runtime_context="auto",
        fail_on_conflict=False,
    )
    with pytest.raises(GovernanceBlockedError):
        run_merge(merge_args)
    assert not (tmp_path / "merge_out.yaml").exists()

    # 2. lifecycle promote: version mismatch on active contract produces BLOCK decision -> raises GovernanceBlockedError
    lifecycle_args = SimpleNamespace(
        contract=str(base_path),
        output=str(tmp_path / "lifecycle_out.yaml"),
        runtime_context="auto",
        schema=None,
        property=None,
    )
    monkeypatch.setattr("semapact.core.lifecycle_cli._apply_contract", lambda c, s: setattr(c, "version", "2.0.0"))
    with pytest.raises(GovernanceBlockedError):
        apply_lifecycle(lifecycle_args, is_promote=True)
    assert not (tmp_path / "lifecycle_out.yaml").exists()

    # 3. release prepare: raises GovernanceBlockedError and does NOT write candidate
    release_prep_args = SimpleNamespace(
        base=str(base_path),
        candidate=str(candidate_path),
        release_tag="v2.0.0",
        output=str(tmp_path / "release_out.yaml"),
        runtime_context="auto",
    )
    with pytest.raises(GovernanceBlockedError):
        run_release_prepare(release_prep_args)
    assert not (tmp_path / "release_out.yaml").exists()

    # 4. pipeline run: writes decision manifest FIRST, then raises GovernanceBlockedError without generating GE/merged contract
    pipeline = ContractPipeline()
    monkeypatch.setattr(ContractPipeline, "import_schema", lambda *a, **k: candidate)
    with pytest.raises(GovernanceBlockedError):
        pipeline.run(
            source_type="sql",
            source=str(candidate_path),
            business_contract_path=str(base_path),
            merged_contract_output_path=str(tmp_path / "pipe_merged.yaml"),
            ge_suite_output_path=str(tmp_path / "ge_suite.json"),
            ci_manifest_output_path=str(tmp_path / "ci_manifest.json"),
        )
    assert (tmp_path / "ci_manifest.json").exists()  # Decision-only audit manifest
    assert not (tmp_path / "pipe_merged.yaml").exists()
    assert not (tmp_path / "ge_suite.json").exists()


def test_retired_contract_mutation_governance_block(tmp_path):
    """Mutating a retired contract triggers BLOCK or MergeConflictError and stops merge operation."""
    base_retired = _make_contract(status="retired")
    candidate = _make_contract(status="retired")
    candidate.schema_[0].properties.append(
        SchemaProperty(name="note", logicalType="string", physicalType="varchar(50)", required=False)
    )

    base_path = dump_yaml(contract_to_dict(base_retired), tmp_path / "retired_base.yaml")
    cand_path = dump_yaml(contract_to_dict(candidate), tmp_path / "retired_cand.yaml")

    merge_args = SimpleNamespace(
        base=str(cand_path),
        business=str(base_path),
        output=str(tmp_path / "retired_out.yaml"),
        runtime_context="auto",
        fail_on_conflict=False,
    )
    with pytest.raises((GovernanceBlockedError, MergeConflictError)):
        run_merge(merge_args)
    assert not (tmp_path / "retired_out.yaml").exists()


def test_batch_release_manifest_skips_blocked_contracts(tmp_path):
    """Batch release manifest moves contracts with BLOCK decisions to skipped list."""
    base_dir = tmp_path / "base_root"
    cand_dir = tmp_path / "cand_root"
    base_dir.mkdir()
    cand_dir.mkdir()

    base_contract = _make_contract(contract_id="contract-1", version="1.0.0")
    cand_valid = _make_contract(contract_id="contract-1", version="1.0.0")
    cand_valid.schema_[0].properties.append(
        SchemaProperty(name="new_field", logicalType="string", physicalType="varchar(50)", required=False)
    )
    dump_yaml(contract_to_dict(base_contract), base_dir / "valid.yaml")
    dump_yaml(contract_to_dict(cand_valid), cand_dir / "valid.yaml")

    base_blocked = _make_contract(contract_id="contract-blocked", version="1.0.0")
    cand_blocked = _make_contract(contract_id="contract-blocked", version="2.0.0")  # Version Mismatch -> BLOCK
    dump_yaml(contract_to_dict(base_blocked), base_dir / "blocked.yaml")
    dump_yaml(contract_to_dict(cand_blocked), cand_dir / "blocked.yaml")

    build = build_batch_release_manifest(
        base_root=str(base_dir),
        candidate_root=str(cand_dir),
    )

    # Valid additive change produces a task
    task_paths = [t.contract_path for t in build.tasks]
    assert "valid.yaml" in task_paths
    assert "blocked.yaml" not in task_paths

    # Blocked contract is in skipped list
    skipped_paths = [s.contract_repo_path for s in build.skipped]
    assert "blocked.yaml" in skipped_paths


def test_breaking_change_review_behavior(tmp_path, capsys):
    """Verify REVIEW decisions allow ANALYZE and PROPOSE but stop APPLY and CI."""
    base = _make_contract(status="active")
    candidate = _make_contract(status="active")
    # Add a new column to candidate -> Additive Change REVIEW
    candidate.schema_[0].properties.append(
        SchemaProperty(name="created_by", logicalType="string", physicalType="varchar(50)", required=False)
    )

    base_path = dump_yaml(contract_to_dict(base), tmp_path / "base_active.yaml")
    cand_path = dump_yaml(contract_to_dict(candidate), tmp_path / "cand_active.yaml")

    # 1. ANALYZE (plan & release classify): Allowed cleanly
    plan_args = SimpleNamespace(
        base=str(base_path),
        source=str(cand_path),
        type="sql",
        tables=None,
        workspace_url=None,
        token=None,
    )
    with mock.patch("semapact.orchestrator.pipeline.ContractPipeline.import_schema", lambda *a, **k: candidate):
        run_plan(plan_args)
    captured = capsys.readouterr().out
    assert "REVIEW" in captured

    classify_args = SimpleNamespace(
        base=str(base_path),
        candidate=str(cand_path),
        runtime_context="auto",
    )
    class_res = run_release_classify(classify_args)
    assert class_res["requiredBump"] == "minor"
    assert class_res["governanceDecision"]["decision"] == "REVIEW"

    # 2. PROPOSE (release prepare): Allowed to produce candidate YAML for review
    prep_args = SimpleNamespace(
        base=str(base_path),
        candidate=str(cand_path),
        release_tag="v1.1.0",
        output=str(tmp_path / "review_candidate.yaml"),
        runtime_context="auto",
    )
    prep_res = run_release_prepare(prep_args)
    assert (tmp_path / "review_candidate.yaml").exists()
    assert prep_res["governanceDecision"]["decision"] == "REVIEW"

    # 3. APPLY (lifecycle deprecate property): Deprecating property in active contract -> REVIEW -> Raises GovernanceReviewRequiredError
    lifecycle_args = SimpleNamespace(
        contract=str(base_path),
        output=str(tmp_path / "review_lifecycle.yaml"),
        runtime_context="auto",
        schema="orders",
        property="amount",
    )
    with pytest.raises(GovernanceReviewRequiredError) as exc:
        apply_lifecycle(lifecycle_args, is_promote=False)
    assert "Governance decision REVIEW required" in str(exc.value)

    # 4. CI (evaluate_ci_gate & pipeline): Returns allowed=False / raises GovernanceReviewRequiredError
    decision = evaluate_governance_decision(base, candidate)
    ci_res = evaluate_ci_gate(decision)
    assert ci_res.allowed is False
    assert ci_res.reason == "review_required"


def test_pipeline_merge_conflict_fail_closed_on_retired_contract(tmp_path):
    """Verify that pipeline run on retired contract raises MergeConflictError fail-closed without writing any artifacts."""
    base_retired = _make_contract(status="retired")
    candidate = _make_contract(status="active")

    base_path = dump_yaml(contract_to_dict(base_retired), tmp_path / "retired_base.yaml")
    cand_path = dump_yaml(contract_to_dict(candidate), tmp_path / "cand.yaml")

    merged_out = tmp_path / "merged_out.yaml"
    ge_out = tmp_path / "ge_suite.json"
    ci_out = tmp_path / "ci_manifest.json"

    pipeline = ContractPipeline()
    with mock.patch("semapact.orchestrator.pipeline.ContractPipeline.import_schema", lambda *a, **k: candidate):
        with pytest.raises(MergeConflictError):
            pipeline.run(
                source_type="sql",
                source=str(cand_path),
                business_contract_path=str(base_path),
                merged_contract_output_path=str(merged_out),
                ge_suite_output_path=str(ge_out),
                ci_manifest_output_path=str(ci_out),
            )

    # Fail closed: No artifacts should be written when merge raises MergeConflictError
    assert not merged_out.exists()
    assert not ge_out.exists()
    assert not ci_out.exists()


def test_prepare_ci_cd_artifacts_enforces_ci_gate_directly(tmp_path):
    """Verify that calling prepare_ci_cd_artifacts directly with a BLOCK decision raises GovernanceBlockedError."""
    base = _make_contract(contract_id="contract-a", version="1.0.0", status="active")
    candidate = _make_contract(contract_id="contract-a", version="1.0.0", status="active")
    from open_data_contract_standard.model import DataQuality
    candidate.schema_[0].properties[0].quality = [DataQuality(type="invalid_quality_type_xyz")]

    decision = evaluate_governance_decision(base, candidate)
    assert decision.decision.value == "BLOCK"

    merged_out = tmp_path / "direct_merged.yaml"
    ge_out = tmp_path / "direct_ge.json"
    ci_out = tmp_path / "direct_ci.json"

    pipeline = ContractPipeline()
    with pytest.raises(GovernanceBlockedError):
        pipeline.prepare_ci_cd_artifacts(
            candidate,
            mock.MagicMock(conflicts=[]),
            decision,
            merged_contract_output_path=str(merged_out),
            ge_suite_output_path=str(ge_out),
            ci_manifest_output_path=str(ci_out),
        )

    assert not merged_out.exists()
    assert not ge_out.exists()


def test_ci_cd_adapter_preserves_allowed_reason():
    """Verify that evaluate_ci_gate returns 'allowed' reason when allowed is True."""
    base = _make_contract(status="active")
    candidate = _make_contract(status="active")
    decision = evaluate_governance_decision(base, candidate)

    ci_dec = evaluate_ci_gate(decision)
    assert ci_dec.allowed is True
    assert ci_dec.reason == "allowed"
