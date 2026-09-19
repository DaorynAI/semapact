"""Canonical in-process application facade for SemaPact clients."""

from __future__ import annotations

from datetime import date
from typing import Sequence

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.application.errors import ApplicationCapabilityUnavailableError
from semapact.application.models.evolution import ContractEvolution
from semapact.application.models.governance import GovernanceProposal
from semapact.application.models.release import ReleasePlanningResult
from semapact.application.services.evolution import EvolutionChainService
from semapact.application.services.governance import GovernanceService
from semapact.application.services.release_planning import ReleasePlanningService
from semapact.governance.models import GovernanceDecision
from semapact.history import DecisionHistoryRepository
from semapact.lifecycle.merge_engine import MergeConflict


class SemaPactApplicationService:
    """Single client-facing facade over canonical application use cases.

    This facade owns no governance, release-classification, or history semantics.
    It delegates to the application services that own those workflows and gives
    CLI/SDK/UI/MCP/agent adapters one stable in-process boundary to consume.

    Draft and actor-capability operations are intentionally added only when their
    owning M4 models/services exist; this class must not invent parallel workflow
    semantics to anticipate downstream milestones.
    """

    def __init__(
        self,
        *,
        governance: GovernanceService | None = None,
        release_planning: ReleasePlanningService | None = None,
        evolution: EvolutionChainService | None = None,
        decisions: DecisionHistoryRepository | None = None,
    ) -> None:
        self._governance = governance or GovernanceService()
        self._release_planning = release_planning or ReleasePlanningService(
            governance_service=self._governance
        )
        self._evolution = evolution
        self._decisions = decisions

    def analyze_contract(
        self,
        base_contract: OpenDataContractStandard,
        candidate_contract: OpenDataContractStandard,
        *,
        effective_date: date | str,
        merge_conflicts: Sequence[MergeConflict] = (),
    ) -> GovernanceDecision:
        """Return the canonical M0 GovernanceDecision for one proposed change."""
        return self._governance.evaluate(
            base_contract,
            candidate_contract,
            effective_date=effective_date,
            merge_conflicts=merge_conflicts,
        )

    def evaluate_proposal(
        self,
        base_contract: OpenDataContractStandard,
        candidate_contract: OpenDataContractStandard,
        *,
        effective_date: date | str,
        base_revision_ref: str,
        candidate_revision_ref: str,
        merge_conflicts: Sequence[MergeConflict] = (),
        source: str | None = None,
        actor_reference: str | None = None,
    ) -> GovernanceProposal:
        """Return ChangeSet + GovernanceDecision from one canonical evaluation."""
        return self._governance.evaluate_proposal(
            base_contract,
            candidate_contract,
            effective_date=effective_date,
            base_revision_ref=base_revision_ref,
            candidate_revision_ref=candidate_revision_ref,
            merge_conflicts=merge_conflicts,
            source=source,
            actor_reference=actor_reference,
        )

    def prepare_release(
        self,
        base_contract: OpenDataContractStandard,
        candidate_contract: OpenDataContractStandard,
        *,
        effective_date: date | str,
        base_revision_ref: str,
        candidate_revision_ref: str,
        authority_reference: str | None = None,
    ) -> ReleasePlanningResult:
        """Delegate canonical ChangeSet → ReleasePlan → VersionResolution planning."""
        return self._release_planning.plan(
            base_contract,
            candidate_contract,
            effective_date=effective_date,
            base_revision_ref=base_revision_ref,
            candidate_revision_ref=candidate_revision_ref,
            authority_reference=authority_reference,
        )

    def get_decision(self, decision_id: str) -> GovernanceDecision:
        """Read one persisted canonical GovernanceDecision without recomputation."""
        if self._decisions is None:
            raise ApplicationCapabilityUnavailableError("decision_history")
        return self._decisions.get_decision(_required_text(decision_id, "decision_id"))

    def get_history(self, contract_id: str) -> ContractEvolution:
        """Reconstruct persisted governance evolution through the M3 read service."""
        if self._evolution is None:
            raise ApplicationCapabilityUnavailableError("evolution_history")
        return self._evolution.reconstruct(_required_text(contract_id, "contract_id"))


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned
