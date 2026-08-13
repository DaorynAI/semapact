"""Centralized fail-closed governance gate for SemaPact."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from semapact.exceptions import GovernanceBlockedError, GovernanceReviewRequiredError
from semapact.governance.models import (
    DecisionResult,
    GovernanceDecision,
    GovernanceModel,
)


class GovernanceOperation(str, Enum):
    """Supported governance execution operations."""

    ANALYZE = "ANALYZE"
    PROPOSE = "PROPOSE"
    APPLY = "APPLY"
    PUBLISH = "PUBLISH"
    CI = "CI"


class GovernanceGateResult(GovernanceModel):
    """Authoritative gate evaluation result for a specific operation."""

    allowed: bool = Field(strict=True)
    reason: Literal["allowed", "blocked", "review_required"]
    decision_id: str

    @model_validator(mode="after")
    def _validate_gate_invariants(self) -> GovernanceGateResult:
        if self.allowed and self.reason != "allowed":
            raise ValueError("GovernanceGateResult invariant violation: allowed=True requires reason='allowed'")
        if not self.allowed and self.reason not in {"blocked", "review_required"}:
            raise ValueError("GovernanceGateResult invariant violation: allowed=False requires reason in ('blocked', 'review_required')")
        return self


def evaluate_governance_gate(
    decision: GovernanceDecision,
    operation: GovernanceOperation,
) -> GovernanceGateResult:
    """Evaluate if an operation is allowed based strictly on GovernanceDecision and GovernanceOperation."""
    if not isinstance(decision, GovernanceDecision):
        raise TypeError(f"evaluate_governance_gate requires GovernanceDecision, got {type(decision).__name__}")
    if not isinstance(operation, GovernanceOperation):
        raise TypeError(f"evaluate_governance_gate requires GovernanceOperation, got {type(operation).__name__}")

    decision_id = decision.decision_id

    # 1. ANALYZE operation is always allowed (displays decision and reasons without mutation/side-effects)
    if operation == GovernanceOperation.ANALYZE:
        return GovernanceGateResult(allowed=True, reason="allowed", decision_id=decision_id)

    # 2. PROPOSE operation allows ALLOW and REVIEW (e.g. producing candidate YAML/PR), but blocks BLOCK
    if operation == GovernanceOperation.PROPOSE:
        if decision.decision in (DecisionResult.ALLOW, DecisionResult.REVIEW):
            return GovernanceGateResult(allowed=True, reason="allowed", decision_id=decision_id)
        return GovernanceGateResult(allowed=False, reason="blocked", decision_id=decision_id)

    # 3. APPLY, PUBLISH, and CI operations allow only ALLOW; REVIEW is gated, and BLOCK is forbidden
    if operation in (GovernanceOperation.APPLY, GovernanceOperation.PUBLISH, GovernanceOperation.CI):
        if decision.decision == DecisionResult.ALLOW:
            return GovernanceGateResult(allowed=True, reason="allowed", decision_id=decision_id)
        if decision.decision == DecisionResult.REVIEW:
            return GovernanceGateResult(allowed=False, reason="review_required", decision_id=decision_id)
        return GovernanceGateResult(allowed=False, reason="blocked", decision_id=decision_id)

    raise ValueError(f"Unsupported GovernanceOperation: {operation}")


def enforce_governance_gate(
    decision: GovernanceDecision,
    operation: GovernanceOperation,
    *,
    manifest_path: Path | str | None = None,
) -> GovernanceGateResult:
    """Enforce governance gate for an operation, raising errors if not allowed."""
    result = evaluate_governance_gate(decision, operation)

    if result.reason == "blocked":
        reasons_text = "; ".join(f"{r.path or 'root'}: {r.message}" for r in decision.reasons) or "Governance decision BLOCKED"
        raise GovernanceBlockedError(
            f"Governance decision BLOCKED for operation {operation.value}: {reasons_text}",
            decision=decision,
            operation=operation,
            manifest_path=manifest_path,
        )

    if result.reason == "review_required":
        reasons_text = "; ".join(f"{r.path or 'root'}: {r.message}" for r in decision.reasons) or "Governance decision REVIEW required"
        raise GovernanceReviewRequiredError(
            f"Governance decision REVIEW required for operation {operation.value}: {reasons_text}",
            decision=decision,
            operation=operation,
            manifest_path=manifest_path,
        )

    return result
