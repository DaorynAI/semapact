"""Durable governance-history boundary.

History persists canonical domain artifacts without becoming a second source of
governance, ContractOps, deployment, or reconciliation semantics.
"""

from semapact.history.repository import (
    GovernanceHistoryRepository,
    HistoryConflictError,
    HistoryCorruptionError,
    HistoryNotFoundError,
    HistoryRepositoryError,
)

__all__ = [
    "GovernanceHistoryRepository",
    "HistoryConflictError",
    "HistoryCorruptionError",
    "HistoryNotFoundError",
    "HistoryRepositoryError",
]
