"""Storage-neutral governance history repository contract."""

from __future__ import annotations

from typing import Protocol

from semapact.contractops import ChangeSet
from semapact.governance import GovernanceDecision


class HistoryRepositoryError(RuntimeError):
    """Base error for durable governance-history access."""


class HistoryNotFoundError(HistoryRepositoryError):
    """Requested historical artifact does not exist."""


class HistoryConflictError(HistoryRepositoryError):
    """An immutable artifact ID already exists with different content."""


class HistoryCorruptionError(HistoryRepositoryError):
    """Persisted or supplied historical content fails canonical validation."""


class GovernanceHistoryRepository(Protocol):
    """Typed persistence/query port for canonical governance history.

    The port deliberately starts with artifacts that already have canonical M0/M2
    ownership. M3 adapters persist and retrieve these exact models rather than
    defining storage-owned replacements.
    """

    def put_decision(self, decision: GovernanceDecision) -> None:
        """Persist one immutable GovernanceDecision idempotently."""
        ...

    def get_decision(self, decision_id: str) -> GovernanceDecision:
        """Load one GovernanceDecision by its exact artifact ID."""
        ...

    def list_decisions(self, contract_id: str) -> tuple[GovernanceDecision, ...]:
        """List decisions for one contract in deterministic artifact-ID order."""
        ...

    def put_change_set(self, change_set: ChangeSet) -> None:
        """Persist one immutable ChangeSet idempotently."""
        ...

    def get_change_set(self, change_set_id: str) -> ChangeSet:
        """Load one ChangeSet by its exact artifact ID."""
        ...

    def list_change_sets(self, contract_id: str) -> tuple[ChangeSet, ...]:
        """List ChangeSets for one contract in deterministic artifact-ID order."""
        ...
