"""Immutable history-owned audit models.

These models record cross-artifact audit relationships without redefining the
canonical domain artifacts they connect.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from semapact.contractops.models import ReviewEvidenceAction, VersionAuthority
from semapact.versioning import ActualVersionBump, RequiredBump


class HistoryModel(BaseModel):
    """Shared immutable base for history-owned logical records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ChangeSetDecisionLink(HistoryModel):
    """Audit provenance linking one ChangeSet to one GovernanceDecision outcome."""

    change_set_id: str
    decision_id: str

    @field_validator("change_set_id", "decision_id")
    @classmethod
    def _require_non_empty_text(cls, value: str) -> str:
        return _required_text(value)


class ReleaseRecord(HistoryModel):
    """Durable audit projection for one finalized governed contract release.

    Canonical ContractOps artifacts remain authoritative for planning, versioning,
    authorization, and APPLY semantics. This record freezes the stable links and
    final facts required to reconstruct one released semantic version.
    """

    release_record_id: str
    contract_id: str
    contract_version: str
    decision_id: str
    change_set_id: str
    release_plan_id: str
    version_resolution_id: str
    authorization_id: str
    applied_release_id: str
    released_revision_id: str
    required_version_bump: RequiredBump
    actual_version_bump: ActualVersionBump
    version_authority: VersionAuthority
    authority_reference: str | None = None
    review_evidence_reference: str | None = None
    review_evidence_action: ReviewEvidenceAction | None = None

    @field_validator(
        "release_record_id",
        "contract_id",
        "contract_version",
        "decision_id",
        "change_set_id",
        "release_plan_id",
        "version_resolution_id",
        "authorization_id",
        "applied_release_id",
        "released_revision_id",
    )
    @classmethod
    def _require_release_text(cls, value: str) -> str:
        return _required_text(value)

    @field_validator(
        "authority_reference",
        "review_evidence_reference",
    )
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


def _required_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("history identifiers must be strings")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("history identifiers must not be empty")
    return cleaned
