from __future__ import annotations

from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)
import pytest

from semapact.application import (
    ApplicationCapabilityUnavailableError,
    SemaPactApplicationService,
)
from semapact.application.models.evolution import ContractEvolution
from semapact.application.services.governance import GovernanceService


def _contract(*, name: str, include_note: bool = False) -> OpenDataContractStandard:
    properties = [
        SchemaProperty(
            name="id",
            logicalType="string",
            physicalType="varchar(255)",
            required=True,
        )
    ]
    if include_note:
        properties.append(
            SchemaProperty(
                name="note",
                logicalType="string",
                physicalType="varchar(255)",
                required=False,
            )
        )
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders-product",
        name=name,
        version="1.2.3",
        status="active",
        schema=[SchemaObject(name="orders", properties=properties)],
    )


class _CountingGovernanceService(GovernanceService):
    def __init__(self) -> None:
        super().__init__()
        self.evaluate_calls = 0
        self.proposal_calls = 0

    def evaluate(self, *args, **kwargs):
        self.evaluate_calls += 1
        return super().evaluate(*args, **kwargs)

    def evaluate_proposal(self, *args, **kwargs):
        self.proposal_calls += 1
        return super().evaluate_proposal(*args, **kwargs)


class _DecisionRepository:
    def __init__(self, decision) -> None:
        self.decision = decision
        self.requested_ids: list[str] = []

    def get_decision(self, decision_id: str):
        self.requested_ids.append(decision_id)
        return self.decision


class _EvolutionService:
    def __init__(self, result: ContractEvolution) -> None:
        self.result = result
        self.contract_ids: list[str] = []

    def reconstruct(self, contract_id: str) -> ContractEvolution:
        self.contract_ids.append(contract_id)
        return self.result


def test_facade_routes_analysis_through_canonical_governance_service() -> None:
    governance = _CountingGovernanceService()
    service = SemaPactApplicationService(governance=governance)

    decision = service.analyze_contract(
        _contract(name="Orders old"),
        _contract(name="Orders new"),
        effective_date="2026-09-20",
    )

    assert governance.evaluate_calls == 1
    assert governance.proposal_calls == 0
    assert decision.contract_id == "orders-product"


def test_prepare_release_reuses_injected_governance_service_once() -> None:
    governance = _CountingGovernanceService()
    service = SemaPactApplicationService(governance=governance)

    result = service.prepare_release(
        _contract(name="Orders old"),
        _contract(name="Orders new", include_note=True),
        effective_date="2026-09-20",
        base_revision_ref="revision:base",
        candidate_revision_ref="revision:candidate",
    )

    assert governance.evaluate_calls == 0
    assert governance.proposal_calls == 1
    assert result.change_set.changes == result.decision.changes
    assert result.release_plan.change_set_id == result.change_set.change_set_id
    assert result.release_plan.decision_id == result.decision.decision_id
    assert result.version_resolution.release_plan_id == result.release_plan.release_plan_id


def test_facade_reads_persisted_decision_without_recomputing_governance() -> None:
    governance = _CountingGovernanceService()
    decision = governance.evaluate(
        _contract(name="Orders old"),
        _contract(name="Orders new"),
        effective_date="2026-09-20",
    )
    repository = _DecisionRepository(decision)
    service = SemaPactApplicationService(
        governance=governance,
        decisions=repository,
    )
    baseline_evaluate_calls = governance.evaluate_calls

    resolved = service.get_decision(decision.decision_id)

    assert resolved is decision
    assert repository.requested_ids == [decision.decision_id]
    assert governance.evaluate_calls == baseline_evaluate_calls


def test_facade_reads_history_through_m3_read_service() -> None:
    expected = ContractEvolution(contract_id="orders-product")
    evolution = _EvolutionService(expected)
    service = SemaPactApplicationService(evolution=evolution)

    actual = service.get_history("orders-product")

    assert actual == expected
    assert evolution.contract_ids == ["orders-product"]


@pytest.mark.parametrize(
    "operation,capability",
    [
        ("decision", "decision_history"),
        ("history", "evolution_history"),
    ],
)
def test_unconfigured_optional_read_capability_has_stable_application_error(
    operation: str,
    capability: str,
) -> None:
    service = SemaPactApplicationService()

    with pytest.raises(ApplicationCapabilityUnavailableError) as caught:
        if operation == "decision":
            service.get_decision("decision-1")
        else:
            service.get_history("orders-product")

    assert caught.value.capability == capability
    assert capability in str(caught.value)
