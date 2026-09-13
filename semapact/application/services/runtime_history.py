"""Application orchestration for point-in-time runtime evidence history."""

from __future__ import annotations

from semapact.history import (
    DeploymentRecord,
    DeploymentRecordHistoryRepository,
    ReleaseRecord,
    ReleaseRecordHistoryRepository,
    RuntimeObservationHistoryRepository,
    RuntimeObservationRecord,
    RuntimeReconciliationHistoryRepository,
    RuntimeReconciliationRecord,
)
from semapact.history.integrity import (
    compute_runtime_observation_record_id,
    compute_runtime_reconciliation_record_id,
)
from semapact.observation import ObservedPlatformState, fingerprint_observed_state
from semapact.reconciliation import (
    ReconciliationResult,
    classify_reconciliation_status,
)


class RuntimeHistoryService:
    """Persist canonical M1 runtime evidence with optional exact lifecycle links."""

    def __init__(
        self,
        *,
        observations: RuntimeObservationHistoryRepository,
        reconciliations: RuntimeReconciliationHistoryRepository,
        releases: ReleaseRecordHistoryRepository,
        deployments: DeploymentRecordHistoryRepository,
    ) -> None:
        self._observations = observations
        self._reconciliations = reconciliations
        self._releases = releases
        self._deployments = deployments

    def record_reconciliation(
        self,
        observation: ObservedPlatformState,
        result: ReconciliationResult,
        *,
        release_record_id: str | None = None,
        deployment_record_id: str | None = None,
    ) -> RuntimeReconciliationRecord:
        """Record one canonical observation/result pair without recomputing M1 semantics."""
        if not isinstance(observation, ObservedPlatformState):
            raise TypeError(
                "observation must be ObservedPlatformState, "
                f"got {type(observation).__name__}"
            )
        if not isinstance(result, ReconciliationResult):
            raise TypeError(
                f"result must be ReconciliationResult, got {type(result).__name__}"
            )

        _validate_observation_result_link(observation, result)
        release = _load_optional_release(self._releases, release_record_id)
        deployment = _load_optional_deployment(
            self._deployments,
            deployment_record_id,
        )
        _validate_optional_history_links(
            observation,
            result,
            release=release,
            deployment=deployment,
        )

        observation_record_id = compute_runtime_observation_record_id(observation)
        observation_record = RuntimeObservationRecord(
            observation_record_id=observation_record_id,
            observation=observation,
        )

        status = classify_reconciliation_status(result)
        runtime_reconciliation_record_id = compute_runtime_reconciliation_record_id(
            observation_record_id=observation_record_id,
            result=result,
            status=status.value,
            release_record_id=(
                release.release_record_id if release is not None else None
            ),
            deployment_record_id=(
                deployment.deployment_record_id if deployment is not None else None
            ),
        )
        record = RuntimeReconciliationRecord(
            runtime_reconciliation_record_id=runtime_reconciliation_record_id,
            observation_record_id=observation_record_id,
            result=result,
            status=status,
            release_record_id=(
                release.release_record_id if release is not None else None
            ),
            deployment_record_id=(
                deployment.deployment_record_id if deployment is not None else None
            ),
        )

        # Persist the canonical observation first so the final linkage record never
        # points at absent runtime evidence after a partial storage failure.
        self._observations.put_runtime_observation_record(observation_record)
        self._reconciliations.put_runtime_reconciliation_record(record)
        return record


def _validate_observation_result_link(
    observation: ObservedPlatformState,
    result: ReconciliationResult,
) -> None:
    if observation.source_identifier != result.observation_source_identifier:
        raise ValueError(
            "ReconciliationResult source does not match ObservedPlatformState"
        )
    observation_fingerprint = observation.fingerprint or fingerprint_observed_state(
        observation
    )
    if observation_fingerprint != result.observation_fingerprint:
        raise ValueError(
            "ReconciliationResult fingerprint does not match ObservedPlatformState"
        )


def _load_optional_release(
    repository: ReleaseRecordHistoryRepository,
    release_record_id: str | None,
) -> ReleaseRecord | None:
    if release_record_id is None:
        return None
    return repository.get_release_record(_required_text(release_record_id, "release_record_id"))


def _load_optional_deployment(
    repository: DeploymentRecordHistoryRepository,
    deployment_record_id: str | None,
) -> DeploymentRecord | None:
    if deployment_record_id is None:
        return None
    return repository.get_deployment_record(
        _required_text(deployment_record_id, "deployment_record_id")
    )


def _validate_optional_history_links(
    observation: ObservedPlatformState,
    result: ReconciliationResult,
    *,
    release: ReleaseRecord | None,
    deployment: DeploymentRecord | None,
) -> None:
    if release is not None:
        if (
            release.contract_id != result.contract_id
            or release.contract_version != result.contract_version
        ):
            raise ValueError(
                "Runtime reconciliation does not match the linked ReleaseRecord"
            )

    if deployment is None:
        return
    if release is None:
        raise ValueError(
            "deployment-linked runtime history requires an explicit ReleaseRecord link"
        )
    if deployment.release_record_id != release.release_record_id:
        raise ValueError(
            "DeploymentRecord does not belong to the linked ReleaseRecord"
        )
    if deployment.platform.strip().casefold() != observation.platform.strip().casefold():
        raise ValueError(
            "DeploymentRecord platform does not match ObservedPlatformState"
        )
    if deployment.source_reference != observation.source_identifier:
        raise ValueError(
            "DeploymentRecord source does not match ObservedPlatformState"
        )


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned
