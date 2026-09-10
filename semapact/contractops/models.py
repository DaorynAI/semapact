"""Immutable ContractOps domain models."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from semapact.change_context import ChangeContext
from semapact.governance.gate import GovernanceOperation
from semapact.lifecycle.changes import GovernanceChange
from semapact.versioning import ActualVersionBump, RequiredBump


class ContractOpsModel(BaseModel):
    """Shared immutable base for M2 ContractOps domain models."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ChangeSet(ContractOpsModel):
    """Deterministic proposal over exact governed contract revisions.

    Revision references are opaque workflow-owned identifiers. They intentionally do
    not assume Git SHAs, storage versions, or ODCS semantic versions.
    """

    change_set_id: str
    contract_id: str
    base_revision_ref: str
    candidate_revision_ref: str
    changes: tuple[GovernanceChange, ...]
    context: ChangeContext
    source: str | None = None
    actor_reference: str | None = None

    @field_validator(
        "change_set_id",
        "contract_id",
        "base_revision_ref",
        "candidate_revision_ref",
    )
    @classmethod
    def _require_non_empty_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned

    @field_validator("source", "actor_reference")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ReleasePrecondition(str, Enum):
    """Explicit prerequisite that must be satisfied before release publication."""

    REVIEW_AUTHORIZATION_REQUIRED = "REVIEW_AUTHORIZATION_REQUIRED"


class ReleasePlan(ContractOpsModel):
    """Pure plan for releasing the exact candidate revision from a ChangeSet."""

    release_plan_id: str
    contract_id: str
    change_set_id: str
    decision_id: str
    release_revision_ref: str
    required_version_bump: RequiredBump
    preconditions: tuple[ReleasePrecondition, ...] = ()

    @field_validator(
        "release_plan_id",
        "contract_id",
        "change_set_id",
        "decision_id",
        "release_revision_ref",
    )
    @classmethod
    def _require_release_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned


class VersionAuthority(str, Enum):
    """Authority that selects the actual released ODCS semantic version."""

    SEMAPACT = "semapact"
    GIT = "git"


class VersionAuthorityConfig(ContractOpsModel):
    """Typed configuration for resolving one ReleasePlan version."""

    authority: VersionAuthority = VersionAuthority.SEMAPACT
    tag_pattern: str | None = None

    @field_validator("tag_pattern")
    @classmethod
    def _normalize_tag_pattern(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def _validate_authority_configuration(self) -> VersionAuthorityConfig:
        if self.authority is VersionAuthority.GIT and self.tag_pattern is None:
            raise ValueError("git version authority requires tag_pattern")
        if self.authority is VersionAuthority.SEMAPACT and self.tag_pattern is not None:
            raise ValueError("tag_pattern is only valid for git version authority")
        return self


class VersionResolution(ContractOpsModel):
    """Pure resolution of the actual release version for one ReleasePlan."""

    version_resolution_id: str
    release_plan_id: str
    contract_id: str
    release_revision_ref: str
    authority: VersionAuthority
    current_version: str
    required_version_bump: RequiredBump
    selected_version: str
    actual_bump: ActualVersionBump
    authority_reference: str | None = None

    @field_validator(
        "version_resolution_id",
        "release_plan_id",
        "contract_id",
        "release_revision_ref",
        "current_version",
        "selected_version",
    )
    @classmethod
    def _require_version_resolution_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned

    @field_validator("authority_reference")
    @classmethod
    def _normalize_authority_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def _validate_authority_reference(self) -> VersionResolution:
        if self.authority is VersionAuthority.GIT and self.authority_reference is None:
            raise ValueError("git version resolution requires authority_reference")
        if (
            self.authority is VersionAuthority.SEMAPACT
            and self.authority_reference is not None
        ):
            raise ValueError(
                "SemaPact version resolution must not contain authority_reference"
            )
        return self


class ReviewEvidenceAction(str, Enum):
    """Explicit review outcome consumed by ContractOps authorization."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class ReviewAuthorizationEvidence(ContractOpsModel):
    """Opaque review evidence projected onto one exact version-resolved action.

    ``scope_reference`` is optional downstream scope provenance. ContractOps preserves
    but does not interpret it. For example, deployment review can bind the evidence
    to an exact ``DeploymentPlan`` without making ContractOps depend on deployment.
    """

    evidence_reference: str
    decision_id: str
    change_set_id: str
    release_plan_id: str
    version_resolution_id: str
    operation: GovernanceOperation
    action: ReviewEvidenceAction
    scope_reference: str | None = None

    @field_validator(
        "evidence_reference",
        "decision_id",
        "change_set_id",
        "release_plan_id",
        "version_resolution_id",
    )
    @classmethod
    def _require_review_evidence_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned

    @field_validator("scope_reference")
    @classmethod
    def _normalize_scope_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class AuthorizationReason(str, Enum):
    """Machine-readable outcome of ContractOps authorization composition."""

    ALLOWED_BY_GOVERNANCE = "allowed_by_governance"
    ALLOWED_BY_REVIEW = "allowed_by_review"
    BLOCKED_BY_GOVERNANCE = "blocked_by_governance"
    REVIEW_AUTHORIZATION_REQUIRED = "review_authorization_required"
    REVIEW_AUTHORIZATION_REJECTED = "review_authorization_rejected"
    REVIEW_AUTHORIZATION_MISMATCH = "review_authorization_mismatch"


class ContractOpsAuthorization(ContractOpsModel):
    """Authoritative authorization result for one exact ContractOps operation."""

    authorization_id: str
    decision_id: str
    change_set_id: str
    release_plan_id: str
    version_resolution_id: str
    operation: GovernanceOperation
    allowed: bool = Field(strict=True)
    reason: AuthorizationReason
    evidence_reference: str | None = None
    evidence_action: ReviewEvidenceAction | None = None
    scope_reference: str | None = None

    @field_validator(
        "authorization_id",
        "decision_id",
        "change_set_id",
        "release_plan_id",
        "version_resolution_id",
    )
    @classmethod
    def _require_authorization_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned

    @field_validator("evidence_reference", "scope_reference")
    @classmethod
    def _normalize_optional_authorization_reference(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def _validate_authorization_invariants(self) -> ContractOpsAuthorization:
        allowed_reasons = {
            AuthorizationReason.ALLOWED_BY_GOVERNANCE,
            AuthorizationReason.ALLOWED_BY_REVIEW,
        }
        if self.allowed != (self.reason in allowed_reasons):
            raise ValueError("ContractOpsAuthorization allowed/reason invariant violation")

        evidence_reasons = {
            AuthorizationReason.ALLOWED_BY_REVIEW,
            AuthorizationReason.REVIEW_AUTHORIZATION_REJECTED,
            AuthorizationReason.REVIEW_AUTHORIZATION_MISMATCH,
        }
        if self.reason in evidence_reasons:
            if self.evidence_reference is None or self.evidence_action is None:
                raise ValueError(
                    "ContractOpsAuthorization evidence reason requires evidence provenance"
                )
        elif (
            self.evidence_reference is not None
            or self.evidence_action is not None
            or self.scope_reference is not None
        ):
            raise ValueError(
                "ContractOpsAuthorization non-evidence reason must not contain evidence provenance"
            )

        if (
            self.reason is AuthorizationReason.ALLOWED_BY_REVIEW
            and self.evidence_action is not ReviewEvidenceAction.APPROVE
        ):
            raise ValueError("Allowed review authorization requires APPROVE evidence")
        if (
            self.reason is AuthorizationReason.REVIEW_AUTHORIZATION_REJECTED
            and self.evidence_action is ReviewEvidenceAction.APPROVE
        ):
            raise ValueError("Rejected review authorization cannot contain APPROVE evidence")
        return self
