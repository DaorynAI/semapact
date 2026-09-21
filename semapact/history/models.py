"""Immutable history-owned audit models.

These models record cross-artifact audit relationships without redefining the
canonical domain artifacts they connect.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator



class HistoryModel(BaseModel):
    """Shared immutable base for history-owned logical records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class HistoryIntegrityIssueCode(str, Enum):
    """Stable diagnostics emitted by a physical history backend integrity scan."""

    CHECKSUM_MISSING = "CHECKSUM_MISSING"
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
    CHECKSUM_INVALID = "CHECKSUM_INVALID"
    ORPHAN_CHECKSUM = "ORPHAN_CHECKSUM"
    ARTIFACT_INVALID = "ARTIFACT_INVALID"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    PATH_PROVENANCE_MISMATCH = "PATH_PROVENANCE_MISMATCH"
    UNKNOWN_ARTIFACT_LAYOUT = "UNKNOWN_ARTIFACT_LAYOUT"


class HistoryStorageIntegrityIssue(HistoryModel):
    """One deterministic storage-integrity diagnostic without mutating history."""

    code: HistoryIntegrityIssueCode
    artifact_kind: str
    storage_reference: str
    artifact_id: str | None = None
    detail: str

    @field_validator("artifact_kind", "storage_reference", "detail")
    @classmethod
    def _require_integrity_text(cls, value: str) -> str:
        return _required_text(value)

    @field_validator("artifact_id")
    @classmethod
    def _normalize_integrity_artifact_id(cls, value: str | None) -> str | None:
        return _optional_text(value)


class ChangeSetDecisionLink(HistoryModel):
    """Audit provenance linking one ChangeSet to one GovernanceDecision outcome."""

    change_set_id: str
    decision_id: str

    @field_validator("change_set_id", "decision_id")
    @classmethod
    def _require_non_empty_text(cls, value: str) -> str:
        return _required_text(value)


def _required_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("history identifiers must be strings")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("history identifiers must not be empty")
    return cleaned


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("optional history references must be strings")
    cleaned = value.strip()
    return cleaned or None
