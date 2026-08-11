from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from semapact.governance.models import DecisionResult, GovernanceDecision


@dataclass(slots=True)
class CIDecision:
    """CI/CD gate decision based on GovernanceDecision."""

    allowed: bool
    reason: str


def evaluate_ci_gate(
    decision: GovernanceDecision | dict[str, Any],
) -> CIDecision:
    """Evaluate if a contract change can pass CI/CD gates based strictly on GovernanceDecision.

    Fail-closed: Invalid, corrupted, or non-conforming payloads return allowed=False with reason="invalid_governance_decision".
    """
    if isinstance(decision, dict):
        try:
            decision_obj = GovernanceDecision.from_dict(decision)
        except Exception:
            return CIDecision(allowed=False, reason="invalid_governance_decision")
    elif isinstance(decision, GovernanceDecision):
        decision_obj = decision
    else:
        return CIDecision(allowed=False, reason="invalid_governance_decision")

    if decision_obj.decision == DecisionResult.ALLOW:
        return CIDecision(allowed=True, reason="ok")
    if decision_obj.decision == DecisionResult.REVIEW:
        return CIDecision(allowed=False, reason="review_required")
    return CIDecision(allowed=False, reason="blocked")


def write_ci_summary(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write CI summary payload as JSON artifact."""
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return resolved
