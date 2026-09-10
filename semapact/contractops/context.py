"""Shared fail-closed validation for ContractOps artifact contexts."""

from __future__ import annotations

from semapact.contractops.models import ChangeSet, ReleasePlan, VersionResolution
from semapact.exceptions import ReleaseValidationError
from semapact.governance.models import GovernanceDecision


def validate_proposal_context(
    decision: GovernanceDecision,
    change_set: ChangeSet,
) -> None:
    """Fail closed unless ChangeSet exactly projects one GovernanceDecision."""
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
