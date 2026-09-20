"""Bind release-level DEPLOY authorization to one exact DeploymentPlan."""

from __future__ import annotations

from semapact.contractops.execution_models import AppliedContractRelease, ReleaseSnapshot
from semapact.contractops.integrity import (
    validate_applied_release_identity,
    validate_contractops_authorization_identity,
    validate_release_snapshot_identity,
)
from semapact.contractops.models import AuthorizationReason, ContractOpsAuthorization
from semapact.deployment.models import (
    DeploymentAuthorization,
    DeploymentPlan,
    compute_deployment_authorization_id,
    validate_deployment_plan_identity,
)
from semapact.exceptions import ReleaseValidationError
from semapact.governance.gate import GovernanceOperation


def authorize_deployment(
    plan: DeploymentPlan,
    release: ReleaseSnapshot | AppliedContractRelease,
    authorization: ContractOpsAuthorization,
) -> DeploymentAuthorization:
    """Bind one DEPLOY authorization to the exact deployment target/plan."""
    if not isinstance(plan, DeploymentPlan):
        raise TypeError(f"plan must be DeploymentPlan, got {type(plan).__name__}")
    if not isinstance(release, (ReleaseSnapshot, AppliedContractRelease)):
        raise TypeError(
            "release must be ReleaseSnapshot or AppliedContractRelease, "
            f"got {type(release).__name__}"
        )
    if not isinstance(authorization, ContractOpsAuthorization):
        raise TypeError(
            "authorization must be ContractOpsAuthorization, "
            f"got {type(authorization).__name__}"
        )

    validate_deployment_plan_identity(plan)
    if isinstance(release, ReleaseSnapshot):
        validate_release_snapshot_identity(release)
        release_id = release.release_snapshot_id
    else:
        validate_applied_release_identity(release)
        release_id = release.applied_release_id
    validate_contractops_authorization_identity(authorization)

    if authorization.operation is not GovernanceOperation.DEPLOY:
        raise ReleaseValidationError(
            "Deployment requires operation-scoped DEPLOY authorization"
        )

    _validate_plan_release_context(plan, release)
    _validate_authorization_release_context(authorization, release)

    if (
        authorization.allowed
        and authorization.reason is AuthorizationReason.ALLOWED_BY_REVIEW
        and authorization.scope_reference != plan.deployment_plan_id
    ):
        raise ReleaseValidationError(
            "Review-based DEPLOY authorization is not scoped to this DeploymentPlan"
        )

    deployment_authorization_id = compute_deployment_authorization_id(
        contract_ops_authorization_id=authorization.authorization_id,
        deployment_plan_id=plan.deployment_plan_id,
        applied_release_id=release_id,
        allowed=authorization.allowed,
    )
    return DeploymentAuthorization(
        deployment_authorization_id=deployment_authorization_id,
        contract_ops_authorization_id=authorization.authorization_id,
        deployment_plan_id=plan.deployment_plan_id,
        applied_release_id=release_id,
        allowed=authorization.allowed,
    )


def _validate_plan_release_context(
    plan: DeploymentPlan,
    release: ReleaseSnapshot | AppliedContractRelease,
) -> None:
    release_id = (
        release.release_snapshot_id
        if isinstance(release, ReleaseSnapshot)
        else release.applied_release_id
    )
    if plan.release_id != release_id:
        raise ReleaseValidationError(
            "DeploymentPlan does not reference the supplied exact release"
        )
    if plan.contract_id != release.contract_id:
        raise ReleaseValidationError(
            "DeploymentPlan and release contract IDs do not match"
        )
    if plan.release_plan_id != release.release_plan_id:
        raise ReleaseValidationError(
            "DeploymentPlan and release plan IDs do not match"
        )
    if plan.released_revision_ref != release.release_revision_ref:
        raise ReleaseValidationError(
            "DeploymentPlan released revision does not match release"
        )
    if plan.selected_version != release.selected_version:
        raise ReleaseValidationError(
            "DeploymentPlan selected version does not match release"
        )


def _validate_authorization_release_context(
    authorization: ContractOpsAuthorization,
    release: ReleaseSnapshot | AppliedContractRelease,
) -> None:
    if authorization.decision_id != release.decision_id:
        raise ReleaseValidationError(
            "DEPLOY authorization decision does not match release"
        )
    if authorization.change_set_id != release.change_set_id:
        raise ReleaseValidationError(
            "DEPLOY authorization ChangeSet does not match release"
        )
    if authorization.release_plan_id != release.release_plan_id:
        raise ReleaseValidationError(
            "DEPLOY authorization ReleasePlan does not match release"
        )
    if authorization.version_resolution_id != release.version_resolution_id:
        raise ReleaseValidationError(
            "DEPLOY authorization version resolution does not match release"
        )
