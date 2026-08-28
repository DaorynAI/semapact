"""Unit and contract-level tests for standardized process outcomes and exit codes."""

from __future__ import annotations

import pytest


from semapact.change_context import ChangeContext
from semapact.core.release import RequiredBump
from semapact.exceptions import (
    GovernanceBlockedError,
    GovernanceReviewRequiredError,
    StorageError,
    ValidationError,
)
from semapact.governance import (
    DecisionResult,
    GovernanceDecision,
    GovernanceGateResult,
    GovernanceOperation,
    PolicyOutcome,
    ValidationOutcome,
    evaluate_governance_gate,
)
from semapact.governance.models import ChangeEvidence
from semapact.interfaces.outcomes import (
    CliExitCode,
    ProcessOutcome,
    exit_code_from_exception,
    exit_code_from_outcome,
    outcome_from_exception,
    outcome_from_gate_result,
)


def _make_dummy_decision(
    decision: DecisionResult,
    bump: RequiredBump = "none",
    breaking: bool = False,
) -> GovernanceDecision:
    return GovernanceDecision(
        decision_id="test-dec-1",
        decision=decision,
        contract_id="test-contract",
        context=ChangeContext(effective_date="2026-08-29"),
        breaking=breaking,
        required_version_bump=bump,
        validation=ValidationOutcome(valid=True),
        policy=PolicyOutcome(valid=True),
        evidence=ChangeEvidence(has_changes=True),
    )


def test_process_outcome_and_exit_code_mappings():
    """Verify exact 1-to-1 semantic vocabulary to shell exit code mapping."""
    expected_mappings = {
        ProcessOutcome.SUCCESS: CliExitCode.SUCCESS,
        ProcessOutcome.VALIDATION_FAILED: CliExitCode.VALIDATION_FAILED,
        ProcessOutcome.GOVERNANCE_BLOCKED: CliExitCode.GOVERNANCE_BLOCKED,
        ProcessOutcome.REVIEW_REQUIRED: CliExitCode.REVIEW_REQUIRED,
        ProcessOutcome.RUNTIME_ERROR: CliExitCode.RUNTIME_ERROR,
    }

    for outcome, expected_code in expected_mappings.items():
        assert exit_code_from_outcome(outcome) == expected_code
        assert int(expected_code) in (0, 2, 3, 4, 5)

    assert int(CliExitCode.SUCCESS) == 0
    assert int(CliExitCode.VALIDATION_FAILED) == 2
    assert int(CliExitCode.GOVERNANCE_BLOCKED) == 3
    assert int(CliExitCode.REVIEW_REQUIRED) == 4
    assert int(CliExitCode.RUNTIME_ERROR) == 5


def test_outcome_from_gate_result():
    """Verify GovernanceGateResult maps directly to the appropriate ProcessOutcome."""
    allowed_res = GovernanceGateResult(
        allowed=True, reason="allowed", decision_id="d1"
    )
    assert outcome_from_gate_result(allowed_res) == ProcessOutcome.SUCCESS

    blocked_res = GovernanceGateResult(
        allowed=False, reason="blocked", decision_id="d2"
    )
    assert outcome_from_gate_result(blocked_res) == ProcessOutcome.GOVERNANCE_BLOCKED

    review_res = GovernanceGateResult(
        allowed=False, reason="review_required", decision_id="d3"
    )
    assert outcome_from_gate_result(review_res) == ProcessOutcome.REVIEW_REQUIRED


def test_outcome_from_exception_and_exit_code():
    """Verify domain, validation, and runtime exceptions map to standardized outcomes and exit codes."""
    blocked_exc = GovernanceBlockedError("Change is blocked")
    assert outcome_from_exception(blocked_exc) == ProcessOutcome.GOVERNANCE_BLOCKED
    assert exit_code_from_exception(blocked_exc) == 3

    review_exc = GovernanceReviewRequiredError("Manual review needed")
    assert outcome_from_exception(review_exc) == ProcessOutcome.REVIEW_REQUIRED
    assert exit_code_from_exception(review_exc) == 4

    val_exc = ValidationError("Invalid ODCS syntax")
    assert outcome_from_exception(val_exc) == ProcessOutcome.VALIDATION_FAILED
    assert exit_code_from_exception(val_exc) == 2

    from semapact.exceptions import ReleaseValidationError

    release_val_exc = ReleaseValidationError("No version bump required")
    assert outcome_from_exception(release_val_exc) == ProcessOutcome.VALIDATION_FAILED
    assert exit_code_from_exception(release_val_exc) == 2


    # Runtime and infrastructure exceptions
    runtime_exc = RuntimeError("Database unreachable")
    assert outcome_from_exception(runtime_exc) == ProcessOutcome.RUNTIME_ERROR
    assert exit_code_from_exception(runtime_exc) == 5

    storage_exc = StorageError("ADLS token expired")
    assert outcome_from_exception(storage_exc) == ProcessOutcome.RUNTIME_ERROR
    assert exit_code_from_exception(storage_exc) == 5

    # SystemExit and KeyboardInterrupt
    assert exit_code_from_exception(KeyboardInterrupt()) == 130
    assert exit_code_from_exception(SystemExit(0)) == 0
    assert exit_code_from_exception(SystemExit(2)) == 2
    assert exit_code_from_exception(SystemExit("string error")) == 5


@pytest.mark.parametrize(
    "operation,decision_result,expected_outcome,expected_exit_code",
    [
        # ANALYZE: Never fails because of governance decision (reports decision transparently)
        (GovernanceOperation.ANALYZE, DecisionResult.ALLOW, ProcessOutcome.SUCCESS, 0),
        (GovernanceOperation.ANALYZE, DecisionResult.REVIEW, ProcessOutcome.SUCCESS, 0),
        (GovernanceOperation.ANALYZE, DecisionResult.BLOCK, ProcessOutcome.SUCCESS, 0),
        # PROPOSE: ALLOW and REVIEW pass; BLOCK is blocked
        (GovernanceOperation.PROPOSE, DecisionResult.ALLOW, ProcessOutcome.SUCCESS, 0),
        (GovernanceOperation.PROPOSE, DecisionResult.REVIEW, ProcessOutcome.SUCCESS, 0),
        (GovernanceOperation.PROPOSE, DecisionResult.BLOCK, ProcessOutcome.GOVERNANCE_BLOCKED, 3),
        # APPLY: ALLOW passes; REVIEW requires review; BLOCK is blocked
        (GovernanceOperation.APPLY, DecisionResult.ALLOW, ProcessOutcome.SUCCESS, 0),
        (GovernanceOperation.APPLY, DecisionResult.REVIEW, ProcessOutcome.REVIEW_REQUIRED, 4),
        (GovernanceOperation.APPLY, DecisionResult.BLOCK, ProcessOutcome.GOVERNANCE_BLOCKED, 3),
        # PUBLISH: Same as APPLY
        (GovernanceOperation.PUBLISH, DecisionResult.ALLOW, ProcessOutcome.SUCCESS, 0),
        (GovernanceOperation.PUBLISH, DecisionResult.REVIEW, ProcessOutcome.REVIEW_REQUIRED, 4),
        (GovernanceOperation.PUBLISH, DecisionResult.BLOCK, ProcessOutcome.GOVERNANCE_BLOCKED, 3),
        # CI: Same as APPLY
        (GovernanceOperation.CI, DecisionResult.ALLOW, ProcessOutcome.SUCCESS, 0),
        (GovernanceOperation.CI, DecisionResult.REVIEW, ProcessOutcome.REVIEW_REQUIRED, 4),
        (GovernanceOperation.CI, DecisionResult.BLOCK, ProcessOutcome.GOVERNANCE_BLOCKED, 3),
    ],
)
def test_governance_gate_to_process_outcome_matrix(
    operation: GovernanceOperation,
    decision_result: DecisionResult,
    expected_outcome: ProcessOutcome,
    expected_exit_code: int,
):
    """Verify that all governance operations and decisions map predictably through the gate."""
    decision = _make_dummy_decision(
        decision_result,
        bump="minor" if decision_result == DecisionResult.REVIEW else ("major" if decision_result == DecisionResult.BLOCK else "none"),
        breaking=(decision_result == DecisionResult.BLOCK),
    )
    gate_res = evaluate_governance_gate(decision, operation)
    outcome = outcome_from_gate_result(gate_res)
    exit_code = exit_code_from_outcome(outcome)

    assert outcome == expected_outcome
    assert int(exit_code) == expected_exit_code
