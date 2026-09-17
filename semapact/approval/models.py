"""Immutable domain model for one explicit governance review action."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, field_validator

from semapact.contractops.models import ReviewEvidenceAction
from semapact.governance.gate import GovernanceOperation


class ApprovalRecord(BaseModel):
    """One immutable review action bound to an exact ContractOps context.

    The record is audit evidence only. It does not reinterpret GovernanceDecision
    and does not authorize an operation until explicitly projected into the existing
    M2 ReviewAuthorizationEvidence contract.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    approval_id: str
    decision_id: str
    change_set_id: str
    release_plan_id: str
    version_resolution_id: str
    operation: GovernanceOperation
    action: ReviewEvidenceAction
    actor_reference: str
    recorded_at: datetime
    scope_reference: str | None = None
    capability_reference: str | None = None
    comment: str | None = None
    evidence_references: tuple[str, ...] = ()

    @field_validator(
        "approval_id",
        "decision_id",
        "change_set_id",
        "release_plan_id",
        "version_resolution_id",
        "actor_reference",
    )
    @classmethod
    def _require_text(cls, value: str) -> str:
        return _required_text(value)

    @field_validator("scope_reference", "capability_reference", "comment")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @field_validator("recorded_at")
    @classmethod
    def _normalize_recorded_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_validator("evidence_references")
    @classmethod
    def _normalize_evidence_references(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        return tuple(sorted({_required_text(item) for item in value}))


def _required_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("value must be str")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("value must not be empty")
    return cleaned


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("value must be str or None")
    cleaned = value.strip()
    return cleaned or None
