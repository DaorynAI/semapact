from __future__ import annotations

from datetime import date

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)
from pydantic import ValidationError as PydanticValidationError

from semapact.change_context import ChangeContext
from semapact.contractops import (
    ReleasePrecondition,
    build_change_set_from_decision,
    build_release_plan,
)
from semapact.exceptions import GovernanceBlockedError, ReleaseValidationError
from semapact.governance import DecisionResult, evaluate_governance_decision


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


def _proposal(
    base: OpenDataContractStandard,
    candidate: OpenDataContractStandard,
    *,
    base_revision_ref: str = "rev:base",
    candidate_revision_ref: str = "rev:candidate",
):
    decision = evaluate_governance_decision(base, candidate, context=CONTEXT)
    change_set = build_change_set_from_decision(
        decision,
        base_revision_ref=base_revision_ref,
        candidate_revision_ref=candidate_revision_ref,
        source="test",
        actor_reference="actor:test",
    )
    return change_set, decision


def test_allow_release_plan_is_deterministic_and_has_no_review_precondition() -> None:
    base = _contract(contract_name="orders-old")
    candidate = _contract(contract_name="orders-new")
    change_set, decision = _proposal(base, candidate)

    assert decision.decision is DecisionResult.ALLOW
    assert decision.required_version_bump == "none"
    assert decision.evidence.has_changes is True

    first = build_release_plan(change_set, decision)
    second = build_release_plan(change_set, decision)

    assert first == second
    assert first.release_plan_id == second.release_plan_id
    assert first.contract_id == change_set.contract_id
    assert first.change_set_id == change_set.change_set_id
    assert first.decision_id == decision.decision_id
    assert first.release_revision_ref == change_set.candidate_revision_ref
    assert first.required_version_bump == decision.required_version_bump
    assert first.preconditions == ()
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_review_release_plan_preserves_decision_and_requires_authorization() -> None:
    base = _contract()
    candidate = _contract(include_created_at=True)
    change_set, decision = _proposal(base, candidate)

    assert decision.decision is DecisionResult.REVIEW
    assert decision.required_version_bump == "minor"

    plan = build_release_plan(change_set, decision)

    assert decision.decision is DecisionResult.REVIEW
    assert plan.required_version_bump == "minor"
    assert plan.preconditions == (
        ReleasePrecondition.REVIEW_AUTHORIZATION_REQUIRED,
    )


def test_block_decision_cannot_produce_release_plan() -> None:
    base = _contract(contract_id="orders-product")
    candidate = _contract(contract_id="other-product")
    change_set, decision = _proposal(base, candidate)

    assert decision.decision is DecisionResult.BLOCK

    with pytest.raises(GovernanceBlockedError):
        build_release_plan(change_set, decision)


def test_release_plan_rejects_no_change_proposal() -> None:
    base = _contract()
    candidate = _contract()
    change_set, decision = _proposal(base, candidate)

    assert decision.decision is DecisionResult.ALLOW
    assert decision.evidence.has_changes is False

    with pytest.raises(ReleaseValidationError, match="no changes"):
        build_release_plan(change_set, decision)


def test_release_plan_fails_closed_for_mismatched_proposal_artifacts() -> None:
    base = _contract()
    review_candidate = _contract(include_created_at=True)
    metadata_candidate = _contract(contract_name="orders-changed")

    review_change_set, review_decision = _proposal(base, review_candidate)
    metadata_change_set, _ = _proposal(base, metadata_candidate)

    assert review_change_set.context == metadata_change_set.context
    assert review_change_set.contract_id == metadata_change_set.contract_id
    assert review_change_set.changes != metadata_change_set.changes

    with pytest.raises(ReleaseValidationError, match="changes do not match"):
        build_release_plan(metadata_change_set, review_decision)


def test_release_plan_identity_changes_with_exact_release_revision() -> None:
    base = _contract(contract_name="orders-old")
    candidate = _contract(contract_name="orders-new")
    first_change_set, first_decision = _proposal(
        base,
        candidate,
        candidate_revision_ref="rev:candidate-1",
    )
    second_change_set, second_decision = _proposal(
        base,
        candidate,
        candidate_revision_ref="rev:candidate-2",
    )

    first = build_release_plan(first_change_set, first_decision)
    second = build_release_plan(second_change_set, second_decision)

    assert first.release_revision_ref != second.release_revision_ref
    assert first.release_plan_id != second.release_plan_id


def test_release_plan_is_immutable() -> None:
    base = _contract(contract_name="orders-old")
    candidate = _contract(contract_name="orders-new")
    change_set, decision = _proposal(base, candidate)
    plan = build_release_plan(change_set, decision)

    with pytest.raises(PydanticValidationError):
        plan.contract_id = "other"  # type: ignore[misc]
