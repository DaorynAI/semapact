"""Application orchestration for durable governance history."""

from __future__ import annotations

from semapact.contractops import ChangeSet
from semapact.governance import GovernanceDecision
from semapact.history import GovernanceHistoryRepository


class GovernanceHistoryService:
    """Thin typed facade over the configured history repository."""

    def __init__(self, repository: GovernanceHistoryRepository) -> None:
        self._repository = repository

    def record_decision(self, decision: GovernanceDecision) -> None:
        self._repository.put_decision(decision)

    def get_decision(self, decision_id: str) -> GovernanceDecision:
        return self._repository.get_decision(decision_id)

    def list_decisions(self, contract_id: str) -> tuple[GovernanceDecision, ...]:
        return self._repository.list_decisions(contract_id)

    def record_change_set(self, change_set: ChangeSet) -> None:
        self._repository.put_change_set(change_set)

    def get_change_set(self, change_set_id: str) -> ChangeSet:
        return self._repository.get_change_set(change_set_id)

    def list_change_sets(self, contract_id: str) -> tuple[ChangeSet, ...]:
        return self._repository.list_change_sets(contract_id)
