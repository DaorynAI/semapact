"""Durable governance-history persistence boundary.

History stores canonical domain artifacts without becoming a second source of
revision, governance, ContractOps, deployment, or reconciliation semantics.
"""

from semapact.history.models import (
    ChangeSetDecisionLink,
    DeploymentRecord,
    DeploymentStatus,
    ReleaseRecord,
)
from semapact.history.repository import (
    ChangeSetDecisionLinkHistoryRepository,
    ChangeSetHistoryRepository,
    ContractRevisionHistoryRepository,
    ContractRevisionSourceHistoryRepository,
    DecisionHistoryRepository,
    DeploymentAuthorizationHistoryRepository,
    DeploymentPlanHistoryRepository,
    DeploymentPreviewHistoryRepository,
    DeploymentRecordHistoryRepository,
    HistoryConflictError,
    HistoryCorruptionError,
    HistoryNotFoundError,
    HistoryRepositoryError,
    ReleasePlanHistoryRepository,
    ReleaseRecordHistoryRepository,
)

__all__ = [
    "ChangeSetDecisionLink",
    "ChangeSetDecisionLinkHistoryRepository",
    "ChangeSetHistoryRepository",
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
    "HistoryNotFoundError",
    "HistoryRepositoryError",
    "ReleasePlanHistoryRepository",
    "ReleaseRecord",
    "ReleaseRecordHistoryRepository",
]
