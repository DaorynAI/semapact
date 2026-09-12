"""Storage-neutral typed persistence ports for governance history."""

from __future__ import annotations

from typing import Protocol

from semapact.contractops import ChangeSet
from semapact.governance import GovernanceDecision
from semapact.history.models import ChangeSetDecisionLink
from semapact.revision.models import ContractRevision, ContractRevisionSource


class HistoryRepositoryError(RuntimeError):
    """Base error for durable governance-history access."""


class HistoryNotFoundError(HistoryRepositoryError):
    """Requested historical artifact does not exist."""


class HistoryConflictError(HistoryRepositoryError):
    """An immutable artifact ID already exists with different content."""


class HistoryCorruptionError(HistoryRepositoryError):
    """Persisted or supplied historical content fails canonical validation."""


class DecisionHistoryRepository(Protocol):
    """Persistence capability for canonical GovernanceDecision history only."""

    def put_decision(self, decision: GovernanceDecision) -> None:
        """Persist one immutable GovernanceDecision idempotently."""
        ...

    def get_decision(self, decision_id: str) -> GovernanceDecision:
        """Load one GovernanceDecision by its exact artifact ID."""
        ...

    def list_decisions(self, contract_id: str) -> tuple[GovernanceDecision, ...]:
        """List decisions for one contract in deterministic artifact-ID order."""
        ...


class ChangeSetHistoryRepository(Protocol):
    """Persistence capability for canonical ChangeSet history only."""

    def put_change_set(self, change_set: ChangeSet) -> None:
        """Persist one immutable ChangeSet idempotently."""
        ...

    def get_change_set(self, change_set_id: str) -> ChangeSet:
        """Load one ChangeSet by its exact artifact ID."""
        ...

    def list_change_sets(self, contract_id: str) -> tuple[ChangeSet, ...]:
        """List ChangeSets for one contract in deterministic artifact-ID order."""
        ...


class ChangeSetDecisionLinkHistoryRepository(Protocol):
    """Persistence capability for ChangeSet-to-decision audit provenance only."""

    def put_change_set_decision_link(self, link: ChangeSetDecisionLink) -> None:
        """Persist one immutable ChangeSet-to-decision link idempotently."""
        ...

    def list_change_set_decision_links(
        self,
        change_set_id: str,
    ) -> tuple[ChangeSetDecisionLink, ...]:
        """List governance outcomes linked to one ChangeSet in deterministic order."""
        ...


class ContractRevisionHistoryRepository(Protocol):
    """Persistence capability for immutable ContractRevision history only."""

    def put_revision(self, revision: ContractRevision) -> None:
        """Persist one immutable ContractRevision idempotently."""
        ...

    def get_revision(self, revision_id: str) -> ContractRevision:
        """Load one ContractRevision by its exact content-derived ID."""
        ...

    def list_revisions(self, contract_id: str) -> tuple[ContractRevision, ...]:
        """List revisions for one contract in deterministic artifact-ID order."""
        ...


class ContractRevisionSourceHistoryRepository(Protocol):
    """Persistence capability for immutable revision provenance links only."""

    def put_revision_source(self, source: ContractRevisionSource) -> None:
        """Persist one revision-to-source provenance link idempotently."""
        ...

    def get_revision_source(self, source_link_id: str) -> ContractRevisionSource:
        """Load one revision provenance link by exact ID."""
        ...

    def list_revision_sources(
        self,
        revision_id: str,
    ) -> tuple[ContractRevisionSource, ...]:
        """List all source links for one revision in deterministic ID order."""
        ...
