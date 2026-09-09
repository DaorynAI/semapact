"""Immutable ContractOps domain models."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator

from semapact.change_context import ChangeContext
from semapact.core.release import RequiredBump
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
