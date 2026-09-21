"""Durable governance-history persistence boundary."""

from semapact.history.models import (
    ChangeSetDecisionLink,
    HistoryIntegrityIssueCode,
    HistoryStorageIntegrityIssue,
)
from semapact.history.repository import (
    ApprovalHistoryRepository,
    ChangeSetDecisionLinkHistoryRepository,
    ChangeSetHistoryRepository,
    ContractReleaseHistoryRepository,
    ContractRevisionHistoryRepository,
    ContractRevisionSourceHistoryRepository,
    DecisionHistoryRepository,
    HistoryConflictError,
    HistoryCorruptionError,
    HistoryIntegrityRepository,
    HistoryNotFoundError,
    HistoryRepositoryError,
    ReleasePlanHistoryRepository,
)

__all__ = [
    "ApprovalHistoryRepository",
    "ChangeSetDecisionLink",
    "ChangeSetDecisionLinkHistoryRepository",
    "ChangeSetHistoryRepository",
    "ContractReleaseHistoryRepository",
    "ContractRevisionHistoryRepository",
    "ContractRevisionSourceHistoryRepository",
    "DecisionHistoryRepository",
    "HistoryConflictError",
    "HistoryCorruptionError",
    "HistoryIntegrityIssueCode",
    "HistoryIntegrityRepository",
    "HistoryNotFoundError",
    "HistoryRepositoryError",
    "HistoryStorageIntegrityIssue",
    "ReleasePlanHistoryRepository",
]


from semapact.history.operational import (
    OperationalDeploymentEvent,
    OperationalHistorySink,
    build_operational_deployment_event,
)
from semapact.history.operational_registry import create_operational_history_sink

__all__.extend(
    [
        "OperationalDeploymentEvent",
        "OperationalHistorySink",
        "build_operational_deployment_event",
        "create_operational_history_sink",
    ]
)
