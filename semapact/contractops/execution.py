"""Explicit ContractOps APPLY and PUBLISH execution boundaries."""

from __future__ import annotations

from typing import Protocol

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.contractops.context import validate_release_context
from semapact.contractops.execution_models import AppliedContractRelease, PublicationResult
from semapact.contractops.integrity import (
    SEMAPACT_APPLIED_RELEASE_NAMESPACE,
    SEMAPACT_PUBLICATION_NAMESPACE,
    compute_applied_release_id,
    compute_publication_id,
    validate_applied_release_identity,
    validate_contractops_authorization_identity,
)
from semapact.contractops.models import (
    ChangeSet,
    ContractOpsAuthorization,
    ReleasePlan,
    VersionResolution,
)
from semapact.exceptions import ContractOpsAuthorizationError, ReleaseValidationError
from semapact.governance.gate import GovernanceOperation
from semapact.governance.models import GovernanceDecision
from semapact.odcs.serialization import canonical_contract_json
from semapact.versioning import normalize_semver


class ContractReleasePublisher(Protocol):
    """Narrow external publication port for one applied contract release."""

    def publish(self, release: AppliedContractRelease) -> str:
        """Publish the exact applied release and return an opaque reference."""
        ...


def apply_contract_release(
    candidate_contract: OpenDataContractStandard,
    *,
    candidate_revision_ref: str,
    decision: GovernanceDecision,
    change_set: ChangeSet,
    release_plan: ReleasePlan,
    version_resolution: VersionResolution,
    authorization: ContractOpsAuthorization,
) -> AppliedContractRelease:
    """Materialize the exact released ODCS state after explicit APPLY authorization.

    This is the canonical M2 apply path. It never re-runs governance, change
    classification, or version authority. The input candidate is not mutated.
    """
    if not isinstance(candidate_contract, OpenDataContractStandard):
        raise TypeError(
            "candidate_contract must be OpenDataContractStandard, "
            f"got {type(candidate_contract).__name__}"
        )
    if not isinstance(candidate_revision_ref, str):
        raise TypeError("candidate_revision_ref must be str")

    validate_release_context(decision, change_set, release_plan, version_resolution)
    _validate_authorization(
        authorization,
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        operation=GovernanceOperation.APPLY,
    )

    supplied_revision_ref = candidate_revision_ref.strip()
    if not supplied_revision_ref:
        raise ReleaseValidationError("candidate_revision_ref must not be empty")
    if supplied_revision_ref != release_plan.release_revision_ref:
        raise ReleaseValidationError(
            "Supplied candidate revision does not match the planned release revision"
        )

    if str(candidate_contract.id or "") != release_plan.contract_id:
        raise ReleaseValidationError(
            "Candidate contract ID does not match the planned release contract"
        )

    current_version = _canonical_version(
        version_resolution.current_version,
        field_name="VersionResolution current_version",
    )
    selected_version = _canonical_version(
        version_resolution.selected_version,
        field_name="VersionResolution selected_version",
    )
    candidate_version = _canonical_version(
        str(candidate_contract.version or ""),
        field_name="candidate contract version",
    )
    if candidate_version != current_version:
        raise ReleaseValidationError(
            "Candidate contract version does not match VersionResolution current_version"
        )

    released_contract = candidate_contract.model_copy(deep=True)
    released_contract.version = selected_version
    released_contract_json = canonical_contract_json(released_contract)

    applied_release_id = compute_applied_release_id(
        contract_id=release_plan.contract_id,
        decision_id=decision.decision_id,
        change_set_id=change_set.change_set_id,
        release_plan_id=release_plan.release_plan_id,
        version_resolution_id=version_resolution.version_resolution_id,
        release_revision_ref=release_plan.release_revision_ref,
        selected_version=selected_version,
        authorization_id=authorization.authorization_id,
        released_contract_json=released_contract_json,
    )

    return AppliedContractRelease(
        applied_release_id=applied_release_id,
        contract_id=release_plan.contract_id,
        decision_id=decision.decision_id,
        change_set_id=change_set.change_set_id,
        release_plan_id=release_plan.release_plan_id,
        version_resolution_id=version_resolution.version_resolution_id,
        release_revision_ref=release_plan.release_revision_ref,
        selected_version=selected_version,
        authorization_id=authorization.authorization_id,
        released_contract_json=released_contract_json,
    )


def publish_contract_release(
    release: AppliedContractRelease,
    *,
    authorization: ContractOpsAuthorization,
    publisher: ContractReleasePublisher,
) -> PublicationResult:
    """Invoke one external publisher only after exact PUBLISH authorization."""
    if not isinstance(release, AppliedContractRelease):
        raise TypeError(
            f"release must be AppliedContractRelease, got {type(release).__name__}"
        )
    if not isinstance(authorization, ContractOpsAuthorization):
        raise TypeError(
            "authorization must be ContractOpsAuthorization, "
            f"got {type(authorization).__name__}"
        )
    if not hasattr(publisher, "publish") or not callable(publisher.publish):
        raise TypeError("publisher must provide a callable publish(release) method")

    validate_applied_release_identity(release)
    _validate_publication_authorization(release, authorization)

    publication_reference = publisher.publish(release)
    if not isinstance(publication_reference, str):
        raise TypeError("publisher.publish() must return str")
    publication_reference = publication_reference.strip()
    if not publication_reference:
        raise ReleaseValidationError(
            "publisher.publish() returned an empty publication reference"
        )

    publication_id = compute_publication_id(
        applied_release_id=release.applied_release_id,
        authorization_id=authorization.authorization_id,
        publication_reference=publication_reference,
    )
    return PublicationResult(
        publication_id=publication_id,
        applied_release_id=release.applied_release_id,
        authorization_id=authorization.authorization_id,
        publication_reference=publication_reference,
    )


def _validate_authorization(
    authorization: ContractOpsAuthorization,
    *,
    decision: GovernanceDecision,
    change_set: ChangeSet,
    release_plan: ReleasePlan,
    version_resolution: VersionResolution,
    operation: GovernanceOperation,
) -> None:
    if not isinstance(authorization, ContractOpsAuthorization):
        raise TypeError(
            "authorization must be ContractOpsAuthorization, "
            f"got {type(authorization).__name__}"
        )
    validate_contractops_authorization_identity(authorization)
    if authorization.operation is not operation:
        raise ReleaseValidationError(
            f"Authorization operation must be {operation.value}, "
            f"got {authorization.operation.value}"
        )
    if (
        authorization.decision_id != decision.decision_id
        or authorization.change_set_id != change_set.change_set_id
        or authorization.release_plan_id != release_plan.release_plan_id
        or authorization.version_resolution_id
        != version_resolution.version_resolution_id
    ):
        raise ReleaseValidationError(
            "Authorization does not match the exact version-resolved release context"
        )
    if not authorization.allowed:
        raise ContractOpsAuthorizationError(
            f"ContractOps {operation.value} is not authorized: "
            f"{authorization.reason.value}"
        )


def _validate_publication_authorization(
    release: AppliedContractRelease,
    authorization: ContractOpsAuthorization,
) -> None:
    validate_contractops_authorization_identity(authorization)
    if authorization.operation is not GovernanceOperation.PUBLISH:
        raise ReleaseValidationError(
            "Publication requires operation-scoped PUBLISH authorization"
        )
    if (
        authorization.decision_id != release.decision_id
        or authorization.change_set_id != release.change_set_id
        or authorization.release_plan_id != release.release_plan_id
        or authorization.version_resolution_id != release.version_resolution_id
    ):
        raise ReleaseValidationError(
            "PUBLISH authorization does not match the applied release context"
        )
    if not authorization.allowed:
        raise ContractOpsAuthorizationError(
            "ContractOps PUBLISH is not authorized: "
            f"{authorization.reason.value}"
        )


def _canonical_version(version: str, *, field_name: str) -> str:
    try:
        canonical = normalize_semver(version)
    except ValueError as exc:
        raise ReleaseValidationError(f"{field_name} is not valid semantic version") from exc
    if canonical != str(version).strip():
        raise ReleaseValidationError(
            f"{field_name} must use canonical major.minor.patch form"
        )
    return canonical
