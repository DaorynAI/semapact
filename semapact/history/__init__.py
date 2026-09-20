"""Durable governance-history persistence boundary.

History stores canonical domain artifacts without becoming a second source of
revision, governance, ContractOps, deployment, or reconciliation semantics.
"""

from semapact.history.models import (
    ChangeSetDecisionLink,
    ContractReleaseRecord,
    DeploymentRecord,
    DeploymentStatus,
    HistoryIntegrityIssueCode,
    HistoryStorageIntegrityIssue,
    ReleaseRecord,
    RuntimeObservationRecord,
    RuntimeReconciliationRecord,
)
from semapact.history.repository import (
    ApprovalHistoryRepository,
    ChangeSetDecisionLinkHistoryRepository,
    ChangeSetHistoryRepository,
    ContractReleaseHistoryRepository,
    ContractRevisionHistoryRepository,
    ContractRevisionSourceHistoryRepository,
    DecisionHistoryRepository,
    DeploymentAuthorizationHistoryRepository,
    DeploymentPlanHistoryRepository,
    DeploymentPreviewHistoryRepository,
    DeploymentRecordHistoryRepository,
    HistoryConflictError,
    HistoryCorruptionError,
    HistoryIntegrityRepository,
    HistoryNotFoundError,
    HistoryRepositoryError,
    ReleasePlanHistoryRepository,
    ReleaseRecordHistoryRepository,
    RuntimeObservationHistoryRepository,
    RuntimeReconciliationHistoryRepository,
)

__all__ = [
    "ApprovalHistoryRepository",
    "ChangeSetDecisionLink",
    "ChangeSetDecisionLinkHistoryRepository",
    "ChangeSetHistoryRepository",
    "ContractReleaseHistoryRepository",
    "ContractReleaseRecord",
    "ContractRevisionHistoryRepository",
    "ContractRevisionSourceHistoryRepository",
    "DecisionHistoryRepository",
    "DeploymentAuthorizationHistoryRepository",
    "DeploymentPlanHistoryRepository",
    "DeploymentPreviewHistoryRepository",
    "DeploymentRecord",
    "DeploymentRecordHistoryRepository",
    "DeploymentStatus",
    "HistoryConflictError",
    "HistoryCorruptionError",
    "HistoryIntegrityIssueCode",
    "HistoryIntegrityRepository",
    "HistoryNotFoundError",
    "HistoryRepositoryError",
    "HistoryStorageIntegrityIssue",
    "ReleasePlanHistoryRepository",
    "ReleaseRecord",
    "ReleaseRecordHistoryRepository",
    "RuntimeObservationHistoryRepository",
    "RuntimeObservationRecord",
    "RuntimeReconciliationHistoryRepository",
    "RuntimeReconciliationRecord",
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
