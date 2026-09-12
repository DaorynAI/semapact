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
from semapact.application.services.release_history import ReleaseHistoryService
from semapact.contractops import (
    VersionAuthorityConfig,
    apply_contract_release,
    authorize_contract_operation,
    build_release_plan,
    resolve_release_version,
)
from semapact.governance.gate import GovernanceOperation
from semapact.history import HistoryConflictError
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
        schema=[
            SchemaObject(
                name="orders",
                properties=properties,
            )
        ],
    )


def _services(tmp_path: Path):
    backend = GitWorkingTreeHistoryRepository(tmp_path)
    proposal_history = ProposalHistoryService(
        revisions=backend,
        change_sets=backend,
        decisions=backend,
        decision_links=backend,
    )
    release_history = ReleaseHistoryService(
        revisions=backend,
        change_sets=backend,
        decisions=backend,
        decision_links=backend,
        release_plans=backend,
        release_records=backend,
    )
    return proposal_history, release_history, backend


def _release_bundle(*, source: str):
    base_revision = build_contract_revision(_contract())
    candidate_revision = build_contract_revision(_contract(include_note=True))
    proposal = GovernanceService().evaluate_proposal(
        base_revision.contract,
        candidate_revision.contract,
        effective_date="2026-09-12",
        base_revision_ref=base_revision.revision_id,
        candidate_revision_ref=candidate_revision.revision_id,
        source=source,
        actor_reference=f"actor:{source}",
    )
    release_plan = build_release_plan(proposal.change_set, proposal.decision)
    version_resolution = resolve_release_version(
        release_plan,
        current_version="1.2.3",
        config=VersionAuthorityConfig(),
    )
    authorization = authorize_contract_operation(
        proposal.decision,
        proposal.change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.APPLY,
    )
    applied_release = apply_contract_release(
        candidate_revision.contract,
        candidate_revision_ref=candidate_revision.revision_id,
        decision=proposal.decision,
        change_set=proposal.change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        authorization=authorization,
    )
    return (
        proposal,
        base_revision,
        candidate_revision,
        release_plan,
        version_resolution,
        authorization,
        applied_release,
    )


def _record_bundle(tmp_path: Path, *, source: str = "test"):
    proposal_history, release_history, backend = _services(tmp_path)
    (
        proposal,
        base_revision,
        candidate_revision,
        release_plan,
        version_resolution,
        authorization,
        applied_release,
    ) = _release_bundle(source=source)
    proposal_history.record_proposal(
        proposal,
        base_revision=base_revision,
        candidate_revision=candidate_revision,
    )
    record = release_history.record_release(
        release_plan=release_plan,
        version_resolution=version_resolution,
        authorization=authorization,
        applied_release=applied_release,
    )
    return (
        record,
        proposal,
        candidate_revision,
        release_plan,
        version_resolution,
        authorization,
        applied_release,
        release_history,
        backend,
    )


def test_records_release_against_exact_plan_and_released_revision(tmp_path: Path) -> None:
    (
        record,
        proposal,
        candidate_revision,
        release_plan,
        version_resolution,
        authorization,
        applied_release,
        _,
        backend,
    ) = _record_bundle(tmp_path)

    assert backend.get_release_plan(release_plan.release_plan_id) == release_plan
    assert backend.get_release_record(record.release_record_id) == record
    assert (
        backend.get_release_record_by_version(
            "orders-product",
            version_resolution.selected_version,
        )
        == record
    )
    released_revision = backend.get_revision(record.released_revision_id)
    assert released_revision.revision_id != candidate_revision.revision_id
    assert str(released_revision.contract.version) == version_resolution.selected_version
    assert record.decision_id == proposal.decision.decision_id
    assert record.change_set_id == proposal.change_set.change_set_id
    assert record.version_resolution_id == version_resolution.version_resolution_id
    assert record.authorization_id == authorization.authorization_id
    assert record.applied_release_id == applied_release.applied_release_id
    assert record.required_version_bump == version_resolution.required_version_bump
    assert record.actual_version_bump == version_resolution.actual_bump
    assert record.version_authority == version_resolution.authority


def test_exact_release_history_write_is_idempotent(tmp_path: Path) -> None:
    (
        first,
        _,
        _,
        release_plan,
        version_resolution,
        authorization,
        applied_release,
        release_history,
        backend,
    ) = _record_bundle(tmp_path)

    second = release_history.record_release(
        release_plan=release_plan,
        version_resolution=version_resolution,
        authorization=authorization,
        applied_release=applied_release,
    )

    assert second == first
    assert backend.list_release_records("orders-product") == (first,)


def test_conflicting_release_for_same_contract_version_fails_closed(tmp_path: Path) -> None:
    _record_bundle(tmp_path, source="first")
    proposal_history, release_history, _ = _services(tmp_path)
    (
        proposal,
        base_revision,
        candidate_revision,
        release_plan,
        version_resolution,
        authorization,
        applied_release,
    ) = _release_bundle(source="second")
    proposal_history.record_proposal(
        proposal,
        base_revision=base_revision,
        candidate_revision=candidate_revision,
    )

    with pytest.raises(HistoryConflictError, match="version"):
        release_history.record_release(
            release_plan=release_plan,
            version_resolution=version_resolution,
            authorization=authorization,
            applied_release=applied_release,
        )


def test_release_history_rejects_wrong_apply_authorization(tmp_path: Path) -> None:
    proposal_history, release_history, _ = _services(tmp_path)
    (
        proposal,
        base_revision,
        candidate_revision,
        release_plan,
        version_resolution,
        _,
        applied_release,
    ) = _release_bundle(source="release")
    proposal_history.record_proposal(
        proposal,
        base_revision=base_revision,
        candidate_revision=candidate_revision,
    )
    publish_authorization = authorize_contract_operation(
        proposal.decision,
        proposal.change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.PUBLISH,
    )

    with pytest.raises(ValueError, match="APPLY"):
        release_history.record_release(
            release_plan=release_plan,
            version_resolution=version_resolution,
            authorization=publish_authorization,
            applied_release=applied_release,
        )
