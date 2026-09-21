from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.application.services.evolution import EvolutionChainService
from semapact.application.services.governance import GovernanceService
from semapact.application.services.history import ProposalHistoryService
from semapact.application.services.release_workflow import ReleaseFinalizer, ReleaseWorkflowService
from semapact.contractops import build_change_set
from semapact.platforms.git import GitWorkingTreeHistoryRepository
from semapact.revision import build_contract_revision


def _contract(*, include_note: bool = False) -> OpenDataContractStandard:
    properties = [
        SchemaProperty(
            name="id",
            logicalType="string",
            physicalType="varchar(255)",
            required=True,
        )
    ]
    if include_note:
        properties.append(
            SchemaProperty(
                name="note",
                logicalType="string",
                physicalType="varchar(255)",
                required=False,
            )
        )
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders-product",
        name="Orders",
        version="1.2.3",
        status="active",
        schema=[SchemaObject(name="orders", properties=properties)],
    )


def _service(backend: GitWorkingTreeHistoryRepository) -> EvolutionChainService:
    return EvolutionChainService(
        revisions=backend,
        change_sets=backend,
        decisions=backend,
        decision_links=backend,
        releases=backend,
    )


def _record_proposal(backend: GitWorkingTreeHistoryRepository):
    base_revision = build_contract_revision(_contract())
    candidate_revision = build_contract_revision(_contract(include_note=True))
    proposal = GovernanceService().evaluate_proposal(
        base_revision.contract,
        candidate_revision.contract,
        effective_date="2026-09-13",
        base_revision_ref=base_revision.revision_id,
        candidate_revision_ref=candidate_revision.revision_id,
        source="test",
        actor_reference="actor:test",
    )
    ProposalHistoryService(
        revisions=backend,
        change_sets=backend,
        decisions=backend,
        decision_links=backend,
    ).record_proposal(
        proposal,
        base_revision=base_revision,
        candidate_revision=candidate_revision,
    )
    return proposal, base_revision, candidate_revision


def _record_release(
    backend: GitWorkingTreeHistoryRepository,
    *,
    base_revision,
    candidate_revision,
):
    workflow = ReleaseWorkflowService()
    bundle = workflow.assess(
        base_revision.contract,
        candidate_revision.contract,
        effective_date="2026-09-13",
        base_revision_ref=base_revision.revision_id,
        candidate_revision_ref=candidate_revision.revision_id,
    )
    approval = workflow.approve(
        bundle,
        actor_reference="human:test",
        recorded_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    release = ReleaseFinalizer().finalize(bundle, approval=approval)
    backend.put_contract_release(release)
    return release


def test_reconstructs_governance_to_contract_release_chain(tmp_path: Path) -> None:
    backend = GitWorkingTreeHistoryRepository(tmp_path)
    proposal, base_revision, candidate_revision = _record_proposal(backend)
    release = _record_release(
        backend,
        base_revision=base_revision,
        candidate_revision=candidate_revision,
    )

    chain = _service(backend).reconstruct("orders-product")

    assert chain.broken_references == ()
    assert chain.unlinked_releases == ()
    assert len(chain.proposals) == 1
    path = chain.proposals[0]
    assert path.base_revision == base_revision
    assert path.candidate_revision == candidate_revision
    assert path.decision == proposal.decision
    assert tuple(item.release for item in path.releases) == (release,)
    assert _service(backend).reconstruct("orders-product") == chain


def test_incomplete_changeset_history_does_not_fabricate_release(tmp_path: Path) -> None:
    backend = GitWorkingTreeHistoryRepository(tmp_path)
    proposal, base_revision, candidate_revision = _record_proposal(backend)

    isolated = build_change_set(
        contract_id=proposal.change_set.contract_id,
        base_revision_ref=base_revision.revision_id,
        candidate_revision_ref=candidate_revision.revision_id,
        changes=proposal.change_set.changes,
        context=proposal.change_set.context,
        source="isolated",
    )
    backend.put_change_set(isolated)

    chain = _service(backend).reconstruct("orders-product")
    isolated_path = next(item for item in chain.proposals if item.change_set == isolated)

    assert isolated_path.decision is None
    assert isolated_path.releases == ()


def test_broken_revision_reference_is_reported_explicitly(tmp_path: Path) -> None:
    backend = GitWorkingTreeHistoryRepository(tmp_path)
    proposal, _, candidate_revision = _record_proposal(backend)
    broken = build_change_set(
        contract_id="orders-product",
        base_revision_ref="missing-revision",
        candidate_revision_ref=candidate_revision.revision_id,
        changes=proposal.change_set.changes,
        context=proposal.change_set.context,
        source="broken",
    )
    backend.put_change_set(broken)

    chain = _service(backend).reconstruct("orders-product")
    path = next(item for item in chain.proposals if item.change_set == broken)

    assert path.base_revision is None
    assert any(
        item.source_id == broken.change_set_id
        and item.reference_field == "base_revision_ref"
        and item.target_id == "missing-revision"
        and item.reason == "NOT_FOUND"
        for item in chain.broken_references
    )
