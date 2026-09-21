"""Legacy in-process deployment authorization plus canonical provenance validation.

Canonical bundle-driven CD uses the validate_* context functions below and leaves
runtime execution permission to the surrounding protected deployment context.
"""

from __future__ import annotations

from semapact.deployment.models import (
    DeploymentAuthorization,
    DeploymentPlan,
    validate_deployment_plan_identity,
)
from semapact.deployment.source import DeploymentSourceSnapshot
from semapact.contractops import ContractRelease
from semapact.governance import DecisionResult, GovernanceDecision
from semapact.exceptions import ReleaseValidationError


def validate_candidate_deployment_context(
    plan: DeploymentPlan,
    source: DeploymentSourceSnapshot,
    decision: GovernanceDecision,
) -> None:
    """Validate candidate deployment provenance and fail closed on BLOCK."""
    if source.source_kind != "candidate":
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
    if source.source_kind != "candidate":
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
    if source.source_kind != "contract_release":
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



