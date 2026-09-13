"""Read models for deterministic governance-history reconstruction."""

from __future__ import annotations

from dataclasses import dataclass

from semapact.contractops import ChangeSet
from semapact.governance import GovernanceDecision
from semapact.history import (
    DeploymentRecord,
    ReleaseRecord,
    RuntimeObservationRecord,
    RuntimeReconciliationRecord,
)
from semapact.revision import ContractRevision


@dataclass(frozen=True)
class BrokenHistoryReference:
    """One explicit history reference that could not be resolved consistently."""

    source_kind: str
    source_id: str
    reference_field: str
    target_kind: str
    target_id: str
    reason: str


@dataclass(frozen=True)
class RuntimeEvolution:
    """One reconciliation occurrence with its exact observed-state evidence when present."""

    reconciliation: RuntimeReconciliationRecord
    observation: RuntimeObservationRecord | None


@dataclass(frozen=True)
class DeploymentEvolution:
    """One deployment occurrence and runtime evidence explicitly linked to it."""

    deployment: DeploymentRecord
    runtime: tuple[RuntimeEvolution, ...] = ()


@dataclass(frozen=True)
class ReleaseEvolution:
    """One finalized release and its downstream execution/runtime history."""

    release: ReleaseRecord
    released_revision: ContractRevision | None
    deployments: tuple[DeploymentEvolution, ...] = ()
    runtime: tuple[RuntimeEvolution, ...] = ()


@dataclass(frozen=True)
class ProposalEvolution:
    """One ChangeSet path through an optional recorded GovernanceDecision."""

    change_set: ChangeSet
    base_revision: ContractRevision | None
    candidate_revision: ContractRevision | None
    decision: GovernanceDecision | None
    releases: tuple[ReleaseEvolution, ...] = ()


@dataclass(frozen=True)
class ContractEvolution:
    """Deterministic read-side reconstruction of one contract's persisted history."""

    contract_id: str
    proposals: tuple[ProposalEvolution, ...] = ()
    unlinked_releases: tuple[ReleaseEvolution, ...] = ()
    unlinked_runtime: tuple[RuntimeEvolution, ...] = ()
    broken_references: tuple[BrokenHistoryReference, ...] = ()
