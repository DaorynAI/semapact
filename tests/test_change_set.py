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
from semapact.contractops import build_change_set, build_change_set_from_decision
from semapact.governance import evaluate_governance_decision
from semapact.lifecycle.changes import (
    GovernanceChange,
    GovernanceChangeDomain,
    GovernanceChangeType,
    GovernanceEntityType,
)


def _change(name: str, *, before: str, after: str) -> GovernanceChange:
    return GovernanceChange(
        change_type=GovernanceChangeType.MODIFY,
        entity_type=GovernanceEntityType.PROPERTY,
        identity=("orders", name),
        path=f"schema[orders].properties[{name}].physicalType",
        field="physicalType",
        before=before,
        after=after,
        domain=GovernanceChangeDomain.STRUCTURE,
    )


def _contract(physical_type: str) -> OpenDataContractStandard:
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders-product",
        name="orders-product",
        version="1.0.0",
        status="active",
        schema=[
            SchemaObject(
                name="orders",
                properties=[
                    SchemaProperty(
                        name="id",
                        physicalType=physical_type,
                        logicalType="string",
                    )
                ],
            )
        ],
    )


def test_changeset_identity_is_deterministic_and_change_order_independent() -> None:
    context = ChangeContext(effective_date=date(2026, 9, 9))
    id_change = _change("id", before="STRING", after="BIGINT")
    amount_change = _change("amount", before="DECIMAL(10,2)", after="DECIMAL(18,2)")

    first = build_change_set(
        contract_id="orders-product",
        base_revision_ref="git:abc123",
        candidate_revision_ref="git:def456",
        changes=(id_change, amount_change),
        context=context,
    )
    second = build_change_set(
        contract_id="orders-product",
        base_revision_ref="git:abc123",
        candidate_revision_ref="git:def456",
        changes=(amount_change, id_change),
        context=context,
    )

    assert first == second
    assert first.change_set_id == second.change_set_id
    assert first.changes == (amount_change, id_change)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_changeset_identity_changes_with_revision_or_governance_context() -> None:
    change = _change("id", before="STRING", after="BIGINT")
    base_args = {
        "contract_id": "orders-product",
        "base_revision_ref": "git:abc123",
        "candidate_revision_ref": "git:def456",
        "changes": (change,),
    }

    first = build_change_set(
        **base_args,
        context=ChangeContext(effective_date=date(2026, 9, 9)),
    )
    different_candidate = build_change_set(
        **{**base_args, "candidate_revision_ref": "git:ghi789"},
        context=ChangeContext(effective_date=date(2026, 9, 9)),
    )
    different_context = build_change_set(
        **base_args,
        context=ChangeContext(effective_date=date(2026, 9, 10)),
    )

    assert first.change_set_id != different_candidate.change_set_id
    assert first.change_set_id != different_context.change_set_id


def test_provenance_does_not_redefine_proposal_identity() -> None:
    change = _change("id", before="STRING", after="BIGINT")
    context = ChangeContext(effective_date=date(2026, 9, 9))

    first = build_change_set(
        contract_id="orders-product",
        base_revision_ref="git:abc123",
        candidate_revision_ref="git:def456",
        changes=(change,),
        context=context,
        source="cli",
        actor_reference="user:alice",
    )
    second = build_change_set(
        contract_id="orders-product",
        base_revision_ref="git:abc123",
        candidate_revision_ref="git:def456",
        changes=(change,),
        context=context,
        source="api",
        actor_reference="service:ci",
    )

    assert first.change_set_id == second.change_set_id
    assert first.source == "cli"
    assert second.source == "api"
    assert first.actor_reference == "user:alice"
    assert second.actor_reference == "service:ci"


def test_changeset_is_immutable() -> None:
    change_set = build_change_set(
        contract_id="orders-product",
        base_revision_ref="git:abc123",
        candidate_revision_ref="git:def456",
        changes=(),
        context=ChangeContext(effective_date=date(2026, 9, 9)),
    )

    with pytest.raises(PydanticValidationError):
        change_set.contract_id = "other"  # type: ignore[misc]


def test_changeset_from_decision_reuses_authoritative_changes_and_context() -> None:
    base = _contract("STRING")
    candidate = _contract("BIGINT")
    context = ChangeContext(effective_date=date(2026, 9, 9))
    decision = evaluate_governance_decision(base, candidate, context=context)

    change_set = build_change_set_from_decision(
        decision,
        base_revision_ref="git:abc123",
        candidate_revision_ref="git:def456",
    )

    assert change_set.contract_id == decision.contract_id
    assert change_set.context is decision.context
    assert change_set.changes == decision.changes
    assert change_set.base_revision_ref == "git:abc123"
    assert change_set.candidate_revision_ref == "git:def456"
