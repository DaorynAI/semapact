"""Durable governance-history boundary.

History persists canonical domain artifacts without becoming a second source of
governance, ContractOps, deployment, or reconciliation semantics.
"""

from semapact.history.repository import (
    ChangeSetHistoryRepository,
    DecisionHistoryRepository,
    HistoryConflictError,
    HistoryCorruptionError,
    HistoryNotFoundError,
    HistoryRepositoryError,
)

__all__ = [
    "ChangeSetHistoryRepository",
    "DecisionHistoryRepository",
    "HistoryConflictError",
    "HistoryCorruptionError",
    "HistoryNotFoundError",
    "HistoryRepositoryError",
]
