"""Standardized process outcome vocabulary and CLI exit code mapping.

This module defines the authoritative semantic outcome vocabulary and shell exit
code adapter for SemaPact CLI and CI automation layers.
"""

from __future__ import annotations

from enum import Enum, IntEnum
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from semapact.governance.gate import GovernanceGateResult
    from semapact.reconciliation import RuntimeDriftStatus


logger = logging.getLogger("semapact")


class ProcessOutcome(str, Enum):
    """Authoritative semantic process outcome vocabulary."""

    SUCCESS = "SUCCESS"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    GOVERNANCE_BLOCKED = "GOVERNANCE_BLOCKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    RUNTIME_DRIFT = "RUNTIME_DRIFT"
    RUNTIME_INDETERMINATE = "RUNTIME_INDETERMINATE"


class CliExitCode(IntEnum):
    """Standardized shell process exit codes for SemaPact."""

    SUCCESS = 0
    VALIDATION_FAILED = 2
    GOVERNANCE_BLOCKED = 3
    REVIEW_REQUIRED = 4
    RUNTIME_ERROR = 5
    RUNTIME_DRIFT = 6
    RUNTIME_INDETERMINATE = 7


_OUTCOME_TO_EXIT_CODE: dict[ProcessOutcome, CliExitCode] = {
    ProcessOutcome.SUCCESS: CliExitCode.SUCCESS,
    ProcessOutcome.VALIDATION_FAILED: CliExitCode.VALIDATION_FAILED,
    ProcessOutcome.GOVERNANCE_BLOCKED: CliExitCode.GOVERNANCE_BLOCKED,
    ProcessOutcome.REVIEW_REQUIRED: CliExitCode.REVIEW_REQUIRED,
    ProcessOutcome.RUNTIME_ERROR: CliExitCode.RUNTIME_ERROR,
    ProcessOutcome.RUNTIME_DRIFT: CliExitCode.RUNTIME_DRIFT,
    ProcessOutcome.RUNTIME_INDETERMINATE: CliExitCode.RUNTIME_INDETERMINATE,
}


def exit_code_from_outcome(outcome: ProcessOutcome) -> CliExitCode:
    """Map a semantic ProcessOutcome to its corresponding CliExitCode."""
    try:
        return _OUTCOME_TO_EXIT_CODE[outcome]
    except KeyError:
        raise ValueError(f"Unsupported ProcessOutcome: {outcome!r}") from None


def outcome_from_gate_result(gate_result: GovernanceGateResult) -> ProcessOutcome:
    """Map a GovernanceGateResult directly to the appropriate ProcessOutcome."""
    if gate_result.allowed:
        return ProcessOutcome.SUCCESS
    if gate_result.reason == "blocked":
        return ProcessOutcome.GOVERNANCE_BLOCKED
    if gate_result.reason == "review_required":
        return ProcessOutcome.REVIEW_REQUIRED
    raise ValueError(f"Unsupported GovernanceGateResult reason: {gate_result.reason!r}")


def outcome_from_reconciliation_status(status: RuntimeDriftStatus) -> ProcessOutcome:
    """Map an M1 runtime-assurance status to a process outcome."""
    from semapact.reconciliation import RuntimeDriftStatus

    if status is RuntimeDriftStatus.IN_SYNC:
        return ProcessOutcome.SUCCESS
    if status is RuntimeDriftStatus.DRIFT:
        return ProcessOutcome.RUNTIME_DRIFT
    if status is RuntimeDriftStatus.INDETERMINATE:
        return ProcessOutcome.RUNTIME_INDETERMINATE
    raise ValueError(f"Unsupported RuntimeDriftStatus: {status!r}")


def exit_code_from_reconciliation_status(status: RuntimeDriftStatus) -> CliExitCode:
    """Map an M1 runtime-assurance status directly to its CLI exit code."""
    return exit_code_from_outcome(outcome_from_reconciliation_status(status))


def outcome_from_exception(exc: BaseException) -> ProcessOutcome:
    """Determine the semantic ProcessOutcome for a given exception."""
    from semapact.exceptions import (
        GovernanceBlockedError,
        GovernanceReviewRequiredError,
        ValidationError,
    )

    if isinstance(exc, GovernanceBlockedError):
        return ProcessOutcome.GOVERNANCE_BLOCKED
    if isinstance(exc, GovernanceReviewRequiredError):
        return ProcessOutcome.REVIEW_REQUIRED
    if isinstance(exc, ValidationError):
        return ProcessOutcome.VALIDATION_FAILED

    return ProcessOutcome.RUNTIME_ERROR


def exit_code_from_exception(exc: BaseException) -> int:
    """Resolve an exit code from an exception.

    Preserves explicit SystemExit and KeyboardInterrupt codes, while mapping all other
    domain, validation, governance, or runtime exceptions to standardized CliExitCodes.
    """
    if isinstance(exc, KeyboardInterrupt):
        return 130
    if isinstance(exc, SystemExit):
        return exc.code if isinstance(exc.code, int) else CliExitCode.RUNTIME_ERROR

    outcome = outcome_from_exception(exc)
    return int(exit_code_from_outcome(outcome))
