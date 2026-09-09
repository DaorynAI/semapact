"""Bind release-level DEPLOY authorization to one exact DeploymentPlan."""

from __future__ import annotations

import uuid

from semapact.contractops.execution_models import AppliedContractRelease
from semapact.contractops.models import ContractOpsAuthorization
from semapact.deployment.models import DeploymentAuthorization, DeploymentPlan
from semapact.exceptions import ReleaseValidationError
from semapact.governance.gate import GovernanceOperation
from semapact.utils.deterministic import deterministic_uuid5


SEMAPACT_DEPLOYMENT_AUTHORIZATION_NAMESPACE = uuid.UUID(
    "c1dd6b40-cb67-44c1-b0f2-5f133ba6a3f5"
)


def authorize_deployment(
    plan: DeploymentPlan,
    release: AppliedContractRelease,
    authorization: ContractOpsAuthorization,
) -> DeploymentAuthorization:
    """Bind one DEPLOY authorization to the exact deployment target/plan.

    The upstream ContractOps authorization remains responsible for governance and
    review semantics. This layer only verifies exact release provenance and binds
    that authorization to ``deployment_plan_id``, whose identity includes the
    deployment target and desired-state actions.
    """
    if not isinstance(plan, DeploymentPlan):
        raise TypeError(f"plan must be DeploymentPlan, got {type(plan).__name__}")
    if not isinstance(release, AppliedContractRelease):
        raise TypeError(
            f"release must be AppliedContractRelease, got {type(release).__name__}"
        )
    if not isinstance(authorization, ContractOpsAuthorization):
        raise TypeError(
            "authorization must be ContractOpsAuthorization, "
            f"got {type(authorization).__name__}"
        )

    if authorization.operation is not GovernanceOperation.DEPLOY:
        raise ReleaseValidationError(
            "Deployment requires operation-scoped DEPLOY authorization"
        )

    _validate_plan_release_context(plan, release)
    _validate_authorization_release_context(authorization, release)

    stable_record = {
        "contract_ops_authorization_id": authorization.authorization_id,
        "deployment_plan_id": plan.deployment_plan_id,
        "applied_release_id": release.applied_release_id,
        "allowed": authorization.allowed,
    }
    return DeploymentAuthorization(
        deployment_authorization_id=deterministic_uuid5(
            SEMAPACT_DEPLOYMENT_AUTHORIZATION_NAMESPACE,
            stable_record,
        ),
        contract_ops_authorization_id=authorization.authorization_id,
        deployment_plan_id=plan.deployment_plan_id,
        applied_release_id=release.applied_release_id,
        allowed=authorization.allowed,
    )


def _validate_plan_release_context(
    plan: DeploymentPlan,
    release: AppliedContractRelease,
) -> None:
    if plan.applied_release_id != release.applied_release_id:
        raise ReleaseValidationError(
            "DeploymentPlan does not reference the supplied AppliedContractRelease"
        )
    if plan.contract_id != release.contract_id:
        raise ReleaseValidationError(
            "DeploymentPlan and AppliedContractRelease contract IDs do not match"
        )
    if plan.release_plan_id != release.release_plan_id:
        raise ReleaseValidationError(
            "DeploymentPlan and AppliedContractRelease release plan IDs do not match"
        )
    if plan.released_revision_ref != release.release_revision_ref:
        raise ReleaseValidationError(
            "DeploymentPlan released revision does not match AppliedContractRelease"
        )
    if plan.selected_version != release.selected_version:
        raise ReleaseValidationError(
            "DeploymentPlan selected version does not match AppliedContractRelease"
        )


def _validate_authorization_release_context(
    authorization: ContractOpsAuthorization,
    release: AppliedContractRelease,
) -> None:
    if authorization.decision_id != release.decision_id:
        raise ReleaseValidationError(
            "DEPLOY authorization decision does not match AppliedContractRelease"
        )
    if authorization.change_set_id != release.change_set_id:
        raise ReleaseValidationError(
            "DEPLOY authorization ChangeSet does not match AppliedContractRelease"
        )
    if authorization.release_plan_id != release.release_plan_id:
        raise ReleaseValidationError(
            "DEPLOY authorization ReleasePlan does not match AppliedContractRelease"
        )
    if authorization.version_resolution_id != release.version_resolution_id:
        raise ReleaseValidationError(
            "DEPLOY authorization version resolution does not match AppliedContractRelease"
        )
