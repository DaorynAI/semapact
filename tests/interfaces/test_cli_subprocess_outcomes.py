"""Subprocess-level acceptance tests for standardized CLI process exit outcomes."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Execute the SemaPact CLI in a subprocess."""
    cmd = [sys.executable, "-m", "semapact.interfaces.cli", *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def active_contract_yaml(tmp_path: Path) -> Path:
    contract = {
        "apiVersion": "v3.1.0",
        "kind": "DataContract",
        "id": "urn:datacontract:orders",
        "name": "orders",
        "version": "1.0.0",
        "status": "active",
        "schema": [
            {
                "name": "orders",
                "properties": [
                    {
                        "name": "order_id",
                        "type": "string",
                    },
                    {
                        "name": "amount",
                        "type": "number",
                    },
                ],
            }
        ],
    }
    path = tmp_path / "active_contract.yaml"
    path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    return path


@pytest.fixture
def review_candidate_yaml(tmp_path: Path) -> Path:
    """Additive change (new column) requiring MINOR bump."""
    contract = {
        "apiVersion": "v3.1.0",
        "kind": "DataContract",
        "id": "urn:datacontract:orders",
        "name": "orders",
        "version": "1.0.0",
        "status": "active",
        "schema": [
            {
                "name": "orders",
                "properties": [
                    {
                        "name": "order_id",
                        "type": "string",
                    },
                    {
                        "name": "amount",
                        "type": "number",
                    },
                    {
                        "name": "customer_id",
                        "type": "string",
                    },
                ],
            }
        ],
    }
    path = tmp_path / "review_candidate.yaml"
    path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    return path


@pytest.fixture
def retired_contract_yaml(tmp_path: Path) -> Path:
    contract = {
        "apiVersion": "v3.1.0",
        "kind": "DataContract",
        "id": "urn:datacontract:orders",
        "name": "orders",
        "version": "1.0.0",
        "status": "retired",
        "schema": [
            {
                "name": "orders",
                "properties": [
                    {
                        "name": "order_id",
                        "type": "string",
                    }
                ],
            }
        ],
    }
    path = tmp_path / "retired_contract.yaml"
    path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    return path


@pytest.fixture
def invalid_contract_yaml(tmp_path: Path) -> Path:
    """Contract that violates ODCS schema structure (raises Pydantic ValidationError)."""
    contract = {
        "apiVersion": "v3.1.0",
        "kind": "DataContract",
        "id": "urn:datacontract:orders",
        "name": "orders",
        "version": "1.0.0",
        "status": "active",
        "schema": "not_a_list_violates_odcs_model",
    }
    path = tmp_path / "invalid_contract.yaml"
    path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    return path


# ==============================================================================
# 1. ANALYZE Commands: Never fail because of governance decision
# ==============================================================================

def test_subprocess_analyze_release_classify_allow(active_contract_yaml: Path):
    res = _run_cli(
        "release",
        "classify",
        "--base",
        str(active_contract_yaml),
        "--candidate",
        str(active_contract_yaml),
        "--effective-date",
        "2026-08-29",
    )
    assert res.returncode == 0
    payload = json.loads(res.stdout)
    assert payload["hasChanges"] is False
    assert payload["requiredBump"] == "none"
    assert "exitCode" not in payload
    assert "exitCode" not in payload.get("governanceDecision", {})


def test_subprocess_analyze_release_classify_review(
    active_contract_yaml: Path, review_candidate_yaml: Path
):
    res = _run_cli(
        "release",
        "classify",
        "--base",
        str(active_contract_yaml),
        "--candidate",
        str(review_candidate_yaml),
        "--effective-date",
        "2026-08-29",
    )
    assert res.returncode == 0
    payload = json.loads(res.stdout)
    assert payload["hasChanges"] is True
    assert payload["requiredBump"] == "minor"
    assert "exitCode" not in payload


def test_subprocess_analyze_release_classify_block(
    retired_contract_yaml: Path, review_candidate_yaml: Path
):
    # ANALYZE on retired base contract still exits with code 0 and reports BLOCK
    res = _run_cli(
        "release",
        "classify",
        "--base",
        str(retired_contract_yaml),
        "--candidate",
        str(review_candidate_yaml),
        "--effective-date",
        "2026-08-29",
    )
    assert res.returncode == 0
    payload = json.loads(res.stdout)
    assert payload["hasChanges"] is True
    assert payload["governanceDecision"]["decision"] == "BLOCK"
    assert "exitCode" not in payload


# ==============================================================================
# 2. PROPOSE Commands: ALLOW & REVIEW -> 0, BLOCK -> 3 (GOVERNANCE_BLOCKED)
# ==============================================================================

def test_subprocess_propose_release_prepare_review(
    active_contract_yaml: Path, review_candidate_yaml: Path, tmp_path: Path
):
    out_yaml = tmp_path / "prepared.yaml"
    res = _run_cli(
        "release",
        "prepare",
        "--base",
        str(active_contract_yaml),
        "--candidate",
        str(review_candidate_yaml),
        "--release-tag",
        "v1.1.0",
        "--output",
        str(out_yaml),
        "--effective-date",
        "2026-08-29",
    )
    assert res.returncode == 0
    payload = json.loads(res.stdout)
    assert payload["actualBump"] == "minor"
    assert "exitCode" not in payload


def test_subprocess_propose_release_prepare_no_bump_validation_failed(
    active_contract_yaml: Path, tmp_path: Path
):
    out_yaml = tmp_path / "prepared.yaml"
    res = _run_cli(
        "release",
        "prepare",
        "--base",
        str(active_contract_yaml),
        "--candidate",
        str(active_contract_yaml),
        "--release-tag",
        "v1.0.0",
        "--output",
        str(out_yaml),
        "--effective-date",
        "2026-08-29",
    )
    # Attempting to prepare a release candidate when no bump is required returns VALIDATION_FAILED (2)
    assert res.returncode == 2
    assert "Contract changes do not require a release version bump" in res.stderr



def test_subprocess_propose_release_prepare_block(
    retired_contract_yaml: Path, review_candidate_yaml: Path, tmp_path: Path
):
    out_yaml = tmp_path / "prepared.yaml"
    res = _run_cli(
        "release",
        "prepare",
        "--base",
        str(retired_contract_yaml),
        "--candidate",
        str(review_candidate_yaml),
        "--release-tag",
        "v2.0.0",
        "--output",
        str(out_yaml),
        "--effective-date",
        "2026-08-29",
    )
    # PROPOSE with BLOCK decision must exit with 3 (GOVERNANCE_BLOCKED)
    assert res.returncode == 3
    assert "Governance decision BLOCKED" in res.stderr
    assert "Traceback (most recent call last)" not in res.stderr


def test_subprocess_propose_merge_block(
    retired_contract_yaml: Path, review_candidate_yaml: Path, tmp_path: Path
):
    out_yaml = tmp_path / "merged.yaml"
    res = _run_cli(
        "merge",
        "--base",
        str(review_candidate_yaml),
        "--business",
        str(retired_contract_yaml),
        "--output",
        str(out_yaml),
        "--effective-date",
        "2026-08-29",
    )
    assert res.returncode == 3
    assert "Governance decision BLOCKED" in res.stderr


# ==============================================================================
# 3. APPLY Commands: ALLOW -> 0, REVIEW -> 4 (REVIEW_REQUIRED), BLOCK -> 3
# ==============================================================================

def test_subprocess_apply_lifecycle_promote_review_required(
    active_contract_yaml: Path, tmp_path: Path
):
    out_yaml = tmp_path / "promoted.yaml"
    res = _run_cli(
        "lifecycle",
        "promote",
        "--contract",
        str(active_contract_yaml),
        "--schema",
        "orders",
        "--property",
        "order_id",
        "--output",
        str(out_yaml),
        "--effective-date",
        "2026-08-29",
    )
    # Applying lifecycle mutation produces a REVIEW decision on additive changes, which requires review (4)
    assert res.returncode == 4
    assert "Governance decision REVIEW required" in res.stderr
    assert "Traceback (most recent call last)" not in res.stderr


def test_subprocess_apply_lifecycle_deprecate_block_on_retired(
    retired_contract_yaml: Path, tmp_path: Path
):
    out_yaml = tmp_path / "deprecated.yaml"
    res = _run_cli(
        "lifecycle",
        "deprecate",
        "--contract",
        str(retired_contract_yaml),
        "--schema",
        "orders",
        "--property",
        "order_id",
        "--output",
        str(out_yaml),
        "--effective-date",
        "2026-08-29",
    )
    # Mutating retired contract is blocked (3)
    assert res.returncode == 3
    assert "Governance decision BLOCKED" in res.stderr


# ==============================================================================
# 4. VALIDATION_FAILED (Exit code 2)
# ==============================================================================

def test_subprocess_validation_failed_on_invalid_arguments():
    res = _run_cli("unknown-command")
    assert res.returncode == 2

    res_missing_args = _run_cli("release", "classify")
    assert res_missing_args.returncode == 2


def test_subprocess_validation_failed_on_invalid_contract(
    invalid_contract_yaml: Path, active_contract_yaml: Path
):
    res = _run_cli(
        "release",
        "classify",
        "--base",
        str(invalid_contract_yaml),
        "--candidate",
        str(active_contract_yaml),
        "--effective-date",
        "2026-08-29",
    )
    assert res.returncode == 2
    assert "❌" in res.stderr



# ==============================================================================
# 5. RUNTIME_ERROR (Exit code 5)
# ==============================================================================

def test_subprocess_runtime_error_on_missing_file(active_contract_yaml: Path):
    res = _run_cli(
        "release",
        "classify",
        "--base",
        "/nonexistent/path/contract.yaml",
        "--candidate",
        str(active_contract_yaml),
        "--effective-date",
        "2026-08-29",
    )
    # File not found error is a runtime execution failure
    assert res.returncode == 5

