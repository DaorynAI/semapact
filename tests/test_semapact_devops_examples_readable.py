from __future__ import annotations

import json
from pathlib import Path

import yaml


def test_release_manifest_example_is_valid_json_array():
    manifest_path = Path("examples/release/release-manifest.example.json")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert isinstance(payload, list)
    assert payload
    assert {
        "base",
        "candidate",
        "contract_path",
        "release_tag",
        "source_branch",
        "target_branch",
    } <= set(payload[0])


def test_ci_shell_examples_reference_release_commands():
    pr_example = Path("examples/ci/pr-check.example.sh").read_text(encoding="utf-8")
    release_example = Path("examples/ci/release.example.sh").read_text(encoding="utf-8")

    assert "release classify-repo" in pr_example
    assert "release build-manifest" in release_example
    assert "release create-prs" in release_example


def test_azure_devops_examples_reference_release_commands():
    pr_pipeline = Path("examples/azure-devops/semapact-pr-validation.yml").read_text(
        encoding="utf-8"
    )
    release_pipeline = Path("examples/azure-devops/semapact-release.yml").read_text(
        encoding="utf-8"
    )

    assert "release classify-repo" in pr_pipeline
    assert "release build-manifest" in release_pipeline
    assert "release create-prs" in release_pipeline


def test_data_product_github_example_uses_bundle_driven_ci_cd() -> None:
    workflow = Path("examples/github/data-product-ci-cd.yml").read_text(
        encoding="utf-8"
    )

    assert "release assess" in workflow
    assert "release approve" in workflow
    assert "release finalize" in workflow
    assert "deployment assess" in workflow
    assert "--release-id" in workflow
    assert "deployment deploy" in workflow
    assert "environment: contract-release" in workflow
    assert "environment: production" in workflow
    assert "--operational-history" not in workflow
    assert "deployment assess \\\n            --release" not in workflow


def test_central_contract_repo_github_example_fans_out_and_commits_ledger_once() -> None:
    workflow = Path("examples/github/central-contract-repo-ci-cd.yml").read_text(
        encoding="utf-8"
    )

    assert "release classify-repo" in workflow
    assert "fromJSON(needs.detect-contracts.outputs.matrix)" in workflow
    assert "release assess" in workflow
    assert "release approve" in workflow
    assert "release finalize" in workflow
    assert "finalize-releases:" in workflow
    assert "deployment assess" in workflow
    assert "--release-id" in workflow
    assert "deployment deploy" in workflow
    assert "merge-multiple: true" in workflow
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
