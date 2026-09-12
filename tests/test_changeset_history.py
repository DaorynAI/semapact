from __future__ import annotations

from pathlib import Path

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.application.services.governance import GovernanceService
from semapact.application.services.history import ProposalHistoryService
from semapact.history import (
    ChangeSetDecisionLinkHistoryRepository,
    ChangeSetHistoryRepository,
    ContractRevisionHistoryRepository,
    DecisionHistoryRepository,
)
from semapact.platforms.git import GitWorkingTreeHistoryRepository
from semapact.revision import build_contract_revision


def _contract(*, name: str) -> OpenDataContractStandard:
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders-product",
        name=name,
        version="1.2.3",
        status="active",
        schema=[
            SchemaObject(
                name="orders",
                properties=[
                    SchemaProperty(
                        name="id",
                        logicalType="string",
                        physicalType="varchar(255)",
                        required=True,
                    )
                ],
            )
        ],
    )


def _proposal(*, effective_date: str = "2026-09-12"):
    base_revision = build_contract_revision(_contract(name="Orders old"))
    candidate_revision = build_contract_revision(_contract(name="Orders new"))
    proposal = GovernanceService().evaluate_proposal(
        base_revision.contract,
        candidate_revision.contract,
        effective_date=effective_date,
        base_revision_ref=base_revision.revision_id,
        candidate_revision_ref=candidate_revision.revision_id,
        source="test",
        actor_reference="user:test",
    )
    return proposal, base_revision, candidate_revision


def _service(tmp_path: Path):
    backend = GitWorkingTreeHistoryRepository(tmp_path)
    revisions: ContractRevisionHistoryRepository = backend
    change_sets: ChangeSetHistoryRepository = backend
    decisions: DecisionHistoryRepository = backend
    links: ChangeSetDecisionLinkHistoryRepository = backend
    service = ProposalHistoryService(
        revisions=revisions,
        change_sets=change_sets,
        decisions=decisions,
        decision_links=links,
    )
    return service, backend


def test_records_exact_proposal_chain_without_recomputing_domain_artifacts(
    tmp_path: Path,
) -> None:
    service, backend = _service(tmp_path)
    proposal, base_revision, candidate_revision = _proposal()

    link = service.record_proposal(
        proposal,
        base_revision=base_revision,
        candidate_revision=candidate_revision,
    )
    # Same exact history write is idempotent.
    assert (
        service.record_proposal(
            proposal,
            base_revision=base_revision,
            candidate_revision=candidate_revision,
        )
        == link
    )

    assert backend.get_revision(base_revision.revision_id) == base_revision
    assert backend.get_revision(candidate_revision.revision_id) == candidate_revision
    assert backend.get_change_set(proposal.change_set.change_set_id) == proposal.change_set
    assert backend.get_decision(proposal.decision.decision_id) == proposal.decision
    assert backend.list_change_set_decision_links(proposal.change_set.change_set_id) == (
        link,
    )
    assert link.change_set_id == proposal.change_set.change_set_id
    assert link.decision_id == proposal.decision.decision_id


def test_changeset_context_round_trips_and_different_contexts_do_not_overwrite(
    tmp_path: Path,
) -> None:
    service, backend = _service(tmp_path)
    first, first_base, first_candidate = _proposal(effective_date="2026-09-12")
    second, second_base, second_candidate = _proposal(effective_date="2026-09-13")

    service.record_proposal(
        first,
        base_revision=first_base,
        candidate_revision=first_candidate,
    )
    service.record_proposal(
        second,
        base_revision=second_base,
        candidate_revision=second_candidate,
    )

    assert first.change_set.change_set_id != second.change_set.change_set_id
    assert backend.get_change_set(first.change_set.change_set_id).context == first.change_set.context
    assert backend.get_change_set(second.change_set.change_set_id).context == second.change_set.context
    assert len(backend.list_change_sets("orders-product")) == 2


def test_rejects_changeset_that_does_not_reference_exact_contract_revisions(
    tmp_path: Path,
) -> None:
    service, _ = _service(tmp_path)
    proposal, base_revision, candidate_revision = _proposal()
    mismatched = proposal.change_set.model_copy(update={"base_revision_ref": "git:base"})
    broken_proposal = proposal.__class__(change_set=mismatched, decision=proposal.decision)

    with pytest.raises(ValueError, match="base_revision_ref"):
        service.record_proposal(
            broken_proposal,
            base_revision=base_revision,
            candidate_revision=candidate_revision,
        )


def test_rejects_decision_that_is_not_the_outcome_of_the_changeset(
    tmp_path: Path,
) -> None:
    service, _ = _service(tmp_path)
    proposal, base_revision, candidate_revision = _proposal()
    other, _, _ = _proposal(effective_date="2026-09-13")
    broken_proposal = proposal.__class__(
        change_set=proposal.change_set,
        decision=other.decision,
    )

    with pytest.raises(ValueError, match="context"):
        service.record_proposal(
            broken_proposal,
            base_revision=base_revision,
            candidate_revision=candidate_revision,
        )
