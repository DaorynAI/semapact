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
from semapact.deployment.source import DeploymentSourceSnapshot
from semapact.contractops import ContractRelease
from semapact.governance import DecisionResult, GovernanceDecision
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

    source_snapshot_id = plan.source_snapshot_id
    if plan.plan_version in {"2", "3"}:
        deployment_authorization_id = compute_deployment_authorization_id(
            contract_ops_authorization_id=authorization.authorization_id,
            deployment_plan_id=plan.deployment_plan_id,
            applied_release_id=source_snapshot_id,
            allowed=authorization.allowed,
            authorization_version="1",
        )
        return DeploymentAuthorization(
            deployment_authorization_id=deployment_authorization_id,
            contract_ops_authorization_id=authorization.authorization_id,
            deployment_plan_id=plan.deployment_plan_id,
            applied_release_id=source_snapshot_id,
            allowed=authorization.allowed,
        )

    deployment_authorization_id = compute_deployment_authorization_id(
        deployment_plan_id=plan.deployment_plan_id,
        source_snapshot_id=source_snapshot_id,
        authorization_kind="contractops",
        authorization_reference=authorization.authorization_id,
        allowed=authorization.allowed,
        authorization_version="2",
    )
    return DeploymentAuthorization(
        deployment_authorization_id=deployment_authorization_id,
        deployment_plan_id=plan.deployment_plan_id,
        source_snapshot_id=source_snapshot_id,
        allowed=authorization.allowed,
        authorization_kind="contractops",
        authorization_reference=authorization.authorization_id,
        authorization_version="2",
    )



def validate_candidate_deployment_context(
    plan: DeploymentPlan,
    source: DeploymentSourceSnapshot,
    decision: GovernanceDecision,
) -> None:
    """Validate candidate deployment provenance and fail closed on BLOCK."""
    if source.source_kind != "candidate" or plan.is_release:
        raise ReleaseValidationError(
            "Candidate deployment requires candidate source without release provenance"
        )
    validate_deployment_plan_identity(plan)
    if plan.source_snapshot_id != source.source_snapshot_id:
        raise ReleaseValidationError(
            "DeploymentPlan does not reference the supplied candidate source"
        )
    if plan.contract_id != source.contract_id:
        raise ReleaseValidationError(
            "DeploymentPlan and candidate source contract IDs do not match"
        )
    if decision.contract_id != source.contract_id:
        raise ReleaseValidationError(
            "GovernanceDecision does not match candidate deployment contract"
        )
    if decision.decision is DecisionResult.BLOCK:
        raise ReleaseValidationError("Candidate deployment is blocked by governance")


def authorize_candidate_deployment(
    plan: DeploymentPlan,
    source: DeploymentSourceSnapshot,
    decision: GovernanceDecision,
) -> DeploymentAuthorization:
    """Authorize a non-release deployment directly from governance outcome.

    Candidate deployment never creates release approval evidence. BLOCK remains
    fail-closed; ALLOW and REVIEW may proceed as non-release runtime validation.
    """
    if plan.is_release or source.source_kind != "candidate":
        raise ReleaseValidationError(
            "Candidate deployment authorization requires non-release plan/source"
        )
    validate_deployment_plan_identity(plan)
    if plan.source_snapshot_id != source.source_snapshot_id:
        raise ReleaseValidationError(
            "DeploymentPlan does not reference the supplied candidate source"
        )
    if plan.contract_id != source.contract_id:
        raise ReleaseValidationError(
            "DeploymentPlan and candidate source contract IDs do not match"
        )
    if decision.contract_id != source.contract_id:
        raise ReleaseValidationError(
            "GovernanceDecision does not match candidate deployment contract"
        )
    allowed = decision.decision is not DecisionResult.BLOCK
    authorization_id = compute_deployment_authorization_id(
        deployment_plan_id=plan.deployment_plan_id,
        source_snapshot_id=source.source_snapshot_id,
        authorization_kind="governance",
        authorization_reference=decision.decision_id,
        allowed=allowed,
        authorization_version="2",
    )
    return DeploymentAuthorization(
        deployment_authorization_id=authorization_id,
        deployment_plan_id=plan.deployment_plan_id,
        source_snapshot_id=source.source_snapshot_id,
        allowed=allowed,
        authorization_kind="governance",
        authorization_reference=decision.decision_id,
        authorization_version="2",
    )


def validate_contract_release_deployment_context(
    plan: DeploymentPlan,
    source: DeploymentSourceSnapshot,
    release: ContractRelease,
) -> None:
    """Validate that one plan is derived from the exact finalized release."""
    if source.source_kind != "contract_release" or not plan.is_release:
        raise ReleaseValidationError(
            "Finalized release deployment requires ContractRelease source provenance"
        )
    validate_deployment_plan_identity(plan)
    if plan.source_snapshot_id != source.source_snapshot_id:
        raise ReleaseValidationError(
            "DeploymentPlan does not reference the supplied release source"
        )
    if source.release_id != release.contract_release_id:
        raise ReleaseValidationError(
            "Deployment source does not reference the finalized ContractRelease"
        )
    if source.contract_id != release.contract_id:
        raise ReleaseValidationError(
            "Deployment source and ContractRelease contract IDs do not match"
        )
    if source.contract_version != release.contract_version:
        raise ReleaseValidationError(
            "Deployment source and ContractRelease versions do not match"
        )
    if source.revision_ref != release.source_revision_ref:
        raise ReleaseValidationError(
            "Deployment source and ContractRelease revisions do not match"
        )
    if plan.release_id != release.contract_release_id:
        raise ReleaseValidationError(
            "DeploymentPlan does not reference the finalized ContractRelease"
        )


def authorize_contract_release_deployment(
    plan: DeploymentPlan,
    source: DeploymentSourceSnapshot,
    release: ContractRelease,
) -> DeploymentAuthorization:
    """Compatibility adapter for callers that still require an authorization artifact.

    Canonical CI/CD validates the release context and treats the protected execution
    boundary as deployment authority; it does not interpret ContractRelease itself as
    authorization.
    """
    validate_contract_release_deployment_context(plan, source, release)
    authorization_id = compute_deployment_authorization_id(
        deployment_plan_id=plan.deployment_plan_id,
        source_snapshot_id=source.source_snapshot_id,
        authorization_kind="contract_release",
        authorization_reference=release.contract_release_id,
        allowed=True,
        authorization_version="2",
    )
    return DeploymentAuthorization(
        deployment_authorization_id=authorization_id,
        deployment_plan_id=plan.deployment_plan_id,
        source_snapshot_id=source.source_snapshot_id,
        allowed=True,
        authorization_kind="contract_release",
        authorization_reference=release.contract_release_id,
        authorization_version="2",
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
