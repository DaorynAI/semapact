"""High-frequency operational deployment history boundary.

Operational history is optional telemetry. It is deliberately separate from the
Git-friendly governance ledger because deployment/reconciliation events can be
high-volume in CI/CD environments.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from semapact.reconciliation import RuntimeDriftStatus
from semapact.utils.deterministic import deterministic_uuid5


SEMAPACT_OPERATIONAL_DEPLOYMENT_NAMESPACE = uuid.UUID(
    "9c0c69eb-6294-48d3-93b7-0959a122168e"
)


class OperationalDeploymentEvent(BaseModel):
    """One immutable deployment occurrence for optional operational persistence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    bundle_digest: str
    release: bool
    release_record_id: str | None = None
    contract_id: str
    contract_version: str
    revision_ref: str
    deployment_plan_id: str
    deployment_preview_id: str | None = None
    deployment_authorization_id: str | None = None
    platform: str
    runtime_target: str
    source_reference: str
    status: Literal["SUCCEEDED", "FAILED"]
    reconciliation_status: RuntimeDriftStatus | None = None
    started_at: datetime
    completed_at: datetime
    error_message: str | None = None

    @field_validator(
        "event_id",
        "bundle_digest",
        "contract_id",
        "contract_version",
        "revision_ref",
        "deployment_plan_id",
        "platform",
        "runtime_target",
        "source_reference",
    )
    @classmethod
    def _require_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned

    @field_validator(
        "release_record_id",
        "deployment_preview_id",
        "deployment_authorization_id",
        "error_message",
    )
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("platform")
    @classmethod
    def _normalize_platform(cls, value: str) -> str:
        return value.strip().casefold()

    @field_validator("started_at", "completed_at")
    @classmethod
    def _normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("operational history timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_event(self) -> "OperationalDeploymentEvent":
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not be earlier than started_at")
        if self.status == "SUCCEEDED" and self.error_message is not None:
            raise ValueError("Successful deployment event must not contain error_message")
        if self.status == "FAILED" and self.error_message is None:
            raise ValueError("Failed deployment event requires error_message")
        expected = compute_operational_deployment_event_id(
            bundle_digest=self.bundle_digest,
            release=self.release,
            release_record_id=self.release_record_id,
            contract_id=self.contract_id,
            contract_version=self.contract_version,
            revision_ref=self.revision_ref,
            deployment_plan_id=self.deployment_plan_id,
            deployment_preview_id=self.deployment_preview_id,
            deployment_authorization_id=self.deployment_authorization_id,
            platform=self.platform,
            runtime_target=self.runtime_target,
            source_reference=self.source_reference,
            status=self.status,
            reconciliation_status=(
                self.reconciliation_status.value
                if self.reconciliation_status is not None
                else None
            ),
            started_at=self.started_at.isoformat(),
            completed_at=self.completed_at.isoformat(),
            error_message=self.error_message,
        )
        if self.event_id != expected:
            raise ValueError(
                "OperationalDeploymentEvent deterministic identity does not match content"
            )
        return self


class OperationalHistorySink(Protocol):
    """Storage-neutral sink for optional high-frequency deployment telemetry."""

    def record_deployment(self, event: OperationalDeploymentEvent) -> None: ...


def build_operational_deployment_event(
    *,
    bundle_digest: str,
    release: bool,
    release_record_id: str | None,
    contract_id: str,
    contract_version: str,
    revision_ref: str,
    deployment_plan_id: str,
    deployment_preview_id: str | None,
    deployment_authorization_id: str | None,
    platform: str,
    runtime_target: str,
    source_reference: str,
    status: Literal["SUCCEEDED", "FAILED"],
    reconciliation_status: RuntimeDriftStatus | None,
    started_at: datetime,
    completed_at: datetime,
    error_message: str | None,
) -> OperationalDeploymentEvent:
    normalized_platform = platform.strip().casefold()
    event_id = compute_operational_deployment_event_id(
        bundle_digest=bundle_digest,
        release=release,
        release_record_id=release_record_id,
        contract_id=contract_id,
        contract_version=contract_version,
        revision_ref=revision_ref,
        deployment_plan_id=deployment_plan_id,
        deployment_preview_id=deployment_preview_id,
        deployment_authorization_id=deployment_authorization_id,
        platform=normalized_platform,
        runtime_target=runtime_target,
        source_reference=source_reference,
        status=status,
        reconciliation_status=(
            reconciliation_status.value if reconciliation_status is not None else None
        ),
        started_at=started_at.astimezone(timezone.utc).isoformat(),
        completed_at=completed_at.astimezone(timezone.utc).isoformat(),
        error_message=error_message,
    )
    return OperationalDeploymentEvent(
        event_id=event_id,
        bundle_digest=bundle_digest,
        release=release,
        release_record_id=release_record_id,
        contract_id=contract_id,
        contract_version=contract_version,
        revision_ref=revision_ref,
        deployment_plan_id=deployment_plan_id,
        deployment_preview_id=deployment_preview_id,
        deployment_authorization_id=deployment_authorization_id,
        platform=normalized_platform,
        runtime_target=runtime_target,
        source_reference=source_reference,
        status=status,
        reconciliation_status=reconciliation_status,
        started_at=started_at,
        completed_at=completed_at,
        error_message=error_message,
    )


def compute_operational_deployment_event_id(**payload: object) -> str:
    return deterministic_uuid5(SEMAPACT_OPERATIONAL_DEPLOYMENT_NAMESPACE, payload)
