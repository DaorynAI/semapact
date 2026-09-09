"""Deterministic release planning from authoritative ContractOps artifacts."""

from __future__ import annotations

import json
import uuid

from semapact.contractops.models import ChangeSet, ReleasePlan, ReleasePrecondition
from semapact.exceptions import ReleaseValidationError
from semapact.governance.gate import (
    GovernanceOperation,
    enforce_governance_gate,
    evaluate_governance_gate,
)
from semapact.governance.models import GovernanceDecision


SEMAPACT_RELEASE_PLAN_NAMESPACE = uuid.UUID("7d2ad1de-c196-4f12-b1af-fdf79105eb04")


def build_release_plan(
    change_set: ChangeSet,
    decision: GovernanceDecision,
) -> ReleasePlan:
    """Build a pure ReleasePlan from one exact ChangeSet and governance decision.

    The function never re-evaluates contract changes, policy, or version
    classification. BLOCK decisions cannot be planned. REVIEW decisions remain
    REVIEW and carry an explicit authorization precondition for later ContractOps
    authorization (#120).
    """
    if not isinstance(change_set, ChangeSet):
        raise TypeError(
            f"change_set must be ChangeSet, got {type(change_set).__name__}"
        )
    if not isinstance(decision, GovernanceDecision):
        raise TypeError(
            f"decision must be GovernanceDecision, got {type(decision).__name__}"
        )

    _validate_proposal_consistency(change_set, decision)

    # Release planning is a pure PROPOSE operation. Reuse the authoritative M0 gate
    # rather than duplicating ALLOW/REVIEW/BLOCK mapping in ContractOps.
    enforce_governance_gate(decision, GovernanceOperation.PROPOSE)

    if not decision.evidence.has_changes:
        raise ReleaseValidationError("Cannot plan a release for a proposal with no changes")

    publish_gate = evaluate_governance_gate(decision, GovernanceOperation.PUBLISH)
    if publish_gate.allowed:
        preconditions: tuple[ReleasePrecondition, ...] = ()
    elif publish_gate.reason == "review_required":
        preconditions = (ReleasePrecondition.REVIEW_AUTHORIZATION_REQUIRED,)
    else:
        # PROPOSE already rejects BLOCK. Reaching this state would mean the M0 gate
        # returned internally inconsistent results for the same immutable decision.
        raise RuntimeError("Governance gate returned inconsistent release eligibility")

    stable_record = {
        "contract_id": change_set.contract_id,
        "change_set_id": change_set.change_set_id,
        "decision_id": decision.decision_id,
        "release_revision_ref": change_set.candidate_revision_ref,
        "required_version_bump": decision.required_version_bump,
        "preconditions": [item.value for item in preconditions],
    }
    canonical_payload = json.dumps(
        stable_record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    release_plan_id = str(
        uuid.uuid5(SEMAPACT_RELEASE_PLAN_NAMESPACE, canonical_payload)
    )

    return ReleasePlan(
        release_plan_id=release_plan_id,
        contract_id=change_set.contract_id,
        change_set_id=change_set.change_set_id,
        decision_id=decision.decision_id,
        release_revision_ref=change_set.candidate_revision_ref,
        required_version_bump=decision.required_version_bump,
        preconditions=preconditions,
    )


def _validate_proposal_consistency(
    change_set: ChangeSet,
    decision: GovernanceDecision,
) -> None:
    """Fail closed when artifacts do not describe the same evaluated proposal."""
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
