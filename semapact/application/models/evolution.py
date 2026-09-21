"""Read models for deterministic governance-history reconstruction."""

from __future__ import annotations

from dataclasses import dataclass

from semapact.contractops import ChangeSet, ContractRelease
from semapact.governance import GovernanceDecision
from semapact.revision import ContractRevision


@dataclass(frozen=True)
class BrokenHistoryReference:
    """One explicit governance-history reference that could not be resolved."""

    source_kind: str
    source_id: str
    reference_field: str
    target_kind: str
    target_id: str
    reason: str


@dataclass(frozen=True)
class ReleaseEvolution:
    """One finalized formal ContractRelease linked to its governance path."""

    release: ContractRelease


@dataclass(frozen=True)
class ProposalEvolution:
    """One ChangeSet path through an optional GovernanceDecision and releases."""

    change_set: ChangeSet
    base_revision: ContractRevision | None
    candidate_revision: ContractRevision | None
    decision: GovernanceDecision | None
    releases: tuple[ReleaseEvolution, ...] = ()


@dataclass(frozen=True)
class ContractEvolution:
    """Deterministic read-side reconstruction of one contract governance history."""

    contract_id: str
    proposals: tuple[ProposalEvolution, ...] = ()
    unlinked_releases: tuple[ReleaseEvolution, ...] = ()
    broken_references: tuple[BrokenHistoryReference, ...] = ()
