"""Governance decision and outcome data models for SemaPact."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from semapact.core.release import RequiredBump


class DecisionResult(str, Enum):
    """Authoritative governance decision outcome."""

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    REVIEW = "REVIEW"


@dataclass(frozen=True, slots=True)
class GovernanceReason:
    """Structured, machine-readable reason for a governance decision."""

    code: str
    message: str
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.path is not None:
            d["path"] = self.path
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GovernanceReason:
        if not isinstance(data, dict):
            raise ValueError(f"GovernanceReason payload must be a dict, got {type(data).__name__}")
        if "code" not in data or "message" not in data:
            raise ValueError("GovernanceReason payload missing required 'code' or 'message' field")
        return cls(
            code=str(data["code"]),
            message=str(data["message"]),
            path=data.get("path"),
        )


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    """Outcome of contract schema and quality validation."""

    valid: bool
    issues: tuple[GovernanceReason, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": [issue.to_dict() for issue in self.issues],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidationOutcome:
        if not isinstance(data, dict) or "valid" not in data:
            raise ValueError("ValidationOutcome payload missing required 'valid' field")
        issues_data = data.get("issues", [])
        if not isinstance(issues_data, (list, tuple)):
            raise ValueError("ValidationOutcome payload 'issues' must be a list")
        return cls(
            valid=bool(data["valid"]),
            issues=tuple(GovernanceReason.from_dict(item) for item in issues_data),
        )


@dataclass(frozen=True, slots=True)
class PolicyOutcome:
    """Outcome of lifecycle policy evaluation."""

    valid: bool
    id_violation: bool = False
    version_violation: bool = False
    retired_violation: bool = False
    violations: tuple[GovernanceReason, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "id_violation": self.id_violation,
            "version_violation": self.version_violation,
            "retired_violation": self.retired_violation,
            "violations": [v.to_dict() for v in self.violations],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolicyOutcome:
        if not isinstance(data, dict) or "valid" not in data:
            raise ValueError("PolicyOutcome payload missing required 'valid' field")
        violations_data = data.get("violations", [])
        if not isinstance(violations_data, (list, tuple)):
            raise ValueError("PolicyOutcome payload 'violations' must be a list")
        return cls(
            valid=bool(data["valid"]),
            id_violation=bool(data.get("id_violation", False)),
            version_violation=bool(data.get("version_violation", False)),
            retired_violation=bool(data.get("retired_violation", False)),
            violations=tuple(GovernanceReason.from_dict(v) for v in violations_data),
        )


@dataclass(frozen=True, slots=True)
class ChangeEvidence:
    """Evidence summarizing contract changes and merge conflicts."""

    has_changes: bool = False
    merge_conflicts_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_changes": self.has_changes,
            "merge_conflicts_count": self.merge_conflicts_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChangeEvidence:
        if not isinstance(data, dict) or "has_changes" not in data:
            raise ValueError("ChangeEvidence payload missing required 'has_changes' field")
        return cls(
            has_changes=bool(data["has_changes"]),
            merge_conflicts_count=int(data.get("merge_conflicts_count", 0)),
        )


@dataclass(frozen=True, slots=True)
class GovernanceDecision:
    """Authoritative, deterministic governance decision for a contract change."""

    decision_id: str
    decision: DecisionResult
    contract_id: str
    breaking: bool
    required_version_bump: RequiredBump
    reasons: tuple[GovernanceReason, ...] = ()
    validation: ValidationOutcome = ValidationOutcome(valid=True)
    policy: PolicyOutcome = PolicyOutcome(valid=True)
    evidence: ChangeEvidence = ChangeEvidence()

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "decision": self.decision.value if isinstance(self.decision, DecisionResult) else str(self.decision),
            "contract_id": self.contract_id,
            "breaking": self.breaking,
            "required_version_bump": self.required_version_bump,
            "reasons": [r.to_dict() for r in self.reasons],
            "validation": self.validation.to_dict(),
            "policy": self.policy.to_dict(),
            "evidence": self.evidence.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GovernanceDecision:
        if not isinstance(data, dict):
            raise ValueError(f"GovernanceDecision payload must be a dict, got {type(data).__name__}")

        required_keys = (
            "decision_id",
            "decision",
            "contract_id",
            "breaking",
            "required_version_bump",
            "validation",
            "policy",
            "evidence",
        )
        for key in required_keys:
            if key not in data:
                raise ValueError(f"GovernanceDecision payload missing required field '{key}'")

        raw_decision = data["decision"]
        try:
            decision_enum = DecisionResult(raw_decision) if isinstance(raw_decision, str) else raw_decision
        except ValueError as exc:
            raise ValueError(f"Invalid DecisionResult value '{raw_decision}'") from exc

        reasons_data = data.get("reasons", [])
        if not isinstance(reasons_data, (list, tuple)):
            raise ValueError("GovernanceDecision payload 'reasons' must be a list")
        reasons = tuple(GovernanceReason.from_dict(r) for r in reasons_data)

        validation = ValidationOutcome.from_dict(data["validation"])
        policy = PolicyOutcome.from_dict(data["policy"])
        evidence = ChangeEvidence.from_dict(data["evidence"])

        bump_val = data["required_version_bump"]
        if bump_val not in ("none", "minor", "major"):
            raise ValueError(f"Invalid required_version_bump value '{bump_val}'")

        return cls(
            decision_id=str(data["decision_id"]),
            decision=decision_enum,
            contract_id=str(data["contract_id"]),
            breaking=bool(data["breaking"]),
            required_version_bump=bump_val,
            reasons=reasons,
            validation=validation,
            policy=policy,
            evidence=evidence,
        )
