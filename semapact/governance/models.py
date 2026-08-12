"""Governance decision and outcome data models for SemaPact using Pydantic v2."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from semapact.core.release import RequiredBump


class DecisionResult(str, Enum):
    """Authoritative governance decision outcome."""

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    REVIEW = "REVIEW"


class GovernanceModel(BaseModel):
    """Shared base for all immutable governance models.

    Enforces frozen=True (immutability) and extra="forbid" (no undeclared fields).
    Subclasses use Field(strict=True) on individual fields where strict type
    coercion is required.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )


class GovernanceReason(GovernanceModel):
    """Structured, machine-readable reason for a governance decision."""

    code: str
    message: str
    path: str | None = None


class ValidationOutcome(GovernanceModel):
    """Outcome of contract schema and quality validation."""

    valid: bool = Field(strict=True)
    issues: tuple[GovernanceReason, ...] = ()


class PolicyOutcome(GovernanceModel):
    """Outcome of lifecycle policy evaluation."""

    valid: bool = Field(strict=True)
    id_violation: bool = Field(default=False, strict=True)
    version_violation: bool = Field(default=False, strict=True)
    retired_violation: bool = Field(default=False, strict=True)
    violations: tuple[GovernanceReason, ...] = ()


class ChangeEvidence(GovernanceModel):
    """Evidence summarizing contract changes and merge conflicts."""

    has_changes: bool = Field(default=False, strict=True)
    merge_conflicts_count: int = Field(default=0, ge=0, strict=True)


class GovernanceDecision(GovernanceModel):
    """Authoritative, deterministic governance decision for a contract change."""

    decision_id: str
    decision: DecisionResult
    contract_id: str
    breaking: bool = Field(strict=True)
    required_version_bump: RequiredBump
    validation: ValidationOutcome
    policy: PolicyOutcome
    evidence: ChangeEvidence
    reasons: tuple[GovernanceReason, ...] = ()

    @model_validator(mode="after")
    def _validate_allow_invariants(self) -> GovernanceDecision:
        if self.decision == DecisionResult.ALLOW:
            if not self.validation.valid:
                raise ValueError("ALLOW decision invariant violation: validation.valid must be True")
            if not self.policy.valid:
                raise ValueError("ALLOW decision invariant violation: policy.valid must be True")
            if self.policy.id_violation:
                raise ValueError("ALLOW decision invariant violation: policy.id_violation must be False")
            if self.policy.version_violation:
                raise ValueError("ALLOW decision invariant violation: policy.version_violation must be False")
            if self.policy.retired_violation:
                raise ValueError("ALLOW decision invariant violation: policy.retired_violation must be False")
            if self.breaking:
                raise ValueError("ALLOW decision invariant violation: breaking must be False")
            if self.required_version_bump != "none":
                raise ValueError(
                    f"ALLOW decision invariant violation: required_version_bump must be 'none', got '{self.required_version_bump}'"
                )
            if self.evidence.merge_conflicts_count != 0:
                raise ValueError(
                    f"ALLOW decision invariant violation: evidence.merge_conflicts_count must be 0, got {self.evidence.merge_conflicts_count}"
                )
        return self
