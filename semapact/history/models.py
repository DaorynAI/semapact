"""Immutable history-owned audit models.

These models record cross-artifact audit relationships without redefining the
canonical domain artifacts they connect.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from semapact.contractops.execution_models import ContractRelease
from semapact.contractops.models import ReviewEvidenceAction, VersionAuthority
from semapact.observation import ObservedPlatformState
from semapact.reconciliation import (
    ReconciliationResult,
    RuntimeDriftStatus,
    classify_reconciliation_status,
)
from semapact.versioning import ActualVersionBump, RequiredBump


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
        return _optional_text(value)

    @model_validator(mode="after")
    def _validate_provenance_pairs(self) -> ReleaseRecord:
        if self.version_authority is VersionAuthority.GIT:
            if self.authority_reference is None:
                raise ValueError("git release history requires authority_reference")
        elif self.authority_reference is not None:
            raise ValueError(
                "SemaPact release history must not contain authority_reference"
            )

        has_reference = self.review_evidence_reference is not None
        has_action = self.review_evidence_action is not None
        if has_reference != has_action:
            raise ValueError(
                "review evidence reference and action must either both be present or both be absent"
            )
        return self


# Backward-compatible persistence name. Canonical ownership lives in ContractOps.
ContractReleaseRecord = ContractRelease
class DeploymentStatus(str, Enum):
    """Terminal provider-execution outcome for one deployment occurrence."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class DeploymentRecord(HistoryModel):
    """Immutable audit record for one completed deployment execution occurrence.

    This records provider execution only. ``SUCCEEDED`` never implies runtime
    convergence; reconciliation remains a separate observation/history concern.
    """

    deployment_record_id: str
    release_record_id: str
    deployment_plan_id: str
    deployment_preview_id: str
    deployment_authorization_id: str
    platform: str
    runtime_target: str
    source_reference: str
    status: DeploymentStatus
    started_at: datetime
    completed_at: datetime
    actor_reference: str | None = None
    external_reference: str | None = None

    @field_validator(
        "deployment_record_id",
        "release_record_id",
        "deployment_plan_id",
        "deployment_preview_id",
        "deployment_authorization_id",
        "runtime_target",
        "source_reference",
    )
    @classmethod
    def _require_deployment_text(cls, value: str) -> str:
        return _required_text(value)

    @field_validator("platform")
    @classmethod
    def _normalize_platform(cls, value: str) -> str:
        return _required_text(value).casefold()

    @field_validator("actor_reference", "external_reference")
    @classmethod
    def _normalize_optional_deployment_text(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @field_validator("started_at", "completed_at")
    @classmethod
    def _normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("deployment timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_timestamp_order(self) -> DeploymentRecord:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not be earlier than started_at")
        return self


class RuntimeObservationRecord(HistoryModel):
    """Content-addressed history envelope around canonical M1 runtime evidence."""

    observation_record_id: str
    observation: ObservedPlatformState

    @field_validator("observation_record_id")
    @classmethod
    def _require_observation_id(cls, value: str) -> str:
        return _required_text(value)


class RuntimeReconciliationRecord(HistoryModel):
    """Immutable linkage from canonical runtime evidence to optional lifecycle context.

    ``result`` remains the canonical M1 ReconciliationResult. This record adds only
    durable identity, point-in-time classification, and optional exact history links.
    """

    runtime_reconciliation_record_id: str
    observation_record_id: str
    result: ReconciliationResult
    status: RuntimeDriftStatus
    release_record_id: str | None = None
    deployment_record_id: str | None = None

    @field_validator(
        "runtime_reconciliation_record_id",
        "observation_record_id",
    )
    @classmethod
    def _require_runtime_history_text(cls, value: str) -> str:
        return _required_text(value)

    @field_validator("release_record_id", "deployment_record_id")
    @classmethod
    def _normalize_runtime_links(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @model_validator(mode="after")
    def _validate_runtime_history_semantics(self) -> RuntimeReconciliationRecord:
        expected_status = classify_reconciliation_status(self.result)
        if self.status is not expected_status:
            raise ValueError(
                "runtime reconciliation status does not match canonical classification"
            )
        if self.deployment_record_id is not None and self.release_record_id is None:
            raise ValueError(
                "deployment-linked runtime history requires release_record_id"
            )
        return self


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
