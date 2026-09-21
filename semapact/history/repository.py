"""Storage-neutral typed persistence ports for governance history."""

from __future__ import annotations

from typing import Protocol

from semapact.approval.models import ApprovalRecord
from semapact.contractops import ChangeSet, ContractRelease, ReleasePlan
from semapact.governance import GovernanceDecision
from semapact.governance.gate import GovernanceOperation
from semapact.history.models import (
    ChangeSetDecisionLink,
    HistoryStorageIntegrityIssue,
)
from semapact.revision.models import ContractRevision, ContractRevisionSource


class HistoryRepositoryError(RuntimeError):
    """Base error for durable governance-history access."""


class HistoryNotFoundError(HistoryRepositoryError):
    """Requested historical artifact does not exist."""


class HistoryConflictError(HistoryRepositoryError):
    """An immutable artifact ID already exists with different content."""


class HistoryCorruptionError(HistoryRepositoryError):
    """Persisted or supplied historical content fails canonical validation."""


class HistoryIntegrityRepository(Protocol):
    """Backend-specific physical integrity inspection without history mutation."""

    def inspect_history_integrity(self) -> tuple[HistoryStorageIntegrityIssue, ...]: ...


class DecisionHistoryRepository(Protocol):
    """Persistence capability for canonical GovernanceDecision history only."""

    def put_decision(self, decision: GovernanceDecision) -> None: ...
    def get_decision(self, decision_id: str) -> GovernanceDecision: ...
    def list_decisions(self, contract_id: str) -> tuple[GovernanceDecision, ...]: ...


class ChangeSetHistoryRepository(Protocol):
    """Persistence capability for canonical ChangeSet history only."""

    def put_change_set(self, change_set: ChangeSet) -> None: ...
    def get_change_set(self, change_set_id: str) -> ChangeSet: ...
    def list_change_sets(self, contract_id: str) -> tuple[ChangeSet, ...]: ...


class ChangeSetDecisionLinkHistoryRepository(Protocol):
    """Persistence capability for ChangeSet-to-decision audit provenance only."""

    def put_change_set_decision_link(self, link: ChangeSetDecisionLink) -> None: ...

    def list_change_set_decision_links(
        self,
        change_set_id: str,
    ) -> tuple[ChangeSetDecisionLink, ...]: ...


class ApprovalHistoryRepository(Protocol):
    """Persistence capability for immutable ApprovalRecord history only."""

    def put_approval_record(self, record: ApprovalRecord) -> None: ...
    def get_approval_record(self, approval_id: str) -> ApprovalRecord: ...

    def list_approval_records_for_context(
        self,
        *,
        decision_id: str,
        change_set_id: str,
        release_plan_id: str,
        version_resolution_id: str,
        operation: GovernanceOperation,
    ) -> tuple[ApprovalRecord, ...]: ...


class ContractRevisionHistoryRepository(Protocol):
    """Persistence capability for immutable ContractRevision history only."""

    def put_revision(self, revision: ContractRevision) -> None: ...
    def get_revision(self, revision_id: str) -> ContractRevision: ...
    def list_revisions(self, contract_id: str) -> tuple[ContractRevision, ...]: ...


class ContractRevisionSourceHistoryRepository(Protocol):
    """Persistence capability for immutable revision provenance links only."""

    def put_revision_source(self, source: ContractRevisionSource) -> None: ...
    def get_revision_source(self, source_link_id: str) -> ContractRevisionSource: ...

    def list_revision_sources(
        self,
        revision_id: str,
    ) -> tuple[ContractRevisionSource, ...]: ...


class ReleasePlanHistoryRepository(Protocol):
    """Persistence capability for canonical ReleasePlan history only."""

    def put_release_plan(self, release_plan: ReleasePlan) -> None: ...
    def get_release_plan(self, release_plan_id: str) -> ReleasePlan: ...


class ContractReleaseHistoryRepository(Protocol):
    """Persistence capability for finalized formal contract release facts."""

    def put_contract_release(self, record: ContractRelease) -> None: ...
    def get_contract_release(self, contract_release_id: str) -> ContractRelease: ...
    def list_contract_releases(
        self,
        contract_id: str,
    ) -> tuple[ContractRelease, ...]: ...
    def get_contract_release_by_version(
        self,
        contract_id: str,
        contract_version: str,
    ) -> ContractRelease: ...
