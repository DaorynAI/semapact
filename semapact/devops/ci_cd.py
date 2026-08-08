from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import json

from semapact.lifecycle.policy import PolicyEvaluation
from semapact.core.validator import ValidationReport


@dataclass(slots=True)
class CIDecision:
    """CI/CD gate decision based on validation and lifecycle policy checks."""

    allowed: bool
    reason: str


def evaluate_ci_gate(
    validation: ValidationReport, policy: PolicyEvaluation
) -> CIDecision:
    """Evaluate if a contract change can pass CI/CD gates."""
    if not validation.valid:
        return CIDecision(allowed=False, reason="contract_validation_failed")
    if not policy.valid:
        return CIDecision(allowed=False, reason="lifecycle_policy_failed")
    return CIDecision(allowed=True, reason="ok")


def write_ci_summary(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write CI summary payload as JSON artifact."""
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return resolved
