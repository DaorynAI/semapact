"""Pure authorization composition for review-required ContractOps actions."""

from __future__ import annotations

from semapact.contractops.context import validate_release_context
from semapact.contractops.integrity import (
    SEMAPACT_CONTRACTOPS_AUTHORIZATION_NAMESPACE,
    compute_contractops_authorization_id,
)
from semapact.contractops.models import (
    AuthorizationReason,
    ChangeSet,
    ContractOpsAuthorization,
    ReleasePlan,
    ReviewAuthorizationEvidence,
    ReviewEvidenceAction,
    VersionResolution,
)
from semapact.governance.gate import GovernanceOperation, evaluate_governance_gate
from semapact.governance.models import GovernanceDecision


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
    evidence. It never mutates or reinterprets the GovernanceDecision. Optional
    downstream scope provenance is preserved opaquely for the owning domain to
    validate later.
    """
    _validate_types(
        decision,
        change_set,
        release_plan,
        version_resolution,
        operation,
        evidence,
    )
    validate_release_context(decision, change_set, release_plan, version_resolution)

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
    scope_reference = evidence.scope_reference if evidence is not None else None

    authorization_id = compute_contractops_authorization_id(
        decision_id=decision.decision_id,
        change_set_id=change_set.change_set_id,
        release_plan_id=release_plan.release_plan_id,
        version_resolution_id=version_resolution.version_resolution_id,
        operation=operation,
        allowed=allowed,
        reason=reason.value,
        evidence_reference=evidence_reference,
        evidence_action=(evidence_action.value if evidence_action is not None else None),
        scope_reference=scope_reference,
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
        scope_reference=scope_reference,
    )
