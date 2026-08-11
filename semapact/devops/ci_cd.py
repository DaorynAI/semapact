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


def evaluate_ci_gate(decision: GovernanceDecision) -> CIDecision:
    """Evaluate if a contract change can pass CI/CD gates based strictly on GovernanceDecision.

    Signature enforces typed GovernanceDecision input without payload union.
    Interface adapters must call GovernanceDecision.model_validate(payload) before calling evaluate_ci_gate.
    """
    if not isinstance(decision, GovernanceDecision):
        raise TypeError(f"evaluate_ci_gate requires GovernanceDecision, got {type(decision).__name__}")

    if decision.decision == DecisionResult.ALLOW:
        return CIDecision(allowed=True, reason="ok")
    if decision.decision == DecisionResult.REVIEW:
        return CIDecision(allowed=False, reason="review_required")
    return CIDecision(allowed=False, reason="blocked")


def write_ci_summary(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write CI summary payload as JSON artifact."""
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return resolved
