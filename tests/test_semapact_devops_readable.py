from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from semapact.devops.audit import build_audit_metadata
from semapact.devops.ci_cd import evaluate_ci_gate, write_ci_summary
from semapact.devops.pr_creator import AzureDevOpsConfig, PullRequestCreator


def _creator() -> PullRequestCreator:
    return PullRequestCreator(
        config=AzureDevOpsConfig(
            organization="org",
            project="proj",
            repository_id="repo",
            pat_token="token-123",
        )
    )


def test_audit_metadata_builder_returns_actor_source_and_timestamp():
    metadata = build_audit_metadata(actor="chaosun", source="sql-import")

    assert metadata.last_merge_actor == "chaosun"
    assert metadata.last_merge_source == "sql-import"
    assert "T" in metadata.last_merge_ts


def test_ci_gate_allows_only_when_validation_and_policy_are_valid():
    from semapact.governance.models import (
        ChangeEvidence,
        DecisionResult,
        GovernanceDecision,
        PolicyOutcome,
        ValidationOutcome,
    )

    val = ValidationOutcome(valid=True)
    pol = PolicyOutcome(valid=True)
    evi = ChangeEvidence()

    dec_allow = GovernanceDecision(
        decision_id="id1",
        decision=DecisionResult.ALLOW,
        contract_id="c1",
        breaking=False,
        required_version_bump="none",
        validation=val,
        policy=pol,
        evidence=evi,
    )
    dec_review = GovernanceDecision(
        decision_id="id2",
        decision=DecisionResult.REVIEW,
        contract_id="c1",
        breaking=False,
        required_version_bump="minor",
        validation=val,
        policy=pol,
        evidence=evi,
    )
    dec_block = GovernanceDecision(
        decision_id="id3",
        decision=DecisionResult.BLOCK,
        contract_id="c1",
        breaking=True,
        required_version_bump="major",
        validation=ValidationOutcome(valid=False),
        policy=PolicyOutcome(valid=False),
        evidence=evi,
    )

    res_allow = evaluate_ci_gate(dec_allow)
    res_review = evaluate_ci_gate(dec_review)
    res_block = evaluate_ci_gate(dec_block)

    assert res_allow.allowed is True and res_allow.reason == "allowed"
    assert res_review.allowed is False and res_review.reason == "review_required"
    assert res_block.allowed is False and res_block.reason == "blocked"


def test_ci_summary_writer_persists_json_payload(tmp_path):
    path = write_ci_summary(tmp_path / "summary.json", {"status": "ok", "count": 2})
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["status"] == "ok"
    assert payload["count"] == 2


def test_pull_request_headers_use_basic_auth_token_encoding():
    creator = _creator()
    headers = creator.provider._headers()  # noqa: SLF001

    assert headers["Content-Type"] == "application/json"
    assert headers["Authorization"].startswith("Basic ")


def test_commit_updated_contracts_returns_head_when_no_changes(monkeypatch, tmp_path):
    creator = _creator()
    calls: list[tuple[list[str], bool]] = []

    monkeypatch.setattr(
        PullRequestCreator, "_ensure_branch", lambda self, repo, source_branch: None
    )

    def fake_git(repo, args, capture_output=False):  # noqa: ANN001
        calls.append((args, capture_output))
        if args == ["status", "--porcelain"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, stdout="abc123\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(PullRequestCreator, "_git", staticmethod(fake_git))

    sha = creator.commit_updated_contracts(
        str(tmp_path),
        source_branch="feature/contracts",
        commit_message="update",
    )

    assert sha == "abc123"
    assert any(args == ["add", "-u"] for args, _ in calls)


def test_commit_updated_contracts_commits_when_changes_exist(monkeypatch, tmp_path):
    creator = _creator()
    calls: list[list[str]] = []

    monkeypatch.setattr(
        PullRequestCreator, "_ensure_branch", lambda self, repo, source_branch: None
    )

    def fake_git(repo, args, capture_output=False):  # noqa: ANN001
        calls.append(args)
        if args == ["status", "--porcelain"]:
            return subprocess.CompletedProcess(
                args, 0, stdout="M contract.yaml\n", stderr=""
            )
        if args == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, stdout="def456\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(PullRequestCreator, "_git", staticmethod(fake_git))

    sha = creator.commit_updated_contracts(
        str(tmp_path),
        source_branch="feature/contracts",
        commit_message="update",
        paths=["contract.yaml"],
    )

    assert sha == "def456"
    assert ["commit", "-m", "update"] in calls


def test_create_pull_request_sends_expected_payload(monkeypatch):
    creator = _creator()
    captured = {}

    class FakeResponse:
        ok = True
        status_code = 200
        text = "ok"

        @staticmethod
        def json():
            return {"pullRequestId": 77}

    def fake_post(url, headers, data, timeout):  # noqa: ANN001
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = json.loads(data)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("semapact.devops.pr_creator.requests.post", fake_post)

    payload = creator.create_pull_request(
        source_branch="feature/contracts",
        target_branch="main",
        title="Update contracts",
        description="Automated",
        reviewers=["user-id-1"],
    )

    assert payload["pullRequestId"] == 77
    assert captured["payload"]["sourceRefName"] == "refs/heads/feature/contracts"
    assert captured["payload"]["reviewers"][0]["id"] == "user-id-1"


def test_create_pull_request_raises_on_failed_response(monkeypatch):
    creator = _creator()

    class FakeResponse:
        ok = False
        status_code = 500
        text = "boom"

    monkeypatch.setattr(
        "semapact.devops.pr_creator.requests.post",
        lambda *args, **kwargs: FakeResponse(),
    )

    with pytest.raises(RuntimeError, match="Failed to create PR"):
        creator.create_pull_request(
            source_branch="feature/contracts",
            target_branch="main",
            title="Update",
            description="Automated",
        )


def test_create_update_pr_pushes_branch_before_creating_pr(monkeypatch, tmp_path):
    creator = _creator()
    calls: list[list[str]] = []

    monkeypatch.setattr(
        PullRequestCreator,
        "commit_updated_contracts",
        lambda self, *args, **kwargs: "abc123",
    )

    def fake_git(repo, args, capture_output=False):  # noqa: ANN001
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(PullRequestCreator, "_git", staticmethod(fake_git))
    monkeypatch.setattr(
        PullRequestCreator,
        "create_pull_request",
        lambda self, **kwargs: {"pullRequestId": 99, "source": kwargs["source_branch"]},
    )

    payload = creator.create_update_pr(
        repo_path=str(tmp_path),
        source_branch="feature/contracts",
        target_branch="main",
        commit_message="update",
        title="Update",
        description="Automated",
        push=True,
    )

    assert payload["pullRequestId"] == 99
    assert ["push", "--set-upstream", "origin", "feature/contracts"] in calls


def test_ensure_branch_checks_out_existing_branch(monkeypatch, tmp_path):
    creator = _creator()
    git_calls: list[list[str]] = []

    def fake_git(repo, args, capture_output=False):  # noqa: ANN001
        git_calls.append(args)
        if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, stdout="main\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(PullRequestCreator, "_git", staticmethod(fake_git))
    monkeypatch.setattr(
        "semapact.devops.pr_creator.subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=0),
    )

    creator._ensure_branch(tmp_path, "feature/contracts")  # noqa: SLF001

    assert ["checkout", "feature/contracts"] in git_calls


def test_ensure_branch_creates_new_branch_when_missing(monkeypatch, tmp_path):
    creator = _creator()
    git_calls: list[list[str]] = []

    def fake_git(repo, args, capture_output=False):  # noqa: ANN001
        git_calls.append(args)
        if args == ["checkout", "feature/new-branch"]:
            raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(PullRequestCreator, "_git", staticmethod(fake_git))

    creator._ensure_branch(tmp_path, "feature/new-branch")  # noqa: SLF001

    assert ["checkout", "-b", "feature/new-branch"] in git_calls
