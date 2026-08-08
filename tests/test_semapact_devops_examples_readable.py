from __future__ import annotations

import json
from pathlib import Path


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
