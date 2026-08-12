from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from semapact.governance.gate import GovernanceOperation, evaluate_governance_gate
from semapact.governance.models import GovernanceDecision


@dataclass(slots=True)
class CIDecision:
    """CI/CD gate decision based on GovernanceDecision."""

    allowed: bool
    reason: str


def evaluate_ci_gate(decision: GovernanceDecision) -> CIDecision:
    """Evaluate if a contract change can pass CI/CD gates based strictly on GovernanceDecision.

    Delegates to evaluate_governance_gate(decision, GovernanceOperation.CI).
    Interface adapters must call GovernanceDecision.model_validate(payload) before calling evaluate_ci_gate.
    """
    res = evaluate_governance_gate(decision, GovernanceOperation.CI)
    reason_str = "ok" if res.allowed else res.reason
    return CIDecision(allowed=res.allowed, reason=reason_str)


def write_ci_summary(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write CI summary payload as JSON artifact."""
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return resolved
