"""Unit tests for SemaPact centralized governance gate."""

from __future__ import annotations

from pathlib import Path
import pytest

from semapact.exceptions import GovernanceBlockedError, GovernanceReviewRequiredError
from semapact.governance import (
    ChangeEvidence,
    DecisionResult,
    GovernanceDecision,
    GovernanceGateResult,
    GovernanceOperation,
    GovernanceReason,
    PolicyOutcome,
    ValidationOutcome,
    enforce_governance_gate,
    evaluate_governance_gate,
)


def _make_decision(result: DecisionResult) -> GovernanceDecision:
    """Helper to construct a typed GovernanceDecision for testing."""
    val_valid = result != DecisionResult.BLOCK
    pol_valid = result == DecisionResult.ALLOW
    breaking = result == DecisionResult.REVIEW
    bump = "none" if result == DecisionResult.ALLOW else ("minor" if result == DecisionResult.REVIEW else "major")
    conflicts_count = 0

    reasons: list[GovernanceReason] = []
    if result == DecisionResult.BLOCK:
        reasons.append(GovernanceReason(code="VALIDATION_ERROR", message="Invalid schema"))
    elif result == DecisionResult.REVIEW:
        reasons.append(GovernanceReason(code="POLICY_BREAKING_CHANGE", message="Additive change"))

    return GovernanceDecision(
        decision_id="dec-123",
        decision=result,
        contract_id="contract-test",
        breaking=breaking,
        required_version_bump=bump,
        validation=ValidationOutcome(valid=val_valid),
        policy=PolicyOutcome(valid=pol_valid, id_violation=not val_valid),
        evidence=ChangeEvidence(has_changes=True, merge_conflicts_count=conflicts_count),
        reasons=tuple(reasons),
    )


@pytest.mark.parametrize(
    ("decision_result", "operation", "expected_allowed", "expected_reason"),
    [
        # ANALYZE operation: always allowed for any decision
        (DecisionResult.ALLOW, GovernanceOperation.ANALYZE, True, "allowed"),
        (DecisionResult.REVIEW, GovernanceOperation.ANALYZE, True, "allowed"),
        (DecisionResult.BLOCK, GovernanceOperation.ANALYZE, True, "allowed"),
        # PROPOSE operation: ALLOW and REVIEW are allowed; BLOCK is blocked
        (DecisionResult.ALLOW, GovernanceOperation.PROPOSE, True, "allowed"),
        (DecisionResult.REVIEW, GovernanceOperation.PROPOSE, True, "allowed"),
        (DecisionResult.BLOCK, GovernanceOperation.PROPOSE, False, "blocked"),
        # APPLY operation: ALLOW is allowed; REVIEW requires review; BLOCK is blocked
        (DecisionResult.ALLOW, GovernanceOperation.APPLY, True, "allowed"),
        (DecisionResult.REVIEW, GovernanceOperation.APPLY, False, "review_required"),
        (DecisionResult.BLOCK, GovernanceOperation.APPLY, False, "blocked"),
        # PUBLISH operation: ALLOW is allowed; REVIEW requires review; BLOCK is blocked
        (DecisionResult.ALLOW, GovernanceOperation.PUBLISH, True, "allowed"),
        (DecisionResult.REVIEW, GovernanceOperation.PUBLISH, False, "review_required"),
        (DecisionResult.BLOCK, GovernanceOperation.PUBLISH, False, "blocked"),
        # CI operation: ALLOW is allowed; REVIEW requires review; BLOCK is blocked
        (DecisionResult.ALLOW, GovernanceOperation.CI, True, "allowed"),
        (DecisionResult.REVIEW, GovernanceOperation.CI, False, "review_required"),
        (DecisionResult.BLOCK, GovernanceOperation.CI, False, "blocked"),
    ],
)
def test_evaluate_governance_gate_matrix(
    decision_result: DecisionResult,
    operation: GovernanceOperation,
    expected_allowed: bool,
    expected_reason: str,
):
    """Verify all 15 combinations of DecisionResult x GovernanceOperation."""
    decision = _make_decision(decision_result)
    result = evaluate_governance_gate(decision, operation)

    assert result.allowed == expected_allowed
    assert result.reason == expected_reason
    assert result.decision_id == "dec-123"


def test_evaluate_governance_gate_type_checks():
    """Verify evaluate_governance_gate rejects non-pydantic decision objects or raw string operations."""
    decision = _make_decision(DecisionResult.ALLOW)

    # Rejects dict input for decision
    with pytest.raises(TypeError, match="evaluate_governance_gate requires GovernanceDecision"):
        evaluate_governance_gate({"decision": "ALLOW"}, GovernanceOperation.CI)  # type: ignore

    # Rejects raw string input for operation
    with pytest.raises(TypeError, match="evaluate_governance_gate requires GovernanceOperation"):
        evaluate_governance_gate(decision, "CI")  # type: ignore


def test_governance_gate_result_invariants():
    """Verify GovernanceGateResult model invariants: allowed=True <-> reason='allowed'."""
    # allowed=True with reason='blocked' should fail
    with pytest.raises(ValueError, match="GovernanceGateResult invariant violation"):
        GovernanceGateResult(allowed=True, reason="blocked", decision_id="dec-1")

    # allowed=False with reason='allowed' should fail
    with pytest.raises(ValueError, match="GovernanceGateResult invariant violation"):
        GovernanceGateResult(allowed=False, reason="allowed", decision_id="dec-1")


def test_enforce_governance_gate_raises_blocked_error():
    """Verify enforce_governance_gate raises GovernanceBlockedError on BLOCK decision."""
    decision = _make_decision(DecisionResult.BLOCK)
    manifest_path = Path("/tmp/manifest.json")

    with pytest.raises(GovernanceBlockedError) as exc_info:
        enforce_governance_gate(decision, GovernanceOperation.PROPOSE, manifest_path=manifest_path)

    err = exc_info.value
    assert err.decision == decision
    assert err.operation == GovernanceOperation.PROPOSE
    assert err.manifest_path == manifest_path
    assert "Governance decision BLOCKED" in str(err)


def test_enforce_governance_gate_raises_review_required_error():
    """Verify enforce_governance_gate raises GovernanceReviewRequiredError on REVIEW decision for APPLY/CI."""
    decision = _make_decision(DecisionResult.REVIEW)

    with pytest.raises(GovernanceReviewRequiredError) as exc_info:
        enforce_governance_gate(decision, GovernanceOperation.APPLY)

    err = exc_info.value
    assert err.decision == decision
    assert err.operation == GovernanceOperation.APPLY
    assert "Governance decision REVIEW required" in str(err)


def test_enforce_governance_gate_passes_for_allowed_operation():
    """Verify enforce_governance_gate returns result when operation is allowed."""
    decision = _make_decision(DecisionResult.REVIEW)
    res = enforce_governance_gate(decision, GovernanceOperation.PROPOSE)

    assert res.allowed is True
    assert res.reason == "allowed"
