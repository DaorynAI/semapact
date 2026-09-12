"""Application orchestration for durable proposal history."""

from __future__ import annotations

from semapact.application.models.governance import GovernanceProposal
from semapact.contractops.integrity import validate_change_set_identity
from semapact.history import (
    ChangeSetDecisionLink,
    ChangeSetDecisionLinkHistoryRepository,
    ChangeSetHistoryRepository,
    ContractRevisionHistoryRepository,
    DecisionHistoryRepository,
)
from semapact.revision.integrity import validate_contract_revision_identity
from semapact.revision.models import ContractRevision


class ProposalHistoryService:
    """Record one already-evaluated proposal without recomputing domain semantics."""

    def __init__(
        self,
        *,
        revisions: ContractRevisionHistoryRepository,
        change_sets: ChangeSetHistoryRepository,
        decisions: DecisionHistoryRepository,
        decision_links: ChangeSetDecisionLinkHistoryRepository,
    ) -> None:
        self._revisions = revisions
        self._change_sets = change_sets
        self._decisions = decisions
        self._decision_links = decision_links

    def record_proposal(
        self,
        proposal: GovernanceProposal,
        *,
        base_revision: ContractRevision,
        candidate_revision: ContractRevision,
    ) -> ChangeSetDecisionLink:
        """Persist the exact revision → ChangeSet → decision proposal history chain.

        This boundary validates cross-artifact references only. It never re-diffs
        contracts or re-runs governance, lifecycle policy, or revision construction.
        """
        if not isinstance(proposal, GovernanceProposal):
            raise TypeError(
                f"proposal must be GovernanceProposal, got {type(proposal).__name__}"
            )
        validate_contract_revision_identity(base_revision)
        validate_contract_revision_identity(candidate_revision)
        validate_change_set_identity(proposal.change_set)
        _validate_proposal_links(
            proposal,
            base_revision=base_revision,
            candidate_revision=candidate_revision,
        )

        # Persist independently valid artifacts first. The relationship marker is
        # written last so a partial failure cannot leave a dangling audit link.
        self._revisions.put_revision(base_revision)
        self._revisions.put_revision(candidate_revision)
        self._change_sets.put_change_set(proposal.change_set)
        self._decisions.put_decision(proposal.decision)

        link = ChangeSetDecisionLink(
            change_set_id=proposal.change_set.change_set_id,
            decision_id=proposal.decision.decision_id,
        )
        self._decision_links.put_change_set_decision_link(link)
        return link


def _validate_proposal_links(
    proposal: GovernanceProposal,
    *,
    base_revision: ContractRevision,
    candidate_revision: ContractRevision,
) -> None:
    change_set = proposal.change_set
    decision = proposal.decision

    base_contract_id = str(base_revision.contract.id or "").strip()
    candidate_contract_id = str(candidate_revision.contract.id or "").strip()
    if not base_contract_id or not candidate_contract_id:
        raise ValueError("proposal history requires non-empty revision contract IDs")
    if base_contract_id != candidate_contract_id:
        raise ValueError("base and candidate revisions must belong to the same contract")
    if change_set.contract_id != base_contract_id or decision.contract_id != base_contract_id:
        raise ValueError("proposal artifacts do not reference the same contract")

    if change_set.base_revision_ref != base_revision.revision_id:
        raise ValueError("ChangeSet base_revision_ref must equal base ContractRevision ID")
    if change_set.candidate_revision_ref != candidate_revision.revision_id:
        raise ValueError(
            "ChangeSet candidate_revision_ref must equal candidate ContractRevision ID"
        )

    if change_set.context != decision.context:
        raise ValueError("ChangeSet context does not match GovernanceDecision context")
    if change_set.changes != decision.changes:
        raise ValueError("ChangeSet changes do not match GovernanceDecision changes")
