"""Application orchestration for canonical ContractOps release planning."""

from __future__ import annotations

from datetime import date

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.application.models.release import ReleasePlanningResult
from semapact.application.services.governance import GovernanceService
from semapact.application.services.version_authority import VersionAuthorityService
from semapact.contractops import build_release_plan


class ReleasePlanningService:
    """Compose governance and canonical release planning exactly once."""

    def __init__(
        self,
        *,
        governance_service: GovernanceService | None = None,
        version_authority_service: VersionAuthorityService | None = None,
    ) -> None:
        self._governance = governance_service or GovernanceService()
        self._version_authority = version_authority_service or VersionAuthorityService()

    def plan(
        self,
        base_contract: OpenDataContractStandard,
        candidate_contract: OpenDataContractStandard,
        *,
        effective_date: date | str,
        base_revision_ref: str,
        candidate_revision_ref: str,
        authority_reference: str | None = None,
    ) -> ReleasePlanningResult:
        """Produce ChangeSet → ReleasePlan → VersionResolution from one decision."""
        proposal = self._governance.evaluate_proposal(
            base_contract,
            candidate_contract,
            effective_date=effective_date,
            base_revision_ref=base_revision_ref,
            candidate_revision_ref=candidate_revision_ref,
        )
        release_plan = build_release_plan(proposal.change_set, proposal.decision)
        version_resolution = self._version_authority.resolve(
            release_plan,
            base_contract,
            authority_reference=authority_reference,
        )
        return ReleasePlanningResult(
            change_set=proposal.change_set,
            decision=proposal.decision,
            release_plan=release_plan,
            version_resolution=version_resolution,
        )
