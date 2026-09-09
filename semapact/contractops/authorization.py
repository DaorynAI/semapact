"""Pure authorization composition for review-required ContractOps actions."""

from __future__ import annotations

import json
import uuid

from semapact.contractops.models import (
    AuthorizationReason,
    ChangeSet,
    ContractOpsAuthorization,
    ReleasePlan,
    ReviewAuthorizationEvidence,
    ReviewEvidenceAction,
    VersionResolution,
)
from semapact.exceptions import ReleaseValidationError
from semapact.governance.gate import GovernanceOperation, evaluate_governance_gate
from semapact.governance.models import GovernanceDecision


SEMAPACT_CONTRACTOPS_AUTHORIZATION_NAMESPACE = uuid.UUID(
    "b6218d0c-3f9d-44a2-8d68-e3b0ee170948"
)


def authorize_contract_operation(
    decision: GovernanceDecision,
    change_set: ChangeSet,
    release_plan: ReleasePlan,
    version_resolution: VersionResolution,
    operation: GovernanceOperation,
    *,
    evidence: ReviewAuthorizationEvidence | None = None,
) -> ContractOpsAuthorization:
    """Authorize one exact version-resolved ContractOps operation.

    M0 governance remains authoritative for decision-level semantics. This function
    only satisfies a ``review_required`` gate result with explicit, exact approval
    evidence. It never mutates or reinterprets the GovernanceDecision.
    """
    _validate_types(
        decision,
        change_set,
        release_plan,
        version_resolution,
        operation,
        evidence,
    )
    _validate_release_context(decision, change_set, release_plan, version_resolution)

    gate = evaluate_governance_gate(decision, operation)

    if gate.reason == "blocked":
        return _build_authorization(
            decision=decision,
            change_set=change_set,
            release_plan=release_plan,
            version_resolution=version_resolution,
            operation=operation,
            allowed=False,
            reason=AuthorizationReason.BLOCKED_BY_GOVERNANCE,
        )

    if gate.allowed:
        return _build_authorization(
            decision=decision,
            change_set=change_set,
            release_plan=release_plan,
            version_resolution=version_resolution,
            operation=operation,
            allowed=True,
            reason=AuthorizationReason.ALLOWED_BY_GOVERNANCE,
        )

    if gate.reason != "review_required":  # pragma: no cover - gate exhaustiveness guard
        raise RuntimeError(f"Unsupported governance gate reason: {gate.reason}")

    if evidence is None:
        return _build_authorization(
            decision=decision,
            change_set=change_set,
            release_plan=release_plan,
            version_resolution=version_resolution,
            operation=operation,
            allowed=False,
            reason=AuthorizationReason.REVIEW_AUTHORIZATION_REQUIRED,
        )

    if not _evidence_matches_release_context(
        evidence,
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        operation=operation,
    ):
        return _build_authorization(
            decision=decision,
            change_set=change_set,
            release_plan=release_plan,
            version_resolution=version_resolution,
            operation=operation,
            allowed=False,
            reason=AuthorizationReason.REVIEW_AUTHORIZATION_MISMATCH,
            evidence=evidence,
        )

    if evidence.action is not ReviewEvidenceAction.APPROVE:
        return _build_authorization(
            decision=decision,
            change_set=change_set,
            release_plan=release_plan,
            version_resolution=version_resolution,
            operation=operation,
            allowed=False,
            reason=AuthorizationReason.REVIEW_AUTHORIZATION_REJECTED,
            evidence=evidence,
        )

    return _build_authorization(
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        operation=operation,
        allowed=True,
        reason=AuthorizationReason.ALLOWED_BY_REVIEW,
        evidence=evidence,
    )


def _validate_types(
    decision: GovernanceDecision,
    change_set: ChangeSet,
    release_plan: ReleasePlan,
    version_resolution: VersionResolution,
    operation: GovernanceOperation,
    evidence: ReviewAuthorizationEvidence | None,
) -> None:
    expected = (
        (decision, GovernanceDecision, "decision"),
        (change_set, ChangeSet, "change_set"),
        (release_plan, ReleasePlan, "release_plan"),
        (version_resolution, VersionResolution, "version_resolution"),
        (operation, GovernanceOperation, "operation"),
    )
    for value, expected_type, name in expected:
        if not isinstance(value, expected_type):
            raise TypeError(
                f"{name} must be {expected_type.__name__}, got {type(value).__name__}"
            )
    if evidence is not None and not isinstance(evidence, ReviewAuthorizationEvidence):
        raise TypeError(
            "evidence must be ReviewAuthorizationEvidence or None, "
            f"got {type(evidence).__name__}"
        )


def _validate_release_context(
    decision: GovernanceDecision,
    change_set: ChangeSet,
    release_plan: ReleasePlan,
    version_resolution: VersionResolution,
) -> None:
    """Fail closed when immutable artifacts do not describe one release context."""
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


def _evidence_matches_release_context(
    evidence: ReviewAuthorizationEvidence,
    *,
    decision: GovernanceDecision,
    change_set: ChangeSet,
    release_plan: ReleasePlan,
    version_resolution: VersionResolution,
    operation: GovernanceOperation,
) -> bool:
    return (
        evidence.decision_id == decision.decision_id
        and evidence.change_set_id == change_set.change_set_id
        and evidence.release_plan_id == release_plan.release_plan_id
        and evidence.version_resolution_id == version_resolution.version_resolution_id
        and evidence.operation is operation
    )


def _build_authorization(
    *,
    decision: GovernanceDecision,
    change_set: ChangeSet,
    release_plan: ReleasePlan,
    version_resolution: VersionResolution,
    operation: GovernanceOperation,
    allowed: bool,
    reason: AuthorizationReason,
    evidence: ReviewAuthorizationEvidence | None = None,
) -> ContractOpsAuthorization:
    evidence_reference = evidence.evidence_reference if evidence is not None else None
    evidence_action = evidence.action if evidence is not None else None

    stable_record = {
        "decision_id": decision.decision_id,
        "change_set_id": change_set.change_set_id,
        "release_plan_id": release_plan.release_plan_id,
        "version_resolution_id": version_resolution.version_resolution_id,
        "operation": operation.value,
        "allowed": allowed,
        "reason": reason.value,
        "evidence_reference": evidence_reference,
        "evidence_action": evidence_action.value if evidence_action is not None else None,
    }
    canonical_payload = json.dumps(
        stable_record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    authorization_id = str(
        uuid.uuid5(SEMAPACT_CONTRACTOPS_AUTHORIZATION_NAMESPACE, canonical_payload)
    )

    return ContractOpsAuthorization(
        authorization_id=authorization_id,
        decision_id=decision.decision_id,
        change_set_id=change_set.change_set_id,
        release_plan_id=release_plan.release_plan_id,
        version_resolution_id=version_resolution.version_resolution_id,
        operation=operation,
        allowed=allowed,
        reason=reason,
        evidence_reference=evidence_reference,
        evidence_action=evidence_action,
    )
