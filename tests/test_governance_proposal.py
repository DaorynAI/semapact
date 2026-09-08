from __future__ import annotations

from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)
import pytest

import semapact.services.governance_service as governance_service_module
from semapact.services import GovernanceService


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


def test_evaluate_proposal_evaluates_once_and_reuses_authoritative_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _contract("STRING")
    candidate = _contract("BIGINT")
    original = governance_service_module.evaluate_governance_decision
    calls = 0

    def counted_evaluator(*args: object, **kwargs: object):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        governance_service_module,
        "evaluate_governance_decision",
        counted_evaluator,
    )

    proposal = GovernanceService().evaluate_proposal(
        base,
        candidate,
        effective_date="2026-09-09",
        base_revision_ref="git:abc123",
        candidate_revision_ref="git:def456",
        source="api",
        actor_reference="service:ci",
    )

    assert calls == 1
    assert proposal.change_set.changes == proposal.decision.changes
    assert proposal.change_set.context is proposal.decision.context
    assert proposal.change_set.base_revision_ref == "git:abc123"
    assert proposal.change_set.candidate_revision_ref == "git:def456"
    assert proposal.change_set.source == "api"
    assert proposal.change_set.actor_reference == "service:ci"
