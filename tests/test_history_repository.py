from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.change_context import ChangeContext
from semapact.contractops import build_change_set_from_decision
from semapact.governance import GovernanceDecision, evaluate_governance_decision
from semapact.history import (
    ChangeSetHistoryRepository,
    DecisionHistoryRepository,
    HistoryConflictError,
    HistoryCorruptionError,
    HistoryNotFoundError,
)
from semapact.platforms.git import GitWorkingTreeHistoryRepository


CONTEXT = ChangeContext(effective_date=date(2026, 9, 12))


def _contract(*, name: str) -> OpenDataContractStandard:
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders-product",
        name=name,
        version="1.0.0",
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


def _decision(*, candidate_name: str) -> GovernanceDecision:
    return evaluate_governance_decision(
        _contract(name="orders-base"),
        _contract(name=candidate_name),
        context=CONTEXT,
    )


def test_artifacts_round_trip_through_segregated_repository_ports(
    tmp_path: Path,
) -> None:
    backend = GitWorkingTreeHistoryRepository(tmp_path)
    decisions: DecisionHistoryRepository = backend
    change_sets: ChangeSetHistoryRepository = backend
    decision = _decision(candidate_name="orders-candidate")
    change_set = build_change_set_from_decision(
        decision,
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        source="history-test",
        actor_reference="service:ci",
    )

    decisions.put_decision(decision)
    change_sets.put_change_set(change_set)

    assert decisions.get_decision(decision.decision_id) == decision
    assert change_sets.get_change_set(change_set.change_set_id) == change_set
    assert change_sets.get_change_set(change_set.change_set_id).context == CONTEXT


def test_identical_writes_are_idempotent(tmp_path: Path) -> None:
    repository = GitWorkingTreeHistoryRepository(tmp_path)
    decision = _decision(candidate_name="orders-candidate")

    repository.put_decision(decision)
    repository.put_decision(decision)

    assert repository.get_decision(decision.decision_id) == decision


def test_conflicting_content_under_existing_id_fails_closed(tmp_path: Path) -> None:
    repository = GitWorkingTreeHistoryRepository(tmp_path)
    decision = _decision(candidate_name="orders-candidate")
    repository.put_decision(decision)

    conflicting = decision.model_copy(update={"contract_id": "different-contract"})

    with pytest.raises(HistoryConflictError, match="different content"):
        repository.put_decision(conflicting)


def test_corrupted_persisted_change_set_fails_closed(tmp_path: Path) -> None:
    repository = GitWorkingTreeHistoryRepository(tmp_path)
    decision = _decision(candidate_name="orders-candidate")
    change_set = build_change_set_from_decision(
        decision,
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
    )
    repository.put_change_set(change_set)

    path = (
        tmp_path
        / ".semapact"
        / "history"
        / "change_sets"
        / f"{change_set.change_set_id}.json"
    )
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(HistoryCorruptionError, match="is invalid"):
        repository.get_change_set(change_set.change_set_id)


def test_missing_artifact_has_explicit_not_found_error(tmp_path: Path) -> None:
    repository = GitWorkingTreeHistoryRepository(tmp_path)

    with pytest.raises(HistoryNotFoundError, match="was not found"):
        repository.get_decision("00000000-0000-0000-0000-000000000000")


def test_contract_scoped_lists_are_deterministic(tmp_path: Path) -> None:
    repository = GitWorkingTreeHistoryRepository(tmp_path)
    decisions = (
        _decision(candidate_name="orders-zeta"),
        _decision(candidate_name="orders-alpha"),
    )
    for decision in reversed(decisions):
        repository.put_decision(decision)

    listed = repository.list_decisions("orders-product")

    assert [item.decision_id for item in listed] == sorted(
        item.decision_id for item in decisions
    )
    assert repository.list_decisions("other-contract") == ()
