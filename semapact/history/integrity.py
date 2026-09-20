"""Deterministic identity for history-owned audit records."""

from __future__ import annotations

import uuid

from semapact.history.models import (
    ContractReleaseRecord,
    DeploymentRecord,
    ReleaseRecord,
    RuntimeObservationRecord,
    RuntimeReconciliationRecord,
)
from semapact.observation import ObservedPlatformState
from semapact.reconciliation import ReconciliationResult
from semapact.utils.deterministic import deterministic_uuid5


SEMAPACT_RELEASE_RECORD_NAMESPACE = uuid.UUID(
    "9f750d1c-8f0a-491a-b861-8e349fc351cb"
)
SEMAPACT_CONTRACT_RELEASE_RECORD_NAMESPACE = uuid.UUID(
    "0f95c8c5-4957-43f7-a38c-2756605c2df6"
)
SEMAPACT_DEPLOYMENT_RECORD_NAMESPACE = uuid.UUID(
    "93db6770-90f0-4ac5-a185-2f21e818d18e"
)
SEMAPACT_RUNTIME_OBSERVATION_RECORD_NAMESPACE = uuid.UUID(
    "8a3c8c10-e7d0-4df6-8b1a-3f087ef7e8e2"
)
SEMAPACT_RUNTIME_RECONCILIATION_RECORD_NAMESPACE = uuid.UUID(
    "11969598-1f11-4c03-8ab0-f99f012a5041"
)


def compute_release_record_id(
    *,
    contract_id: str,
    contract_version: str,
    decision_id: str,
    change_set_id: str,
    release_plan_id: str,
    version_resolution_id: str,
    authorization_id: str,
    applied_release_id: str,
    released_revision_id: str,
    required_version_bump: str,
    actual_version_bump: str,
    version_authority: str,
    authority_reference: str | None,
    review_evidence_reference: str | None,
    review_evidence_action: str | None,
) -> str:
    """Derive one stable identity from the complete immutable release audit record."""
    return deterministic_uuid5(
        SEMAPACT_RELEASE_RECORD_NAMESPACE,
        {
            "contract_id": contract_id,
            "contract_version": contract_version,
            "decision_id": decision_id,
            "change_set_id": change_set_id,
            "release_plan_id": release_plan_id,
            "version_resolution_id": version_resolution_id,
            "authorization_id": authorization_id,
            "applied_release_id": applied_release_id,
            "released_revision_id": released_revision_id,
            "required_version_bump": required_version_bump,
            "actual_version_bump": actual_version_bump,
            "version_authority": version_authority,
            "authority_reference": authority_reference,
            "review_evidence_reference": review_evidence_reference,
            "review_evidence_action": review_evidence_action,
        },
    )


def validate_release_record_identity(record: ReleaseRecord) -> None:
    """Fail closed when a persisted release record ID does not match its content."""
    expected = compute_release_record_id(
        contract_id=record.contract_id,
        contract_version=record.contract_version,
        decision_id=record.decision_id,
        change_set_id=record.change_set_id,
        release_plan_id=record.release_plan_id,
        version_resolution_id=record.version_resolution_id,
        authorization_id=record.authorization_id,
        applied_release_id=record.applied_release_id,
        released_revision_id=record.released_revision_id,
        required_version_bump=record.required_version_bump,
        actual_version_bump=record.actual_version_bump,
        version_authority=record.version_authority.value,
        authority_reference=record.authority_reference,
        review_evidence_reference=record.review_evidence_reference,
        review_evidence_action=(
            record.review_evidence_action.value
            if record.review_evidence_action is not None
            else None
        ),
    )
    if record.release_record_id != expected:
        raise ValueError("ReleaseRecord deterministic identity does not match its content")


def compute_contract_release_record_id(
    *,
    contract_id: str,
    contract_version: str,
    decision_id: str,
    change_set_id: str,
    release_plan_id: str,
    version_resolution_id: str,
    release_snapshot_id: str,
    revision_ref: str,
    released_contract_json: str,
) -> str:
    return deterministic_uuid5(
        SEMAPACT_CONTRACT_RELEASE_RECORD_NAMESPACE,
        {
            "contract_id": contract_id,
            "contract_version": contract_version,
            "decision_id": decision_id,
            "change_set_id": change_set_id,
            "release_plan_id": release_plan_id,
            "version_resolution_id": version_resolution_id,
            "release_snapshot_id": release_snapshot_id,
            "revision_ref": revision_ref,
            "released_contract_json": released_contract_json,
        },
    )


def validate_contract_release_record_identity(
    record: ContractReleaseRecord,
) -> None:
    expected = compute_contract_release_record_id(
        contract_id=record.contract_id,
        contract_version=record.contract_version,
        decision_id=record.decision_id,
        change_set_id=record.change_set_id,
        release_plan_id=record.release_plan_id,
        version_resolution_id=record.version_resolution_id,
        release_snapshot_id=record.release_snapshot_id,
        revision_ref=record.revision_ref,
        released_contract_json=record.released_contract_json,
    )
    if record.contract_release_id != expected:
        raise ValueError(
            "ContractReleaseRecord deterministic identity does not match content"
        )


def compute_deployment_record_id(
    *,
    release_record_id: str,
    deployment_plan_id: str,
    deployment_preview_id: str,
    deployment_authorization_id: str,
    platform: str,
    runtime_target: str,
    source_reference: str,
    status: str,
    started_at: str,
    completed_at: str,
    actor_reference: str | None,
    external_reference: str | None,
) -> str:
    """Derive one stable identity for a concrete deployment execution occurrence."""
    return deterministic_uuid5(
        SEMAPACT_DEPLOYMENT_RECORD_NAMESPACE,
        {
            "release_record_id": release_record_id,
            "deployment_plan_id": deployment_plan_id,
            "deployment_preview_id": deployment_preview_id,
            "deployment_authorization_id": deployment_authorization_id,
            "platform": platform,
            "runtime_target": runtime_target,
            "source_reference": source_reference,
            "status": status,
            "started_at": started_at,
            "completed_at": completed_at,
            "actor_reference": actor_reference,
            "external_reference": external_reference,
        },
    )


def validate_deployment_record_identity(record: DeploymentRecord) -> None:
    """Fail closed when a deployment occurrence ID does not match its content."""
    expected = compute_deployment_record_id(
        release_record_id=record.release_record_id,
        deployment_plan_id=record.deployment_plan_id,
        deployment_preview_id=record.deployment_preview_id,
        deployment_authorization_id=record.deployment_authorization_id,
        platform=record.platform,
        runtime_target=record.runtime_target,
        source_reference=record.source_reference,
        status=record.status.value,
        started_at=record.started_at.isoformat(),
        completed_at=record.completed_at.isoformat(),
        actor_reference=record.actor_reference,
        external_reference=record.external_reference,
    )
    if record.deployment_record_id != expected:
        raise ValueError(
            "DeploymentRecord deterministic identity does not match its content"
        )


def compute_runtime_observation_record_id(
    observation: ObservedPlatformState,
) -> str:
    """Derive stable history identity from the exact canonical M1 observation."""
    if not isinstance(observation, ObservedPlatformState):
        raise TypeError(
            "observation must be ObservedPlatformState, "
            f"got {type(observation).__name__}"
        )
    return deterministic_uuid5(
        SEMAPACT_RUNTIME_OBSERVATION_RECORD_NAMESPACE,
        {"observation": observation.model_dump(mode="json")},
    )


def validate_runtime_observation_record_identity(
    record: RuntimeObservationRecord,
) -> None:
    """Fail closed when observation history identity does not match exact evidence."""
    expected = compute_runtime_observation_record_id(record.observation)
    if record.observation_record_id != expected:
        raise ValueError(
            "RuntimeObservationRecord deterministic identity does not match content"
        )


def compute_runtime_reconciliation_record_id(
    *,
    observation_record_id: str,
    result: ReconciliationResult,
    status: str,
    release_record_id: str | None,
    deployment_record_id: str | None,
) -> str:
    """Derive stable identity for one persisted runtime reconciliation conclusion."""
    if not isinstance(result, ReconciliationResult):
        raise TypeError(
            f"result must be ReconciliationResult, got {type(result).__name__}"
        )
    return deterministic_uuid5(
        SEMAPACT_RUNTIME_RECONCILIATION_RECORD_NAMESPACE,
        {
            "observation_record_id": observation_record_id,
            "result": result.model_dump(mode="json"),
            "status": status,
            "release_record_id": release_record_id,
            "deployment_record_id": deployment_record_id,
        },
    )


def validate_runtime_reconciliation_record_identity(
    record: RuntimeReconciliationRecord,
) -> None:
    """Fail closed when runtime reconciliation history identity is stale/tampered."""
    expected = compute_runtime_reconciliation_record_id(
        observation_record_id=record.observation_record_id,
        result=record.result,
        status=record.status.value,
        release_record_id=record.release_record_id,
        deployment_record_id=record.deployment_record_id,
    )
    if record.runtime_reconciliation_record_id != expected:
        raise ValueError(
            "RuntimeReconciliationRecord deterministic identity does not match content"
        )
