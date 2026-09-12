"""Durable governance-history persistence boundary.

History stores canonical domain artifacts without becoming a second source of
revision, governance, ContractOps, deployment, or reconciliation semantics.
"""

from semapact.history.repository import (
    ChangeSetHistoryRepository,
    ContractRevisionHistoryRepository,
    ContractRevisionSourceHistoryRepository,
    DecisionHistoryRepository,
    HistoryConflictError,
    HistoryCorruptionError,
    HistoryNotFoundError,
    HistoryRepositoryError,
)

__all__ = [
    "ChangeSetHistoryRepository",
    "ContractRevisionHistoryRepository",
    "ContractRevisionSourceHistoryRepository",
    "DecisionHistoryRepository",
    "HistoryConflictError",
    "HistoryCorruptionError",
    "HistoryNotFoundError",
    "HistoryRepositoryError",
]
