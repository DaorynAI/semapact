from __future__ import annotations

from datetime import date

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.change_context import ChangeContext
from semapact.contractops import (
    AuthorizationReason,
    ReleasePlan,
    ReviewAuthorizationEvidence,
    ReviewEvidenceAction,
    VersionAuthorityConfig,
    authorize_contract_operation,
    build_change_set_from_decision,
    build_release_plan,
    resolve_release_version,
)
from semapact.exceptions import ReleaseValidationError
from semapact.governance import DecisionResult, evaluate_governance_decision
from semapact.governance.gate import GovernanceOperation


CONTEXT = ChangeContext(effective_date=date(2026, 9, 9))


def _contract(
    *,
    contract_id: str = "orders-product",
    contract_name: str | None = None,
    include_created_at: bool = False,
) -> OpenDataContractStandard:
    properties = [
        SchemaProperty(
            name="id",
            logicalType="string",
            physicalType="varchar(255)",
            required=True,
        )
    ]
    if include_created_at:
        properties.append(
            SchemaProperty(
                name="created_at",
                logicalType="timestamp",
                physicalType="timestamp",
                required=False,
            )
        )
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id=contract_id,
        name=contract_name or contract_id,
        version="1.0.0",
        status="active",
        schema=[SchemaObject(name="orders", properties=properties)],
    )


def _release_context(kind: str):
    base = _contract(contract_name="orders-old")
    if kind == "allow":
        candidate = _contract(contract_name="orders-new")
    elif kind == "review":
        candidate = _contract(contract_name="orders-old", include_created_at=True)
    elif kind == "block":
        candidate = _contract(contract_id="other-product", contract_name="orders-old")
    else:  # pragma: no cover - test helper guard
        raise ValueError(kind)

    decision = evaluate_governance_decision(base, candidate, context=CONTEXT)
    change_set = build_change_set_from_decision(
        decision,
        base_revision_ref="rev:base",
        candidate_revision_ref="rev:candidate",
        source="test",
        actor_reference="actor:test",
    )

    if decision.decision is DecisionResult.BLOCK:
        # BLOCK cannot normally produce a ReleasePlan. Constructing an internally
        # associated plan here proves that explicit review evidence still cannot
        # override the authoritative M0 BLOCK result.
        release_plan = ReleasePlan(
            release_plan_id="release-plan-block-test",
            contract_id=change_set.contract_id,
            change_set_id=change_set.change_set_id,
            decision_id=decision.decision_id,
            release_revision_ref=change_set.candidate_revision_ref,
            required_version_bump=decision.required_version_bump,
        )
    else:
        release_plan = build_release_plan(change_set, decision)

    version_resolution = resolve_release_version(
        release_plan,
        current_version="1.0.0",
        config=VersionAuthorityConfig(),
    )
    return decision, change_set, release_plan, version_resolution


def _evidence(
    decision,
    change_set,
    release_plan,
    version_resolution,
    *,
    operation: GovernanceOperation = GovernanceOperation.PUBLISH,
    action: ReviewEvidenceAction = ReviewEvidenceAction.APPROVE,
    evidence_reference: str = "approval:test-1",
    version_resolution_id: str | None = None,
) -> ReviewAuthorizationEvidence:
    return ReviewAuthorizationEvidence(
        evidence_reference=evidence_reference,
        decision_id=decision.decision_id,
        change_set_id=change_set.change_set_id,
        release_plan_id=release_plan.release_plan_id,
        version_resolution_id=(
            version_resolution_id or version_resolution.version_resolution_id
        ),
        operation=operation,
        action=action,
    )


def test_allow_requires_no_synthetic_review_evidence() -> None:
    decision, change_set, release_plan, version_resolution = _release_context("allow")

    result = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.PUBLISH,
    )

    assert decision.decision is DecisionResult.ALLOW
    assert result.allowed is True
    assert result.reason is AuthorizationReason.ALLOWED_BY_GOVERNANCE
    assert result.evidence_reference is None
    assert result.evidence_action is None


def test_review_without_evidence_remains_denied() -> None:
    decision, change_set, release_plan, version_resolution = _release_context("review")

    result = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.PUBLISH,
    )

    assert decision.decision is DecisionResult.REVIEW
    assert result.allowed is False
    assert result.reason is AuthorizationReason.REVIEW_AUTHORIZATION_REQUIRED


def test_matching_approval_authorizes_review_without_rewriting_decision() -> None:
    decision, change_set, release_plan, version_resolution = _release_context("review")
    evidence = _evidence(decision, change_set, release_plan, version_resolution)

    result = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.PUBLISH,
        evidence=evidence,
    )

    assert decision.decision is DecisionResult.REVIEW
    assert result.allowed is True
    assert result.reason is AuthorizationReason.ALLOWED_BY_REVIEW
    assert result.evidence_reference == evidence.evidence_reference
    assert result.evidence_action is ReviewEvidenceAction.APPROVE


@pytest.mark.parametrize(
    "action",
    [ReviewEvidenceAction.REJECT, ReviewEvidenceAction.REQUEST_CHANGES],
)
def test_rejected_review_evidence_cannot_authorize(
    action: ReviewEvidenceAction,
) -> None:
    decision, change_set, release_plan, version_resolution = _release_context("review")
    evidence = _evidence(
        decision,
        change_set,
        release_plan,
        version_resolution,
        action=action,
    )

    result = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.PUBLISH,
        evidence=evidence,
    )

    assert result.allowed is False
    assert result.reason is AuthorizationReason.REVIEW_AUTHORIZATION_REJECTED
    assert result.evidence_action is action


def test_stale_version_resolution_evidence_cannot_authorize() -> None:
    decision, change_set, release_plan, version_resolution = _release_context("review")
    evidence = _evidence(
        decision,
        change_set,
        release_plan,
        version_resolution,
        version_resolution_id="version-resolution:stale",
    )

    result = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.PUBLISH,
        evidence=evidence,
    )

    assert result.allowed is False
    assert result.reason is AuthorizationReason.REVIEW_AUTHORIZATION_MISMATCH


def test_approval_is_operation_scoped() -> None:
    decision, change_set, release_plan, version_resolution = _release_context("review")
    evidence = _evidence(
        decision,
        change_set,
        release_plan,
        version_resolution,
        operation=GovernanceOperation.APPLY,
    )

    result = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.PUBLISH,
        evidence=evidence,
    )

    assert result.allowed is False
    assert result.reason is AuthorizationReason.REVIEW_AUTHORIZATION_MISMATCH


def test_block_cannot_be_overridden_by_approval_evidence() -> None:
    decision, change_set, release_plan, version_resolution = _release_context("block")
    evidence = _evidence(decision, change_set, release_plan, version_resolution)

    result = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.PUBLISH,
        evidence=evidence,
    )

    assert decision.decision is DecisionResult.BLOCK
    assert result.allowed is False
    assert result.reason is AuthorizationReason.BLOCKED_BY_GOVERNANCE
    assert result.evidence_reference is None
    assert result.evidence_action is None


def test_invalid_release_context_fails_closed_before_authorization() -> None:
    decision, change_set, release_plan, version_resolution = _release_context("review")
    invalid_plan = ReleasePlan(
        release_plan_id=release_plan.release_plan_id,
        contract_id=release_plan.contract_id,
        change_set_id="change-set:other",
        decision_id=release_plan.decision_id,
        release_revision_ref=release_plan.release_revision_ref,
        required_version_bump=release_plan.required_version_bump,
        preconditions=release_plan.preconditions,
    )

    with pytest.raises(ReleaseValidationError, match="supplied ChangeSet"):
        authorize_contract_operation(
            decision,
            change_set,
            invalid_plan,
            version_resolution,
            GovernanceOperation.PUBLISH,
        )


def test_authorization_is_deterministic_for_equivalent_inputs() -> None:
    decision, change_set, release_plan, version_resolution = _release_context("review")
    evidence = _evidence(decision, change_set, release_plan, version_resolution)

    first = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.PUBLISH,
        evidence=evidence,
    )
    second = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.PUBLISH,
        evidence=evidence,
    )

    assert first == second
    assert first.authorization_id == second.authorization_id
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
