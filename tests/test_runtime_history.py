from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from semapact.application.services.runtime_history import RuntimeHistoryService
from semapact.contractops import VersionAuthority
from semapact.history import DeploymentRecord, DeploymentStatus, ReleaseRecord
from semapact.history.integrity import compute_deployment_record_id, compute_release_record_id
from semapact.observation import (
    ObservedAsset,
    ObservedAssetIdentity,
    ObservedPlatformState,
    fingerprint_observed_state,
    with_observed_state_fingerprint,
)
from semapact.platforms.git import GitWorkingTreeHistoryRepository
from semapact.reconciliation import (
    ReconciliationDifference,
    ReconciliationDifferenceType,
    ReconciliationResult,
    ReconciliationSubject,
    RuntimeDriftStatus,
    RuntimeReasonCode,
)


def _raw_observation(
    at: datetime,
    *,
    asset_type: str = "TABLE",
    source: str = "workspace:test",
) -> ObservedPlatformState:
    return ObservedPlatformState(
        platform="databricks",
        source_identifier=source,
        assets=(
            ObservedAsset(
                identity=ObservedAssetIdentity(
                    platform="databricks",
                    namespace=("catalog", "schema"),
                    asset="orders",
                ),
                asset_type=asset_type,
            ),
        ),
        captured_at=at,
    )


def _observation(at: datetime, *, asset_type: str = "TABLE", source: str = "workspace:test") -> ObservedPlatformState:
    return with_observed_state_fingerprint(
        _raw_observation(at, asset_type=asset_type, source=source)
    )


def _result(observation: ObservedPlatformState, *, drift: bool = False) -> ReconciliationResult:
    differences = ()
    if drift:
        differences = (
            ReconciliationDifference(
                difference_type=ReconciliationDifferenceType.MISMATCH,
                subject=ReconciliationSubject.PHYSICAL_TYPE,
                reason_code=RuntimeReasonCode.RUNTIME_PHYSICAL_TYPE_CHANGED,
                path="orders.id.physical_type",
                asset_identity="orders",
                property_identity="id",
                expected="STRING",
                observed="BIGINT",
            ),
        )
    assert observation.fingerprint is not None
    return ReconciliationResult(
        contract_id="orders-product",
        contract_version="1.3.0",
        observation_source_identifier=observation.source_identifier,
        observation_fingerprint=observation.fingerprint,
        differences=differences,
    )


def _release() -> ReleaseRecord:
    fields = dict(
        contract_id="orders-product",
        contract_version="1.3.0",
        decision_id="decision-1",
        change_set_id="changeset-1",
        release_plan_id="release-plan-1",
        version_resolution_id="version-resolution-1",
        authorization_id="apply-authorization-1",
        applied_release_id="applied-release-1",
        released_revision_id="released-revision-1",
        required_version_bump="minor",
        actual_version_bump="minor",
        version_authority=VersionAuthority.SEMAPACT,
        authority_reference=None,
        review_evidence_reference=None,
        review_evidence_action=None,
    )
    record_id = compute_release_record_id(
        **{**fields, "version_authority": fields["version_authority"].value}
    )
    return ReleaseRecord(release_record_id=record_id, **fields)


def _deployment(release_id: str, *, source: str = "workspace:test") -> DeploymentRecord:
    started = datetime(2026, 9, 13, tzinfo=timezone.utc)
    completed = started + timedelta(seconds=1)
    fields = dict(
        release_record_id=release_id,
        deployment_plan_id="deployment-plan-1",
        deployment_preview_id="deployment-preview-1",
        deployment_authorization_id="deployment-authorization-1",
        platform="databricks",
        runtime_target="catalog.schema",
        source_reference=source,
        status=DeploymentStatus.SUCCEEDED,
        started_at=started,
        completed_at=completed,
        actor_reference=None,
        external_reference=None,
    )
    record_id = compute_deployment_record_id(
        release_record_id=release_id,
        deployment_plan_id=fields["deployment_plan_id"],
        deployment_preview_id=fields["deployment_preview_id"],
        deployment_authorization_id=fields["deployment_authorization_id"],
        platform=fields["platform"],
        runtime_target=fields["runtime_target"],
        source_reference=fields["source_reference"],
        status=fields["status"].value,
        started_at=started.isoformat(),
        completed_at=completed.isoformat(),
        actor_reference=None,
        external_reference=None,
    )
    return DeploymentRecord(deployment_record_id=record_id, **fields)


def _service(tmp_path: Path):
    backend = GitWorkingTreeHistoryRepository(tmp_path)
    return RuntimeHistoryService(
        observations=backend,
        reconciliations=backend,
        releases=backend,
        deployments=backend,
    ), backend


def test_round_trip_and_idempotency(tmp_path: Path) -> None:
    service, backend = _service(tmp_path)
    observation = _observation(datetime(2026, 9, 13, 1, tzinfo=timezone.utc))
    result = _result(observation)

    first = service.record_reconciliation(observation, result)
    second = service.record_reconciliation(observation, result)

    assert first == second
    assert backend.get_runtime_observation_record(first.observation_record_id).observation == observation
    assert backend.get_runtime_reconciliation_record(first.runtime_reconciliation_record_id) == first
    assert first.status is RuntimeDriftStatus.IN_SYNC


def test_missing_fingerprint_is_materialized_before_history_persistence(tmp_path: Path) -> None:
    service, backend = _service(tmp_path)
    observation = _raw_observation(datetime(2026, 9, 13, 1, tzinfo=timezone.utc))
    semantic_fingerprint = fingerprint_observed_state(observation)
    result = ReconciliationResult(
        contract_id="orders-product",
        contract_version="1.3.0",
        observation_source_identifier=observation.source_identifier,
        observation_fingerprint=semantic_fingerprint,
    )

    record = service.record_reconciliation(observation, result)
    persisted = backend.get_runtime_observation_record(record.observation_record_id)

    assert observation.fingerprint is None
    assert persisted.observation.fingerprint == semantic_fingerprint


def test_stale_materialized_fingerprint_is_rejected(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    observation = _raw_observation(datetime(2026, 9, 13, 1, tzinfo=timezone.utc)).model_copy(
        update={"fingerprint": "stale"}
    )
    result = ReconciliationResult(
        contract_id="orders-product",
        contract_version="1.3.0",
        observation_source_identifier=observation.source_identifier,
        observation_fingerprint=fingerprint_observed_state(observation),
    )

    with pytest.raises(ValueError, match="canonical semantic content"):
        service.record_reconciliation(observation, result)


def test_same_semantic_state_at_different_times_keeps_both_observations(tmp_path: Path) -> None:
    service, backend = _service(tmp_path)
    first_observation = _observation(datetime(2026, 9, 13, 1, tzinfo=timezone.utc))
    second_observation = _observation(datetime(2026, 9, 13, 2, tzinfo=timezone.utc))

    first = service.record_reconciliation(first_observation, _result(first_observation))
    second = service.record_reconciliation(second_observation, _result(second_observation))

    assert first_observation.fingerprint == second_observation.fingerprint
    assert first.observation_record_id != second.observation_record_id
    assert len(backend.list_runtime_observation_records("workspace:test")) == 2


def test_sync_then_drift_coexist(tmp_path: Path) -> None:
    service, backend = _service(tmp_path)
    sync_observation = _observation(datetime(2026, 9, 13, 1, tzinfo=timezone.utc))
    drift_observation = _observation(
        datetime(2026, 9, 13, 2, tzinfo=timezone.utc),
        asset_type="VIEW",
    )

    sync = service.record_reconciliation(sync_observation, _result(sync_observation))
    drift = service.record_reconciliation(drift_observation, _result(drift_observation, drift=True))

    records = backend.list_runtime_reconciliation_records_for_source("workspace:test")
    assert set(records) == {sync, drift}
    assert {item.status for item in records} == {RuntimeDriftStatus.IN_SYNC, RuntimeDriftStatus.DRIFT}


def test_exact_release_and_deployment_links_are_optional(tmp_path: Path) -> None:
    service, backend = _service(tmp_path)
    release = _release()
    deployment = _deployment(release.release_record_id)
    backend.put_release_record(release)
    backend.put_deployment_record(deployment)
    observation = _observation(datetime(2026, 9, 13, 1, tzinfo=timezone.utc))

    record = service.record_reconciliation(
        observation,
        _result(observation),
        release_record_id=release.release_record_id,
        deployment_record_id=deployment.deployment_record_id,
    )

    assert record.release_record_id == release.release_record_id
    assert record.deployment_record_id == deployment.deployment_record_id


def test_deployment_success_can_coexist_with_later_drift(tmp_path: Path) -> None:
    service, backend = _service(tmp_path)
    release = _release()
    deployment = _deployment(release.release_record_id)
    backend.put_release_record(release)
    backend.put_deployment_record(deployment)
    observation = _observation(
        datetime(2026, 9, 13, 2, tzinfo=timezone.utc),
        asset_type="VIEW",
    )

    record = service.record_reconciliation(
        observation,
        _result(observation, drift=True),
        release_record_id=release.release_record_id,
        deployment_record_id=deployment.deployment_record_id,
    )

    assert deployment.status is DeploymentStatus.SUCCEEDED
    assert record.status is RuntimeDriftStatus.DRIFT


def test_rejects_mismatched_runtime_evidence(tmp_path: Path) -> None:
    service, backend = _service(tmp_path)
    observation = _observation(datetime(2026, 9, 13, 1, tzinfo=timezone.utc))
    wrong_result = _result(observation).model_copy(update={"observation_fingerprint": "wrong"})
    with pytest.raises(ValueError, match="fingerprint"):
        service.record_reconciliation(observation, wrong_result)

    release = _release()
    deployment = _deployment(release.release_record_id, source="workspace:other")
    backend.put_release_record(release)
    backend.put_deployment_record(deployment)
    with pytest.raises(ValueError, match="source"):
        service.record_reconciliation(
            observation,
            _result(observation),
            release_record_id=release.release_record_id,
            deployment_record_id=deployment.deployment_record_id,
        )
