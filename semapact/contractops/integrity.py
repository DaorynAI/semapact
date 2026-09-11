"""Deterministic identity computation and fail-closed validation for ContractOps artifacts.

GovernanceDecision is intentionally excluded: its historical decision ID depends on
source-contract fingerprints that are not contained in the serialized decision itself.
All downstream ContractOps artifacts are self-describing and can therefore validate
their deterministic identities after persistence/deserialization.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

from semapact.change_context import ChangeContext
from semapact.contractops.execution_models import AppliedContractRelease, PublicationResult
from semapact.contractops.models import (
    ChangeSet,
    ContractOpsAuthorization,
    ReleasePlan,
    ReleasePrecondition,
    VersionAuthority,
    VersionResolution,
)
from semapact.exceptions import ReleaseValidationError
from semapact.governance.gate import GovernanceOperation
from semapact.lifecycle.changes import GovernanceChange, governance_change_sort_key
from semapact.utils.deterministic import canonical_compact_json, deterministic_uuid5
from semapact.versioning import ActualVersionBump, RequiredBump


SEMAPACT_CHANGESET_NAMESPACE = uuid.UUID("3ea0f6d8-28ca-4bb4-94f5-ea1f0f48cb84")
SEMAPACT_RELEASE_PLAN_NAMESPACE = uuid.UUID("7d2ad1de-c196-4f12-b1af-fdf79105eb04")
SEMAPACT_VERSION_RESOLUTION_NAMESPACE = uuid.UUID(
    "4a2bd29d-2e44-44a0-9fc9-a1f4c81a2108"
)
SEMAPACT_CONTRACTOPS_AUTHORIZATION_NAMESPACE = uuid.UUID(
    "b6218d0c-3f9d-44a2-8d68-e3b0ee170948"
)
SEMAPACT_APPLIED_RELEASE_NAMESPACE = uuid.UUID(
    "a5de2e65-aee7-48ac-9cb6-6a785f4cdf33"
)
SEMAPACT_PUBLICATION_NAMESPACE = uuid.UUID(
    "f776fc77-b37f-43ef-bf6d-d8dcf38d264f"
)


def validate_contractops_artifact_identity(artifact: object) -> None:
    """Validate deterministic identity for self-describing ContractOps artifacts.

    Non-identity configuration/evidence models are intentionally ignored. This hook
    is called by ``ContractOpsModel.model_post_init`` so persisted artifacts cannot
    be rehydrated with IDs that do not match their immutable content.
    """
    if isinstance(artifact, ChangeSet):
        validate_change_set_identity(artifact)
    elif isinstance(artifact, ReleasePlan):
        validate_release_plan_identity(artifact)
    elif isinstance(artifact, VersionResolution):
        validate_version_resolution_identity(artifact)
    elif isinstance(artifact, ContractOpsAuthorization):
        validate_contractops_authorization_identity(artifact)
    elif isinstance(artifact, AppliedContractRelease):
        validate_applied_release_identity(artifact)
    elif isinstance(artifact, PublicationResult):
        validate_publication_result_identity(artifact)


def compute_change_set_id(
    *,
    contract_id: str,
    base_revision_ref: str,
    candidate_revision_ref: str,
    changes: Sequence[GovernanceChange],
    context: ChangeContext,
    source: str | None,
    actor_reference: str | None,
) -> str:
    canonical_changes = tuple(sorted(tuple(changes), key=governance_change_sort_key))
    payload = {
        "contract_id": contract_id,
        "base_revision_ref": base_revision_ref,
        "candidate_revision_ref": candidate_revision_ref,
        "context": context.model_dump(mode="json"),
        "changes": [change.model_dump(mode="json") for change in canonical_changes],
        "source": source,
        "actor_reference": actor_reference,
    }
    return deterministic_uuid5(SEMAPACT_CHANGESET_NAMESPACE, payload)


def validate_change_set_identity(change_set: ChangeSet) -> None:
    canonical_changes = tuple(sorted(change_set.changes, key=governance_change_sort_key))
    if change_set.changes != canonical_changes:
        raise ReleaseValidationError("ChangeSet changes are not in canonical order")
    expected = compute_change_set_id(
        contract_id=change_set.contract_id,
        base_revision_ref=change_set.base_revision_ref,
        candidate_revision_ref=change_set.candidate_revision_ref,
        changes=change_set.changes,
        context=change_set.context,
        source=change_set.source,
        actor_reference=change_set.actor_reference,
    )
    _require_identity(change_set.change_set_id, expected, "ChangeSet")


def compute_release_plan_id(
    *,
    contract_id: str,
    change_set_id: str,
    decision_id: str,
    release_revision_ref: str,
    required_version_bump: RequiredBump,
    preconditions: Sequence[ReleasePrecondition],
) -> str:
    payload = {
        "contract_id": contract_id,
        "change_set_id": change_set_id,
        "decision_id": decision_id,
        "release_revision_ref": release_revision_ref,
        "required_version_bump": required_version_bump,
        "preconditions": [item.value for item in preconditions],
    }
    return deterministic_uuid5(SEMAPACT_RELEASE_PLAN_NAMESPACE, payload)


def validate_release_plan_identity(release_plan: ReleasePlan) -> None:
    expected = compute_release_plan_id(
        contract_id=release_plan.contract_id,
        change_set_id=release_plan.change_set_id,
        decision_id=release_plan.decision_id,
        release_revision_ref=release_plan.release_revision_ref,
        required_version_bump=release_plan.required_version_bump,
        preconditions=release_plan.preconditions,
    )
    _require_identity(release_plan.release_plan_id, expected, "ReleasePlan")


def compute_version_resolution_id(
    *,
    release_plan_id: str,
    contract_id: str,
    release_revision_ref: str,
    authority: VersionAuthority,
    current_version: str,
    required_version_bump: RequiredBump,
    selected_version: str,
    actual_bump: ActualVersionBump,
    authority_reference: str | None,
) -> str:
    payload = {
        "release_plan_id": release_plan_id,
        "contract_id": contract_id,
        "release_revision_ref": release_revision_ref,
        "authority": authority.value,
        "current_version": current_version,
        "required_version_bump": required_version_bump,
        "selected_version": selected_version,
        "actual_bump": actual_bump,
        "authority_reference": authority_reference,
    }
    return deterministic_uuid5(SEMAPACT_VERSION_RESOLUTION_NAMESPACE, payload)


def validate_version_resolution_identity(resolution: VersionResolution) -> None:
    expected = compute_version_resolution_id(
        release_plan_id=resolution.release_plan_id,
        contract_id=resolution.contract_id,
        release_revision_ref=resolution.release_revision_ref,
        authority=resolution.authority,
        current_version=resolution.current_version,
        required_version_bump=resolution.required_version_bump,
        selected_version=resolution.selected_version,
        actual_bump=resolution.actual_bump,
        authority_reference=resolution.authority_reference,
    )
    _require_identity(resolution.version_resolution_id, expected, "VersionResolution")


def compute_contractops_authorization_id(
    *,
    decision_id: str,
    change_set_id: str,
    release_plan_id: str,
    version_resolution_id: str,
    operation: GovernanceOperation,
    allowed: bool,
    reason: str,
    evidence_reference: str | None,
    evidence_action: str | None,
    scope_reference: str | None,
) -> str:
    payload: dict[str, object] = {
        "decision_id": decision_id,
        "change_set_id": change_set_id,
        "release_plan_id": release_plan_id,
        "version_resolution_id": version_resolution_id,
        "operation": operation.value,
        "allowed": allowed,
        "reason": reason,
        "evidence_reference": evidence_reference,
        "evidence_action": evidence_action,
    }
    # Compatibility invariant: scope_reference did not participate in pre-#122 IDs
    # when it was absent. Keep that byte-for-byte behavior.
    if scope_reference is not None:
        payload["scope_reference"] = scope_reference
    return deterministic_uuid5(SEMAPACT_CONTRACTOPS_AUTHORIZATION_NAMESPACE, payload)


def validate_contractops_authorization_identity(
    authorization: ContractOpsAuthorization,
) -> None:
    expected = compute_contractops_authorization_id(
        decision_id=authorization.decision_id,
        change_set_id=authorization.change_set_id,
        release_plan_id=authorization.release_plan_id,
        version_resolution_id=authorization.version_resolution_id,
        operation=authorization.operation,
        allowed=authorization.allowed,
        reason=authorization.reason.value,
        evidence_reference=authorization.evidence_reference,
        evidence_action=(
            authorization.evidence_action.value
            if authorization.evidence_action is not None
            else None
        ),
        scope_reference=authorization.scope_reference,
    )
    _require_identity(
        authorization.authorization_id,
        expected,
        "ContractOpsAuthorization",
    )


def compute_applied_release_id(
    *,
    contract_id: str,
    decision_id: str,
    change_set_id: str,
    release_plan_id: str,
    version_resolution_id: str,
    release_revision_ref: str,
    selected_version: str,
    authorization_id: str,
    released_contract_json: str,
) -> str:
    payload = {
        "contract_id": contract_id,
        "decision_id": decision_id,
        "change_set_id": change_set_id,
        "release_plan_id": release_plan_id,
        "version_resolution_id": version_resolution_id,
        "release_revision_ref": release_revision_ref,
        "selected_version": selected_version,
        "authorization_id": authorization_id,
        "released_contract_json": released_contract_json,
    }
    return deterministic_uuid5(SEMAPACT_APPLIED_RELEASE_NAMESPACE, payload)


def validate_applied_release_identity(release: AppliedContractRelease) -> None:
    _require_canonical_json(release.released_contract_json, "AppliedContractRelease snapshot")
    expected = compute_applied_release_id(
        contract_id=release.contract_id,
        decision_id=release.decision_id,
        change_set_id=release.change_set_id,
        release_plan_id=release.release_plan_id,
        version_resolution_id=release.version_resolution_id,
        release_revision_ref=release.release_revision_ref,
        selected_version=release.selected_version,
        authorization_id=release.authorization_id,
        released_contract_json=release.released_contract_json,
    )
    _require_identity(release.applied_release_id, expected, "AppliedContractRelease")


def compute_publication_id(
    *,
    applied_release_id: str,
    authorization_id: str,
    publication_reference: str,
) -> str:
    return deterministic_uuid5(
        SEMAPACT_PUBLICATION_NAMESPACE,
        {
            "applied_release_id": applied_release_id,
            "authorization_id": authorization_id,
            "publication_reference": publication_reference,
        },
    )


def validate_publication_result_identity(result: PublicationResult) -> None:
    expected = compute_publication_id(
        applied_release_id=result.applied_release_id,
        authorization_id=result.authorization_id,
        publication_reference=result.publication_reference,
    )
    _require_identity(result.publication_id, expected, "PublicationResult")


def _require_identity(actual: str, expected: str, artifact: str) -> None:
    if actual != expected:
        raise ReleaseValidationError(
            f"{artifact} deterministic identity does not match its content"
        )


def _require_canonical_json(value: str, artifact: str) -> None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:  # defensive; model validation normally catches this
        raise ReleaseValidationError(f"{artifact} is not valid JSON") from exc
    if canonical_compact_json(parsed) != value:
        raise ReleaseValidationError(f"{artifact} must use canonical compact JSON")
