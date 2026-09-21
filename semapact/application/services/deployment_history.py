"""Application orchestration for terminal deployment execution history."""

from __future__ import annotations

from datetime import datetime, timezone

from semapact.deployment import DeploymentAuthorization, DeploymentPlan, DeploymentPreview
from semapact.deployment.models import (
    validate_deployment_authorization_identity,
    validate_deployment_plan_identity,
    validate_deployment_preview_identity,
)
from semapact.history import (
    DeploymentAuthorizationHistoryRepository,
    DeploymentPlanHistoryRepository,
    DeploymentPreviewHistoryRepository,
    DeploymentRecord,
    DeploymentRecordHistoryRepository,
    DeploymentStatus,
    ReleaseRecord,
    ReleaseRecordHistoryRepository,
)
from semapact.history.integrity import compute_deployment_record_id


class DeploymentHistoryService:
    """Record already-observed provider execution outcomes without executing them."""

    def __init__(
        self,
        *,
        releases: ReleaseRecordHistoryRepository,
        deployment_plans: DeploymentPlanHistoryRepository,
        deployment_previews: DeploymentPreviewHistoryRepository,
        deployment_authorizations: DeploymentAuthorizationHistoryRepository,
        deployment_records: DeploymentRecordHistoryRepository,
    ) -> None:
        self._releases = releases
        self._deployment_plans = deployment_plans
        self._deployment_previews = deployment_previews
        self._deployment_authorizations = deployment_authorizations
        self._deployment_records = deployment_records

    def record_execution(
        self,
        *,
        plan: DeploymentPlan,
        preview: DeploymentPreview,
        authorization: DeploymentAuthorization,
        status: DeploymentStatus,
        started_at: datetime,
        completed_at: datetime,
        actor_reference: str | None = None,
        external_reference: str | None = None,
    ) -> DeploymentRecord:
        """Persist one terminal execution occurrence against exact deployment artifacts.

        The caller supplies the outcome after the provider execution boundary has
        completed. This method never invokes a DeploymentAdapter and never infers
        runtime convergence from execution success.
        """
        _validate_types(plan, preview, authorization, status)
        validate_deployment_plan_identity(plan)
        validate_deployment_preview_identity(preview)
        validate_deployment_authorization_identity(authorization)

        release = self._releases.get_release_record_by_version(
            plan.contract_id,
            plan.contract_version,
        )
        _validate_release_link(release, plan)
        _validate_preview_link(preview, plan)
        _validate_authorization_link(authorization, plan)

        started = _utc_timestamp(started_at, "started_at")
        completed = _utc_timestamp(completed_at, "completed_at")
        if completed < started:
            raise ValueError("completed_at must not be earlier than started_at")

        actor = _optional_text(actor_reference)
        external = _optional_text(external_reference)
        deployment_record_id = compute_deployment_record_id(
            release_record_id=release.release_record_id,
            deployment_plan_id=plan.deployment_plan_id,
            deployment_preview_id=preview.deployment_preview_id,
            deployment_authorization_id=authorization.deployment_authorization_id,
            platform=plan.target.platform,
            runtime_target=plan.target.runtime_target,
            source_reference=plan.target.source_reference,
            status=status.value,
            started_at=started.isoformat(),
            completed_at=completed.isoformat(),
            actor_reference=actor,
            external_reference=external,
        )
        record = DeploymentRecord(
            deployment_record_id=deployment_record_id,
            release_record_id=release.release_record_id,
            deployment_plan_id=plan.deployment_plan_id,
            deployment_preview_id=preview.deployment_preview_id,
            deployment_authorization_id=authorization.deployment_authorization_id,
            platform=plan.target.platform,
            runtime_target=plan.target.runtime_target,
            source_reference=plan.target.source_reference,
            status=status,
            started_at=started,
            completed_at=completed,
            actor_reference=actor,
            external_reference=external,
        )

        # Persist exact referenced artifacts before the occurrence record so a
        # partial failure cannot leave history pointing at absent dependencies.
        self._deployment_plans.put_deployment_plan(plan)
        self._deployment_previews.put_deployment_preview(preview)
        self._deployment_authorizations.put_deployment_authorization(authorization)
        self._deployment_records.put_deployment_record(record)
        return record


def _validate_types(
    plan: DeploymentPlan,
    preview: DeploymentPreview,
    authorization: DeploymentAuthorization,
    status: DeploymentStatus,
) -> None:
    expected = (
        (plan, DeploymentPlan, "plan"),
        (preview, DeploymentPreview, "preview"),
        (authorization, DeploymentAuthorization, "authorization"),
        (status, DeploymentStatus, "status"),
    )
    for value, expected_type, name in expected:
        if not isinstance(value, expected_type):
            raise TypeError(
                f"{name} must be {expected_type.__name__}, got {type(value).__name__}"
            )


def _validate_release_link(release: ReleaseRecord, plan: DeploymentPlan) -> None:
    if (
        release.contract_id != plan.contract_id
        or release.contract_version != plan.contract_version
        or release.applied_release_id != plan.source_snapshot_id
    ):
        raise ValueError("DeploymentPlan does not match the finalized ReleaseRecord")


def _validate_preview_link(preview: DeploymentPreview, plan: DeploymentPlan) -> None:
    if preview.deployment_plan_id != plan.deployment_plan_id:
        raise ValueError("DeploymentPreview does not reference the supplied DeploymentPlan")
    if preview.platform.strip().casefold() != plan.target.platform:
        raise ValueError("DeploymentPreview platform does not match DeploymentPlan target")
    if preview.runtime_target != plan.target.runtime_target:
        raise ValueError("DeploymentPreview runtime target does not match DeploymentPlan")
    if preview.source_identifier != plan.target.source_reference:
        raise ValueError("DeploymentPreview source does not match DeploymentPlan source reference")


def _validate_authorization_link(
    authorization: DeploymentAuthorization,
    plan: DeploymentPlan,
) -> None:
    if authorization.deployment_plan_id != plan.deployment_plan_id:
        raise ValueError(
            "DeploymentAuthorization does not reference the supplied DeploymentPlan"
        )
    if authorization.source_snapshot_id != plan.source_snapshot_id:
        raise ValueError(
            "DeploymentAuthorization does not reference the plan source snapshot"
        )
    if not authorization.allowed:
        raise ValueError("deployment history requires an allowed DeploymentAuthorization")


def _utc_timestamp(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("optional deployment references must be strings")
    cleaned = value.strip()
    return cleaned or None
