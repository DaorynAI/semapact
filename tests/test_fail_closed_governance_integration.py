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
from semapact.exceptions import GovernanceBlockedError, GovernanceReviewRequiredError
from semapact.governance import (
    GovernanceOperation,
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
    """Mutating a retired contract produces GovernanceDecision.BLOCK raised as GovernanceBlockedError with operation PROPOSE."""
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
    with pytest.raises(GovernanceBlockedError) as exc_info:
        run_merge(merge_args)
    assert exc_info.value.decision is not None
    assert exc_info.value.decision.decision.value == "BLOCK"
    assert exc_info.value.operation == GovernanceOperation.PROPOSE
    assert not (tmp_path / "retired_out.yaml").exists()


def test_conflict_with_fail_on_conflict_does_not_bypass_gate(tmp_path):
    """Verify run_merge with fail_on_conflict=True does not raise MergeConflictError directly, but enforces GovernanceOperation.PROPOSE gate."""
    base = _make_contract(status="active")
    candidate = _make_contract(status="active")
    # Physical type change creates a conflict and REVIEW decision
    candidate.schema_[0].properties[0].physicalType = "bigint"

    base_path = dump_yaml(contract_to_dict(base), tmp_path / "base.yaml")
    cand_path = dump_yaml(contract_to_dict(candidate), tmp_path / "cand.yaml")

    merge_args = SimpleNamespace(
        base=str(cand_path),
        business=str(base_path),
        output=str(tmp_path / "out.yaml"),
        runtime_context="auto",
        fail_on_conflict=True,
    )

    # Allowed for PROPOSE gate since REVIEW decision allows proposal creation
    out_path = run_merge(merge_args)
    assert out_path.exists()


def test_import_existing_block_prevents_plugin_and_file_write(tmp_path, monkeypatch):
    """Verify import --existing with a BLOCK decision prevents post-gate plugin hook execution and file writing."""
    base_retired = _make_contract(status="retired")
    candidate = _make_contract(status="active")

    base_path = dump_yaml(contract_to_dict(base_retired), tmp_path / "existing_retired.yaml")
    cand_path = dump_yaml(contract_to_dict(candidate), tmp_path / "source.yaml")
    out_path = tmp_path / "import_out.yaml"

    plugin_called = False

    def fake_hook(name, **kwargs):
        nonlocal plugin_called
        plugin_called = True
        return None

    monkeypatch.setattr("semapact.core.plugin_registry.PluginRegistry.execute_hook", fake_hook)

    import_args = SimpleNamespace(
        format="sql",
        source=str(cand_path),
        existing=str(base_path),
        output=str(out_path),
        runtime_context="auto",
    )

    with mock.patch("datacontract.data_contract.DataContract.import_from_source", lambda **k: candidate):
        from semapact.interfaces.commands.import_cmd import run_import
        with pytest.raises(GovernanceBlockedError) as exc_info:
            run_import(import_args)

    assert exc_info.value.operation == GovernanceOperation.PROPOSE
    assert not plugin_called, "Plugin hook must not execute when governance gate BLOCKS"
    assert not out_path.exists(), "Output file must not be written when governance gate BLOCKS"


def test_import_plugin_deepcopy_prevents_output_mutation(tmp_path, monkeypatch):
    """Verify post-gate plugin hook receiving deepcopy cannot mutate the dumped output contract."""
    base = _make_contract(contract_id="contract-1", status="active")
    candidate = _make_contract(contract_id="contract-1", status="active")

    base_path = dump_yaml(contract_to_dict(base), tmp_path / "existing.yaml")
    cand_path = dump_yaml(contract_to_dict(candidate), tmp_path / "source.yaml")
    out_path = tmp_path / "import_out.yaml"

    def mutating_hook(name, **kwargs):
        c = kwargs.get("contract")
        if c:
            c.id = "MUTATED_ID"
        return None

    monkeypatch.setattr("semapact.core.plugin_registry.PluginRegistry.execute_hook", mutating_hook)

    import_args = SimpleNamespace(
        format="sql",
        source=str(cand_path),
        existing=str(base_path),
        output=str(out_path),
        runtime_context="auto",
    )

    with mock.patch("datacontract.data_contract.DataContract.import_from_source", lambda **k: candidate):
        from semapact.interfaces.commands.import_cmd import run_import
        run_import(import_args)

    assert out_path.exists()
    from semapact.utils.yaml_utils import load_yaml
    written_data = load_yaml(out_path)
    assert written_data["id"] == "contract-1", "Written contract must not be mutated by plugin hook"


def test_release_create_pr_block_prevents_all_side_effects(tmp_path):
    """Verify create_release_pull_request with a BLOCK decision does not dump YAML, commit/push, or create PR."""
    base = _make_contract(contract_id="contract-a", version="1.0.0", status="active")
    candidate = _make_contract(contract_id="contract-a", version="1.0.0", status="active")
    from open_data_contract_standard.model import DataQuality
    candidate.schema_[0].properties[0].quality = [DataQuality(type="invalid_type")]

    from semapact.devops.pr_creator import GitHubConfig
    from semapact.devops.release_workflow import create_release_pull_request

    config = GitHubConfig(owner="org", repo="repo", token="fake")
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    contract_repo_path = "contracts/my_contract.yaml"

    with mock.patch("semapact.devops.pr_creator.PullRequestCreator.create_update_pr") as mock_pr:
        with pytest.raises(GovernanceBlockedError) as exc_info:
            create_release_pull_request(
                config=config,
                repo_path=str(repo_dir),
                contract_repo_path=contract_repo_path,
                base_contract=base,
                candidate_contract=candidate,
                release_tag="v1.0.1",
                source_branch="release/v1.0.1",
                target_branch="main",
            )

    assert exc_info.value.operation == GovernanceOperation.PROPOSE
    assert not (repo_dir / contract_repo_path).exists(), "Candidate YAML must not be dumped when governance gate BLOCKS"
    assert mock_pr.call_count == 0, "Pull request creator must not be called when governance gate BLOCKS"


def test_batch_release_manifest_evaluates_governance_once_per_task(tmp_path, monkeypatch):
    """Verify build_batch_release_manifest and create_release_pull_requests_from_manifest evaluate underlying policy exactly ONCE per task per phase without duplicate evaluations."""
    base_dir = tmp_path / "base_root"
    cand_dir = tmp_path / "cand_root"
    repo_dir = tmp_path / "repo"
    base_dir.mkdir()
    cand_dir.mkdir()
    repo_dir.mkdir()

    for i in range(2):
        base_c = _make_contract(contract_id=f"c{i}", version="1.0.0")
        cand_c = _make_contract(contract_id=f"c{i}", version="1.0.0")
        cand_c.schema_[0].properties.append(
            SchemaProperty(name=f"new_{i}", logicalType="string", physicalType="varchar(10)", required=False)
        )
        dump_yaml(contract_to_dict(base_c), base_dir / f"c{i}.yaml")
        dump_yaml(contract_to_dict(cand_c), cand_dir / f"c{i}.yaml")

    policy_eval_calls = 0
    from semapact.lifecycle.policy import evaluate_merge_policy
    orig_eval_policy = evaluate_merge_policy

    def counted_policy_eval(*args, **kwargs):
        nonlocal policy_eval_calls
        policy_eval_calls += 1
        return orig_eval_policy(*args, **kwargs)

    monkeypatch.setattr("semapact.governance.evaluator.evaluate_merge_policy", counted_policy_eval)

    # 1. Build manifest (2 tasks created, exactly 2 policy evaluations)
    build = build_batch_release_manifest(
        base_root=str(base_dir),
        candidate_root=str(cand_dir),
    )
    assert len(build.tasks) == 2
    assert policy_eval_calls == 2, f"Expected 2 policy evaluations during build, got {policy_eval_calls}"

    # 2. Run PR creation from manifest tasks (exactly 2 more policy evaluations: 1 per task in evaluate_governance_decision, 0 in apply_release_candidate)
    monkeypatch.setattr("semapact.devops.pr_creator.PullRequestCreator.create_update_pr", lambda *a, **k: {})
    from semapact.devops.pr_creator import GitHubConfig
    from semapact.devops.release_workflow import create_release_pull_requests_from_manifest

    config = GitHubConfig(owner="org", repo="repo", token="fake")
    create_release_pull_requests_from_manifest(
        config=config,
        repo_path=str(repo_dir),
        tasks=build.tasks,
    )

    assert policy_eval_calls == 4, f"Expected exactly 4 total policy evaluations across build+create (1 per task per phase), got {policy_eval_calls}"


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
    assert exc.value.operation == GovernanceOperation.APPLY
    assert "Governance decision REVIEW required" in str(exc.value)

    # 4. CI (evaluate_ci_gate & pipeline): Returns allowed=False / raises GovernanceReviewRequiredError
    decision = evaluate_governance_decision(base, candidate)
    ci_res = evaluate_ci_gate(decision)
    assert ci_res.allowed is False
    assert ci_res.reason == "review_required"


def test_pipeline_merge_conflict_fail_closed_on_retired_contract(tmp_path):
    """Verify that pipeline run on retired contract raises GovernanceBlockedError and writes audit manifest but no other artifacts."""
    base_retired = _make_contract(status="retired")
    candidate = _make_contract(status="active")

    base_path = dump_yaml(contract_to_dict(base_retired), tmp_path / "retired_base.yaml")
    cand_path = dump_yaml(contract_to_dict(candidate), tmp_path / "cand.yaml")

    merged_out = tmp_path / "merged_out.yaml"
    ge_out = tmp_path / "ge_suite.json"
    ci_out = tmp_path / "ci_manifest.json"

    pipeline = ContractPipeline()
    with mock.patch("semapact.orchestrator.pipeline.ContractPipeline.import_schema", lambda *a, **k: candidate):
        with pytest.raises(GovernanceBlockedError) as exc_info:
            pipeline.run(
                source_type="sql",
                source=str(cand_path),
                business_contract_path=str(base_path),
                merged_contract_output_path=str(merged_out),
                ge_suite_output_path=str(ge_out),
                ci_manifest_output_path=str(ci_out),
            )

    # Decision must be BLOCK due to retired-contract mutation
    assert exc_info.value.decision is not None
    assert exc_info.value.decision.decision.value == "BLOCK"
    assert exc_info.value.operation == GovernanceOperation.CI
    # Fail closed: audit manifest written; merged contract and GE suite must NOT be written
    assert ci_out.exists(), "Audit manifest must be written even on BLOCK"
    assert not merged_out.exists()
    assert not ge_out.exists()


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

    from semapact.lifecycle.merge_engine import MergeResult
    real_merge_result = MergeResult(contract=candidate, conflicts=[])

    pipeline = ContractPipeline()
    with pytest.raises(GovernanceBlockedError) as exc_info:
        pipeline.prepare_ci_cd_artifacts(
            candidate,
            real_merge_result,
            decision,
            merged_contract_output_path=str(merged_out),
            ge_suite_output_path=str(ge_out),
            ci_manifest_output_path=str(ci_out),
        )

    assert exc_info.value.operation == GovernanceOperation.CI
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


def test_release_prepare_includes_breaking_changes(tmp_path):
    """Verify run_release_prepare returns breaking changes when breaking policy violations exist."""
    base = _make_contract(status="active")
    candidate = _make_contract(status="active")
    # Removing a property from active schema creates a breaking policy change
    candidate.schema_[0].properties = []

    base_path = dump_yaml(contract_to_dict(base), tmp_path / "base.yaml")
    cand_path = dump_yaml(contract_to_dict(candidate), tmp_path / "cand.yaml")

    prep_args = SimpleNamespace(
        base=str(base_path),
        candidate=str(cand_path),
        release_tag="v2.0.0",
        output=str(tmp_path / "prep_out.yaml"),
        runtime_context="auto",
    )

    res = run_release_prepare(prep_args)
    assert len(res["breakingChanges"]) > 0
    assert any("removed" in str(bc.get("message", "")).lower() or "breaking" in str(bc.get("message", "")).lower() for bc in res["breakingChanges"])


def test_classify_repo_sets_blocked_status(tmp_path):
    """Verify classify_contracts_in_repo sets status='blocked' when a contract generates a BLOCK governance decision."""
    base_dir = tmp_path / "base_root"
    cand_dir = tmp_path / "cand_root"
    base_dir.mkdir()
    cand_dir.mkdir()

    base_blocked = _make_contract(contract_id="contract-blocked", version="1.0.0")
    cand_blocked = _make_contract(contract_id="contract-blocked", version="2.0.0")  # Version mismatch -> BLOCK
    dump_yaml(contract_to_dict(base_blocked), base_dir / "blocked.yaml")
    dump_yaml(contract_to_dict(cand_blocked), cand_dir / "blocked.yaml")

    from semapact.devops.release_workflow import classify_contracts_in_repo
    changes = classify_contracts_in_repo(base_root=str(base_dir), candidate_root=str(cand_dir))
    blocked_change = next(c for c in changes if c.contract_repo_path == "blocked.yaml")
    assert blocked_change.status == "blocked"
    assert blocked_change.governance_decision is not None
    assert blocked_change.governance_decision.decision.value == "BLOCK"
