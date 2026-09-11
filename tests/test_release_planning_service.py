from __future__ import annotations

from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.contractops import VersionAuthorityConfig, resolve_release_version
from semapact.services import GovernanceService, ReleasePlanningService


class CountingGovernanceService:
    def __init__(self) -> None:
        self.calls = 0
        self._delegate = GovernanceService()

    def evaluate_proposal(self, *args, **kwargs):
        self.calls += 1
        return self._delegate.evaluate_proposal(*args, **kwargs)


class FixedVersionAuthorityService:
    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, release_plan, released_contract, *, authority_reference=None):
        self.calls += 1
        assert authority_reference is None
        return resolve_release_version(
            release_plan,
            current_version=str(released_contract.version),
            config=VersionAuthorityConfig(),
        )


def _contract(*, name: str) -> OpenDataContractStandard:
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders-product",
        name=name,
        version="1.2.3",
        status="active",
        schema=[
            SchemaObject(
                name="orders",
                properties=[
                    SchemaProperty(
                        name="id",
                        logicalType="string",
                        physicalType="varchar(255)",
                        required=True,
                    )
                ],
            )
        ],
    )


def test_release_planning_composes_one_decision_into_exact_m2_artifacts() -> None:
    governance = CountingGovernanceService()
    version_authority = FixedVersionAuthorityService()
    service = ReleasePlanningService(
        governance_service=governance,
        version_authority_service=version_authority,
    )

    result = service.plan(
        _contract(name="Orders old"),
        _contract(name="Orders new"),
        effective_date="2026-09-11",
        base_revision_ref="git:base-123",
        candidate_revision_ref="git:candidate-456",
    )

    assert governance.calls == 1
    assert version_authority.calls == 1
    assert result.change_set.contract_id == "orders-product"
    assert result.change_set.base_revision_ref == "git:base-123"
    assert result.change_set.candidate_revision_ref == "git:candidate-456"
    assert result.release_plan.change_set_id == result.change_set.change_set_id
    assert result.release_plan.decision_id == result.decision.decision_id
    assert result.release_plan.release_revision_ref == "git:candidate-456"
    assert result.version_resolution.release_plan_id == result.release_plan.release_plan_id
    assert result.version_resolution.current_version == "1.2.3"
    assert result.version_resolution.selected_version == "1.2.4"


def test_release_planning_is_deterministic_for_same_exact_inputs() -> None:
    service = ReleasePlanningService(
        governance_service=GovernanceService(),
        version_authority_service=FixedVersionAuthorityService(),
    )
    base = _contract(name="Orders old")
    candidate = _contract(name="Orders new")

    first = service.plan(
        base,
        candidate,
        effective_date="2026-09-11",
        base_revision_ref="git:base-123",
        candidate_revision_ref="git:candidate-456",
    )
    second = service.plan(
        base,
        candidate,
        effective_date="2026-09-11",
        base_revision_ref="git:base-123",
        candidate_revision_ref="git:candidate-456",
    )

    assert first == second
    assert first.change_set.change_set_id == second.change_set.change_set_id
    assert first.release_plan.release_plan_id == second.release_plan.release_plan_id
    assert (
        first.version_resolution.version_resolution_id
        == second.version_resolution.version_resolution_id
    )
