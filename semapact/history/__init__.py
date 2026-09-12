"""Durable governance-history boundary.

History persists canonical domain artifacts without becoming a second source of
governance, ContractOps, deployment, or reconciliation semantics.
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
from semapact.history.revisions import (
    SEMAPACT_CONTRACT_REVISION_NAMESPACE,
    SEMAPACT_CONTRACT_REVISION_SOURCE_NAMESPACE,
    ContractRevision,
    ContractRevisionSource,
    build_contract_revision,
    compute_contract_content_fingerprint,
    compute_contract_revision_id,
    compute_contract_revision_source_id,
    link_contract_revision_source,
)

__all__ = [
    "ChangeSetHistoryRepository",
    "ContractRevision",
    "ContractRevisionHistoryRepository",
    "ContractRevisionSource",
    "ContractRevisionSourceHistoryRepository",
    "DecisionHistoryRepository",
    "HistoryConflictError",
    "HistoryCorruptionError",
    "HistoryNotFoundError",
    "HistoryRepositoryError",
    "SEMAPACT_CONTRACT_REVISION_NAMESPACE",
    "SEMAPACT_CONTRACT_REVISION_SOURCE_NAMESPACE",
    "build_contract_revision",
    "compute_contract_content_fingerprint",
    "compute_contract_revision_id",
    "compute_contract_revision_source_id",
    "link_contract_revision_source",
]
