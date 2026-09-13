from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.application.services.evolution import EvolutionChainService
from semapact.application.services.governance import GovernanceService
from semapact.application.services.history import ProposalHistoryService
from semapact.application.services.runtime_history import RuntimeHistoryService
from semapact.contractops import VersionAuthority, build_change_set
from semapact.history import DeploymentRecord, DeploymentStatus, ReleaseRecord
from semapact.history.integrity import compute_deployment_record_id, compute_release_record_id
from semapact.observation import (
    ObservedAsset,
    ObservedAssetIdentity,
    ObservedPlatformState,
    with_observed_state_fingerprint,
)
from semapact.platforms.git import GitWorkingTreeHistoryRepository
from semapact.reconciliation import ReconciliationResult
from semapact.revision import build_contract_revision


def _contract(*, version: str = "1.2.3", include_note: bool = False) -> OpenDataContractStandard:
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
        version=version,
        status="active",
        schema=[SchemaObject(name="orders", properties=properties)],
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


def _release_record(proposal, released_revision_id: str) -> ReleaseRecord:
    fields = dict(
        contract_id="orders-product",
        contract_version="1.3.0",
        decision_id=proposal.decision.decision_id,
        change_set_id=proposal.change_set.change_set_id,
        release_plan_id="release-plan-1",
        version_resolution_id="version-resolution-1",
        authorization_id="apply-authorization-1",
        applied_release_id="applied-release-1",
        released_revision_id=released_revision_id,
        required_version_bump="minor",
        actual_version_bump="minor",
        version_authority=VersionAuthority.SEMAPACT,
        authority_reference=None,
        review_evidence_reference=None,
        review_evidence_action=None,
    )
    release_record_id = compute_release_record_id(
        **{**fields, "version_authority": fields["version_authority"].value}
    )
    return ReleaseRecord(release_record_id=release_record_id, **fields)


def _deployment_record(release_record_id: str) -> DeploymentRecord:
    started = datetime(2026, 9, 13, 1, tzinfo=timezone.utc)
    completed = started + timedelta(seconds=2)
    fields = dict(
        release_record_id=release_record_id,
        deployment_plan_id="deployment-plan-1",
        deployment_preview_id="deployment-preview-1",
        deployment_authorization_id="deployment-authorization-1",
        platform="databricks",
        runtime_target="catalog.schema",
        source_reference="workspace:test",
        status=DeploymentStatus.SUCCEEDED,
        started_at=started,
        completed_at=completed,
        actor_reference=None,
        external_reference="pipeline:1",
    )
    deployment_record_id = compute_deployment_record_id(
        release_record_id=release_record_id,
        deployment_plan_id=fields["deployment_plan_id"],
        deployment_preview_id=fields["deployment_preview_id"],
        deployment_authorization_id=fields["deployment_authorization_id"],
        platform=fields["platform"],
        runtime_target=fields["runtime_target"],
        source_reference=fields["source_reference"],
        status=fields["status"].value,
        started_at=started.isoformat(),
        completed_at=completed.isoformat(),
        actor_reference=None,
        external_reference=fields["external_reference"],
    )
    return DeploymentRecord(deployment_record_id=deployment_record_id, **fields)


def _observation(at: datetime) -> ObservedPlatformState:
    return with_observed_state_fingerprint(
        ObservedPlatformState(
            platform="databricks",
            source_identifier="workspace:test",
            assets=(
                ObservedAsset(
                    identity=ObservedAssetIdentity(
                        platform="databricks",
                        namespace=("catalog", "schema"),
                        asset="orders",
                    ),
                    asset_type="TABLE",
                ),
            ),
            captured_at=at,
        )
    )


def _result(observation: ObservedPlatformState) -> ReconciliationResult:
    assert observation.fingerprint is not None
    return ReconciliationResult(
        contract_id="orders-product",
        contract_version="1.3.0",
        observation_source_identifier=observation.source_identifier,
        observation_fingerprint=observation.fingerprint,
    )


def _service(backend: GitWorkingTreeHistoryRepository) -> EvolutionChainService:
    return EvolutionChainService(
        revisions=backend,
        change_sets=backend,
        decisions=backend,
        decision_links=backend,
        releases=backend,
        deployments=backend,
        observations=backend,
        runtime_reconciliations=backend,
    )


def test_reconstructs_complete_governance_evolution_chain(tmp_path: Path) -> None:
    backend = GitWorkingTreeHistoryRepository(tmp_path)
    proposal, base_revision, candidate_revision = _record_proposal(backend)

    released_revision = build_contract_revision(
        _contract(version="1.3.0", include_note=True)
    )
    backend.put_revision(released_revision)
    release = _release_record(proposal, released_revision.revision_id)
    backend.put_release_record(release)
    deployment = _deployment_record(release.release_record_id)
    backend.put_deployment_record(deployment)

    observation = _observation(datetime(2026, 9, 13, 2, tzinfo=timezone.utc))
    runtime = RuntimeHistoryService(
        observations=backend,
        reconciliations=backend,
        releases=backend,
        deployments=backend,
    ).record_reconciliation(
        observation,
        _result(observation),
        release_record_id=release.release_record_id,
        deployment_record_id=deployment.deployment_record_id,
    )

    chain = _service(backend).reconstruct("orders-product")

    assert chain.broken_references == ()
    assert chain.unlinked_releases == ()
    assert chain.unlinked_runtime == ()
    assert len(chain.proposals) == 1
    path = chain.proposals[0]
    assert path.base_revision == base_revision
    assert path.candidate_revision == candidate_revision
    assert path.decision == proposal.decision
    assert len(path.releases) == 1
    release_path = path.releases[0]
    assert release_path.release == release
    assert release_path.released_revision == released_revision
    assert len(release_path.deployments) == 1
    deployment_path = release_path.deployments[0]
    assert deployment_path.deployment == deployment
    assert tuple(item.reconciliation for item in deployment_path.runtime) == (runtime,)
    assert deployment_path.runtime[0].observation is not None
    assert _service(backend).reconstruct("orders-product") == chain


def test_incomplete_changeset_history_does_not_fabricate_downstream_stages(tmp_path: Path) -> None:
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
    isolated_paths = [item for item in chain.proposals if item.change_set == isolated]

    assert len(isolated_paths) == 1
    assert isolated_paths[0].decision is None
    assert isolated_paths[0].releases == ()


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


def test_contract_level_runtime_evidence_remains_unlinked(tmp_path: Path) -> None:
    backend = GitWorkingTreeHistoryRepository(tmp_path)
    observation = _observation(datetime(2026, 9, 13, 3, tzinfo=timezone.utc))
    runtime = RuntimeHistoryService(
        observations=backend,
        reconciliations=backend,
        releases=backend,
        deployments=backend,
    ).record_reconciliation(observation, _result(observation))

    chain = _service(backend).reconstruct("orders-product")

    assert chain.proposals == ()
    assert chain.unlinked_releases == ()
    assert tuple(item.reconciliation for item in chain.unlinked_runtime) == (runtime,)
    assert chain.unlinked_runtime[0].observation is not None
    assert chain.broken_references == ()
