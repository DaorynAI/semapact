from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import json

from semapact.governance.models import DecisionResult, GovernanceDecision
from semapact.lifecycle.policy import PolicyEvaluation
from semapact.core.validator import ValidationReport


@dataclass(slots=True)
class CIDecision:
    """CI/CD gate decision based on GovernanceDecision."""

    allowed: bool
    reason: str


def evaluate_ci_gate(
    decision_or_validation: GovernanceDecision | dict[str, Any] | ValidationReport,
    policy: PolicyEvaluation | None = None,
) -> CIDecision:
    """Evaluate if a contract change can pass CI/CD gates based on GovernanceDecision."""
    if isinstance(decision_or_validation, ValidationReport):
        if not decision_or_validation.valid:
            return CIDecision(allowed=False, reason="contract_validation_failed")
        if policy is not None and not policy.valid:
            return CIDecision(allowed=False, reason="lifecycle_policy_failed")
        return CIDecision(allowed=True, reason="ok")

    if isinstance(decision_or_validation, dict):
        decision_obj = GovernanceDecision.from_dict(decision_or_validation)
    else:
        decision_obj = decision_or_validation

    if decision_obj.decision == DecisionResult.ALLOW:
        return CIDecision(allowed=True, reason="ok")
    elif decision_obj.decision == DecisionResult.REVIEW:
        return CIDecision(allowed=False, reason="review_required")
    else:
        return CIDecision(allowed=False, reason="blocked")


def write_ci_summary(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write CI summary payload as JSON artifact."""
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return resolved
