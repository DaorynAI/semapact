from __future__ import annotations

from datetime import date
import json

from semapact.core.release import prepare_release_candidate
from semapact.devops.pr_creator import AzureDevOpsConfig
from semapact.devops.release_workflow import (
    build_batch_release_manifest,
    BatchReleaseTask,
    build_release_pr_plan,
    classify_contracts_in_repo,
    create_release_pull_request,
    create_release_pull_requests_from_manifest,
)
from semapact.governance import ChangeContext
from semapact.interfaces import cli
from semapact.utils.yaml_utils import dump_yaml, load_yaml


TEST_CONTEXT = ChangeContext(effective_date=date(2026, 1, 1))


def test_build_release_pr_plan_uses_per_contract_defaults(sample_odcs_model):
    base = sample_odcs_model.model_copy(deep=True)
    candidate = sample_odcs_model.model_copy(deep=True)
    assert candidate.schema_ is not None
    assert candidate.schema_[0].properties is not None
    candidate.schema_[0].properties.append(
        candidate.schema_[0]
        .properties[0]
        .model_copy(update={"name": "new_optional_column", "id": "new_optional_column"})
    )

    promotion = prepare_release_candidate(base, candidate, "orders/v1.2.0")
    plan = build_release_pr_plan(
        promotion=promotion,
        contract_repo_path="contracts/orders.yaml",
        source_branch="release/orders-v1.1.1",
        target_branch="release",
    )

    assert plan.contract_id == str(base.id)
    assert plan.target_version == "1.2.0"
    assert plan.commit_message == f"release({base.id}): prepare 1.2.0"
    assert "current version" in plan.description


def test_create_release_pull_request_writes_contract_and_calls_pr_creator(
    sample_odcs_model, tmp_path, monkeypatch
):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    base = sample_odcs_model.model_copy(deep=True)
    candidate = sample_odcs_model.model_copy(deep=True)
    assert candidate.schema_ is not None
    assert candidate.schema_[0].properties is not None
    candidate.schema_[0].properties.append(
        candidate.schema_[0]
        .properties[0]
        .model_copy(update={"name": "new_optional_column", "id": "new_optional_column"})
    )

    captured: dict[str, object] = {}

    def fake_create_update_pr(self, **kwargs):  # noqa: ANN001
        captured["kwargs"] = kwargs
        return {"pullRequestId": 42}

    monkeypatch.setattr(
        "semapact.devops.release_workflow.PullRequestCreator.create_update_pr",
        fake_create_update_pr,
    )

    payload = create_release_pull_request(
        config=AzureDevOpsConfig(
            organization="org",
            project="proj",
            repository_id="repo",
            pat_token="token",
        ),
        repo_path=str(repo_path),
        contract_repo_path="contracts/orders.yaml",
        base_contract=base,
        candidate_contract=candidate,
        release_tag="orders/v1.2.0",
        source_branch="release/orders-v1.2.0",
        target_branch="release",
        context=TEST_CONTEXT,
        push=True,
    )

    written = load_yaml(repo_path / "contracts/orders.yaml")
    assert payload["pullRequest"]["pullRequestId"] == 42
    assert payload["promotion"]["targetVersion"] == "1.2.0"
    assert written["version"] == "1.2.0"
    assert written["id"] == str(base.id)
    assert captured["kwargs"]["paths"] == ["contracts/orders.yaml"]  # type: ignore[index]
    assert captured["kwargs"]["push"] is True  # type: ignore[index]


def test_cli_release_create_pr_outputs_plan_and_pr_payload(
    sample_odcs_model, tmp_path, capsys, monkeypatch
):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    base = sample_odcs_model.model_copy(deep=True)
    candidate = sample_odcs_model.model_copy(deep=True)
    assert candidate.schema_ is not None
    assert candidate.schema_[0].properties is not None
    candidate.schema_[0].properties.append(
        candidate.schema_[0]
        .properties[0]
        .model_copy(update={"name": "new_optional_column", "id": "new_optional_column"})
    )

    base_path = dump_yaml(base, tmp_path / "base.yaml")
    candidate_path = dump_yaml(candidate, tmp_path / "candidate.yaml")

    monkeypatch.setattr(
        "semapact.devops.release_workflow.create_release_pull_request",
        lambda **kwargs: {
            "promotion": {"contractId": str(base.id), "targetVersion": "1.2.0"},
            "pullRequest": {"pullRequestId": 77},
        },
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "semapact",
            "release",
            "create-pr",
            "--base",
            str(base_path),
            "--candidate",
            str(candidate_path),
            "--release-tag",
            "orders/v1.2.0",
            "--repo-path",
            str(repo_path),
            "--contract-path",
            "contracts/orders.yaml",
            "--source-branch",
            "release/orders-v1.2.0",
            "--target-branch",
            "release",
            "--effective-date",
            "2026-01-01",
            "--organization",
            "org",
            "--project",
            "proj",
            "--repository-id",
            "repo",
            "--pat-token",
            "token",
        ],
    )

    exit_code = cli.main()
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["pullRequest"]["pullRequestId"] == 77
    assert payload["promotion"]["targetVersion"] == "1.2.0"


def test_classify_contracts_in_repo_reports_changed_added_removed_and_unchanged(
    sample_odcs_model, tmp_path
):
    base_root = tmp_path / "base"
    candidate_root = tmp_path / "candidate"

    unchanged = sample_odcs_model.model_copy(deep=True)
    changed = sample_odcs_model.model_copy(deep=True)
    assert changed.description is not None
    changed.description.usage = "Updated descriptive text only"
    added = sample_odcs_model.model_copy(deep=True)
    added.id = "new-contract"
    added.version = "1.0.0"

    dump_yaml(unchanged, base_root / "unchanged.yaml")
    dump_yaml(unchanged, candidate_root / "unchanged.yaml")
    dump_yaml(sample_odcs_model, base_root / "changed.yaml")
    dump_yaml(changed, candidate_root / "changed.yaml")
    dump_yaml(sample_odcs_model, base_root / "removed.yaml")
    dump_yaml(added, candidate_root / "added.yaml")

    results = classify_contracts_in_repo(
        base_root=base_root,
        candidate_root=candidate_root,
        context=TEST_CONTEXT,
    )
    by_path = {item.contract_repo_path: item for item in results}

    assert by_path["unchanged.yaml"].status == "unchanged"
    assert by_path["changed.yaml"].status == "changed"
    assert by_path["changed.yaml"].required_bump == "none"
    assert by_path["changed.yaml"].suggested_release_version is None
    assert by_path["added.yaml"].status == "added"
    assert by_path["removed.yaml"].status == "removed"


def test_create_release_pull_requests_from_manifest_runs_each_contract(
    sample_odcs_model, tmp_path, monkeypatch
):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    base_a = sample_odcs_model.model_copy(deep=True)
    candidate_a = sample_odcs_model.model_copy(deep=True)
    assert candidate_a.schema_ is not None
    assert candidate_a.schema_[0].properties is not None
    candidate_a.schema_[0].properties.append(
        candidate_a.schema_[0]
        .properties[0]
        .model_copy(update={"name": "new_optional_column", "id": "new_optional_column"})
    )

    base_b = sample_odcs_model.model_copy(deep=True)
    base_b.id = "payments"
    candidate_b = base_b.model_copy(deep=True)
    assert candidate_b.schema_ is not None
    assert candidate_b.schema_[0].properties is not None
    candidate_b.schema_[0].properties.append(
        candidate_b.schema_[0]
        .properties[0]
        .model_copy(update={"name": "new_optional_column", "id": "new_optional_column"})
    )

    base_a_path = dump_yaml(base_a, tmp_path / "base-a.yaml")
    candidate_a_path = dump_yaml(candidate_a, tmp_path / "candidate-a.yaml")
    base_b_path = dump_yaml(base_b, tmp_path / "base-b.yaml")
    candidate_b_path = dump_yaml(candidate_b, tmp_path / "candidate-b.yaml")

    calls: list[str] = []

    def fake_create_update_pr(self, **kwargs):  # noqa: ANN001
        calls.append(kwargs["paths"][0])
        return {"pullRequestId": len(calls)}

    monkeypatch.setattr(
        "semapact.devops.release_workflow.PullRequestCreator.create_update_pr",
        fake_create_update_pr,
    )

    results = create_release_pull_requests_from_manifest(
        config=AzureDevOpsConfig(
            organization="org",
            project="proj",
            repository_id="repo",
            pat_token="token",
        ),
        repo_path=str(repo_path),
        tasks=[
            BatchReleaseTask(
                base=str(base_a_path),
                candidate=str(candidate_a_path),
                contract_path="contracts/orders.yaml",
                release_tag="orders/v1.2.0",
                source_branch="release/orders-v1.2.0",
                target_branch="release",
                effective_date="2026-01-01",
            ),
            BatchReleaseTask(
                base=str(base_b_path),
                candidate=str(candidate_b_path),
                contract_path="contracts/payments.yaml",
                release_tag="payments/v1.2.0",
                source_branch="release/payments-v1.2.0",
                target_branch="release",
                effective_date="2026-01-01",
            ),
        ],
        push=False,
    )

    assert len(results) == 2
    assert calls == ["contracts/orders.yaml", "contracts/payments.yaml"]


def test_build_batch_release_manifest_generates_editable_tasks_and_skips_manual_cases(
    sample_odcs_model, tmp_path
):
    base_root = tmp_path / "base"
    candidate_root = tmp_path / "candidate"

    unchanged = sample_odcs_model.model_copy(deep=True)
    docs_only = sample_odcs_model.model_copy(deep=True)
    assert docs_only.description is not None
    docs_only.description.usage = "Updated descriptive text only"

    additive = sample_odcs_model.model_copy(deep=True)
    assert additive.schema_ is not None
    assert additive.schema_[0].properties is not None
    additive.schema_[0].properties.append(
        additive.schema_[0]
        .properties[0]
        .model_copy(update={"name": "new_optional_column", "id": "new_optional_column"})
    )

    added = sample_odcs_model.model_copy(deep=True)
    added.id = "new-contract"
    added.version = "1.0.0"

    dump_yaml(unchanged, base_root / "unchanged.yaml")
    dump_yaml(unchanged, candidate_root / "unchanged.yaml")
    dump_yaml(sample_odcs_model, base_root / "docs.yaml")
    dump_yaml(docs_only, candidate_root / "docs.yaml")
    dump_yaml(sample_odcs_model, base_root / "additive.yaml")
    dump_yaml(additive, candidate_root / "additive.yaml")
    dump_yaml(sample_odcs_model, base_root / "removed.yaml")
    dump_yaml(added, candidate_root / "added.yaml")

    build = build_batch_release_manifest(
        base_root=base_root,
        candidate_root=candidate_root,
        context=TEST_CONTEXT,
    )
    tasks_by_path = {task.contract_path: task for task in build.tasks}
    skipped_by_path = {item.contract_repo_path: item for item in build.skipped}

    assert tasks_by_path["additive.yaml"].release_tag.endswith("/v1.2.0")
    assert tasks_by_path["additive.yaml"].target_branch == "release"
    assert tasks_by_path["additive.yaml"].effective_date == "2026-01-01"
    assert "docs.yaml" in skipped_by_path
    assert skipped_by_path["docs.yaml"].status == "changed"
    assert "unchanged.yaml" in skipped_by_path
    assert skipped_by_path["unchanged.yaml"].status == "unchanged"
    assert skipped_by_path["added.yaml"].status == "added"
    assert skipped_by_path["removed.yaml"].status == "removed"
