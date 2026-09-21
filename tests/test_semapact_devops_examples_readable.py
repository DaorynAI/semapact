from __future__ import annotations

from pathlib import Path

import yaml


def test_pr_validation_examples_use_repository_classification() -> None:
    shell = Path("examples/ci/pr-check.example.sh").read_text(encoding="utf-8")
    azure = Path("examples/azure-devops/semapact-pr-validation.yml").read_text(
        encoding="utf-8"
    )

    assert "release classify-repo" in shell
    assert "release classify-repo" in azure
    assert "build-manifest" not in shell
    assert "create-prs" not in shell
    assert "build-manifest" not in azure
    assert "create-prs" not in azure


def test_data_product_github_example_uses_bundle_driven_ci_cd() -> None:
    workflow = Path("examples/github/data-product-ci-cd.yml").read_text(
        encoding="utf-8"
    )

    assert "release assess" in workflow
    assert "release approve" in workflow
    assert "release finalize" in workflow
    assert "deployment assess" in workflow
    assert "--release " in workflow
    assert "--release-id" not in workflow
    assert "deployment deploy" in workflow
    assert "environment: contract-release" in workflow
    assert "environment: production" in workflow
    assert "--operational-history" not in workflow


def test_central_contract_repo_github_example_fans_out_and_commits_ledger_once() -> None:
    workflow = Path("examples/github/central-contract-repo-ci-cd.yml").read_text(
        encoding="utf-8"
    )

    assert "release classify-repo" in workflow
    assert "fromJSON(needs.detect-contracts.outputs.matrix)" in workflow
    assert "artifact: .artifactKey" in workflow
    assert 'gsub("[^A-Za-z0-9_-]"; "_")' not in workflow
    assert "release assess" in workflow
    assert "release approve" in workflow
    assert "release finalize" in workflow
    assert "finalize-releases:" in workflow
    assert "deployment assess" in workflow
    assert "--release " in workflow
    assert "--release-id" not in workflow
    assert "deployment deploy" in workflow
    assert "semapact-finalized-releases" in workflow
    assert "--operational-history" not in workflow


def test_bundle_driven_github_examples_are_valid_yaml() -> None:
    for path in (
        Path("examples/github/data-product-ci-cd.yml"),
        Path("examples/github/central-contract-repo-ci-cd.yml"),
    ):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        assert isinstance(payload.get("jobs"), dict)
        assert payload["jobs"]
