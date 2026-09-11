"""Shared fail-closed validation for ContractOps artifact contexts."""

from __future__ import annotations

from semapact.contractops.integrity import (
    validate_change_set_identity,
    validate_release_plan_identity,
    validate_version_resolution_identity,
)
from semapact.contractops.models import (
    ChangeSet,
    ReleasePlan,
    ReleasePrecondition,
    VersionResolution,
)
from semapact.exceptions import ReleaseValidationError
from semapact.governance.gate import GovernanceOperation, evaluate_governance_gate
from semapact.governance.models import GovernanceDecision


def validate_proposal_context(
    decision: GovernanceDecision,
    change_set: ChangeSet,
) -> None:
    """Fail closed unless ChangeSet exactly projects one GovernanceDecision."""
    validate_change_set_identity(change_set)

    if change_set.contract_id != decision.contract_id:
        raise ReleaseValidationError(
            "ChangeSet and GovernanceDecision contract IDs do not match"
        )
    if change_set.context != decision.context:
        raise ReleaseValidationError(
            "ChangeSet and GovernanceDecision governance contexts do not match"
        )
    if change_set.changes != decision.changes:
        raise ReleaseValidationError(
            "ChangeSet changes do not match authoritative GovernanceDecision changes"
        )


def validate_release_context(
    decision: GovernanceDecision,
    change_set: ChangeSet,
    release_plan: ReleasePlan,
    version_resolution: VersionResolution,
) -> None:
    """Fail closed unless immutable artifacts describe one exact release context."""
    validate_proposal_context(decision, change_set)
    validate_release_plan_identity(release_plan)
    validate_version_resolution_identity(version_resolution)

    if release_plan.contract_id != change_set.contract_id:
        raise ReleaseValidationError("ReleasePlan and ChangeSet contract IDs do not match")
    if release_plan.change_set_id != change_set.change_set_id:
        raise ReleaseValidationError("ReleasePlan does not reference the supplied ChangeSet")
    if release_plan.decision_id != decision.decision_id:
        raise ReleaseValidationError(
            "ReleasePlan does not reference the supplied GovernanceDecision"
        )
    if release_plan.release_revision_ref != change_set.candidate_revision_ref:
        raise ReleaseValidationError(
            "ReleasePlan release revision does not match ChangeSet candidate revision"
        )
    if release_plan.required_version_bump != decision.required_version_bump:
        raise ReleaseValidationError(
            "ReleasePlan required version bump does not match GovernanceDecision"
        )

    publish_gate = evaluate_governance_gate(decision, GovernanceOperation.PUBLISH)
    if publish_gate.reason == "review_required":
        expected_preconditions = (ReleasePrecondition.REVIEW_AUTHORIZATION_REQUIRED,)
    else:
        # ALLOW and BLOCK carry no review precondition. BLOCK cannot be produced by
        # the canonical planner, but authorization must still preserve its existing
        # fail-closed result if a structurally valid historical/context artifact is
        # supplied; review evidence can never override that decision.
        expected_preconditions = ()
    if release_plan.preconditions != expected_preconditions:
        raise ReleaseValidationError(
            "ReleasePlan preconditions do not match authoritative governance disposition"
        )

    if version_resolution.release_plan_id != release_plan.release_plan_id:
        raise ReleaseValidationError(
            "VersionResolution does not reference the supplied ReleasePlan"
        )
    if version_resolution.contract_id != release_plan.contract_id:
        raise ReleaseValidationError(
            "VersionResolution and ReleasePlan contract IDs do not match"
        )
    if version_resolution.release_revision_ref != release_plan.release_revision_ref:
        raise ReleaseValidationError(
            "VersionResolution release revision does not match ReleasePlan"
        )
    if version_resolution.required_version_bump != release_plan.required_version_bump:
        raise ReleaseValidationError(
            "VersionResolution required version bump does not match ReleasePlan"
        )
