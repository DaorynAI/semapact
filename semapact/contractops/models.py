"""Immutable ContractOps domain models."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from semapact.change_context import ChangeContext
from semapact.core.release import ActualVersionBump, RequiredBump
from semapact.lifecycle.changes import GovernanceChange


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
