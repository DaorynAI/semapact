from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from semapact.application.services.deployment_history import DeploymentHistoryService
from semapact.contractops import VersionAuthority
from semapact.deployment import (
    DeploymentAuthorization,
    DeploymentPlan,
    DeploymentPreview,
    DeploymentTarget,
)
from semapact.deployment.models import (
    compute_deployment_authorization_id,
    compute_deployment_plan_id,
    compute_deployment_preview_id,
)
from semapact.history import (
    DeploymentStatus,
    HistoryCorruptionError,
    ReleaseRecord,
)
from semapact.history.integrity import compute_release_record_id
from semapact.platforms.git import GitWorkingTreeHistoryRepository


def _release_record() -> ReleaseRecord:
    fields = {
        "contract_id": "orders-product",
        "contract_version": "1.3.0",
        "decision_id": "decision-1",
        "change_set_id": "changeset-1",
        "release_plan_id": "release-plan-1",
        "version_resolution_id": "version-resolution-1",
        "authorization_id": "apply-authorization-1",
        "applied_release_id": "applied-release-1",
        "released_revision_id": "released-revision-1",
        "required_version_bump": "minor",
        "actual_version_bump": "minor",
        "version_authority": VersionAuthority.SEMAPACT,
        "authority_reference": None,
        "review_evidence_reference": None,
        "review_evidence_action": None,
    }
    release_record_id = compute_release_record_id(
        **{
            **fields,
            "version_authority": fields["version_authority"].value,
        }
    )
    return ReleaseRecord(release_record_id=release_record_id, **fields)


def _deployment_artifacts(*, preview_runtime_target: str = "catalog.schema", allowed: bool = True):
    target = DeploymentTarget(
        platform="databricks",
        runtime_target="catalog.schema",
        source_reference="workspace:test",
    )
    plan_id = compute_deployment_plan_id(
        applied_release_id="applied-release-1",
        contract_id="orders-product",
        release_plan_id="release-plan-1",
        released_revision_ref="candidate-revision-1",
        selected_version="1.3.0",
        target=target,
        actions=(),
    )
    plan = DeploymentPlan(
        deployment_plan_id=plan_id,
        applied_release_id="applied-release-1",
        contract_id="orders-product",
        release_plan_id="release-plan-1",
        released_revision_ref="candidate-revision-1",
        selected_version="1.3.0",
        target=target,
        actions=(),
    )

    preview_id = compute_deployment_preview_id(
        deployment_plan_id=plan.deployment_plan_id,
        platform="databricks",
        runtime_target=preview_runtime_target,
        source_identifier="workspace:test",
        observation_fingerprint="observation-1",
        operations=(),
    )
    preview = DeploymentPreview(
        deployment_preview_id=preview_id,
        deployment_plan_id=plan.deployment_plan_id,
        platform="databricks",
        runtime_target=preview_runtime_target,
        source_identifier="workspace:test",
        observation_fingerprint="observation-1",
        operations=(),
    )

    authorization_id = compute_deployment_authorization_id(
        contract_ops_authorization_id="deploy-authorization-1",
        deployment_plan_id=plan.deployment_plan_id,
        applied_release_id=plan.applied_release_id,
        allowed=allowed,
    )
    authorization = DeploymentAuthorization(
        deployment_authorization_id=authorization_id,
        contract_ops_authorization_id="deploy-authorization-1",
        deployment_plan_id=plan.deployment_plan_id,
        applied_release_id=plan.applied_release_id,
        allowed=allowed,
    )
    return plan, preview, authorization


def _service(tmp_path: Path):
    backend = GitWorkingTreeHistoryRepository(tmp_path)
    backend.put_release_record(_release_record())
    service = DeploymentHistoryService(
        releases=backend,
        deployment_plans=backend,
        deployment_previews=backend,
        deployment_authorizations=backend,
        deployment_records=backend,
    )
    return service, backend


def test_records_terminal_deployment_occurrence(tmp_path: Path) -> None:
    service, backend = _service(tmp_path)
    plan, preview, authorization = _deployment_artifacts()
    started = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    completed = started + timedelta(seconds=12)

    record = service.record_execution(
        plan=plan,
        preview=preview,
        authorization=authorization,
        status=DeploymentStatus.SUCCEEDED,
        started_at=started,
        completed_at=completed,
        actor_reference="agent:deploy",
        external_reference="pipeline:42",
    )

    assert backend.get_deployment_plan(plan.deployment_plan_id) == plan
    assert backend.get_deployment_preview(preview.deployment_preview_id) == preview
    assert (
        backend.get_deployment_authorization(authorization.deployment_authorization_id)
        == authorization
    )
    assert backend.get_deployment_record(record.deployment_record_id) == record
    assert backend.list_deployment_records_for_release(record.release_record_id) == (
        record,
    )
    assert backend.list_deployment_records_for_plan(plan.deployment_plan_id) == (record,)
    assert record.platform == "databricks"
    assert record.runtime_target == "catalog.schema"
    assert record.source_reference == "workspace:test"
    assert record.status is DeploymentStatus.SUCCEEDED


def test_exact_deployment_history_write_is_idempotent(tmp_path: Path) -> None:
    service, backend = _service(tmp_path)
    plan, preview, authorization = _deployment_artifacts()
    started = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    completed = started + timedelta(seconds=1)

    first = service.record_execution(
        plan=plan,
        preview=preview,
        authorization=authorization,
        status=DeploymentStatus.SUCCEEDED,
        started_at=started,
        completed_at=completed,
    )
    second = service.record_execution(
        plan=plan,
        preview=preview,
        authorization=authorization,
        status=DeploymentStatus.SUCCEEDED,
        started_at=started,
        completed_at=completed,
    )

    assert second == first
    assert backend.list_deployment_records_for_plan(plan.deployment_plan_id) == (first,)


def test_failed_attempt_remains_after_later_success(tmp_path: Path) -> None:
    service, backend = _service(tmp_path)
    plan, preview, authorization = _deployment_artifacts()
    started = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)

    failed = service.record_execution(
        plan=plan,
        preview=preview,
        authorization=authorization,
        status=DeploymentStatus.FAILED,
        started_at=started,
        completed_at=started + timedelta(seconds=2),
        external_reference="pipeline:42",
    )
    succeeded = service.record_execution(
        plan=plan,
        preview=preview,
        authorization=authorization,
        status=DeploymentStatus.SUCCEEDED,
        started_at=started + timedelta(minutes=5),
        completed_at=started + timedelta(minutes=5, seconds=3),
        external_reference="pipeline:43",
    )

    records = backend.list_deployment_records_for_plan(plan.deployment_plan_id)
    assert set(records) == {failed, succeeded}
    assert {record.status for record in records} == {
        DeploymentStatus.FAILED,
        DeploymentStatus.SUCCEEDED,
    }


def test_rejects_preview_for_different_runtime_target(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    plan, preview, authorization = _deployment_artifacts(
        preview_runtime_target="other.schema"
    )

    with pytest.raises(ValueError, match="runtime target"):
        service.record_execution(
            plan=plan,
            preview=preview,
            authorization=authorization,
            status=DeploymentStatus.FAILED,
            started_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
            completed_at=datetime(2026, 9, 13, 0, 0, 1, tzinfo=timezone.utc),
        )


def test_rejects_denied_deployment_authorization(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    plan, preview, authorization = _deployment_artifacts(allowed=False)

    with pytest.raises(ValueError, match="allowed"):
        service.record_execution(
            plan=plan,
            preview=preview,
            authorization=authorization,
            status=DeploymentStatus.FAILED,
            started_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
            completed_at=datetime(2026, 9, 13, 0, 0, 1, tzinfo=timezone.utc),
        )


def test_rejects_naive_execution_timestamps(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    plan, preview, authorization = _deployment_artifacts()

    with pytest.raises(ValueError, match="timezone-aware"):
        service.record_execution(
            plan=plan,
            preview=preview,
            authorization=authorization,
            status=DeploymentStatus.SUCCEEDED,
            started_at=datetime(2026, 9, 13),
            completed_at=datetime(2026, 9, 13, 0, 0, 1),
        )


def test_tampered_deployment_record_identity_fails_closed(tmp_path: Path) -> None:
    service, backend = _service(tmp_path)
    plan, preview, authorization = _deployment_artifacts()
    started = datetime(2026, 9, 13, tzinfo=timezone.utc)
    record = service.record_execution(
        plan=plan,
        preview=preview,
        authorization=authorization,
        status=DeploymentStatus.SUCCEEDED,
        started_at=started,
        completed_at=started + timedelta(seconds=1),
    )

    tampered = record.model_copy(update={"status": DeploymentStatus.FAILED})
    with pytest.raises(HistoryCorruptionError, match="invalid"):
        backend.put_deployment_record(tampered)
